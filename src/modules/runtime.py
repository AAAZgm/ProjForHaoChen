"""Locations shared by source launches and the portable application."""

import os
from pathlib import Path
import sys
import tempfile
import uuid

APP_VERSION = "1.2.0-beta.1"
RELEASES_URL = "https://github.com/AAAZgm/ProjForHaoChen/releases"
_run_id = uuid.uuid4().hex


def application_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def data_dir() -> Path:
    """Prefer the portable folder; read-only installations use the user folder."""
    override = os.environ.get("BILI_VIDEO_HOME")
    if override:
        return Path(override).expanduser().resolve()
    preferred = application_dir()
    try:
        with tempfile.TemporaryFile(dir=preferred):
            pass
        return preferred
    except OSError:
        return config_dir() / "files"


def config_dir() -> Path:
    override = os.environ.get("BILI_CONFIG_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".config"
    return base / "BiliVideoTool"


def cache_dir() -> Path:
    return config_dir() / "cache"


def session_cache() -> Path:
    return cache_dir() / "runs" / _run_id
