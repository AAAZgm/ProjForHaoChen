"""Install pinned ffprobe; build the POSIX binary from verified upstream source."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = "8.1.2"
URL = "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-8.1.2-essentials_build.zip"
SHA256 = "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"
SOURCE_URL = f"https://www.ffmpeg.org/releases/ffmpeg-{VERSION}.tar.xz"
SOURCE_SHA256 = "464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c"


def prepare_posix():
    if sys.platform not in ("darwin", "linux"):
        raise RuntimeError(f"Unsupported build platform: {sys.platform}")
    destination = ROOT / "src" / "vendor" / "ffprobe"
    binary = destination / "ffprobe"
    manifest = destination / "source.json"
    target = f"{sys.platform}-{platform.machine()}"
    if binary.is_file() and manifest.is_file():
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
        if (recorded.get("archive_sha256") == SOURCE_SHA256 and recorded.get("target") == target
                and recorded.get("binary_sha256") == digest(binary)):
            return
    cache = ROOT / ".cache" / "ffprobe"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"ffmpeg-{VERSION}.tar.xz"
    if not archive.is_file() or digest(archive) != SOURCE_SHA256:
        partial = archive.with_suffix(".part")
        try:
            with urllib.request.urlopen(SOURCE_URL, timeout=90) as response, partial.open("wb") as output:
                shutil.copyfileobj(response, output)
            if digest(partial) != SOURCE_SHA256:
                raise RuntimeError("FFmpeg source checksum mismatch")
            partial.replace(archive)
        finally:
            partial.unlink(missing_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"build-{target}-", dir=cache))
    with tarfile.open(archive, "r:xz") as source:
        source.extractall(work, filter="data")
    source = work / f"ffmpeg-{VERSION}"
    flags = ["--disable-autodetect", "--disable-shared", "--enable-static",
             "--disable-programs", "--enable-ffprobe", "--disable-doc", "--disable-debug",
             "--disable-x86asm", "--disable-network", "--disable-encoders", "--disable-muxers",
             "--disable-devices", "--disable-filters", "--disable-hwaccels",
             "--disable-protocols", "--enable-protocol=file"]
    log_path = cache / f"build-{target}.log"
    print(f"Building native ffprobe {VERSION}; log: {log_path}", flush=True)
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.run(["sh", "configure", *flags], cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(["make", f"-j{min(os.cpu_count() or 2, 4)}", "ffprobe"], cwd=source,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    subprocess.run([str(source / "ffprobe"), "-version"], check=True, capture_output=True)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "ffprobe", binary)
    binary.chmod(0o755)
    shutil.copy2(source / "COPYING.LGPLv2.1", destination / "LICENSE.txt")
    (destination / "README.txt").write_text(
        f"FFprobe {VERSION}, built from {SOURCE_URL}\nSHA256: {SOURCE_SHA256}\n"
        + "Configure: " + " ".join(flags) + "\nNo external optional libraries; FFmpeg libraries linked statically.\n",
        encoding="utf-8")
    manifest.write_text(json.dumps(dict(version=VERSION, url=SOURCE_URL, archive_sha256=SOURCE_SHA256,
        binary_sha256=digest(binary), target=target, configure=flags), indent=2), encoding="utf-8")


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def prepare():
    if os.name != "nt":
        prepare_posix()
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
