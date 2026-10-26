@echo off
rem ============================================================
rem 一键打包 .exe 脚本 (Windows)
rem 用法：双击运行 build.bat
rem 生成的文件在 dist\B站视频处理工具.exe
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

rem 1. 查找 Python
where py >nul 2>nul
if %errorlevel%==0 (
    set PY_CMD=py -3
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set PY_CMD=python
    ) else (
        echo [错误] 未找到 Python，请先安装 Python 3.10+ 并勾选 Add to PATH
        pause
        exit /b 1
    )
)

rem 2. 优先使用项目虚拟环境
if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

rem 3. 安装打包工具
echo 安装打包工具 pyinstaller ...
pip install pyinstaller -q

rem 4. 执行打包（使用 bili_video_tool.spec 配置）
echo 开始打包，首次需要几分钟，请耐心等待 ...
python -m PyInstaller --noconfirm bili_video_tool.spec

rem 5. 提示结果
if exist "dist\B站视频处理工具.exe" (
    echo.
    echo ======================================================
    echo   打包成功！
    echo   文件位置：dist\B站视频处理工具.exe
    echo   双击即可运行，可拷贝到任意电脑使用（无需安装 Python）
    echo ======================================================
) else (
    echo.
    echo [错误] 打包失败，请把上方红色报错信息截图反馈
)
pause
