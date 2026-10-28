"""Compare real RC1/RC2 API exports on identical generated 1080p media."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from modules import ffmpeg_util


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True, help="Verified RC1 BiliVideoTool.exe")
    parser.add_argument("--hardware", default="Not recorded", help="GPU/CPU description for the report")
    options = parser.parse_args()
    old = options.baseline.resolve()
    if not old.is_file():
        parser.error("--baseline must point to the verified RC1 executable")
    base = ROOT / "build" / "rc2-benchmark"
    base.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=base))
    source = base / "1080p-60s.mp4"
    if not source.exists():
        print("Generating 60-second 1080p fixture...", flush=True)
        ffmpeg_util.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=30:duration=60",
            "-f", "lavfi", "-i", "sine=frequency=880:duration=60", "-c:v", "libx264", "-preset", "ultrafast",
            "-crf", "25", "-c:a", "aac", str(source)])
    from gradio_client import Client, handle_file
    report = {"fixture": "Generated 60-second 1920x1080 30fps video, watermark fading + mute",
              "hardware": options.hardware, "measure": "API submission through export completion; fixture upload excluded", "cases": []}
    for version, command in (("rc1", [str(old)]), ("rc2", [sys.executable, "-X", "utf8", str(ROOT / "src" / "main.py")])):
        folder = work / version
        folder.mkdir(exist_ok=True)
        env = os.environ.copy()
        env.update(BILI_CONFIG_HOME=str(folder / "config"), BILI_VIDEO_HOME=str(folder / "data"), PYTHONUTF8="1")
        with (folder / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command + ["--no-browser", "--port", "57541"], cwd=folder, env=env,
                stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            client = None
            try:
                deadline = time.monotonic() + 60
                statefile = folder / "config" / "instance.json"
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"{version} startup failed")
                    if statefile.exists():
                        state = json.loads(statefile.read_text(encoding="utf-8"))
                        url = f"http://127.0.0.1:{state['port']}/"
                        break
                    if time.monotonic() > deadline: raise TimeoutError("startup")
                    time.sleep(.2)
                client = Client(url, verbose=False, analytics_enabled=False, httpx_kwargs={"trust_env":False}, download_files=False)
                loaded = client.predict(handle_file(str(source)), api_name="/import_video")
                client.predict(True, 1, "全部片段", api_name="/effects")
                frame = json.loads(loaded[8]); frame["rect"] = [.8, .8, .95, .95]
                client.predict(json.dumps(frame), "水印淡化", "全部片段", api_name="/region")
                cases = [("full_60s", "cpu")] if version == "rc1" else [("full_60s", "cpu"), ("full_60s", "auto")]
                cases += [("tail_5s", "cpu")]
                for case, mode in cases:
                    if case == "tail_5s": client.predict(50, 55, api_name="/trim")
                    name = f"{case}_{mode}"
                    args = ["通用 MP4", 15, .5, name, str(folder / "output")]
                    if version == "rc2": args.append(mode)
                    start = time.perf_counter()
                    result = client.submit(*args, api_name="/export_video").result(timeout=600)
                    seconds = time.perf_counter() - start
                    if "导出完成" not in result[3]: raise RuntimeError(str(result))
                    output = folder / "output" / (name + ".mp4")
                    metadata = ffmpeg_util.get_video_info(output)
                    ffmpeg_util.run_ffmpeg(["-v", "error", "-i", str(output), "-f", "null", "-"])
                    entry = dict(version=version, case=case, mode=mode, seconds=round(seconds, 2), bytes=output.stat().st_size,
                                 media=metadata, message=result[3])
                    report["cases"].append(entry)
                    print(json.dumps(entry, ensure_ascii=False), flush=True)
                client.predict(api_name="/exit_app")
                process.wait(timeout=30)
            finally:
                if client: client.close()
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=15)
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Report: {work / 'report.json'}", flush=True)


if __name__ == "__main__": main()
