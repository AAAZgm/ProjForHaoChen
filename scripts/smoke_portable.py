"""Check an extracted portable build without Python/FFmpeg on its PATH."""

import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


def wait_ready(process, work, opener):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Portable server exited: see {work / 'server.log'}")
        try:
            state = json.loads((work / "config" / "instance.json").read_text(encoding="utf-8"))
            url = f"http://127.0.0.1:{int(state['port'])}/"
            with opener.open(url + "config", timeout=2) as response:
                return url, json.load(response)
        except (OSError, ValueError, KeyError):
            time.sleep(.5)
    raise RuntimeError("Portable server did not start within 60 seconds")


def smoke_portable(executable: Path, work: Path) -> dict:
    executable, work = executable.resolve(), work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    env = {key.upper(): value for key, value in os.environ.items()} if os.name == "nt" else os.environ.copy()
    for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "CONDA_PREFIX", "IMAGEIO_FFMPEG_EXE",
                "BILI_VIDEO_HOME", "GRADIO_SERVER_NAME", "GRADIO_SERVER_PORT"):
        env.pop(key, None)
    if os.name == "nt":
        system = Path(env["SYSTEMROOT"])
        env["PATH"] = os.pathsep.join([str(system / "System32"), str(system)])
    else:
        env["PATH"] = "/usr/bin:/bin"
    env.update(GRADIO_ANALYTICS_ENABLED="False", PYTHONUTF8="1", NO_PROXY="localhost,127.0.0.1,::1",
               no_proxy="localhost,127.0.0.1,::1", GRADIO_TEMP_DIR=str(work / "gradio"),
               BILI_CONFIG_HOME=str(work / "config"))
    hidden = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    media_log = work / "selfcheck.log"
    with media_log.open("w", encoding="utf-8") as log:
        subprocess.run([str(executable), "--self-test", str(work / "media")],
                       cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=120, creationflags=hidden)
    reports = list((work / "media").glob("selfcheck_*/report.json"))
    if len(reports) != 1:
        raise RuntimeError("Expected exactly one portable self-check report")
    media = json.loads(reports[0].read_text(encoding="utf-8"))
    if not media["frozen"] or media["utf8_mode"] != 1:
        raise RuntimeError("The portable runtime is not frozen or UTF-8 enabled")
    if not Path(media["ffmpeg"]).resolve().is_relative_to(executable.parent):
        raise RuntimeError("The application used an external FFmpeg")
    if not Path(media["ffprobe"]).resolve().is_relative_to(executable.parent):
        raise RuntimeError("The application used an external ffprobe")

    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    port = occupied.getsockname()[1]
    url = f"http://127.0.0.1:{port}/"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with (work / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(executable), "--no-browser", "--port", str(port), "--data-dir", str(work / "data")],
            cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=hidden,
        )
        try:
            url, config = wait_ready(process, work, opener)
            assert url != f"http://127.0.0.1:{port}/", "Occupied port was not replaced"
            occupied.close()
            duplicate = subprocess.run([str(executable), "--no-browser"], cwd=work, env=env,
                capture_output=True, timeout=60, creationflags=hidden, check=True)
            assert "程序已在运行" in duplicate.stdout.decode("utf-8"), duplicate.stdout
            assert process.poll() is None
            with opener.open(url, timeout=5) as response:
                html = response.read().decode("utf-8")
            assets = re.findall(r'(?:src|href)="([^\"]+\.(?:js|css)(?:\?[^\"]*)?)"', html)
            local_assets = [urllib.parse.urljoin(url, asset) for asset in assets
                            if urllib.parse.urljoin(url, asset).startswith(url)]
            if not local_assets or not config.get("components"):
                raise RuntimeError("Missing interface components or local static assets")
            for asset in local_assets:
                with opener.open(asset, timeout=10) as response:
                    if response.status != 200 or not response.read(1):
                        raise RuntimeError(f"Missing static asset: {asset}")
            from check_editor_api import check_editor
            source = Path(media["directory"]) / "原始 样例.mp4"
            editor_report = check_editor(url, source, work / "client-downloads")
            from check_release_api import check_release, verify_restart_and_exit
            release_report = check_release(url, source, work)
            from gradio_client import Client
            exit_client = Client(url, verbose=False, analytics_enabled=False,
                                 httpx_kwargs={"trust_env": False}, download_files=False)
            try:
                exit_client.predict(api_name="/exit_app")
            finally:
                exit_client.close()
            assert process.wait(timeout=30) == 0
            assert not (work / "config" / "instance.json").exists()
            assert not list((work / "config" / "cache" / "runs").iterdir())
            process = subprocess.Popen([str(executable), "--no-browser", "--data-dir", str(work / "data")],
                cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=hidden)
            url, _ = wait_ready(process, work, opener)
            verify_restart_and_exit(url, release_report, source)
            assert process.wait(timeout=30) == 0
            release_report.update(repeat_launch="passed", occupied_port="passed", restart_persistence="passed",
                                  graceful_exit_and_cache_cleanup="passed", exit_cancels_active_export="passed")
            return {"status": "passed", "media": media,
                    "http": {"components": len(config["components"]), "local_assets": len(local_assets),
                             "editor": editor_report, "release": release_report},
                    "isolation": "Frozen executable, bundled FFmpeg and ffprobe, stripped PATH, unrelated working directory"}
        finally:
            occupied.close()
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
