@echo off
rem ============================================
rem Bili video download & process tool - launcher
rem Uses conda env "bili_build" (all deps installed)
rem Auto-opens browser after startup.
rem ============================================
chcp 65001 >nul
rem Force UTF-8 for python subprocesses (ffmpeg/yt-dlp output on zh-CN Windows)
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"

rem Prefer conda env bili_build; fall back to system python
set "PY_EXE=C:\Users\Administrator\.conda\envs\bili_build\python.exe"
if not exist "%PY_EXE%" set "PY_EXE=python"

"%PY_EXE%" main.py
pause
