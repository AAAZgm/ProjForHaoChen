"""Session-owned editing model; operations preserve user order and undo history."""

from copy import deepcopy
from dataclasses import dataclass, field, replace
import math
import uuid

from . import editor, segmenter
from .segmenter import Segment


def number(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("请输入有效数字")
    return result


@dataclass
class Workspace:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    media_id: str = ""
    path: str = ""
    last_output: str = ""
    info: dict = field(default_factory=dict)
    segments: list = field(default_factory=list)
    selected: int = 0
    undo_stack: list = field(default_factory=list)
    redo_stack: list = field(default_factory=list)

    def load(self, path, info):
        if info["duration"] <= 0 or min(info["width"], info["height"]) < 2:
            raise ValueError("无法读取有效视频，请换一个 MP4/MOV 等视频文件")
        self.media_id = uuid.uuid4().hex
        self.path, self.info = path, info
        self.segments = segmenter.make_full_segment(info["duration"])
        self.selected = 0
        self.undo_stack.clear()
        self.redo_stack.clear()

    def current(self):
        if not self.segments:
            raise ValueError("请先导入视频，或撤销删除操作")
        self.selected = max(0, min(self.selected, len(self.segments) - 1))
        return self.segments[self.selected]

    def snapshot(self):
        return deepcopy((self.segments, self.selected))

    def commit(self, segments, selected=None):
        self.undo_stack.append(self.snapshot())
        self.undo_stack = self.undo_stack[-50:]
        self.redo_stack.clear()
        self.segments = deepcopy(segments)
        self.selected = max(0, min(self.selected if selected is None else selected, len(segments) - 1))

    def history(self, redo=False):
        source, target = (self.redo_stack, self.undo_stack) if redo else (self.undo_stack, self.redo_stack)
        if not source:
            raise ValueError("没有可重做的操作" if redo else "没有可撤销的操作")
        target.append(self.snapshot())
        self.segments, self.selected = source.pop()

    def split(self, at):
        seg = self.current()
        at = number(at)
        if at - seg.start < 0.05 or seg.end - at < 0.05:
            raise ValueError("分割位置需在当前片段内部，两侧至少保留 0.05 秒")
        rows = deepcopy(self.segments)
        rows[self.selected:self.selected + 1] = [replace(seg, end=at), replace(seg, start=at)]
        self.commit(rows)

    def trim(self, start, end):
        self.current()
        start, end = number(start), number(end)
        if not 0 <= start < end <= self.info["duration"] or end - start < 0.05:
            raise ValueError("起止时间必须在视频范围内，且至少保留 0.05 秒")
        rows = deepcopy(self.segments)
        rows[self.selected] = replace(rows[self.selected], start=start, end=end)
        self.commit(rows)

    def move(self, delta):
        self.current()
        destination = self.selected + delta
        if not 0 <= destination < len(self.segments):
            raise ValueError("已到列表边界")
        rows = deepcopy(self.segments)
        rows[self.selected], rows[destination] = rows[destination], rows[self.selected]
        self.commit(rows, destination)

    def delete(self):
        self.current()
        rows = deepcopy(self.segments)
        del rows[self.selected]
        self.commit(rows)

    def effects(self, mute, speed, all_segments=False):
        self.current()
        speed = number(speed)
        if not 0.25 <= speed <= 4:
            raise ValueError("倍速需为 0.25–4")
        rows = deepcopy(self.segments)
        for i, row in enumerate(rows):
            if all_segments or i == self.selected:
                row.mute, row.speed = bool(mute), speed
        self.commit(rows)

    def region(self, payload, mode, all_segments=False):
        self.current()
        if payload.get("media_id") != self.media_id:
            raise ValueError("画面已过期，请重新提取当前素材画面")
        rect = [number(v) for v in payload.get("rect", [])]
        if len(rect) != 4 or not all(0 <= v <= 1 for v in rect):
            raise ValueError("请先在画面上拖出矩形区域")
        x1, y1, x2, y2 = rect
        width, height = self.info["width"], self.info["height"]
        x, y = round(min(x1, x2) * width), round(min(y1, y2) * height)
        w, h = round(max(x1, x2) * width) - x, round(max(y1, y2) * height) - y
        w, h = min(w, width - x), min(h, height - y)
        if min(w, h) < 2:
            raise ValueError("选区太小，请重新框选")
        rows = deepcopy(self.segments)
        for i, row in enumerate(rows):
            if all_segments or i == self.selected:
                if mode == "裁剪画面":
                    row.crop = (x, y, w // 2 * 2, h // 2 * 2)
                else:
                    row.watermark = editor.sanitize_watermark(dict(x=x, y=y, w=w, h=h), width, height)
                    if not row.watermark:
                        raise ValueError("该选区无法进行水印淡化，请调整范围")
        self.commit(rows)

    def clear_region(self, all_segments=False):
        self.current()
        rows = deepcopy(self.segments)
        for i, row in enumerate(rows):
            if all_segments or i == self.selected:
                row.crop = row.watermark = None
        self.commit(rows)

    def estimate(self, preset="通用 MP4"):
        kept = [s for s in self.segments if not s.deleted]
        duration = segmenter.estimate_output_duration(kept)
        w, h = self.info.get("width", 0), self.info.get("height", 0)
        for s in kept:
            if s.crop:
                w, h = s.crop[2:]
                break
        if preset == "较小 MP4" and max(w, h) > 1280:
            scale = 1280 / max(w, h)
            w, h = int(w * scale), int(h * scale)
        return duration, w // 2 * 2, h // 2 * 2
