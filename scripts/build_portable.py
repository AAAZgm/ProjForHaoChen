"""Run regressions, freeze, archive, then verify the extracted distribution."""

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from modules.runtime import APP_VERSION
from modules.ffmpeg_util import get_ffmpeg_exe
from smoke_portable import smoke_portable
from prepare_ffprobe import prepare as prepare_ffprobe


def third_party_notices(bundle: Path) -> None:
    lines = ["BiliVideoTool third-party component/build environment inventory", ""]
    for dist in sorted(importlib.metadata.distributions(), key=lambda item: item.metadata["Name"].lower()):
        name = dist.metadata["Name"]
        license_text = dist.metadata.get("License-Expression") or dist.metadata.get("License", "See package metadata")
        lines.extend([f"{name} {dist.version}", license_text, ""])
    lines.extend(["FFmpeg build license (source/build information: https://github.com/imageio/imageio-ffmpeg):", ""])
    result = subprocess.run([get_ffmpeg_exe(), "-L"], capture_output=True, check=True)
    lines.append((result.stdout + result.stderr).decode("utf-8", errors="replace"))
    lines.append("Full dependency license files are retained in _internal package metadata where supplied.")
    lines += ["", "ffprobe 8.1.2: https://www.gyan.dev/ffmpeg/builds/", 
              "Build source, license and checksum: _internal/vendor/ffprobe/README.txt, LICENSE.txt, source.json.",
              "Project source is MIT licensed; dependency licenses apply to their respective components."]
    (bundle / "THIRD_PARTY_NOTICES.txt").write_text("\n".join(lines), encoding="utf-8")
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, bundle / "PYTHON_LICENSE.txt")


def main() -> None:
    build, dist = ROOT / "build", ROOT / "dist"
    # PyInstaller may replace its generated bundle: constrain those paths to this repository.
    for directory in (build, dist, dist / "BiliVideoTool"):
        if not directory.resolve().is_relative_to(ROOT):
            raise RuntimeError(f"Build output is outside this repository: {directory}")
    build.mkdir(exist_ok=True)
    dist.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(PYTHONUTF8="1", GRADIO_ANALYTICS_ENABLED="False",
               PYINSTALLER_CONFIG_DIR=str(build / "pyinstaller-cache"),
               BILI_CONFIG_HOME=str(build / "test-config"), BILI_VIDEO_HOME=str(build / "test-data"))
    prepare_ffprobe()
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                   cwd=ROOT, env=env, check=True)
    with (build / "pyinstaller.log").open("w", encoding="utf-8") as log:
        print(f"Building portable app; log: {build / 'pyinstaller.log'}", flush=True)
        subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                        "--distpath", str(dist), "--workpath", str(build / "pyinstaller"),
                        str(ROOT / "src" / "bili_video_tool.spec")],
                       cwd=ROOT / "src", env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    bundle = dist / "BiliVideoTool"
    shutil.copy2(ROOT / "docs" / "PORTABLE_README.md", bundle / "README.md")
    shutil.copy2(ROOT / "src" / "requirements.txt", bundle / "requirements.txt")
    for document in ("LICENSE", "CHANGELOG.md"):
        shutil.copy2(ROOT / document, bundle / document)
    third_party_notices(bundle)
    arch = "x64" if platform.machine().lower() in ("amd64", "x86_64") else platform.machine().lower()
    name = f"bili-video-tool-{APP_VERSION}-{platform.system().lower()}-{arch}"
    # A failed smoke check must not leave a final-named release zip behind.
    candidate = build / f"{name}.candidate.zip"
    with zipfile.ZipFile(candidate, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(bundle.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(dist))
    check_dir = Path(tempfile.mkdtemp(prefix="portable-中文 ", dir=build))
    with zipfile.ZipFile(candidate) as archive:
        archive.extractall(check_dir)
    executable = check_dir / "BiliVideoTool" / ("BiliVideoTool.exe" if os.name == "nt" else "BiliVideoTool")
    print("Verifying extracted zip with system-only PATH...", flush=True)
    report = smoke_portable(executable, check_dir / "verification")
    final_zip = dist / f"{name}.zip"
    candidate.replace(final_zip)
    digest = hashlib.sha256()
    with final_zip.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    checksum = digest.hexdigest()
    (dist / f"{name}.sha256").write_text(f"{checksum}  {final_zip.name}\n", encoding="ascii")
    report.update(archive=final_zip.name, sha256=checksum, bytes=final_zip.stat().st_size)
    (dist / f"{name}-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "archive": str(final_zip), "bytes": report["bytes"],
                      "sha256": checksum}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
