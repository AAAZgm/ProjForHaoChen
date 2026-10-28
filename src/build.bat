@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem ============================================================
rem 一键打包 .exe 脚本 (Windows)
rem 用法：双击运行 build.bat
rem 生成经过检查的便携 ZIP，位于仓库根目录 dist
rem ============================================================
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
pushd "%~dp0" || exit /b 1
set "BUILD_PY=%CD%\.venv\Scripts\python.exe"
if not exist "%BUILD_PY%" (
    echo [错误] 请先运行 install.bat 创建项目环境。
    set "EXIT_CODE=1"
    goto finish
)
echo 安装已锁定的构建依赖 ...
"%BUILD_PY%" -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
echo 开始测试、打包和便携包验证，可能需要几分钟 ...
"%BUILD_PY%" ..\scripts\build_portable.py
if errorlevel 1 goto failed
echo [完成] 便携 ZIP、SHA256 和验证报告位于仓库根目录 dist 文件夹。
set "EXIT_CODE=0"
goto finish

:failed
echo [错误] 测试或打包未完成，请查看上方错误及 build\pyinstaller.log。
set "EXIT_CODE=1"

:finish
popd
pause
endlocal & exit /b %EXIT_CODE%
