@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem ============================================
rem Bili video download & process tool - launcher
rem Uses the project .venv created by install.bat.
rem Auto-opens browser after startup.
rem ============================================
chcp 65001 >nul
rem Force UTF-8 for python subprocesses (ffmpeg/yt-dlp output on zh-CN Windows)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
pushd "%~dp0" || exit /b 1

rem Call the interpreter directly: no activation or system Python fallback.
set "PY_EXE=%CD%\.venv\Scripts\python.exe"
if not exist "%PY_EXE%" goto missing_environment

"%PY_EXE%" main.py
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" goto finish
echo.
echo [错误] 程序退出，错误代码：%EXIT_CODE%
echo 请查看上方错误信息；如果提示缺少依赖，请重新运行 install.bat。
goto finish

:missing_environment
echo [错误] 未找到项目运行环境 .venv\Scripts\python.exe。
echo 请先双击同一文件夹中的 install.bat，安装成功后再运行 start.bat。
set "EXIT_CODE=1"

:finish
popd
pause
endlocal & exit /b %EXIT_CODE%
