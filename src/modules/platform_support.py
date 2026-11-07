"""Early platform checks; keep this module free of third-party imports."""
import platform
import re
import sys

MIN_MACOS = (15, 0)
MIN_MACOS_TEXT = ".".join(map(str, MIN_MACOS))


def compatibility_error(system=None, release=None):
    system = sys.platform if system is None else system
    if system != "darwin":
        return ""
    release = platform.mac_ver()[0] if release is None else release
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", release)
    if not match:
        return f"无法确认当前 macOS 版本；轻剪此版本需要 macOS {MIN_MACOS_TEXT} 或更新系统，请先检查系统版本。"
    if tuple(map(int, match.groups())) < MIN_MACOS:
        return (f"轻剪此版本需要 macOS {MIN_MACOS_TEXT} 或更新系统，当前为 macOS {release}。"
                "请升级系统后再启动，或使用支持当前系统的版本。")
    return ""


def require_supported_platform():
    message = compatibility_error()
    if message:
        print(message, file=sys.stderr, flush=True)
        raise SystemExit(2)
