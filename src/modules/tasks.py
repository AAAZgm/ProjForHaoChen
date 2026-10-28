"""Per-session cancellation and a single heavy-work slot, independent of Gradio."""

from contextlib import contextmanager
from contextvars import ContextVar
import os
import subprocess
import threading


class Cancelled(RuntimeError):
    pass


class Token:
    def __init__(self):
        self.event = threading.Event()

    def check(self):
        if self.event.is_set():
            raise Cancelled("任务已取消，临时文件已清理，可继续操作")


CURRENT = ContextVar("video_task", default=None)
_active = {}
_lock = threading.Lock()
_slot = threading.Lock()
_closing = False


def check():
    token = CURRENT.get()
    if token:
        token.check()


def busy(session_id):
    with _lock:
        return session_id in _active


def cancel(session_id):
    with _lock:
        token = _active.get(session_id)
        if token:
            token.event.set()
    return bool(token)


def cancel_all():
    global _closing
    with _lock:
        _closing = True
        for token in _active.values():
            token.event.set()


def any_busy():
    with _lock:
        return bool(_active)


@contextmanager
def task(session_id, progress=None):
    token = Token()
    with _lock:
        if _closing:
            raise Cancelled("程序正在退出，请重新启动后操作")
        if session_id in _active:
            raise RuntimeError("当前页面已有任务，请等待完成或先取消")
        _active[session_id] = token
    acquired = False
    context = CURRENT.set(token)
    try:
        if progress:
            progress(0, "等待处理资源；可随时取消")
        while not acquired:
            token.check()
            acquired = _slot.acquire(timeout=0.1)
        token.check()
        yield token
    finally:
        CURRENT.reset(context)
        if acquired:
            _slot.release()
        with _lock:
            _active.pop(session_id, None)


def stop_process(process, tree=False):
    if process.poll() is not None:
        return
    if tree and os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@contextmanager
def watch_process(process, tree=False):
    """Kill a cancelled child even when its stdout/progress pipe is silent."""
    token = CURRENT.get()
    finished = threading.Event()

    def watch():
        while not finished.wait(0.1):
            if token and token.event.is_set():
                stop_process(process, tree)
                return

    thread = threading.Thread(target=watch, daemon=True)
    thread.start()
    try:
        yield
        check()
    finally:
        finished.set()
        thread.join(timeout=6)


def friendly_error(error):
    from .diagnostics import redact
    text = redact(error)
    if isinstance(error, Cancelled):
        return text
    if "412" in text or "403" in text:
        return "网站暂时拒绝请求。请确认链接在浏览器中可访问，稍后重试，或先导入本地视频。"
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "连接超时，请检查网络后重试。"
    if isinstance(error, PermissionError):
        return "保存目录不可写或文件正在被占用，请在“设置与帮助”更换目录，或关闭占用文件后重试。"
    if getattr(error, "errno", None) == 28 or "No space left" in text:
        return "磁盘空间不足，请清理空间，或在“设置与帮助”更换保存目录后重试。"
    if isinstance(error, FileNotFoundError):
        return "文件已被移动或删除，请重新导入；如提示缺少程序组件，请重新解压完整压缩包。"
    return f"操作未完成：{text}。可调整设置后重试。"
