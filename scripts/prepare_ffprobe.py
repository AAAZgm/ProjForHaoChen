"""Install the pinned Windows ffprobe for source use and portable builds."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "8.1.2"
URL = "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip"
SHA256 = "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def prepare():
    if os.name != "nt":
        if not shutil.which("ffprobe"):
            raise RuntimeError("Please install FFmpeg including ffprobe using your system package manager.")
        return
    cache = ROOT / ".cache" / "ffprobe"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"ffmpeg-{VERSION}.zip"
    if not archive.exists() or digest(archive) != SHA256:
        partial = archive.with_suffix(".part")
        try:
            print(f"Downloading pinned ffprobe {VERSION} from gyan.dev...", flush=True)
            with urllib.request.urlopen(URL, timeout=60) as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output)
            if digest(partial) != SHA256:
                raise RuntimeError("FFprobe archive checksum mismatch; the download was not installed.")
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    destination = ROOT / "src" / "vendor" / "ffprobe"
    destination.mkdir(parents=True, exist_ok=True)
    prefix = f"ffmpeg-{VERSION}-essentials_build/"
    with zipfile.ZipFile(archive) as zipped:
        for member, name in (("bin/ffprobe.exe", "ffprobe.exe"), ("LICENSE", "LICENSE.txt"), ("README.txt", "README.txt")):
            with zipped.open(prefix + member) as source, (destination / name).open("wb") as output:
                shutil.copyfileobj(source, output)
    (destination / "source.json").write_text(json.dumps(dict(version=VERSION, url=URL,
        archive_sha256=SHA256, binary_sha256=digest(destination / "ffprobe.exe")), indent=2), encoding="utf-8")
    print(f"Verified ffprobe installed: {destination}", flush=True)


if __name__ == "__main__":
    prepare()
