# -*- coding: utf-8 -*-
"""
ffmpeg 工具模块
==============
职责：
  1. 定位可用的 ffmpeg 可执行文件（优先使用 imageio-ffmpeg 自带的二进制，
     这样用户无需手动安装 ffmpeg，对小白最友好；找不到时回退到系统 PATH）
  2. 封装 ffmpeg 命令执行，支持进度回调（解析 -progress 输出）
  3. 读取视频基本信息（时长、分辨率、帧率、音频采样率）

二次开发提示：
  所有处理模块（editor / exporter）都通过 get_ffmpeg_exe() 获取 ffmpeg 路径，
  如果你想替换为自己的 ffmpeg，只需修改 get_ffmpeg_exe() 即可。
"""

import os
import json
import math
from pathlib import Path
import sys
from fractions import Fraction
import shutil
import subprocess
import threading
from typing import Callable, Dict, Optional
from . import tasks, runtime, process_performance

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
DEFAULT_FPS = 30          # 片段标准化帧率（保证拼接时参数一致）
DEFAULT_SAMPLE_RATE = 44100  # 片段标准化音频采样率（保证拼接时参数一致）

# 进度回调函数签名：callback(percent: float, message: str)
ProgressCallback = Optional[Callable[[float, str], None]]


# ---------------------------------------------------------------------------
# ffmpeg 二进制定位
# ---------------------------------------------------------------------------
def get_ffmpeg_exe() -> str:
    """返回 ffmpeg 可执行文件路径。

    优先级：imageio-ffmpeg 自带二进制 > 系统 PATH 中的 ffmpeg。
    """
    # 方式1：imageio-ffmpeg 自带静态二进制（pip 安装即可用，无需系统安装）
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        return exe
    except Exception:
        pass
    # 方式2：系统 PATH 中查找
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    raise RuntimeError(
        "未找到 ffmpeg！请先执行 pip install imageio-ffmpeg，"
        "或手动安装 ffmpeg 并加入系统 PATH。"
    )


# ---------------------------------------------------------------------------
# 视频信息读取
# ---------------------------------------------------------------------------
def get_ffprobe_exe() -> str:
    root = Path(getattr(sys, "_MEIPASS", runtime.application_dir()))
    bundled = root / "vendor" / "ffprobe" / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
    if bundled.is_file():
        return str(bundled)
    # A portable build must not silently depend on the host installation.
    if not getattr(sys, "frozen", False):
        system = shutil.which("ffprobe")
        if system:
            return system
    raise RuntimeError("缺少 ffprobe。便携版请重新解压完整压缩包；源码版请重新运行安装脚本。")


def probe(path):
    tasks.check()
    result = subprocess.run([get_ffprobe_exe(), "-v", "error", "-show_format", "-show_streams",
                             "-of", "json", str(path)], capture_output=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    tasks.check()
    if result.returncode:
        raise RuntimeError("无法读取视频时长或画面；文件可能损坏、已被移动或不是有效视频。")
    return json.loads(result.stdout)


def _positive(value, default=0):
    try:
        number = float(Fraction(str(value)))
        return number if math.isfinite(number) and number > 0 else default
    except (ValueError, ZeroDivisionError, TypeError):
        return default


def get_video_info(path: str) -> Dict:
    """Read structured stream metadata; editing uses FFmpeg's rotated orientation."""
    metadata = probe(path)
    streams = metadata.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    if not videos:
        raise RuntimeError("没有可编辑的视频画面，请选择有效的视频文件")
    stream = videos[0]
    width, height = int(stream.get("width", 0)), int(stream.get("height", 0))
    angle = stream.get("tags", {}).get("rotate", 0)
    for side in stream.get("side_data_list", []):
        if "rotation" in side:
            angle = side["rotation"]
            break
    angle = float(angle)
    if not math.isfinite(angle):
        angle = 0
    if round(angle) % 180 == 90:
        width, height = height, width
    duration = _positive(stream.get("duration")) or _positive(metadata.get("format", {}).get("duration"))
    if duration <= 0 or min(width, height) < 2:
        raise RuntimeError("无法读取视频时长或画面，请确认文件完整且未损坏")
    return dict(duration=duration, width=width, height=height,
                fps=_positive(stream.get("avg_frame_rate")) or _positive(stream.get("r_frame_rate")),
                has_audio=any(s.get("codec_type") == "audio" for s in streams), rotation=angle,
                codec=stream.get("codec_name", ""), pixel_format=stream.get("pix_fmt", ""))


def extract_frame(input_path: str, t: float, out_path: str) -> str:
    """从视频中提取一帧画面保存为图片（png），用于界面预览。

    参数：
      input_path  视频文件路径
      t           提取第 t 秒的画面
      out_path    输出图片路径（.png）

    返回：out_path
    """
    ffmpeg = get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg, "-hide_banner", "-y", "-ss", f"{t:.3f}", "-i", str(input_path),
         "-frames:v", "1", str(out_path)],
        capture_output=True, text=False, timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode != 0 or not os.path.exists(out_path):
        err = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"提取画面失败：{err.strip().splitlines()[-1:]}")
    return out_path


# ---------------------------------------------------------------------------
# ffmpeg 命令执行（带进度回调）
# ---------------------------------------------------------------------------
def run_ffmpeg(
    args: list,
    total_duration: float = 0.0,
    on_progress: ProgressCallback = None,
    extra_message: str = "处理中",
) -> subprocess.CompletedProcess:
    """执行一条 ffmpeg 命令。

    参数：
      args            ffmpeg 参数列表（不包含 ffmpeg 程序名）
      total_duration  视频总时长（秒），用于换算进度百分比；传 0 则不报告进度
      on_progress     进度回调 callback(percent, message)
      extra_message   进度消息前缀

    实现方式：通过 `-progress pipe:1 -nostats` 让 ffmpeg 把进度信息
    写到 stdout，逐行解析 out_time_us（已处理的时间，微秒）。
    """
    tasks.check()
    ffmpeg = get_ffmpeg_exe()
    # -y 覆盖输出文件；-progress pipe:1 输出进度；-nostats 关闭多余统计
    cmd = [ffmpeg, "-hide_banner", "-y", "-progress", "pipe:1", "-nostats"] + list(args)

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    # Windows 管道缓冲较小，ffmpeg 编码结束时向 stderr 输出的统计信息（如
    # libx264 汇总）容易写满缓冲区，导致 ffmpeg 阻塞在写 stderr 无法退出，
    # 而主线程在读 stdout 时形成死锁。用后台线程持续读 stderr 避免。
    stderr_lines: list = []
    stderr_thread = threading.Thread(
        target=lambda: stderr_lines.extend(process.stderr), daemon=True
    )
    stderr_thread.start()

    out_time_us = 0.0

    try:
        with tasks.watch_process(process):
            process_performance.request_high_qos(process.pid)
            for line in process.stdout:
                line = line.strip()
                if line.startswith("out_time_us="):
                    try:
                        out_time_us = float(line.split("=", 1)[1])
                    except ValueError:
                        continue
                    if total_duration > 0 and on_progress:
                        percent = min(100.0, out_time_us / 1_000_000 / total_duration * 100)
                        on_progress(percent, extra_message)
            return_code = process.wait()
    finally:
        # 回调异常时也结束子进程，确保临时文件可以被清理。
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        stderr_thread.join()
        process.stdout.close()
        process.stderr.close()
    stderr_text = "".join(stderr_lines)
    if return_code != 0:
        # 提取最后几行错误信息便于定位问题
        tail = "\n".join(stderr_text.strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg 执行失败（返回码 {return_code}）:\n{tail}")

    if on_progress:
        on_progress(100.0, extra_message)
    return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=stderr_text)
