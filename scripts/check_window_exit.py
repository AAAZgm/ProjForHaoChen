"""Opt-in Windows integration check with real isolated browser processes.

python scripts/check_window_exit.py --executable dist/BiliVideoTool/BiliVideoTool.exe
Omit --executable to test source. Opens app and unrelated control windows; does
not inspect or automate browser content. Uses the application's public exit API.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from modules import app_window, tasks
from smoke_portable import wait_ready


def check(command, work):
    if os.name != "nt":
        raise RuntimeError("Windows integration check")
    executable = app_window.browser_executable()
    if not executable:
        raise RuntimeError("Edge or Chrome is required for this check")
    work.mkdir(parents=True, exist_ok=False)
    env = os.environ.copy()
    env.update(BILI_CONFIG_HOME=str(work / "config"), BILI_VIDEO_HOME=str(work / "data"),
               PYTHONUTF8="1", GRADIO_ANALYTICS_ENABLED="False")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    hidden = subprocess.CREATE_NO_WINDOW
    # Control browser has its own profile, unrelated to the application or user.
    control = subprocess.Popen([executable, f"--user-data-dir={work / 'control-profile'}", "--new-window",
                                "--no-first-run", "--no-default-browser-check", "--disable-background-mode",
                                "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=hidden)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    browser_handle = None
    process = None
    try:
        with (work / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=hidden)
            url, _ = wait_ready(process, work, opener)
            application_log = work / "config/logs/application.log"
            deadline = time.monotonic() + 30
            pids = []
            while time.monotonic() < deadline:
                pids = re.findall(r"Opened app window process (\d+)", application_log.read_text(encoding="utf-8"))
                if pids:
                    break
                time.sleep(.2)
            assert len(pids) == 1, pids
            browser_handle = kernel.OpenProcess(0x100000, False, int(pids[0]))  # SYNCHRONIZE only.
            assert browser_handle, ctypes.get_last_error()
            assert kernel.WaitForSingleObject(browser_handle, 0) == 258, "Browser exited during startup"
            time.sleep(6)  # Allow the real window to appear before testing repeat launch.
            duplicate = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                       timeout=60, creationflags=hidden, check=True)
            reply = duplicate.stdout.decode("utf-8")
            assert "当前编辑内容保留" in reply, reply
            log_text = application_log.read_text(encoding="utf-8")
            assert len(re.findall(r"Opened app window process (\d+)", log_text)) == 1
            assert process.poll() is None and control.poll() is None
            from gradio_client import Client
            client = Client(url, verbose=False, analytics_enabled=False,
                            httpx_kwargs={"trust_env": False}, download_files=False)
            try:
                assert "自动关闭" in client.predict(api_name="/exit_app")
            finally:
                client.close()
            assert process.wait(timeout=30) == 0
            assert kernel.WaitForSingleObject(browser_handle, 10000) == 0, "Owned browser remains alive"
            assert control.poll() is None, "Unrelated browser was closed"
            assert not (work / "config/instance.json").exists()
            assert not list((work / "config/cache/runs").iterdir()), "Run cache remains"
        result = dict(status="passed", browser=Path(executable).name,
                      repeat_launch_preserves_window="passed", exit_stops_owned_browser_and_server="passed",
                      unrelated_browser_survives="passed", cache_cleanup="passed",
                      ui_click="not automated; API and real processes verified")
        (work / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result
    finally:
        if browser_handle:
            kernel.CloseHandle(browser_handle)
        tasks.stop_process(control, tree=True)
        if process is not None:
            tasks.stop_process(process, tree=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path)
    args = parser.parse_args()
    command = [str(args.executable.resolve())] if args.executable else [sys.executable, "-X", "utf8", str(ROOT / "src/main.py")]
    directory = ROOT / "build" / f"window-exit-{time.time_ns()}"
    print(json.dumps(check(command, directory), ensure_ascii=False, indent=2))
