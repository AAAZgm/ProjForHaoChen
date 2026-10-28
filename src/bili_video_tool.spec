# -*- mode: python ; coding: utf-8 -*-
"""Portable onedir bundle; build from a clean, locked project environment."""

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

source = Path(SPECPATH)
datas, binaries, hiddenimports = [], [], []
probe = source / "vendor" / "ffprobe"
if not (probe / "ffprobe.exe").is_file():
    raise RuntimeError("Run scripts/prepare_ffprobe.py before building")
binaries.append((str(probe / "ffprobe.exe"), "vendor/ffprobe"))
datas.extend((str(probe / name), "vendor/ffprobe") for name in ("LICENSE.txt", "README.txt", "source.json"))

# These packages load assets/extractors by path or dynamic import.
for package in ("gradio", "gradio_client", "yt_dlp", "imageio_ffmpeg"):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports

for package in ("safehttpx", "groovy"):
    datas += collect_data_files(package)

# Keep metadata used at runtime and in the offline self-check.
datas += copy_metadata("gradio", recursive=True)
for distribution in ("yt-dlp", "imageio-ffmpeg", "Pillow"):
    datas += copy_metadata(distribution)

a = Analysis(
    [str(source / "main.py")], pathex=[str(source)],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[], runtime_hooks=[],
    excludes=["matplotlib", "scipy", "PyQt5", "PySide2", "tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [("X utf8", None, "OPTION")],
    exclude_binaries=True, name="BiliVideoTool", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="BiliVideoTool")
