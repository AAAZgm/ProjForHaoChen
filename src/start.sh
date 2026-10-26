#!/usr/bin/env bash
# ============================================================
# B站视频下载处理工具 - 一键启动脚本 (Linux / macOS)
# 启动后会自动打开浏览器，即可开始使用
# ============================================================
cd "$(dirname "$0")"

# 强制 Python 使用 UTF-8 模式（避免中文系统下子进程输出 GBK 解码报错）
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

# 优先使用虚拟环境，找不到则用系统 Python
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

python3 main.py
