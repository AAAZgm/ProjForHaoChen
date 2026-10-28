"""One process per user configuration, stale-safe locking and graceful shutdown."""
import json
import os
from pathlib import Path
import secrets
import socket
import threading
import time
import urllib.request
import webbrowser

from . import runtime, tasks

shutdown = threading.Event()
_url = ""


class Instance:
    def __init__(self):
        self.directory = runtime.config_dir()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file = None
        self.nonce = secrets.token_hex(24)

    def acquire(self):
        self.file = (self.directory / "instance.lock").open("a+b")
        self.file.seek(0, os.SEEK_END)
        if not self.file.tell():
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.file.close()
            self.file = None
            return False

    def publish(self, url):
        global _url
        _url = url
        file = self.directory / "instance.json"
        temporary = file.with_suffix(".tmp")
        temporary.write_text(json.dumps(dict(port=int(url.split(":")[-1].rstrip("/")), nonce=self.nonce)), encoding="utf-8")
        temporary.replace(file)

    def existing_url(self, timeout=45):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                state = json.loads((self.directory / "instance.json").read_text(encoding="utf-8"))
                port = int(state["port"])
                if not 1 <= port <= 65535:
                    raise ValueError("Invalid port")
                url = f"http://127.0.0.1:{port}/"
                with opener.open(url + "bili-health", timeout=1) as response:
                    health = json.load(response)
                if secrets.compare_digest(str(health["nonce"]), str(state["nonce"])):
                    return url
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(.3)
        raise RuntimeError("已有程序正在启动或退出，请稍后再次双击；也可检查仍打开的启动窗口。")

    def close(self):
        if self.file is not None:
            try:
                (self.directory / "instance.json").unlink(missing_ok=True)
            finally:
                self.file.close()  # OS releases the lock, including on process crashes.
                self.file = None


def available_port(preferred=7860):
    if not 1 <= preferred <= 65535:
        raise ValueError("端口需为 1–65535")
    for port in range(preferred, min(preferred + 100, 65536)):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def reopen():
    if not _url:
        return "页面尚未启动，请稍后重试"
    webbrowser.open(_url)
    return "已请求浏览器重新打开页面"


def request_shutdown():
    tasks.cancel_all()
    # Leave enough time for the click response to reach the browser.
    timer = threading.Timer(1, shutdown.set)
    timer.daemon = True
    timer.start()
    return "正在取消剩余任务并退出程序。稍后可关闭此页面；下次双击即可重新启动。"
