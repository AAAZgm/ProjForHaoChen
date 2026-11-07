"""Distribution invariants and POSIX process ownership."""
import io
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from modules import runtime, desktop, tasks
from portable_archive import create_archive, extract_archive, write_launcher
import prepare_ffprobe


class PlatformPackaging(unittest.TestCase):
    def test_source_mirrors_reject_wrong_hash_before_fallback(self):
        import hashlib
        good = b"verified source"
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "source.tar.xz"
            with patch.object(prepare_ffprobe, "SOURCE_SHA256", hashlib.sha256(good).hexdigest()), \
                    patch.object(prepare_ffprobe.urllib.request, "urlopen", side_effect=[
                        OSError("offline"), io.BytesIO(b"corrupt"), io.BytesIO(good)]):
                prepare_ffprobe.download_source(archive)
            self.assertEqual(archive.read_bytes(), good)
            self.assertFalse(archive.with_suffix(".part").exists())

    def test_macos_config_and_explicit_override(self):
        home = Path.home()
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, "platform", "darwin"), \
                patch.object(Path, "home", return_value=home):
            self.assertEqual(runtime.config_dir(), home / "Library/Application Support/BiliVideoTool")
            with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"BILI_CONFIG_HOME": temp}):
                self.assertEqual(runtime.config_dir(), Path(temp).resolve())

    def test_external_helpers_restore_library_environment(self):
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/bundle", "LD_LIBRARY_PATH_ORIG": "/system",
                                    "DYLD_LIBRARY_PATH": "/bundle"}, clear=True), \
                patch.object(sys, "frozen", True, create=True):
            result = desktop.system_environment()
            self.assertEqual(result["LD_LIBRARY_PATH"], "/system")
            self.assertNotIn("DYLD_LIBRARY_PATH", result)
            self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/bundle")

    def test_windows_archive_roundtrip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "BiliVideoTool"
            bundle.mkdir()
            (bundle / "中文.txt").write_text("data", encoding="utf-8")
            archive = root / "app.zip"
            create_archive(bundle, archive, True)
            extract_archive(archive, root / "unpacked", True)
            self.assertEqual((root / "unpacked/BiliVideoTool/中文.txt").read_text(), "data")

    def test_tar_rejects_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                member = tarfile.TarInfo("../escape")
                member.size = 1
                output.addfile(member, io.BytesIO(b"x"))
            with self.assertRaises(tarfile.FilterError):
                extract_archive(archive, root / "output", False)
            self.assertFalse((root / "escape").exists())

    @unittest.skipIf(os.name == "nt", "POSIX file modes and symbolic links")
    def test_native_archive_preserves_launcher_and_symlinks(self):
        with tempfile.TemporaryDirectory(prefix="中文 archive ") as temp:
            root = Path(temp)
            bundle = root / "BiliVideoTool"
            bundle.mkdir()
            exe = bundle / "BiliVideoTool"
            exe.write_text('#!/bin/sh\nprintf "%s" "$1"\n')
            exe.chmod(0o755)
            (bundle / "alias").symlink_to("BiliVideoTool")
            macos = sys.platform == "darwin"
            write_launcher(bundle, macos)
            archive = root / "app.tar.gz"
            create_archive(bundle, archive, False)
            unpacked = root / "unpacked"
            extract_archive(archive, unpacked, False)
            self.assertTrue((unpacked / "BiliVideoTool/alias").is_symlink())
            result = subprocess.run([str(unpacked / "BiliVideoTool" / ("Start.command" if macos else "start.sh")), "中文 参数"],
                                    cwd=root, capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout, "中文 参数")

    @unittest.skipIf(os.name == "nt", "POSIX process groups")
    def test_cancellation_stops_owned_descendant_and_preserves_unrelated_process(self):
        # A descendant holds the stdout pipe: orphaning it makes communicate time out.
        child_code = 'import time; print("ready", flush=True); time.sleep(60)'
        worker_code = f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{child_code!r}]); time.sleep(60)'
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        worker = subprocess.Popen([sys.executable, "-c", worker_code], start_new_session=True,
                                  stdout=subprocess.PIPE, text=True)
        worker._bili_process_group = True
        try:
            self.assertEqual(worker.stdout.readline().strip(), "ready")
            tasks.stop_process(worker, tree=True)
            worker.communicate(timeout=5)
            self.assertIsNone(unrelated.poll())
        finally:
            tasks.stop_process(worker, tree=True)
            unrelated.terminate()
            unrelated.wait(timeout=5)
