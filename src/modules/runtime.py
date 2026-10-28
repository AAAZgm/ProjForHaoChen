"""Locations shared by source launches and the portable application."""

import os
from pathlib import Path
import sys
import tempfile
import uuid

APP_VERSION = "1.0.0-rc.4"
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
    base = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "BiliVideoTool"


def cache_dir() -> Path:
    return config_dir() / "cache"


def session_cache() -> Path:
    return cache_dir() / "runs" / _run_id
