#!/usr/bin/env bash
# ============================================================
# 打包为单文件可执行程序 (Linux / macOS)
# 用法：bash build.sh
# 生成的文件在 dist/ 目录
# （Windows 的 .exe 请在 Windows 上运行 build.bat，
#   或推送到 GitHub 自动构建，见 .github/workflows/build-exe.yml）
# ============================================================
set -e
cd "$(dirname "$0")"

# 优先使用虚拟环境
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

echo "安装已锁定的构建依赖 ..."
python -m pip install -r requirements-build.txt

echo "开始打包（首次需要几分钟）..."
python ../scripts/build_portable.py

echo ""
echo "======================================================"
echo "  打包成功！便携 ZIP 位于仓库根目录 dist/"
echo "======================================================"
