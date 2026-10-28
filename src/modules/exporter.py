# -*- coding: utf-8 -*-
"""
导出模块（拼接 + 导出 mp4 / gif）
================================
职责：
  1. concat_videos()：把多个"标准化中间视频"拼接为一个完整视频
     （管线标准片段复制视频流拼接；其他调用使用 concat 滤镜重新编码）
  2. export_mp4()：导出为 mp4（H.264 + AAC，兼容几乎所有播放器）
  3. export_gif()：导出为 gif（使用调色板优化，画质好、体积小）

二次开发提示：
  如需添加新的导出格式（如 webm、逐帧图片序列），照 export_mp4 的
  模式新增一个函数即可：用 ffmpeg_util.run_ffmpeg 执行 ffmpeg 命令。
"""

import os
from pathlib import Path
import tempfile
from typing import List, Optional

from . import ffmpeg_util
from .ffmpeg_util import ProgressCallback


# ---------------------------------------------------------------------------
# 片段拼接
# ---------------------------------------------------------------------------
def concat_videos(
    video_files: List[str],
    out_path: str,
    on_progress: ProgressCallback = None,
    crf: int = 20,
    normalized: bool = False,
) -> str:
    """拼接视频；normalized 仅供同次管线产生的标准片段使用。

    标准片段保留已编码视频，音频对齐后重编码；外部调用默认用 concat 滤镜。
    """
    if not video_files:
        raise RuntimeError("没有可拼接的片段（可能全部被删除了）")

    if len(video_files) == 1:
        # 只有一个片段：直接复制为最终文件（减少一次重编码损耗）
        # 注意：仍需重新封装 mp4，保证导出参数一致
        args = ["-i", video_files[0], "-c", "copy", "-movflags", "+faststart", str(out_path)]
        ffmpeg_util.run_ffmpeg(args, total_duration=0, on_progress=on_progress, extra_message="拼接中")
        return out_path

    if normalized:
        # Only our own normalized H.264/stereo AAC segments use this fast path.
        # External callers retain the general concat-filter implementation below.
        with tempfile.TemporaryDirectory(prefix="concat_", dir=Path(out_path).resolve().parent) as work:
            manifest = Path(work) / "segments.ffconcat"
            lines, total = ["ffconcat version 1.0"], 0.0
            for file in video_files:
                duration = ffmpeg_util.get_video_info(file)["duration"]
                total += duration
                escaped = Path(file).resolve().as_posix().replace("'", "'\\''")
                lines.extend([f"file '{escaped}'", f"duration {duration:.9f}"])
            manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
            # Video is already encoded once. Audio is re-timed/re-encoded to
            # avoid accumulating AAC frame padding across many cuts.
            args = ["-f", "concat", "-safe", "0", "-i", str(manifest), "-map", "0:v:0", "-map", "0:a:0",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-af", f"aresample=async=1:first_pts=0,apad,atrim=duration={total:.9f}",
                    "-movflags", "+faststart", str(out_path)]
            ffmpeg_util.run_ffmpeg(args, total_duration=total, on_progress=on_progress, extra_message="合并片段（保留已编码画面）")
        return out_path

    # 多个片段：构造 concat 滤镜
    #   [0:v][0:a][1:v][1:a]...concat=n=N:v=1:a=1[v][a]
    #   a=1 表示有音频（所有片段统一有/无音频，此处用第一个片段判断）
    has_audio = False
    # 用 ffmpeg 探测第一个文件是否含音频
    probe = ffmpeg_util.get_video_info(video_files[0])
    has_audio = probe["has_audio"]

    args = []
    for f in video_files:
        args += ["-i", f]

    n = len(video_files)
    if has_audio:
        concat_fm = "".join(f"[{i}:v][{i}:a]" for i in range(n))
        concat_fm += f"concat=n={n}:v=1:a=1[v][a]"
        args += ["-filter_complex", concat_fm, "-map", "[v]", "-map", "[a]"]
    else:
        concat_fm = "".join(f"[{i}:v]" for i in range(n))
        concat_fm += f"concat=n={n}:v=1:a=0[v]"
        args += ["-filter_complex", concat_fm, "-map", "[v]"]

    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
             "-pix_fmt", "yuv420p"]
    if has_audio:
        args += ["-c:a", "aac", "-b:a", "128k"]
    args += ["-movflags", "+faststart", str(out_path)]

    total = sum(ffmpeg_util.get_video_info(f)["duration"] for f in video_files)
    ffmpeg_util.run_ffmpeg(args, total_duration=total, on_progress=on_progress, extra_message="拼接中")
    return out_path


# ---------------------------------------------------------------------------
# 导出为 mp4
# ---------------------------------------------------------------------------
def export_mp4(
    video_files: List[str],
    out_path: str,
    on_progress: ProgressCallback = None,
    crf: int = 20,
    normalized: bool = False,
) -> str:
    """导出为 mp4：先拼接，再重新封装为 mp4。

    如果输入只有一个文件，concat_videos 内部会直接复制，不重复转码。
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    return concat_videos(video_files, out_path, on_progress, crf=crf, normalized=normalized)


# ---------------------------------------------------------------------------
# 导出为 gif
# ---------------------------------------------------------------------------
def export_gif(
    video_files: List[str],
    out_path: str,
    fps: int = 15,
    scale: float = 0.5,
    on_progress: ProgressCallback = None,
    normalized: bool = False,
) -> str:
    """导出为 gif 动图。

    参数：
      video_files 待拼接的视频文件列表（内部先拼接再转 gif）
      out_path    输出路径（.gif）
      fps         gif 帧率（建议 10~20，越大文件越大）
      scale       gif 缩放比例（如 0.5 = 宽高各缩小一半，减小体积）

    质量优化：使用 palettegen + paletteuse 两遍法，
    先生成调色板再着色，比直接转 gif 画质明显更好。
    """
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    # 第一步：先把多个片段拼接为临时 mp4（拼接逻辑复用）
    tmp_concat = out_path + ".tmp.mp4"
    try:
        def part(start, span):
            return (lambda p, m: on_progress(start + span * p / 100, m)) if on_progress else None
        concat_videos(video_files, tmp_concat, on_progress=part(0, 30), normalized=normalized)

        # 第二步：临时 mp4 -> gif（palettegen + paletteuse 两遍法）
        vf = (
            f"fps={int(fps)},"
            f"scale=trunc(iw*{scale}/2)*2:trunc(ih*{scale}/2)*2:flags=lanczos,"
            f"split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer"
        )
        args = ["-i", tmp_concat, "-vf", vf, str(out_path)]
        # gif 转码需要读取出时长来报进度
        info = ffmpeg_util.get_video_info(tmp_concat)
        ffmpeg_util.run_ffmpeg(args, total_duration=info["duration"],
                               on_progress=part(30, 70), extra_message="生成 GIF 中")
    finally:
        # 清理临时文件
        if os.path.exists(tmp_concat):
            os.remove(tmp_concat)
    return out_path
