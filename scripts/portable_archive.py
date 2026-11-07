"""Preserve POSIX execute bits and PyInstaller's internal symbolic links."""
from pathlib import Path
import tarfile
import zipfile


def create_archive(bundle, destination, windows):
    bundle, destination = Path(bundle), Path(destination)
    if windows:
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for file in sorted(bundle.rglob("*")):
                if file.is_file():
                    archive.write(file, file.relative_to(bundle.parent))
    else:
        with tarfile.open(destination, "w:gz", dereference=False) as archive:
            archive.add(bundle, arcname=bundle.name)


def extract_archive(source, destination, windows):
    if windows:
        with zipfile.ZipFile(source) as archive:
            archive.extractall(destination)
    else:
        # data filter rejects absolute/traversing paths and escaping symlinks.
        with tarfile.open(source, "r:gz") as archive:
            archive.extractall(destination, filter="data")


def write_launcher(bundle, macos):
    launcher = Path(bundle) / ("Start.command" if macos else "start.sh")
    launcher.write_text('#!/bin/sh\nset -eu\ncd "$(dirname "$0")"\nexec ./BiliVideoTool "$@"\n', encoding="utf-8", newline="\n")
    launcher.chmod(0o755)
