"""Verify settings and file management in the actual launched app."""
from pathlib import Path


def check_release(url, source, work):
    from gradio_client import Client, handle_file
    work = Path(work)
    output = work / "自定义 成品"
    download = work / "自定义 下载"
    client = Client(url, verbose=False, analytics_enabled=False,
                    httpx_kwargs={"trust_env": False, "timeout": 60}, download_files=work / "release-downloads")
    def call(name, *args):
        return client.submit(*args, api_name="/" + name).result(timeout=90)
    try:
        saved = call("save_settings", str(output), str(download), "较小 MP4", 12, .75, 3)
        assert "设置已保存" in saved, saved
        values = call("read_settings")
        assert values[:6] == (str(output), str(download), "较小 MP4", 12, .75, 3), values
        call("import_video", handle_file(str(source)))
        # A new destination is not globally served; only actual results are permitted.
        first = call("export_video", "较小 MP4", 12, .75, "中文 成品", str(output))
        assert "导出完成" in first[3] and (output / "中文 成品.mp4").is_file(), first
        first_bytes = (output / "中文 成品.mp4").read_bytes()
        clean = call("clean_cache")
        assert "受到保护" in clean, clean
        second = call("export_video", "较小 MP4", 12, .75, "中文 成品", str(output))
        assert "导出完成" in second[3], second
        assert len(list(output.glob("中文 成品*.mp4"))) == 2
        assert (output / "中文 成品.mp4").read_bytes() == first_bytes
        diagnostic = call("diagnostics")
        assert "ffprobe" in diagnostic and "最近日志" in diagnostic, diagnostic
        bad = call("export_video", "通用 MP4", 15, .5, "../错误", str(output))
        assert "文件名" in bad[3], bad
        return dict(status="passed", settings_and_custom_paths="passed", no_overwrite="passed",
                    cache_protects_loaded_video="passed", diagnostics="passed", invalid_filename="passed",
                    output=str(output), download=str(download))
    finally:
        client.close()


def verify_restart_and_exit(url, expected, source=None):
    import time
    from gradio_client import Client, handle_file
    if source is None:
        source = next((Path(expected["output"]).parent / "media").glob("selfcheck_*/原始 样例.mp4"))
    client = Client(url, verbose=False, analytics_enabled=False,
                    httpx_kwargs={"trust_env": False, "timeout": 30}, download_files=False)
    try:
        values = client.predict(api_name="/read_settings")
        assert values[:6] == (expected["output"], expected["download"], "较小 MP4", 12, .75, 3), values
        loaded = client.predict(handle_file(str(source)), api_name="/import_video")
        table = dict(loaded[1])
        table["data"] *= 80
        client.predict(table, api_name="/table")
        job = client.submit("通用 MP4", 15, .5, "退出时取消测试", expected["output"], api_name="/export_video")
        time.sleep(.5)
        message = client.predict(api_name="/exit_app")
        assert "退出" in message
        result = job.result(timeout=30)
        assert "已取消" in result[3] or "正在退出" in result[3], result
        assert not list(Path(expected["output"]).glob("退出时取消测试*.mp4"))
    finally:
        client.close()
