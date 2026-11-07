"""Regressions for the independently reported release audit findings."""
import hashlib
import io
import json
import os
from pathlib import Path
import runpy
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from modules import platform_support
from portable_archive import write_launcher
from bundle_validation import finalize_ffprobe_manifest, verify_bundle, verify_macos_binaries, macho_metadata


def macho(cpu=0x100000C, minimum=(15, 0, 0)):
    version = (minimum[0] << 16) | (minimum[1] << 8) | minimum[2]
    return (struct.pack("<8I", 0xFEEDFACF, cpu, 0, 2, 1, 24, 0, 0)
            + struct.pack("<6I", 0x32, 24, 1, version, version, 0))


class DistributionAudit(unittest.TestCase):
    def test_macos_versions_and_unreadable_version(self):
        for version in ("11.0", "12.7.6", "14.9", "", "unknown"):
            with self.subTest(version=version):
                self.assertIn("需要 macOS 15.0", platform_support.compatibility_error("darwin", version))
        for version in ("15.0", "15.8.2", "26.0.1"):
            self.assertEqual(platform_support.compatibility_error("darwin", version), "")

    def test_windows_and_linux_are_not_subject_to_macos_requirement(self):
        for system in ("win32", "linux"):
            self.assertEqual(platform_support.compatibility_error(system, "0.0"), "")

    def test_main_rejects_old_macos_before_importing_gradio(self):
        import builtins
        original = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name in ("gradio", "orjson"):
                self.fail("Native interface dependencies were imported before rejecting macOS")
            return original(name, *args, **kwargs)
        output = io.StringIO()
        with patch.object(sys, "platform", "darwin"), \
                patch.object(platform_support.platform, "mac_ver", return_value=("14.7", (), "")), \
                patch.object(builtins, "__import__", side_effect=guarded_import), \
                patch.object(sys, "stderr", output), self.assertRaises(SystemExit) as error:
            runpy.run_path(str(ROOT / "src/main.py"), run_name="__main__")
        self.assertEqual(error.exception.code, 2)
        self.assertIn("当前为 macOS 14.7", output.getvalue())

    @unittest.skipIf(os.name == "nt", "POSIX shell")
    def test_launcher_rejects_old_and_unknown_versions_without_running_binary(self):
        with tempfile.TemporaryDirectory(prefix="轻剪 启动 ") as temp:
            root = Path(temp)
            binary = root / "BiliVideoTool"
            binary.write_text('#!/bin/sh\nprintf "ran:%s" "$1"\n')
            binary.chmod(0o755)
            write_launcher(root, True)
            launcher = root / "Start.command"
            template = launcher.read_text()
            for version, status in (("14.7", 2), ("", 2), ("unreadable", 2), ("15.0", 0), ("26.1", 0)):
                # Replace only the OS API in a temporary copy; product has no bypass environment variable.
                launcher.write_text(template.replace("SYSTEM_VERSION_COMPAT=0 /usr/bin/sw_vers -productVersion", f"printf '%s' '{version}'"))
                result = subprocess.run([str(launcher), "中文 参数"], cwd=ROOT, text=True,
                                        capture_output=True, timeout=5)
                self.assertEqual(result.returncode, status)
                if status:
                    self.assertIn("需要 macOS 15.0", result.stderr)
                    self.assertNotIn("ran:", result.stdout)
                else:
                    self.assertEqual(result.stdout, "ran:中文 参数")

    def test_final_manifest_tracks_frozen_bytes_and_detects_later_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / "_internal/vendor/ffprobe"
            folder.mkdir(parents=True)
            binary = folder / "ffprobe"
            binary.write_bytes(b"rewritten and signed")
            before = hashlib.sha256(b"original").hexdigest()
            (folder / "source.json").write_text(json.dumps({"binary_sha256": before, "url": "source-url"}))
            (folder / "README.txt").write_text("source info")
            finalize_ffprobe_manifest(root)
            data = json.loads((folder / "source.json").read_text())
            self.assertEqual(data["sha256_before_freeze"], before)
            self.assertEqual(data["url"], "source-url")
            self.assertEqual(binary.read_bytes(), b"rewritten and signed")
            self.assertEqual(verify_bundle(root)["ffprobe"]["status"], "passed")
            binary.write_bytes(b"modified after packaging")
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                verify_bundle(root)

    def test_old_prefreeze_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "_internal/vendor/ffprobe"
            folder.mkdir(parents=True)
            (folder / "ffprobe").write_bytes(b"same")
            (folder / "source.json").write_text(json.dumps({"binary_sha256": hashlib.sha256(b"same").hexdigest()}))
            with self.assertRaises(RuntimeError):
                verify_bundle(Path(temp))

    def test_every_macho_dependency_must_match_architecture_and_os_floor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "main").write_bytes(macho())
            dependency = root / "dependency.so"
            dependency.write_bytes(macho(minimum=(12, 0, 0)))
            self.assertEqual(verify_macos_binaries(root, "arm64")["mach_o_count"], 2)
            for data in (macho(minimum=(15, 1, 0)), macho(cpu=0x1000007)):
                dependency.write_bytes(data)
                with self.assertRaisesRegex(RuntimeError, "requirements exceeded"):
                    verify_macos_binaries(root, "arm64")

    def test_truncated_macho_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "broken"
            path.write_bytes(macho()[:-4])
            with self.assertRaises(RuntimeError):
                macho_metadata(path)

    def test_foreign_platform_and_unsupported_macho_formats_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "foreign"
            ios = bytearray(macho())
            struct.pack_into("<I", ios, 40, 2)
            for content in (ios, b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
                path.write_bytes(content)
                with self.assertRaises(RuntimeError):
                    macho_metadata(path)
