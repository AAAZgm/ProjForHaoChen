@echo off
rem ============================================================
rem B站视频下载处理工具 - 一键安装脚本 (Windows)
rem 用法：双击运行 install.bat
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"

rem 1. 检查 Python 是否存在
where py >nul 2>nul
if %errorlevel%==0 (
    set PY_CMD=py -3
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        set PY_CMD=python
    ) else (
        echo [错误] 未找到 Python，请先到 https://www.python.org 安装 Python 3.10+ ^(安装时勾选 Add to PATH^)
        pause
        exit /b 1
    )
)

%PY_CMD% --version

rem 2. 创建虚拟环境
if not exist ".venv" (
    echo 创建虚拟环境 .venv ...
    %PY_CMD% -m venv .venv
)

rem 3. 安装依赖
call .venv\Scripts\activate.bat
echo 升级 pip ...
python -m pip install --upgrade pip -q
echo 安装依赖（首次可能需要几分钟）...
pip install -r requirements.txt

echo.
echo ======================================================
echo   安装完成！
echo   启动方法：双击 start.bat
echo ======================================================
pause
