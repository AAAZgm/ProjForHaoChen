#!/usr/bin/env bash
# ============================================================
# 构建并验证目录式便携包 (Linux / macOS)
# 用法：bash build.sh
# 生成的文件在 dist/ 目录
# （Windows 的 .exe 请在 Windows 上运行 build.bat，
#   或推送到 GitHub 自动构建，见 .github/workflows/build-exe.yml）
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "安装已锁定的构建依赖 ..."
python -m pip install -r requirements-build.txt

echo "开始打包（首次需要几分钟）..."
python ../scripts/build_portable.py

echo ""
echo "======================================================"
echo "  打包成功！便携 tar.gz、SHA256 和验证报告位于仓库根目录 dist/"
echo "======================================================"
