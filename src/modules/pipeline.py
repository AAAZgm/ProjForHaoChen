# -*- coding: utf-8 -*-
"""
处理管线模块（总调度）
====================
职责：
  把"原视频 + 片段列表 + 导出设置"串成一条完整流水线：

    读取视频信息 -> 清洗/校验片段 -> 计算统一分辨率
    -> 逐个片段渲染中间文件 -> 拼接 -> 导出 mp4 / gif -> 清理临时文件

  这是程序化调用的总入口，网页界面（main.py）最终也是调用这里。

二次开发提示（示例）：
    from modules.pipeline import VideoPipeline
    from modules.segmenter import Segment

    pipe = VideoPipeline()
    segments = [
        Segment(0, 10, speed=1.5, mute=True),          # 第1段：1.5倍速+消音
        Segment(10, 20, watermark={"x":1700,"y":900,"w":180,"h":60,"mode":"delogo"}),
    ]
    pipe.process("input.mp4", segments, out_format="gif", gif_fps=12, gif_scale=0.5)
"""

import os
import tempfile
import time
import uuid
from typing import List, Optional

from . import editor, exporter, ffmpeg_util, segmenter, tasks, runtime, storage, settings, encoding, diagnostics
from .ffmpeg_util import ProgressCallback
from .segmenter import Segment


class VideoPipeline:
    """视频处理流水线。"""

    def __init__(self, work_dir: Optional[str] = None):
        self.work_dir = work_dir or str(runtime.session_cache() / "work")
        self.last_engine = "cpu"
        self.last_decoder = "cpu"

    # ------------------------------------------------------------------
    def _common_size(self, input_path: str, segments: List[Segment], info=None) -> Optional[tuple]:
        """计算统一的输出分辨率。

        规则：取第一个"设置过裁剪"的保留片段的裁剪尺寸作为统一分辨率，
        其余片段会自动等比缩放 + 黑边补齐到该尺寸（保证拼接成功）。
        若所有片段都没有裁剪，则返回 None（保持原分辨率）。
        """
        info = info or ffmpeg_util.get_video_info(input_path)
        for seg in segments:
            if not seg.deleted and seg.crop:
                _, _, w, h = seg.crop
                # libx264 要求偶数尺寸
                return (w // 2 * 2, h // 2 * 2)
        # 没有裁剪：若原分辨率是奇数则修正为偶数
        w, h = info["width"], info["height"]
        if w % 2 or h % 2:
            return (w // 2 * 2, h // 2 * 2)
        return None

    # ------------------------------------------------------------------
    def process(
        self,
        input_path: str,
        segments: List[Segment],
        out_format: str = "mp4",          # 导出格式：mp4 / gif
        out_dir: str = "output",
        out_name: str = "",
        gif_fps: int = 15,                # gif 帧率
        gif_scale: float = 0.5,           # gif 缩放比例
        on_progress: ProgressCallback = None,
        preset: str = "standard",
        acceleration: str = "cpu",
    ) -> str:
        """执行完整处理流水线，返回导出文件路径。

        参数说明：
          input_path  原视频文件路径
          segments    片段列表（由 segmenter.Segment 构成）
          out_format  导出格式 mp4 / gif
          out_dir     输出目录
          out_name    输出文件名（不含扩展名），默认 "output_时间戳"
          gif_fps / gif_scale  gif 导出参数
          on_progress 进度回调 callback(percent, message)
        """
        # ---------- 0. 准备 ----------
        os.makedirs(out_dir, exist_ok=True)
        os.makedirs(self.work_dir, exist_ok=True)
        settings.writable_directory(out_dir)
        storage.require_space(out_dir)
        storage.require_space(self.work_dir)

        # 读取视频信息
        info = ffmpeg_util.get_video_info(input_path)
        if info["duration"] <= 0:
            raise RuntimeError("无法读取视频时长，请确认文件是有效的视频")

        # ---------- 1. 清洗与校验片段 ----------
        segments = segmenter.sanitize_segments(segments, info["duration"])
        if not segments:
            raise RuntimeError("没有有效的片段（请检查起止时间）")
        errors = segmenter.validate_segments(segments)
        if errors:
            raise RuntimeError("片段参数有误：\n" + "\n".join(errors))

        # 统计保留片段
        kept = [s for s in segments if not s.deleted]
        if not kept:
            raise RuntimeError("所有片段都被删除了，没有可导出的内容")

        for seg in kept:
            if seg.crop:
                x, y, w, h = seg.crop
                if x < 0 or y < 0 or w < 2 or h < 2 or x + w > info["width"] or y + h > info["height"]:
                    raise ValueError("裁剪区域必须位于画面内，宽高至少为 2 像素")

        # ---------- 2. 计算统一分辨率 ----------
        common_size = self._common_size(input_path, segments, info)
        crf = 26 if preset == "small" else 20
        if preset in ("small", "preview"):
            w, h = common_size or (info["width"], info["height"])
            ratio = min(1, (720 if preset == "preview" else 1280) / max(w, h))
            common_size = (max(2, int(w * ratio) // 2 * 2), max(2, int(h * ratio) // 2 * 2))

        last_progress = 0.0
        started = time.monotonic()
        def report(value, message):
            nonlocal last_progress
            tasks.check()
            last_progress = max(last_progress, min(100, value))
            if on_progress:
                elapsed = time.monotonic() - started
                if elapsed >= 5 and 2 < last_progress < 98:
                    remaining = elapsed * (100 - last_progress) / last_progress
                    message += f" · 已用 {int(elapsed)} 秒 · 剩余约 {max(1, round(remaining / 60))} 分钟"
                on_progress(last_progress, message)

        def part(start, span):
            return lambda p, m: report(start + span * p / 100, m)

        out_ext = out_format.lower().lstrip(".")
        if out_ext not in ("mp4", "gif"):
            raise ValueError("仅支持 MP4 和 GIF")
        if not 5 <= gif_fps <= 30 or not 0.1 <= gif_scale <= 1:
            raise ValueError("GIF 帧率需为 5–30，缩放比例需为 0.1–1")
        out_name = out_name or f"output_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        self.last_engine = encoding.select(acceleration, *(common_size or (info['width'], info['height'])))
        self.last_decoder = encoding.select_decoder(self.last_engine, info)
        diagnostics.LOG.info("Export encoder: %s, %sx%s, %s segments", self.last_engine, info['width'], info['height'], len(kept))
        diagnostics.LOG.info("Export decoder: %s; source codec: %s; preset: %s; source/output seconds: %.3f/%.3f",
            self.last_decoder, info.get("codec"), preset, info['duration'], sum(s.output_duration() for s in kept))
        out_path = storage.reserve_output(out_dir, out_name, out_ext)

        # ---------- 3. 逐个渲染保留片段 ----------
        intermediate_files: List[str] = []
        try:
            with tempfile.TemporaryDirectory(prefix="seg_", dir=self.work_dir) as tmp_dir:
                total = sum(s.output_duration() for s in kept)
                report(2, "已读取素材，准备处理")
                def render_all():
                    completed = 0.0
                    intermediate_files.clear()
                    for i, seg in enumerate(kept):
                        tasks.check()
                        seg_path = os.path.join(tmp_dir, f"seg_{i:03d}.mp4")
                        span = 78 * seg.output_duration() / total
                        editor.render_segment(input_path, seg, seg_path, common_size=common_size,
                            on_progress=part(2 + completed, span), seg_index=i, seg_total=len(kept), crf=crf,
                            encoder=self.last_engine, source_info=info, decoder=self.last_decoder)
                        completed += span
                        intermediate_files.append(seg_path)
                try:
                    try:
                        render_all()
                    except encoding.HardwareDecodingError as error:
                        diagnostics.LOG.warning("GPU decode/render failed; retrying with software decoding: %s", error)
                        self.last_decoder = "cpu"
                        report(last_progress, "显卡解码暂不可用，改用 CPU 解码重新处理")
                        render_all()
                except encoding.HardwareEncodingError as error:
                    diagnostics.LOG.warning("NVENC failed; retrying entire export on CPU: %s", error)
                    self.last_engine = "cpu"
                    self.last_decoder = "cpu"
                    report(last_progress, "显卡编码暂不可用，正在用 CPU 重新处理")
                    render_all()
                if out_ext == "gif":
                    exporter.export_gif(intermediate_files, out_path, fps=gif_fps,
                                        scale=gif_scale, on_progress=part(80, 19), normalized=True)
                else:
                    exporter.export_mp4(intermediate_files, out_path,
                                         on_progress=part(80, 19), crf=crf, normalized=True)
                report(100, "全部完成")
                return out_path
        except BaseException:
            if os.path.isfile(out_path):
                os.remove(out_path)
            raise
