"""Small, versioned preferences. Writes are atomic and corrupt files are preserved."""
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time

from . import runtime

PRESETS = ["通用 MP4", "较小 MP4", "GIF 动图"]
_lock = threading.RLock()
_notice = ""


def defaults():
    return dict(schema=1, output_dir=str(runtime.data_dir() / "output"),
                download_dir=str(runtime.data_dir() / "downloads"),
                preset=PRESETS[0], gif_fps=15, gif_scale=.5, cache_days=7, acceleration="auto")


def validate(values):
    result = defaults()
    result.update({k: v for k, v in values.items() if k in result})
    result["schema"] = 1
    for key in ("output_dir", "download_dir"):
        value = str(result[key]).strip()
        if not value or not Path(value).expanduser().is_absolute():
            raise ValueError("保存目录请填写完整路径，例如 D:\\视频成品")
        result[key] = str(Path(value).expanduser().resolve())
        path = Path(result[key])
        # User files must never be placed in directories the app may clean.
        if path.is_relative_to(runtime.cache_dir().resolve()):
            raise ValueError("保存目录不能放在程序缓存中，请选择其他文件夹")
    if result["preset"] not in PRESETS:
        raise ValueError("请选择有效的导出预设")
    if result["acceleration"] not in ("auto", "cpu"):
        raise ValueError("请选择自动加速或 CPU 兼容模式")
    for key, low, high in (("gif_fps", 5, 30), ("cache_days", 1, 90)):
        number = float(result[key])
        if not math.isfinite(number) or number != int(number) or not low <= number <= high:
            raise ValueError(f"{key} 需为 {low}–{high} 的整数")
        result[key] = int(number)
    result["gif_scale"] = float(result["gif_scale"])
    if not math.isfinite(result["gif_scale"]) or not .1 <= result["gif_scale"] <= 1:
        raise ValueError("GIF 缩放比例需为 0.1–1")
    return result


def load():
    global _notice
    with _lock:
        file = runtime.config_dir() / "settings.json"
        try:
            raw = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("schema", 1) != 1:
                raise ValueError("Unsupported settings schema")
            return validate(raw)
        except FileNotFoundError:
            return defaults()
        except (ValueError, TypeError, OSError):
            backup = file.with_name(f"settings.invalid-{time.time_ns()}.json")
            try:
                file.replace(backup)
                _notice = "配置文件无法读取，已备份并恢复默认设置。请重新确认保存位置。"
            except OSError:
                _notice = "配置文件无法读取，正在使用默认设置。请检查配置文件夹权限。"
            return defaults()


def notice():
    return _notice


def writable_directory(value):
    path = Path(value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile(dir=path):
        pass
    return path


def save(**changes):
    with _lock:
        values = validate({**load(), **changes})
        for key in ("output_dir", "download_dir"):
            writable_directory(values[key])
        root = runtime.config_dir()
        root.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix="settings_", suffix=".tmp", dir=root)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(values, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            Path(name).replace(root / "settings.json")
        finally:
            Path(name).unlink(missing_ok=True)
        return values
