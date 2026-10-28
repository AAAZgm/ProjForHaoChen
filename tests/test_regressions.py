"""Input and UI callback regressions, independent of live websites."""

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import main
from modules import runtime


class InputRegressions(unittest.TestCase):
    def test_query_and_fragment_survive_share_text(self):
        url = "https://www.bilibili.com/video/BV1xx/?p=2&t=12#reply123"
        self.assertEqual(main.extract_url("【分享标题】 " + url + " 看这个视频"), url)

    def test_encoded_query_characters_are_preserved(self):
        url = "https://b23.tv/abc?token=a%2Bb%3D&from=share"
        self.assertEqual(main.extract_url("（" + url + "）"), url)

    def test_share_punctuation_and_empty_input(self):
        for value, expected in [(None, ""), ("  ", ""), ("https://b23.tv/abc。", "https://b23.tv/abc"),
                                ("(HTTPS://b23.tv/abc?p=3)", "HTTPS://b23.tv/abc?p=3")]:
            with self.subTest(value=value):
                self.assertEqual(main.extract_url(value), expected)

    def test_missing_video_returns_two_outputs(self):
        result = main.on_process(None, [], "mp4", 15, 0.5)
        self.assertEqual(len(result), 2)
        self.assertIsNone(result[0])
        self.assertIn("请先选择", result[1])

    def test_empty_table_returns_two_outputs(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            result = main.on_process(video.name, [], "mp4", 15, 0.5)
        self.assertEqual(len(result), 2)
        self.assertIn("片段表格为空", result[1])

    def test_processing_failure_is_displayed(self):
        row = [0, 1, False, False, 1, 0, 0, 0, 0, 0, 0, 0, 0, "delogo"]
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            with patch.object(main._pipeline, "process", side_effect=RuntimeError("模拟编码失败")):
                result = main.on_process(video.name, [row], "mp4", 15, 0.5)
        self.assertEqual(result, (None, "处理失败：模拟编码失败"))

    def test_non_finite_cells_do_not_crash_conversion(self):
        row = [0, 1, False, False, float("nan"), float("inf"), 0, 20, 20,
               float("nan"), 0, 20, 20, "delogo"]
        segment = main.table_to_segments([row])[0]
        self.assertEqual(segment.speed, 1)
        self.assertEqual(segment.crop, (0, 0, 20, 20))
        self.assertEqual(segment.watermark["x"], 0)

    def test_invalid_watermark_returns_message(self):
        row = [0, 1, False, False, 1, 0, 0, 0, 0, 0, 0, 0, 0, "delogo"]
        result = main.on_apply_wm(("unused.png", 100, 100), 99, 99, 1, 1, [row])
        self.assertEqual(len(result), 2)
        self.assertIn("请调整选区", result[1])

    def test_output_location_ignores_current_directory(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BILI_VIDEO_HOME", None)
            self.assertEqual(runtime.data_dir(), Path(main.__file__).resolve().parent)
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"BILI_VIDEO_HOME": directory}):
                self.assertEqual(runtime.data_dir(), Path(directory).resolve())

    def test_ui_builds_with_locked_gradio(self):
        ui = main.build_ui()
        from ui import export_video
        callbacks = [fn for fn in ui.fns.values() if fn.fn is export_video]
        self.assertEqual(len(callbacks), 1)
        self.assertEqual(len(callbacks[0].outputs), 5)
        names = [fn.api_name for fn in ui.fns.values()]
        for endpoint in ("import_video", "download_video", "cancel_task", "export_video"):
            self.assertEqual(names.count(endpoint), 1)


if __name__ == "__main__":
    unittest.main()
