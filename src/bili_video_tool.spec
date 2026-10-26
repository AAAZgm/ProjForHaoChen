# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置（用于生成可执行文件）
========================================
- Windows 下运行 build.bat（或直接执行：pyinstaller bili_video_tool.spec）
- Linux/macOS 下运行 build.sh
- GitHub Actions 云端自动构建见 .github/workflows/build-exe.yml

说明：
  Gradio / yt-dlp / imageio-ffmpeg 等库带有大量数据文件（前端资源、
  二进制、图标等），必须用 collect_all 把它们的 datas/binaries/
  hiddenimports 全部收集进来，否则打包出的程序运行时会报缺文件。
"""

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# 需要完整收集的第三方库（含隐藏导入、数据文件、二进制）
COLLECT_PACKAGES = [
    "gradio",             # 网页界面（前端静态资源较多）
    "yt_dlp",             # 视频下载
    "imageio_ffmpeg",     # 自带 ffmpeg 二进制（关键！）
    "fastapi",            # gradio 依赖的 Web 框架
    "starlette",
    "uvicorn",
    "pydantic",
    "httpx",
    "huggingface_hub",
    "aiohttp",
    "numpy",
    "pandas",
    "websockets",
]

# gradio 依赖链里的"版本标记包"（如 safehttpx、groovy）在导入时会读取自带的
# version.txt 数据文件，漏收集会导致打包后运行报 FileNotFoundError。
# 自动把已安装且带 version.txt 的包收进来，避免逐个手动维护。
import sys as _sys
import pathlib as _pathlib

for _p in _sys.path:
    _pp = _pathlib.Path(_p)
    if not _pp.is_dir():
        continue
    for _d in _pp.iterdir():
        if _d.is_dir() and (_d / "version.txt").exists() \
                and not _d.name.startswith("_") and _d.name not in COLLECT_PACKAGES:
            COLLECT_PACKAGES.append(_d.name)

for pkg in COLLECT_PACKAGES:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[警告] 收集 {pkg} 失败（可忽略）: {e}")

a = Analysis(
    ["main.py"],                       # 程序入口
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # 排除用不到的重量级库，减小体积
        "matplotlib", "scipy", "PyQt5", "PySide2", "tkinter", "test",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="B站视频处理工具",            # 生成的可执行文件名
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                         # 关闭 UPX（避免误报杀毒）
    console=True,                      # 显示控制台窗口（便于看报错信息）
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    onefile=True,                      # 单文件模式：一个 .exe 即全部
)
