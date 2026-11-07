"""Verify the final, frozen files rather than their pre-freeze inputs."""
import hashlib
import json
from pathlib import Path
import struct


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def probe_paths(bundle):
    folder = Path(bundle) / "_internal" / "vendor" / "ffprobe"
    binary = folder / "ffprobe"
    if not binary.is_file():
        binary = folder / "ffprobe.exe"
    return folder, binary


def finalize_ffprobe_manifest(bundle):
    folder, binary = probe_paths(bundle)
    manifest = folder / "source.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data.setdefault("sha256_before_freeze", data["binary_sha256"])
    data["binary_sha256"] = digest(binary)
    data["binary_sha256_stage"] = "packaged_after_freeze"
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    with (folder / "README.txt").open("a", encoding="utf-8") as stream:
        stream.write("\nsource.json: binary_sha256 hashes the delivered ffprobe after freezing/signing.\n"
                     "sha256_before_freeze hashes the original build input; these may differ on macOS.\n")


def macho_metadata(path):
    with Path(path).open("rb") as stream:
        magic = stream.read(4)
        if magic in (b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca", b"\xca\xfe\xba\xbf", b"\xbf\xba\xfe\xca",
                     b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf"):
            raise RuntimeError(f"Unsupported Mach-O format in single-architecture 64-bit package: {path}")
        if magic != b"\xcf\xfa\xed\xfe":
            return None
        header = stream.read(28)
        if len(header) != 28:
            raise RuntimeError(f"Truncated Mach-O header: {path}")
        cpu, _, _, count, size, _, _ = struct.unpack("<7I", header)
        if size > 16 * 1024 * 1024:
            raise RuntimeError(f"Invalid Mach-O commands size: {path}")
        commands = stream.read(size)
    offset, minimum = 0, None
    for _ in range(count):
        if offset + 8 > len(commands):
            raise RuntimeError(f"Truncated Mach-O commands: {path}")
        cmd, length = struct.unpack_from("<II", commands, offset)
        if length < 8 or offset + length > len(commands):
            raise RuntimeError(f"Invalid Mach-O command: {path}")
        if cmd in (0x32, 0x24):
            if length < (24 if cmd == 0x32 else 16):
                raise RuntimeError(f"Invalid Mach-O version command: {path}")
            if cmd == 0x32 and struct.unpack_from("<I", commands, offset + 8)[0] != 1:
                raise RuntimeError(f"Non-macOS Mach-O platform: {path}")
            value = struct.unpack_from("<I", commands, offset + (12 if cmd == 0x32 else 8))[0]
            version = (value >> 16, (value >> 8) & 255, value & 255)
            minimum = max(minimum or version, version)
        offset += length
    if minimum is None:
        raise RuntimeError(f"Missing macOS minimum version: {path}")
    return cpu, minimum


def verify_macos_binaries(bundle, architecture):
    from modules.platform_support import MIN_MACOS
    expected = {"arm64": 0x100000C, "x86_64": 0x1000007}[architecture]
    ceiling = (*MIN_MACOS, 0)
    binaries = []
    for path in sorted(Path(bundle).rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        metadata = macho_metadata(path)
        if metadata is None:
            continue
        cpu, minimum = metadata
        if cpu != expected or minimum > ceiling:
            raise RuntimeError(f"Package platform requirements exceeded: {path}: CPU={cpu:x}, macOS={minimum}")
        binaries.append({"path": path.relative_to(bundle).as_posix(),
                         "minimum_macos": ".".join(map(str, minimum))})
    if not binaries:
        raise RuntimeError("No Mach-O binaries in macOS package")
    return {"status": "passed", "architecture": architecture, "minimum_supported_macos": ".".join(map(str, ceiling)),
            "mach_o_count": len(binaries), "binaries": binaries}


def verify_bundle(bundle, macos_architecture=None):
    folder, binary = probe_paths(bundle)
    data = json.loads((folder / "source.json").read_text(encoding="utf-8"))
    actual = digest(binary)
    if data.get("binary_sha256_stage") != "packaged_after_freeze" or data.get("binary_sha256") != actual:
        raise RuntimeError("Delivered ffprobe does not match source.json")
    result = {"ffprobe": {"status": "passed", "binary_sha256": actual,
                          "sha256_before_freeze": data["sha256_before_freeze"]}}
    if macos_architecture:
        result["macos"] = verify_macos_binaries(bundle, macos_architecture)
    return result
