#!/usr/bin/env bash
# ============================================================
# B站视频下载处理工具 - 一键安装脚本 (Linux / macOS)
# 用法：在终端中执行  bash install.sh
# ============================================================
set -e
cd "$(dirname "$0")"

# 1. 检查 Python 版本（要求 3.10 及以上）
PY_CMD=""
if command -v python3 >/dev/null 2>&1; then
    PY_CMD=python3
elif command -v python >/dev/null 2>&1; then
    PY_CMD=python
else
    echo "[错误] 未找到 Python，请先安装 Python 3.10+ 后重试"
    exit 1
fi

PY_VER=$("$PY_CMD" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "检测到 Python 版本：$PY_VER"
case "$PY_VER" in
    3.10*|3.11*|3.12*|3.13*|3.14*|3.15*) ;;
    *) echo "[错误] 需要 Python 3.10+，当前版本 $PY_VER"; exit 1 ;;
esac

# 2. 创建虚拟环境（隔离依赖，不影响系统）
if [ ! -d ".venv" ]; then
    echo "创建虚拟环境 .venv ..."
    "$PY_CMD" -m venv .venv
fi

# 3. 激活虚拟环境并安装依赖
source .venv/bin/activate
echo "升级 pip ..."
pip install --upgrade pip -q
echo "安装依赖（首次可能需要几分钟）..."
pip install -r requirements.txt
python ../scripts/prepare_ffprobe.py

echo ""
echo "======================================================"
echo "  安装完成！"
echo "  启动方法：双击 start.sh 或执行  bash start.sh"
echo "======================================================"
