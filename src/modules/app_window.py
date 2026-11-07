"""Own a separate browser profile/window, never the user's normal browser."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser

from . import diagnostics, runtime, tasks


def browser_executable():
    if os.name != "nt":
        return None
    candidates = []
    for relative in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
        for key in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            if os.environ.get(key):
                candidates.append(Path(os.environ[key]) / relative)
    # App Paths also covers installations outside the usual directories.
    import winreg
    for name in ("msedge.exe", "chrome.exe"):
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{name}") as key:
                    candidates.append(Path(winreg.QueryValue(key, None).strip('"')))
            except OSError:
                pass
    return next((str(path) for path in candidates if path.is_file()), None)


def _windows(process, close=False):
    """Focus/close only windows belonging to a still-live child we launched."""
    if os.name != "nt" or process.poll() is not None:
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    found = False

    @callback_type
    def visit(window, _):
        nonlocal found
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value == process.pid and user32.IsWindowVisible(window) and process.poll() is None:
            found = True
            if close:
                user32.PostMessageW(window, 0x0010, 0, 0)  # WM_CLOSE, allow normal browser cleanup.
            else:
                if user32.IsIconic(window):
                    user32.ShowWindow(window, 9)  # SW_RESTORE only when minimized.
                user32.SetForegroundWindow(window)
        return True

    user32.EnumWindows(visit, 0)
    return found


class AppWindow:
    def __init__(self):
        self._lock = threading.Lock()
        self._children = []
        self._closing = False
        self._started = 0.0

    def open(self, url):
        with self._lock:
            if self._closing:
                return "程序正在退出，请稍后重新启动"
            self._children = [child for child in self._children if child.poll() is None]
            for child in self._children:
                if _windows(child):
                    diagnostics.LOG.info("Reused app window process %d", child.pid)
                    return "已返回轻剪窗口，当前编辑内容保留"
            # A second double-click during browser startup must not create another session.
            if self._children and time.monotonic() - self._started < 5:
                return "轻剪窗口正在打开，请稍候"
            executable = browser_executable()
            if executable:
                root = runtime.session_cache() / "browser"
                root.mkdir(parents=True, exist_ok=True)
                # A new profile cannot be handed off to an unrelated running browser.
                profile = tempfile.mkdtemp(prefix="window-", dir=root)
                command = [executable, f"--user-data-dir={profile}", f"--app={url}",
                           "--no-first-run", "--no-default-browser-check", "--disable-background-mode",
                           "--disable-sync", "--window-size=1280,900"]
                try:
                    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
                    self._children.append(child)
                    self._started = time.monotonic()
                    diagnostics.LOG.info("Opened app window process %d", child.pid)
                    return "已打开轻剪独立窗口；点击“退出程序”会同时关闭窗口和后台"
                except OSError as error:
                    diagnostics.LOG.warning("App window unavailable: %s", error)
            if os.name != "nt" and getattr(sys, "frozen", False):
                from .desktop import open_target
                try:
                    open_target(url)
                except OSError:
                    diagnostics.LOG.warning("无法打开默认浏览器，请手动访问 %s", url)
            else:
                webbrowser.open(url)
            return "已使用默认浏览器打开；退出后若标签页未自动关闭，请手动关闭"

    def close(self):
        with self._lock:
            self._closing = True
            children = self._children
            self._children = []
        for child in children:
            try:
                _windows(child, close=True)
            except OSError:
                diagnostics.LOG.exception("Could not request app window close")
        deadline = time.monotonic() + 3
        for child in children:
            try:
                child.wait(timeout=max(.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                # Only our isolated profile's retained Popen handle/tree is eligible.
                tasks.stop_process(child, tree=True)


window = AppWindow()

# Run only after the exit callback succeeds. A manually opened browser tab may
# reject close(); navigate away from Gradio so it cannot show reconnection errors.
EXIT_JS = """() => {
    window.close();
    setTimeout(() => window.location.replace('/bili-goodbye'), 100);
}"""
GOODBYE_HTML = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>轻剪已退出</title><body style="font:18px system-ui;margin:12vh auto;max-width:600px;padding:24px">
<h1>轻剪已退出</h1><p>可以关闭此标签页。再次双击程序即可重新打开。</p></body></html>"""
