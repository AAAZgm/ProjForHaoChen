"""File naming, explicit open actions and conservative cache housekeeping."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

from . import runtime


def filename(value):
    value = str(value or "").strip()
    if not value:
        return f"轻剪_{time.strftime('%Y%m%d_%H%M%S')}"
    if len(value) > 120 or re.search(r'[<>:"/\\|?*\x00-\x1f]', value) or value.endswith((".", " ")):
        raise ValueError("文件名请勿包含路径或特殊符号，长度不超过 120 个字符")
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}:
        raise ValueError("该名称是系统保留名称，请换一个文件名")
    return value


def reserve_output(directory, name, extension):
    """Reserve with exclusive creation so concurrent exports cannot overwrite files."""
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    stem = filename(name)
    for index in range(100):
        suffix = "" if index == 0 else f"_{uuid.uuid4().hex[:8]}"
        path = root / f"{stem}{suffix}.{extension}"
        try:
            with path.open("xb"):
                pass
            return str(path)
        except FileExistsError:
            continue
    raise RuntimeError("无法生成不重复的文件名，请换一个名称")


def require_space(directory, minimum=64 * 1024 * 1024):
    if shutil.disk_usage(directory).free < minimum:
        raise OSError(28, "磁盘可用空间不足，请清理空间或更换保存目录")


def _linked(path):
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _safe_tree(path, root):
    if _linked(path) or not path.resolve().is_relative_to(root.resolve()) or path.resolve() == root.resolve():
        return False
    # Do not traverse junctions/symlinks, even when they point inside the cache.
    for base, directories, files in os.walk(path, followlinks=False):
        if any(_linked(Path(base) / name) for name in directories + files):
            return False
    return True


def clean_cache(days=0):
    """Only delete prior *runs*. The entire current run stays protected."""
    root = runtime.cache_dir() / "runs"
    if _linked(runtime.cache_dir()) or _linked(root):
        raise ValueError("缓存目录是文件系统链接，已跳过清理。请检查配置目录。")
    root.mkdir(parents=True, exist_ok=True)
    current = runtime.session_cache().resolve()
    removed, skipped, size = 0, 0, 0
    cutoff = time.time() - float(days) * 86400
    for path in root.iterdir():
        if not path.is_dir() or path.resolve() == current or not re.fullmatch(r"[0-9a-f]{32}", path.name):
            continue
        try:
            if path.stat().st_mtime > cutoff or not _safe_tree(path, root):
                skipped += 1
                continue
            count = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            shutil.rmtree(path)
            removed += 1
            size += count
        except OSError:
            skipped += 1
    return removed, size, skipped


def clean_current_run():
    path = runtime.session_cache()
    root = runtime.cache_dir() / "runs"
    if not _linked(runtime.cache_dir()) and not _linked(root) and path.is_dir() and _safe_tree(path, root):
        shutil.rmtree(path, ignore_errors=True)


def open_local(path, folder=False):
    path = Path(path).resolve()
    if not path.exists():
        raise ValueError("文件已被移动或删除，请检查保存位置")
    if not folder and path.suffix.lower() not in (".mp4", ".gif"):
        raise ValueError("只能打开本程序导出的 MP4 或 GIF 文件")
    if folder:
        path = path if path.is_dir() else path.parent
    if os.name == "nt":
        os.startfile(str(path))
    else:
        import sys
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
