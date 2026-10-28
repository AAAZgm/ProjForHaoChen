"""Bounded local logs with credentials and URL queries removed."""
import importlib.metadata
import logging
from logging.handlers import RotatingFileHandler
import platform
import re

from . import runtime

LOG = logging.getLogger("bili_video_tool")


def redact(text):
    text = str(text)
    # Drop whole sensitive header lines and standalone cookie/token values.
    text = re.sub(r"(?im)^.*(?:cookie|authorization|proxy-authorization)\s*[:=].*$", "[登录凭据已隐藏]", text)
    text = re.sub(r"(?i)(?:https?://)[^\s<>\"']+", "[链接已隐藏]", text)
    text = re.sub(r"(?i)\b(?:SESSDATA|bili_jct|access_token|refresh_token|token|password)\s*[=:]\s*[^\s,;]+", "[凭据已隐藏]", text)
    return text


class PrivateFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))


def setup():
    root = runtime.config_dir() / "logs"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "application.log"
    for handler in list(LOG.handlers):
        LOG.removeHandler(handler)
        handler.close()
    handler = RotatingFileHandler(target, maxBytes=1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(PrivateFormatter("%(asctime)s %(levelname)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False
    LOG.info("Starting %s on %s", runtime.APP_VERSION, platform.platform())


def error(operation, exception):
    from .tasks import Cancelled
    if isinstance(exception, Cancelled):
        LOG.info("%s cancelled", operation)
    else:
        LOG.error("%s: %s", operation, exception, exc_info=(type(exception), exception, exception.__traceback__))
    return redact(exception)


def report():
    from . import ffmpeg_util, settings
    values = settings.load()
    lines = [f"轻剪 {runtime.APP_VERSION}", f"系统：{platform.platform()}",
             f"Python：{platform.python_version()}",
             f"配置目录：{runtime.config_dir()}", f"导出目录：{values['output_dir']}",
             f"下载目录：{values['download_dir']}", f"缓存目录：{runtime.cache_dir()}"]
    for name in ("gradio", "yt-dlp", "imageio-ffmpeg"):
        lines.append(f"{name}：{importlib.metadata.version(name)}")
    for name, getter in (("FFmpeg", ffmpeg_util.get_ffmpeg_exe), ("ffprobe", ffmpeg_util.get_ffprobe_exe)):
        try:
            lines.append(f"{name}：{getter()}")
        except Exception as exc:
            lines.append(f"{name}：{exc}")
    file = runtime.config_dir() / "logs" / "application.log"
    try:
        with file.open("rb") as stream:
            stream.seek(max(0, file.stat().st_size - 12000))
            lines += ["", "最近日志：", stream.read().decode("utf-8", errors="replace")]
    except FileNotFoundError:
        lines.append("尚无日志")
    return redact("\n".join(lines))
