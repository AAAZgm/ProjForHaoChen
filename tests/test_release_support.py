"""Release-support behavior: persistence, safe cleanup, redaction and recovery."""
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from modules import runtime, settings, storage, diagnostics, lifecycle, updates, tasks


class ReleaseSupport(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="轻剪 配置_")
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"BILI_CONFIG_HOME": str(self.root / "config"),
                                          "BILI_VIDEO_HOME": str(self.root / "files")})
        self.env.start()

    def tearDown(self):
        for handler in list(diagnostics.LOG.handlers):
            diagnostics.LOG.removeHandler(handler)
            handler.close()
        settings._notice = ""
        self.env.stop()
        self.temp.cleanup()

    def test_preferences_roundtrip_and_no_temporary_file(self):
        values = settings.save(output_dir=str(self.root / "中文 成品"), preset="GIF 动图", gif_fps=10)
        self.assertEqual(settings.load(), values)
        self.assertEqual(list(runtime.config_dir().glob("*.tmp")), [])
        self.assertEqual(settings.load()["gif_fps"], 10)

    def test_export_summary_uses_current_unsaved_folder(self):
        from modules.workspace import Workspace
        from ui import summary
        project = Workspace()
        project.load("sample.mp4", dict(duration=2, width=160, height=120))
        new_path = str(self.root / "新成品位置")
        result = summary(project, directory=new_path)
        self.assertIn(new_path, result)
        self.assertNotIn(str(runtime.data_dir() / "output"), result)

    def test_invalid_preferences_preserved_and_restored(self):
        runtime.config_dir().mkdir()
        (runtime.config_dir() / "settings.json").write_text("broken {", encoding="utf-8")
        self.assertEqual(settings.load()["preset"], settings.PRESETS[0])
        self.assertEqual(len(list(runtime.config_dir().glob("settings.invalid-*.json"))), 1)
        self.assertIn("备份", settings.notice())

    def test_invalid_save_cannot_replace_valid_config(self):
        old = settings.save()
        with self.assertRaises(ValueError):
            settings.save(gif_fps=float("nan"))
        self.assertEqual(settings.load(), old)
        with self.assertRaises(ValueError):
            settings.save(output_dir=str(runtime.cache_dir() / "danger"))
        with self.assertRaises(ValueError):
            settings.save(output_dir="relative")

    def test_readonly_application_folder_falls_back(self):
        with patch.dict(os.environ, {}, clear=False), patch("modules.runtime.tempfile.TemporaryFile", side_effect=PermissionError):
            os.environ.pop("BILI_VIDEO_HOME", None)
            self.assertEqual(runtime.data_dir(), runtime.config_dir() / "files")

    def test_no_overwrite_and_invalid_names(self):
        existing = self.root / "源素材.mp4"
        existing.write_bytes(b"original")
        output = storage.reserve_output(self.root, "源素材", "mp4")
        self.assertNotEqual(str(existing), output)
        self.assertEqual(existing.read_bytes(), b"original")
        for name in ("../escape", "CON", "A:B", "..", "\\escape", "a" * 121):
            with self.subTest(name=name), self.assertRaises(ValueError):
                storage.filename(name)

    def test_cache_only_deletes_old_runs_protects_current_and_user_files(self):
        current = runtime.session_cache()
        old = runtime.cache_dir() / "runs" / ("a" * 32)
        unknown = runtime.cache_dir() / "runs" / "personal"
        output = runtime.data_dir() / "output"
        for folder in (current, old, unknown, output):
            folder.mkdir(parents=True)
            (folder / "keep.mp4").write_bytes(b"1234")
        removed, size, skipped = storage.clean_cache()
        self.assertEqual((removed, size), (1, 4))
        self.assertFalse(old.exists())
        for folder in (current, unknown, output):
            self.assertTrue((folder / "keep.mp4").is_file())

    def test_cache_retention_and_linked_tree_are_skipped(self):
        folder = runtime.cache_dir() / "runs" / ("b" * 32)
        folder.mkdir(parents=True)
        self.assertEqual(storage.clean_cache(days=7)[0], 0)
        with patch("modules.storage._linked", side_effect=lambda p: p == folder):
            self.assertEqual(storage.clean_cache(days=0)[0], 0)
        self.assertTrue(folder.exists())

    def test_disk_full_and_unwritable_folder_have_actionable_errors(self):
        with patch("modules.storage.shutil.disk_usage") as usage:
            usage.return_value.free = 0
            with self.assertRaises(OSError) as exc:
                storage.require_space(self.root)
            self.assertIn("空间不足", tasks.friendly_error(exc.exception))
        with patch("modules.settings.tempfile.TemporaryFile", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                settings.save()
        self.assertIn("更换目录", tasks.friendly_error(PermissionError()))

    def test_log_redaction_and_bounded_rotation(self):
        diagnostics.setup()
        text = "Cookie: SESSDATA=secretCookie\nAuthorization: Bearer secretBearer\nhttps://example.com/path?token=secretQuery\npassword=secretPassword"
        diagnostics.LOG.error(text)
        saved = (runtime.config_dir() / "logs" / "application.log").read_text(encoding="utf-8")
        for secret in ("secretCookie", "secretBearer", "secretQuery", "secretPassword"):
            self.assertNotIn(secret, saved)
        handler = diagnostics.LOG.handlers[0]
        self.assertEqual((handler.maxBytes, handler.backupCount), (1024 * 1024, 3))

    def test_single_instance_lock_release_and_occupied_port(self):
        first, second = lifecycle.Instance(), lifecycle.Instance()
        self.assertTrue(first.acquire())
        try:
            self.assertFalse(second.acquire())
        finally:
            first.close()
        self.assertTrue(second.acquire())
        second.close()
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            self.assertNotEqual(lifecycle.available_port(occupied.getsockname()[1]), occupied.getsockname()[1])

    def test_updates_new_same_offline_missing_and_rate_limited(self):
        for tag, message in (("v1.0.0", "发现正式版本"), ("v0.2.0", "未发现更新")):
            with patch("modules.updates.urllib.request.urlopen", return_value=io.BytesIO(json.dumps({"tag_name": tag}).encode())):
                self.assertIn(message, updates.check_update())
        with patch("modules.updates.urllib.request.urlopen", side_effect=OSError("offline")):
            self.assertIn("本地编辑不受影响", updates.check_update())
        for code, message in ((404, "尚未提供"), (403, "限流")):
            with patch("modules.updates.urllib.request.urlopen", side_effect=urllib.error.HTTPError(updates.API, code, "", {}, None)):
                self.assertIn(message, updates.check_update())
