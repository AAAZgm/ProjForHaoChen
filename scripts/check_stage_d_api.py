"""Exercise Stage D through real Gradio sessions, including frozen distributions."""
from pathlib import Path
import time


def check_stage_d(url, source, work):
    from gradio_client import Client, handle_file
    from modules import ffmpeg_util
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    portrait = work / "竖屏 无声.mp4"
    ffmpeg_util.run_ffmpeg(["-i", str(source), "-vf", "transpose=1", "-an", "-r", "15", "-c:v", "libx264", str(portrait)])
    clients = [Client(url, verbose=False, analytics_enabled=False, httpx_kwargs={"trust_env": False, "timeout": 60},
                      download_files=work / f"client-{i}") for i in range(2)]
    client, other = clients
    def call(name, *args, current=client):
        return current.submit(*args, api_name="/" + name).result(timeout=120)
    output = str(work / "成品")
    try:
        added = call("studio_add", [handle_file(str(source)), handle_file(str(portrait))])
        assert len(added[1]["data"]) == 2, added
        empty = call("studio_run", "分别导出", "WAV 音频", output, "empty", "cpu", 15, .5, current=other)
        assert "先添加" in empty[2], empty
        loaded = call("studio_to_editor")
        assert "已载入列表素材" in loaded[6], loaded
        call("effects", True, 2, "全部片段")
        changed = call("studio_replace")
        assert "更新" in changed[2], changed
        merged = call("studio_run", "按顺序拼接", "较小 MP4", output, "混合拼接", "cpu", 15, .5)
        assert "拼接导出完成" in merged[2], merged
        assert (Path(output) / "混合拼接.mp4").is_file()
        batch = call("studio_run", "分别导出", "MP3 音频", output, "音频", "cpu", 15, .5)
        assert "成功 2 项，失败 0 项" in batch[2], batch
        assert len(batch[3]) == 2, batch
        saved = call("studio_save", output, "可恢复方案", "按顺序拼接", "M4A 音频", 12, .5)
        assert "已保存" in saved[1], saved
        plan = saved[0]
        restored = call("studio_load", handle_file(plan), current=other)
        assert len(restored[1]["data"]) == 2 and "已恢复" in restored[2], restored
        assert restored[3:7] == ("按顺序拼接", "M4A 音频", 12, .5), restored
        cleared = call("studio_clear")
        assert not cleared[1]["data"]
        audio = call("studio_run", "按顺序拼接", "M4A 音频", output, "恢复后音频", "cpu", 15, .5, current=other)
        assert "完成" in audio[2], audio
        invalid = call("studio_parse", "https://example.org/not-bilibili")
        assert "仅支持" in invalid[2], invalid
        assert not invalid[3]["choices"], invalid
        # Long list of cuts ensures cancellation reaches a running batch task.
        call("studio_load", handle_file(plan))
        loaded = call("studio_to_editor")
        table = loaded[1]
        table["data"] *= 80
        call("table", table)
        call("studio_replace")
        job = client.submit("分别导出", "通用 MP4", output, "取消批量", "cpu", 15, .5, api_name="/studio_run")
        time.sleep(.5)
        cancellation = call("studio_cancel")
        result = job.result(timeout=40)
        assert "取消" in cancellation and "取消" in result[2], (cancellation, result)
        # The other page still has its own two short clips and can export after cancel.
        recovered = call("studio_run", "分别导出", "WAV 音频", output, "另一个页面", "cpu", 15, .5, current=other)
        assert "成功 2 项" in recovered[2], recovered
        return dict(status="passed", multiple_uploads="passed", editor_snapshot_update="passed",
                    mixed_merge="passed", batch_audio="passed", portable_plan_restore="passed",
                    session_isolation="passed", cancellation_and_recovery="passed", part_worker_validation="passed")
    finally:
        for c in clients:
            c.close()


def check_stage_d_restart(url, work):
    """Restore from the saved artifact after the previous run's cache was removed."""
    from gradio_client import Client, handle_file
    from modules import ffmpeg_util
    work = Path(work)
    client = Client(url, verbose=False, analytics_enabled=False,
                    httpx_kwargs={"trust_env": False}, download_files=False)
    try:
        restored = client.predict(handle_file(str(work / "成品" / "可恢复方案.qjproj")), api_name="/studio_load")
        assert len(restored[1]["data"]) == 2 and "已恢复" in restored[2], restored
        output = work / "重启恢复"
        result = client.submit("按顺序拼接", "WAV 音频", str(output), "重启后音频", "cpu", 15, .5,
                               api_name="/studio_run").result(timeout=120)
        assert "拼接导出完成" in result[2], result
        streams = ffmpeg_util.probe(output / "重启后音频.wav")["streams"]
        assert [s["codec_type"] for s in streams] == ["audio"], streams
        return "passed"
    finally:
        client.close()
