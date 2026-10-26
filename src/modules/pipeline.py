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
from typing import List, Optional

from . import editor, exporter, ffmpeg_util, segmenter
from .ffmpeg_util import ProgressCallback
from .segmenter import Segment


class VideoPipeline:
    """视频处理流水线。"""

    def __init__(self, work_dir: Optional[str] = None):
        # 临时文件目录（中间渲染文件），默认用系统临时目录
        self.work_dir = work_dir or os.path.join(tempfile.gettempdir(), "bili_video_tool")

    # ------------------------------------------------------------------
    def _common_size(self, input_path: str, segments: List[Segment]) -> Optional[tuple]:
        """计算统一的输出分辨率。

        规则：取第一个"设置过裁剪"的保留片段的裁剪尺寸作为统一分辨率，
        其余片段会自动等比缩放 + 黑边补齐到该尺寸（保证拼接成功）。
        若所有片段都没有裁剪，则返回 None（保持原分辨率）。
        """
        info = ffmpeg_util.get_video_info(input_path)
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

        # ---------- 2. 计算统一分辨率 ----------
        common_size = self._common_size(input_path, segments)

        # ---------- 3. 逐个渲染保留片段 ----------
        tmp_dir = tempfile.mkdtemp(prefix="seg_", dir=self.work_dir)
        intermediate_files: List[str] = []
        try:
            for i, seg in enumerate(kept):
                seg_path = os.path.join(tmp_dir, f"seg_{i:03d}.mp4")
                editor.render_segment(
                    input_path, seg, seg_path, common_size=common_size,
                    on_progress=on_progress, seg_index=i, seg_total=len(kept),
                )
                intermediate_files.append(seg_path)

            # ---------- 4. 导出 ----------
            out_ext = out_format.lower().lstrip(".")
            if out_ext == "gif":
                out_name = out_name or f"output_{int(time.time())}"
                out_path = os.path.join(out_dir, f"{out_name}.gif")
                exporter.export_gif(
                    intermediate_files, out_path,
                    fps=gif_fps, scale=gif_scale, on_progress=on_progress,
                )
            else:  # mp4
                out_name = out_name or f"output_{int(time.time())}"
                out_path = os.path.join(out_dir, f"{out_name}.mp4")
                exporter.export_mp4(intermediate_files, out_path, on_progress=on_progress)

            if on_progress:
                on_progress(100.0, "全部完成")
            return out_path

        finally:
            # ---------- 5. 清理临时文件 ----------
            for f in intermediate_files:
                try:
                    os.remove(f)
                except OSError:
                    pass
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass
