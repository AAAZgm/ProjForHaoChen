"""Probe real NVENC initialization, not merely the compiled encoder list."""
from functools import lru_cache
import os
import subprocess

from . import ffmpeg_util, diagnostics, tasks


class HardwareEncodingError(RuntimeError):
    pass


class HardwareDecodingError(RuntimeError):
    pass


def select_decoder(encoder, info):
    # Enable only the AV1 8-bit, unrotated path covered by media regressions.
    # Driver/codec initialization is tested by the actual render; failure retries
    # all segments in software while retaining NVENC if it remains usable.
    return "av1_cuvid" if (encoder == "nvenc" and info.get("codec") == "av1"
        and info.get("pixel_format") == "yuv420p" and not info.get("rotation")) else "cpu"


@lru_cache(maxsize=16)
def nvenc_available(width, height):
    try:
        result = subprocess.run([ffmpeg_util.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi",
            "-i", f"color=size={width}x{height}:rate=30", "-frames:v", "3",
            *video_args("nvenc", 20), "-f", "null", "-"], capture_output=True, timeout=12,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode:
            diagnostics.LOG.info("NVENC unavailable: %s", result.stderr.decode("utf-8", errors="replace")[-1500:])
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as error:
        diagnostics.LOG.info("NVENC probe: %s", error)
        return False


def select(mode, width, height):
    if mode not in ("auto", "cpu"):
        raise ValueError("请选择自动加速或 CPU 兼容模式")
    tasks.check()
    choice = "nvenc" if mode == "auto" and nvenc_available(width, height) else "cpu"
    tasks.check()
    return choice


def video_args(encoder, crf):
    if encoder == "nvenc":
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-tune", "hq", "-rc", "vbr",
                "-cq", str(crf + 3), "-b:v", "0", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p"]


def label(encoder, decoder="cpu"):
    if encoder == "nvenc" and decoder == "av1_cuvid":
        return "NVIDIA 显卡解码 + 编码"
    return "NVIDIA 显卡编码" if encoder == "nvenc" else "CPU 兼容编码"
