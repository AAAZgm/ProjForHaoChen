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

echo "安装打包工具 pyinstaller ..."
pip install pyinstaller -q

echo "开始打包（首次需要几分钟）..."
python -m PyInstaller --noconfirm bili_video_tool.spec

echo ""
echo "======================================================"
echo "  打包成功！文件位置：dist/ 目录"
echo "======================================================"
