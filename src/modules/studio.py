"""Session-owned multi-source job list. Editor snapshots never share segments."""
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import re
import uuid

from . import tasks, ffmpeg_util, settings
from .workspace import Workspace
from .pipeline import VideoPipeline
from .audio_export import export_audio

FORMATS = ["通用 MP4", "较小 MP4", "GIF 动图", "M4A 音频", "MP3 音频", "WAV 音频"]
MAX_ITEMS = 100


@dataclass
class Item:
    name: str
    project: Workspace
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = "待处理"
    output: str = ""
    signature: tuple = ()


def clone(project):
    if not project.path or not project.segments:
        raise ValueError("请先导入素材并设置片段")
    result = Workspace()
    result.load(project.path, deepcopy(project.info))
    result.segments = deepcopy(project.segments)
    result.selected = min(project.selected, len(result.segments) - 1)
    return result


@dataclass
class Studio:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    items: list = field(default_factory=list)
    selected: str = ""
    parts: list = field(default_factory=list)
    merged_output: str = ""

    def current(self):
        return next((item for item in self.items if item.id == self.selected), None)

    def add(self, project, name=""):
        if len(self.items) >= MAX_ITEMS:
            raise ValueError("每个方案最多 100 个素材，请分批处理")
        item = Item(name or Path(project.path).name, clone(project))
        self.items.append(item)
        self.selected = item.id
        self.merged_output = ""
        return item

    def add_path(self, path, name=""):
        project = Workspace()
        project.load(str(path), ffmpeg_util.get_video_info(path))
        return self.add(project, name)

    def edit(self, action):
        item = self.current()
        if not item:
            raise ValueError("请先选择列表中的素材")
        i = self.items.index(item)
        if action == "delete":
            self.items.pop(i)
            self.selected = self.items[min(i, len(self.items) - 1)].id if self.items else ""
        elif action in ("up", "down"):
            j = max(0, min(len(self.items) - 1, i + (-1 if action == "up" else 1)))
            self.items[i], self.items[j] = self.items[j], self.items[i]
        self.merged_output = ""

    def outputs(self):
        return list(dict.fromkeys(p for p in [self.merged_output] + [i.output for i in self.items] if p and Path(p).is_file()))


def export_sources(sources, format_name, directory, name, acceleration, fps, scale, progress):
    if format_name not in FORMATS:
        raise ValueError("请选择有效的导出格式")
    if format_name.endswith("音频"):
        return export_audio(sources, directory, name, format_name.split()[0].lower(), progress)
    return VideoPipeline().process_many(sources, out_dir=directory, out_name=name,
        out_format="gif" if format_name == "GIF 动图" else "mp4", preset="small" if format_name == "较小 MP4" else "standard",
        acceleration=acceleration, gif_fps=fps, gif_scale=scale, on_progress=progress)


def run(studio, merge, format_name, directory, name="", acceleration="auto", fps=15, scale=.5, resume=False, progress=None):
    """Caller holds tasks.task(studio.id); never yield while a task context is live."""
    if not studio.items:
        raise ValueError("请先添加素材")
    directory = settings.validate({"output_dir": directory})["output_dir"]
    snapshot = deepcopy(studio.items)
    signature = (format_name, str(Path(directory).resolve()), name, acceleration, fps, scale)
    def report(p, message):
        tasks.check()
        if progress:
            progress(p, message)
    if merge:
        studio.merged_output = ""
        sources = [(i.project.path, i.project.segments) for i in snapshot]
        studio.merged_output = export_sources(sources, format_name, directory, name, acceleration, fps, scale, report)
        return "拼接导出完成"
    studio.merged_output = ""
    completed, failed = 0, 0
    for index, saved in enumerate(snapshot):
        tasks.check()
        item = studio.items[index]
        if resume and item.status == "已完成" and item.signature == signature and Path(item.output).is_file():
            completed += 1
            continue
        item.status, item.output = "处理中", ""
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(saved.name).stem).strip(" .")[:65] or "素材"
        filename = f"{name or '批量'}_{index + 1:03d}_{stem}"
        try:
            item.output = export_sources([(saved.project.path, saved.project.segments)], format_name, directory,
                filename, acceleration, fps, scale,
                lambda p, m: report((index + p / 100) / len(snapshot) * 100, f"素材 {index + 1}/{len(snapshot)} · {m}"))
            item.status, item.signature = "已完成", signature
            completed += 1
        except tasks.Cancelled:
            item.status = "已取消"
            raise
        except Exception as error:
            item.status = tasks.friendly_error(error)
            failed += 1
    return f"批量任务完成：成功 {completed} 项，失败 {failed} 项。可点击“继续未完成任务”重试。"
