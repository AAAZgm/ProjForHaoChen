"""Exercise the same session API used by the page, including cancellation/retry."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import time
from urllib.parse import quote


def check_editor(url, source, downloads):
    from gradio_client import Client, handle_file
    source = Path(source).resolve()
    clients = [Client(url, verbose=False, analytics_enabled=False,
                      httpx_kwargs={"trust_env": False, "timeout": 60},
                      download_files=Path(downloads) / str(i)) for i in range(2)]
    client, other = clients
    def call(name, *args):
        if name == "export_video" and len(args) == 3:
            args = (*args, "", "")
        return client.submit(*args, api_name="/" + name).result(timeout=90)
    try:
        loaded = call("import_video", handle_file(str(source)))
        table, duration = loaded[1], loaded[3]
        assert table["data"] and duration > 0, str(loaded)[:300]
        split = call("split", duration / 2)
        assert len(split[1]["data"]) == 2
        call("select_segment", "1")
        moved = call("up")
        assert moved[1]["data"][0][0] == round(duration / 2, 3)
        call("undo")
        call("redo")
        effects = call("effects", True, 2, "当前片段")
        assert effects[1]["data"][0][3:5] == [True, 2]
        preview = call("preview_segment")
        assert "预览完成" in preview[1], str(preview)
        frame = json.loads(loaded[8])
        frame["rect"] = [.1, .1, .9, .9]
        region = call("region", json.dumps(frame), "裁剪画面", "全部片段")
        assert region[1]["data"][0][7] > 0
        gif = call("export_video", "GIF 动图", 10, .5)
        assert gif[2] and Path(gif[2]).is_file() and "导出完成" in gif[3], str(gif)
        # A second client must have no source, selection or effects from the first.
        empty = other.submit("通用 MP4", 15, .5, "", "", api_name="/export_video").result(timeout=30)
        assert "请先导入" in empty[3], str(empty)
        # Make rendering long enough to exercise the cancel endpoint rather than job.cancel().
        full = call("reset")
        many = dict(full[1])
        many["data"] = many["data"] * 80
        call("table", many)
        job = client.submit("通用 MP4", 15, .5, "", "", api_name="/export_video")
        requested = False
        for _ in range(50):
            message = call("cancel_task")
            if "正在取消" in message:
                requested = True
                break
            if job.done(): break
            time.sleep(.1)
        result = job.result(timeout=45)
        assert requested and "已取消" in result[3], str(result)
        call("reset")
        exported = call("export_video", "较小 MP4", 15, .5)
        assert exported[2] and Path(exported[2]).is_file() and "导出完成" in exported[3], str(exported)
        # Serve generated test media locally to verify the real yt-dlp child/merge path offline.
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                if self.path.startswith("/slow/"):
                    # Keep the child inside a network operation while cancellation is requested.
                    time.sleep(5)
                    self.path = self.path[len("/slow"):]
                try:
                    super().do_GET()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(source.parent)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            local_url = f"http://127.0.0.1:{server.server_port}/{quote(source.name)}"
            downloaded = call("download_video", local_url, "最高可用")
            assert "已载入" in downloaded[6], str(downloaded)[:500]
            assert downloaded[1]["data"] and downloaded[3] == duration
            slow_url = f"http://127.0.0.1:{server.server_port}/slow/{quote(source.name)}"
            slow = client.submit(slow_url, "最高可用", api_name="/download_video")
            time.sleep(1)
            assert "正在取消" in call("cancel_task")
            cancelled_download = slow.result(timeout=30)
            assert "已取消" in cancelled_download[6], str(cancelled_download)[:300]
            after_cancel = call("export_video", "通用 MP4", 15, .5)
            assert "导出完成" in after_cancel[3]
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        return dict(status="passed", auto_import="passed", split_reorder_history="passed",
                    crop_preview_gif="passed", session_isolation="passed", cancel_then_mp4="passed",
                    download_worker_local_http="passed", cancel_download_then_export="passed")
    finally:
        for client in clients: client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("source")
    parser.add_argument("downloads")
    args = parser.parse_args()
    print(json.dumps(check_editor(args.url, args.source, args.downloads), ensure_ascii=False, indent=2))
