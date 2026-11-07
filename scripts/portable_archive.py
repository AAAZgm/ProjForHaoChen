"""Preserve POSIX execute bits and PyInstaller's internal symbolic links."""
from pathlib import Path
import tarfile
import zipfile


def create_archive(bundle, destination, windows):
    bundle, destination = Path(bundle), Path(destination)
    if windows:
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for file in sorted(bundle.rglob("*")):
                if file.is_file():
                    archive.write(file, file.relative_to(bundle.parent))
    else:
        with tarfile.open(destination, "w:gz", dereference=False) as archive:
            archive.add(bundle, arcname=bundle.name)


def extract_archive(source, destination, windows):
    if windows:
        with zipfile.ZipFile(source) as archive:
            archive.extractall(destination)
    else:
        # data filter rejects absolute/traversing paths and escaping symlinks.
        with tarfile.open(source, "r:gz") as archive:
            archive.extractall(destination, filter="data")


def write_launcher(bundle, macos):
    launcher = Path(bundle) / ("Start.command" if macos else "start.sh")
    gate = ""
    if macos:
        # Check before the frozen bootloader or Python loads any binary dependency.
        from modules.platform_support import MIN_MACOS, MIN_MACOS_TEXT
        gate = f'''version=$(SYSTEM_VERSION_COMPAT=0 /usr/bin/sw_vers -productVersion 2>/dev/null) || version=""
major=${{version%%.*}}
case "$major" in
    ''|*[!0-9]*) supported=false ;;
    *) if [ "$major" -ge {MIN_MACOS[0]} ]; then supported=true; else supported=false; fi ;;
esac
if [ "$supported" = false ]; then
    printf '%s\\n' "轻剪此版本需要 macOS {MIN_MACOS_TEXT} 或更新系统，当前版本：${{version:-无法确认}}。请检查系统版本后再启动。" >&2
    if [ -t 0 ]; then
        printf '%s' '按回车关闭此窗口。' >&2
        IFS= read -r reply || :
    fi
    exit 2
fi
'''
    launcher.write_text('#!/bin/sh\nset -eu\n' + gate + 'cd "$(dirname "$0")"\nexec ./BiliVideoTool "$@"\n', encoding="utf-8", newline="\n")
    launcher.chmod(0o755)
