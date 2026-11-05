"""Portable editing plans with embedded media, bounded and transactional restore."""
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import stat
import tempfile
import zipfile

from . import runtime, storage, settings, tasks, segmenter, ffmpeg_util
from .studio import Studio, MAX_ITEMS, FORMATS
from .workspace import Workspace

MAX_BYTES = 20 * 1024 ** 3
MAX_MANIFEST = 2 * 1024 ** 2


def copy_stream(source, target):
    digest = hashlib.sha256()
    while True:
        tasks.check()
        block = source.read(1024 * 1024)
        if not block:
            return digest.hexdigest()
        target.write(block)
        digest.update(block)


def options(value):
    value = value or {}
    result = dict(format=value.get("format", FORMATS[0]), merge=value.get("merge", False),
                  fps=value.get("fps", 15), scale=value.get("scale", .5))
    if (result["format"] not in FORMATS or type(result["merge"]) is not bool
            or not isinstance(result["fps"], (int, float)) or not 5 <= result["fps"] <= 30
            or not isinstance(result["scale"], (int, float)) or not .1 <= result["scale"] <= 1):
        raise ValueError("方案导出设置无效")
    return result


def read_segments(rows, info):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 1000:
        raise ValueError("方案片段数量无效")
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"start", "end", "speed", "mute", "deleted", "crop", "watermark"}:
            raise ValueError("方案片段格式无效")
        for key in ("start", "end", "speed"):
            if type(row[key]) not in (int, float) or not math.isfinite(row[key]):
                raise ValueError("方案时间或速度无效")
        if type(row["mute"]) is not bool or type(row["deleted"]) is not bool:
            raise ValueError("方案片段开关无效")
        if not (0 <= row["start"] < row["end"] <= info["duration"] + .001 and row["end"] - row["start"] >= .05):
            raise ValueError("方案片段超出原素材时长")
        crop, wm = row["crop"], row["watermark"]
        if crop is not None:
            if not isinstance(crop, (list, tuple)) or len(crop) != 4 or any(type(n) is not int for n in crop):
                raise ValueError("方案裁剪坐标无效")
            x, y, w, h = crop
            if min(x, y) < 0 or min(w, h) < 2 or x + w > info["width"] or y + h > info["height"]:
                raise ValueError("方案裁剪范围无效")
        if wm is not None:
            if (not isinstance(wm, dict) or set(wm) != {"x", "y", "w", "h", "mode"} or wm["mode"] != "delogo"
                    or any(type(wm[k]) is not int for k in ("x", "y", "w", "h"))
                    or min(wm["x"], wm["y"]) < 0 or min(wm["w"], wm["h"]) < 1
                    or wm["x"] + wm["w"] > info["width"] or wm["y"] + wm["h"] > info["height"]):
                raise ValueError("方案水印范围无效")
        seg = segmenter.Segment(**row)
        seg.crop = tuple(crop) if crop is not None else None
        if segmenter.validate_segments([seg]):
            raise ValueError("方案片段参数无效")
        result.append(seg)
    return result


def save(studio, directory, name="", export_options=None, progress=None):
    if not 1 <= len(studio.items) <= MAX_ITEMS:
        raise ValueError("请先添加 1–100 个素材")
    directory = settings.writable_directory(settings.validate({"output_dir": str(directory)})["output_dir"])
    paths = list(dict.fromkeys(str(Path(i.project.path).resolve()) for i in studio.items))
    size = sum(Path(p).stat().st_size for p in paths)
    if size > MAX_BYTES:
        raise ValueError("方案原素材合计超过 20 GB，请拆分保存")
    storage.require_space(directory, size + 64 * 1024 ** 2)
    manifest = dict(schema=1, options=options(export_options), items=[], media={})
    for i in studio.items:
        read_segments([asdict(s) for s in i.project.segments], i.project.info)
    output = storage.reserve_output(directory, name or "轻剪方案", "qjproj")
    try:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            names = {}
            for index, path in enumerate(paths):
                tasks.check()
                suffix = Path(path).suffix.lower()
                if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
                    suffix = ".mp4"
                entry = f"media/{index:04d}{suffix}"
                with Path(path).open("rb") as source, archive.open(entry, "w", force_zip64=True) as target:
                    digest = copy_stream(source, target)
                names[path] = entry
                manifest["media"][entry] = digest
                if progress:
                    progress((index + 1) / len(paths) * 95, f"保存原素材 {index + 1}/{len(paths)}")
            for item in studio.items:
                manifest["items"].append(dict(name=item.name[:200], media=names[str(Path(item.project.path).resolve())],
                    segments=[asdict(s) for s in item.project.segments]))
            encoded = json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(encoded) > MAX_MANIFEST:
                raise ValueError("方案片段过多，请拆分保存")
            archive.writestr("project.json", encoded)
        tasks.check()
        return output
    except BaseException:
        Path(output).unlink(missing_ok=True)
        raise


def load(path, progress=None):
    root = runtime.session_cache() / "projects"
    root.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="restore_", dir=root))
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            names = [e.filename for e in entries]
            if len(names) != len(set(names)) or not 2 <= len(names) <= MAX_ITEMS + 1 or "project.json" not in names:
                raise ValueError("方案文件列表无效")
            if archive.getinfo("project.json").file_size > MAX_MANIFEST:
                raise ValueError("方案清单过大")
            total = sum(e.file_size for e in entries)
            if total > MAX_BYTES + MAX_MANIFEST:
                raise ValueError("方案超过 20 GB 限制")
            storage.require_space(root, total + 64 * 1024 ** 2)
            for entry in entries:
                if (entry.filename != "project.json" and not re.fullmatch(r"media/[0-9]{4}\.[a-z0-9]{1,10}", entry.filename)
                        or stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1):
                    raise ValueError("方案包含不支持的文件路径或加密内容")
            manifest = json.loads(archive.read("project.json"))
            if type(manifest) is not dict or manifest.get("schema") != 1:
                raise ValueError("不支持的方案版本")
            items, media = manifest.get("items"), manifest.get("media")
            if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS or not isinstance(media, dict):
                raise ValueError("方案内容无效")
            if set(media) != set(names) - {"project.json"}:
                raise ValueError("方案素材清单不一致")
            restored = {}
            for index, (entry, expected) in enumerate(media.items()):
                target = work / Path(entry).name
                with archive.open(entry) as source, target.open("xb") as output:
                    digest = copy_stream(source, output)
                if digest != expected:
                    raise ValueError("方案素材校验失败，文件可能损坏")
                restored[entry] = target
                if progress:
                    progress((index + 1) / len(media) * 80, "恢复原素材")
            studio = Studio()
            for item in items:
                if not isinstance(item, dict) or item.get("media") not in restored or not isinstance(item.get("name"), str):
                    raise ValueError("方案素材引用无效")
                project = Workspace()
                source = restored[item["media"]]
                project.load(str(source), ffmpeg_util.get_video_info(source))
                project.segments = read_segments(item.get("segments"), project.info)
                studio.add(project, item["name"][:200])
            tasks.check()
            return studio, options(manifest.get("options"))
    except BaseException:
        if storage._safe_tree(work, root):
            shutil.rmtree(work)
        raise
