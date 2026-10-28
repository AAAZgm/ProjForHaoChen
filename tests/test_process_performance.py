"""Windows QoS must preserve unrelated policy and never block an export."""

import ctypes
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from modules import ffmpeg_util, process_performance as performance


class ProcessPerformance(unittest.TestCase):
    def setUp(self):
        self.kernel = Mock()
        self.kernel.OpenProcess.return_value = 123
        self.kernel.GetProcessInformation.return_value = 1
        self.kernel.SetProcessInformation.return_value = 1
        self.platform = patch.object(performance, "os", SimpleNamespace(name="nt"))
        self.platform.start()
        self.addCleanup(self.platform.stop)
        self.api = patch.object(performance, "_windows_api", return_value=self.kernel)
        self.api.start()
        self.addCleanup(self.api.stop)

    def test_explicit_high_qos_preserves_other_flags(self):
        for control, state in ((0, 0), (1, 1), (5, 5), (4, 4), (1, 0)):
            with self.subTest(control=control, state=state):
                def read(handle, info_class, pointer, size):
                    self.assertEqual((handle, info_class, size), (123, 4, 12))
                    value = pointer._obj
                    self.assertEqual(value.Version, 1)
                    value.ControlMask, value.StateMask = control, state
                    return 1

                def write(handle, info_class, pointer, size):
                    self.assertEqual((handle, info_class, size), (123, 4, 12))
                    value = pointer._obj
                    self.assertEqual((value.Version, value.ControlMask, value.StateMask),
                                     (1, control | 1, state & ~1))
                    return 1

                self.kernel.reset_mock()
                self.kernel.GetProcessInformation.side_effect = read
                self.kernel.SetProcessInformation.side_effect = write
                self.assertTrue(performance.request_high_qos(456))
                self.kernel.OpenProcess.assert_called_once_with(0x1200, False, 456)
                self.kernel.SetProcessInformation.assert_called_once()
                self.kernel.CloseHandle.assert_called_once_with(123)

    def test_non_windows_does_not_load_api(self):
        with patch.object(performance, "os", SimpleNamespace(name="posix")), \
                patch.object(performance, "_windows_api") as load:
            self.assertFalse(performance.request_high_qos(456))
        load.assert_not_called()

    def test_missing_api_is_nonfatal_and_logged(self):
        with patch.object(performance, "_windows_api", side_effect=AttributeError("unsupported")), \
                self.assertLogs("bili_video_tool", level="INFO") as logs:
            self.assertFalse(performance.request_high_qos(456))
        self.assertIn("keeping existing scheduling", logs.output[0])
        self.kernel.OpenProcess.assert_not_called()

    def test_open_failure_does_not_close_invalid_handle(self):
        self.kernel.OpenProcess.return_value = 0
        self.assertFalse(performance.request_high_qos(456))
        self.kernel.GetProcessInformation.assert_not_called()
        self.kernel.CloseHandle.assert_not_called()

    def test_read_failure_preserves_policy_and_closes_handle(self):
        self.kernel.GetProcessInformation.return_value = 0
        self.assertFalse(performance.request_high_qos(456))
        self.kernel.SetProcessInformation.assert_not_called()
        self.kernel.CloseHandle.assert_called_once_with(123)

    def test_write_failure_closes_handle(self):
        self.kernel.SetProcessInformation.return_value = 0
        self.assertFalse(performance.request_high_qos(456))
        self.kernel.CloseHandle.assert_called_once_with(123)

    def test_unexpected_api_error_is_nonfatal_and_closes_handle(self):
        self.kernel.GetProcessInformation.side_effect = RuntimeError("API failed")
        self.assertFalse(performance.request_high_qos(456))
        self.kernel.CloseHandle.assert_called_once_with(123)


class FFmpegPerformanceIntegration(unittest.TestCase):
    command = ["-f", "lavfi", "-i", "color=size=16x16:rate=10:duration=0.2", "-f", "null", "-"]

    def test_ffmpeg_completes_when_qos_api_unavailable(self):
        with patch.object(performance, "os", SimpleNamespace(name="nt")), \
                patch.object(performance, "_windows_api", side_effect=OSError("not permitted")) as load:
            self.assertEqual(ffmpeg_util.run_ffmpeg(self.command).returncode, 0)
        load.assert_called_once()

    @unittest.skipUnless(sys.platform == "win32", "Windows process information")
    def test_real_ffmpeg_child_has_explicit_high_qos(self):
        apply = performance.request_high_qos
        observed = []

        def inspect(pid):
            if not apply(pid):
                self.skipTest("HighQoS unavailable on this Windows host")
            kernel = performance._windows_api()
            handle = kernel.OpenProcess(0x1000, False, pid)
            self.assertTrue(handle)
            try:
                state = performance._PowerThrottlingState(1, 0, 0)
                self.assertTrue(kernel.GetProcessInformation(handle, 4, ctypes.byref(state), ctypes.sizeof(state)))
                observed.append((state.ControlMask & 1, state.StateMask & 1))
            finally:
                kernel.CloseHandle(handle)
            return True

        # Use a bounded real process so the policy can be read before it exits.
        with patch.object(performance, "request_high_qos", side_effect=inspect):
            ffmpeg_util.run_ffmpeg(["-re", *self.command])
        self.assertEqual(observed, [(1, 0)])


if __name__ == "__main__":
    unittest.main()
