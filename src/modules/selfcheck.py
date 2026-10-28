"""Offline smoke check that also runs inside the frozen executable."""

import importlib.metadata
import platform
from pathlib import Path
import sys
import tempfile

from . import ffmpeg_util, runtime
from .pipeline import VideoPipeline
from .segmenter import Segment


def run_self_check(output_dir: str) -> dict:
    base = Path(output_dir).resolve()
    base.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="selfcheck_", dir=base))
    source = directory / "原始 样例.mp4"
    ffmpeg_util.run_ffmpeg([
        "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
        "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        str(source),
    ])
    pipeline = VideoPipeline(work_dir=str(directory / "work"))
    output = pipeline.process(
        str(source),
        [Segment(0, 1, speed=2, mute=True, crop=(0, 0, 120, 100)),
         Segment(1, 2, watermark={"x": 10, "y": 10, "w": 20, "h": 12})],
        out_dir=str(directory), out_name="处理结果",
    )
    info = ffmpeg_util.get_video_info(output)
    if not (info["width"] == 120 and info["height"] == 100
            and info["has_audio"] and abs(info["duration"] - 1.5) < 0.2):
        raise RuntimeError(f"导出结果不符合预期：{info}")
    # A readable container is insufficient: decode every output frame as well.
    ffmpeg_util.run_ffmpeg(["-v", "error", "-i", output, "-f", "null", "-"])
    if any((directory / "work").iterdir()):
        raise RuntimeError("处理完成后仍有片段临时文件残留")
    # Exercise hardware selection inside the shipped EXE as well. Machines
    # without an available NVIDIA encoder must complete the same export on CPU.
    auto_source = directory / "加速样例.mp4"
    ffmpeg_util.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=320x240:rate=30:duration=1",
                          "-c:v", "libaom-av1", "-cpu-used", "8", "-threads", "2", str(auto_source)])
    auto_output = pipeline.process(str(auto_source),
        [Segment(0, .5, mute=True, watermark={"x": 10, "y": 10, "w": 24, "h": 18}),
         Segment(.5, 1, mute=True)], out_dir=str(directory), out_name="自动编码结果", acceleration="auto")
    auto_info = ffmpeg_util.get_video_info(auto_output)
    ffmpeg_util.run_ffmpeg(["-v", "error", "-i", auto_output, "-f", "null", "-"])
    if auto_info["width"] != 320 or abs(auto_info["duration"] - 1) > .15 or any((directory / "work").iterdir()):
        raise RuntimeError(f"自动编码结果不符合预期：{auto_info}")
    return {
        "status": "passed", "version": runtime.APP_VERSION,
        "python": platform.python_version(), "platform": platform.platform(),
        "frozen": bool(getattr(sys, "frozen", False)), "utf8_mode": sys.flags.utf8_mode,
        "ffmpeg": ffmpeg_util.get_ffmpeg_exe(), "ffprobe": ffmpeg_util.get_ffprobe_exe(), "directory": str(directory),
        "output": output, "media": info,
        "auto_encoding": {"engine": pipeline.last_engine, "decoder": pipeline.last_decoder,
                          "output": auto_output, "media": auto_info},
        "dependencies": {name: importlib.metadata.version(name) for name in
                         ("gradio", "yt-dlp", "imageio-ffmpeg", "Pillow")},
    }
