@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem ============================================================
rem B站视频下载处理工具 - 一键安装脚本 (Windows)
rem 用法：双击运行 install.bat
rem ============================================================
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
pushd "%~dp0" || exit /b 1
set "VENV_PY=%CD%\.venv\Scripts\python.exe"

rem Reuse the same environment as start.bat, regardless of PATH or Conda.
if exist "%VENV_PY%" goto check_environment
if exist ".venv" goto invalid_environment

rem Check the actual interpreter version, not just command availability.
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=py -3"
    goto create_environment
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=python"
    goto create_environment
)
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=python3"
    goto create_environment
)
echo [错误] 未找到可用的 Python 3.10 或更高版本。
echo 请从 https://www.python.org 安装 Python 3.10+，勾选 Add to PATH 后重新运行本脚本。
set "EXIT_CODE=1"
goto finish

:create_environment
echo 创建项目运行环境 .venv ...
%PY_CMD% -m venv .venv
if errorlevel 1 goto failed
if not exist "%VENV_PY%" goto invalid_environment

:check_environment
"%VENV_PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto invalid_environment
"%VENV_PY%" --version

rem Always install through this environment's Python, never a global pip.
"%VENV_PY%" -m pip --version >nul 2>nul
if not errorlevel 1 goto install_dependencies
"%VENV_PY%" -m ensurepip --upgrade
if errorlevel 1 goto failed

:install_dependencies
echo 升级 pip ...
"%VENV_PY%" -m pip install --upgrade pip -q
if errorlevel 1 goto failed
echo 安装依赖（首次可能需要几分钟）...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo 准备视频探测组件 ...
"%VENV_PY%" ..\scripts\prepare_ffprobe.py
if errorlevel 1 goto failed

echo.
echo ======================================================
echo   安装完成！
echo   启动方法：双击 start.bat
echo ======================================================
set "EXIT_CODE=0"
goto finish

:invalid_environment
echo [错误] 项目 .venv 不完整、不可用或 Python 版本低于 3.10。
echo 请关闭程序，将本文件夹中的 .venv 改名备份，再重新运行 install.bat。
set "EXIT_CODE=1"
goto finish

:failed
echo.
echo [错误] 安装未完成，请根据上方错误信息处理后重新运行 install.bat。
set "EXIT_CODE=1"

:finish
popd
pause
endlocal & exit /b %EXIT_CODE%
