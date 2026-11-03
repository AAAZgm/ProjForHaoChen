"""Window ownership, repeat launch and shutdown must never target personal tabs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from modules import app_window, lifecycle


class AppWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="轻剪 窗口测试_")
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"BILI_CONFIG_HOME": str(self.root)})
        self.env.start()
        self.window = app_window.AppWindow()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_launch_uses_unique_profile_and_retains_only_own_process(self):
        child = Mock()
        child.poll.return_value = None
        with patch.object(app_window, "browser_executable", return_value="browser.exe"), \
                patch.object(app_window.subprocess, "Popen", return_value=child) as launch, \
                patch.object(app_window.subprocess, "CREATE_NO_WINDOW", 0, create=True):
            self.window.open("http://127.0.0.1:7860/")
            command = launch.call_args.args[0]
        profile = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--user-data-dir=")))
        self.assertTrue(profile.is_relative_to(app_window.runtime.session_cache()))
        self.assertTrue(profile.is_dir())
        self.assertIn("--app=http://127.0.0.1:7860/", command)
        self.assertEqual(self.window._children, [child])

    def test_reopen_focuses_existing_window_and_preserves_session(self):
        child = Mock()
        child.poll.return_value = None
        self.window._children = [child]
        with patch.object(app_window, "_windows", return_value=True) as windows, \
                patch.object(app_window.subprocess, "Popen") as launch:
            self.assertIn("当前编辑内容保留", self.window.open("http://127.0.0.1:7860/"))
        windows.assert_called_once_with(child)
        launch.assert_not_called()

    def test_double_click_during_startup_does_not_duplicate(self):
        child = Mock()
        child.poll.return_value = None
        self.window._children = [child]
        self.window._started = app_window.time.monotonic()
        with patch.object(app_window, "_windows", return_value=False), \
                patch.object(app_window.subprocess, "Popen") as launch:
            self.assertIn("正在打开", self.window.open("http://127.0.0.1:7860/"))
        launch.assert_not_called()

    def test_close_all_owned_windows_and_fallback_only_for_unresponsive_child(self):
        normal, hung = Mock(), Mock()
        hung.wait.side_effect = subprocess.TimeoutExpired("browser", 3)
        self.window._children = [normal, hung]
        with patch.object(app_window, "_windows") as windows, \
                patch.object(app_window.tasks, "stop_process") as stop:
            self.window.close()
            self.window.close()
        self.assertEqual(windows.call_count, 2)
        windows.assert_any_call(normal, close=True)
        windows.assert_any_call(hung, close=True)
        stop.assert_called_once_with(hung, tree=True)
        self.assertEqual(self.window._children, [])
        with patch.object(app_window.subprocess, "Popen") as launch:
            self.assertIn("正在退出", self.window.open("http://127.0.0.1:7860/"))
        launch.assert_not_called()

    def test_default_browser_is_never_added_to_owned_children(self):
        with patch.object(app_window, "browser_executable", return_value=None), \
                patch.object(app_window.webbrowser, "open") as open_browser, \
                patch.object(app_window.tasks, "stop_process") as stop:
            message = self.window.open("http://127.0.0.1:7860/")
            self.window.close()
        self.assertIn("手动关闭", message)
        open_browser.assert_called_once()
        stop.assert_not_called()

    def test_failed_launch_falls_back_without_claiming_other_processes(self):
        with patch.object(app_window, "browser_executable", return_value="browser.exe"), \
                patch.object(app_window.subprocess, "Popen", side_effect=OSError("unavailable")), \
                patch.object(app_window.subprocess, "CREATE_NO_WINDOW", 0, create=True), \
                patch.object(app_window.webbrowser, "open") as open_browser:
            self.window.open("http://127.0.0.1:7860/")
        open_browser.assert_called_once()
        self.assertEqual(self.window._children, [])

    def test_existing_instance_reopen_is_authenticated_and_bypasses_proxy(self):
        instance = lifecycle.Instance()
        (self.root / "instance.json").write_text(json.dumps(dict(port=7860, nonce=instance.nonce)), encoding="utf-8")
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"message":"opened"}'
        opener = Mock()
        opener.open.return_value = response
        with patch.object(lifecycle.urllib.request, "build_opener", return_value=opener):
            self.assertEqual(instance.reopen_existing("http://127.0.0.1:7860/"), "opened")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.get_header("X-bili-instance"), instance.nonce)
        with self.assertRaises(RuntimeError):
            instance.reopen_existing("http://127.0.0.1:9999/")

    def test_exit_response_is_sent_before_shutdown(self):
        with patch.object(lifecycle.tasks, "cancel_all") as cancel, \
                patch.object(lifecycle.threading, "Timer") as timer:
            self.assertIn("自动关闭", lifecycle.request_shutdown())
        cancel.assert_called_once()
        timer.assert_called_once_with(1, lifecycle.shutdown.set)
        timer.return_value.start.assert_called_once()
