"""Run yt-dlp in an owned child so download and FFmpeg merge can be cancelled."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid

from . import tasks


def worker(request_path):
    from .downloader import BiliDownloader
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    def progress(pct, message):
        print("BILI_PROGRESS:" + json.dumps([pct, message], ensure_ascii=True), flush=True)
    try:
        path = BiliDownloader().download(request["url"], request["directory"],
                                         progress, request["height"])
        result = {"path": path}
    except Exception as error:
        result = {"error": str(error)}
    Path(request["result"]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


def download(url, directory, height=0, progress=None):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="download_", dir=directory) as temp:
        work = Path(temp)
        request = work / "request.json"
        result_file = work / "result.json"
        request.write_text(json.dumps(dict(url=url, directory=str(work), height=height,
                                          result=str(result_file))), encoding="utf-8")
        command = [sys.executable]
        if not getattr(sys, "frozen", False):
            command += [str(Path(__file__).resolve().parents[1] / "main.py")]
        command += ["--download-worker", str(request)]
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   encoding="utf-8", errors="replace",
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        last = 0
        try:
            with tasks.watch_process(process, tree=True):
                for line in process.stdout:
                    if line.startswith("BILI_PROGRESS:") and progress:
                        value, message = json.loads(line.split(":", 1)[1])
                        last = max(last, min(95, value * .95))
                        progress(last, message)
                process.wait()
        finally:
            tasks.stop_process(process, tree=True)
            process.stdout.close()
        tasks.check()
        if not result_file.is_file():
            raise RuntimeError("下载进程异常结束，请重试")
        result = json.loads(result_file.read_text(encoding="utf-8"))
        if "error" in result:
            raise RuntimeError(result["error"])
        source = Path(result["path"]).resolve()
        if not source.is_relative_to(work) or not source.is_file():
            raise RuntimeError("本次下载未生成有效视频文件")
        target = directory / f"{uuid.uuid4().hex[:8]}_{source.name}"
        shutil.move(str(source), target)
        return str(target)
