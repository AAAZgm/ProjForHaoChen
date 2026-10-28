"""Real FFmpeg checks using generated media; no network or private videos."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PIL import Image
from modules import editor, ffmpeg_util
from modules.pipeline import VideoPipeline
from modules.segmenter import Segment
from modules.selfcheck import run_self_check


class MediaRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="bili_media_")
        cls.directory = Path(cls.temp.name)
        cls.source = cls.directory / "无声 竖屏.mp4"
        ffmpeg_util.run_ffmpeg([
            "-f", "lavfi", "-i", "testsrc2=size=120x160:rate=30", "-t", "1.2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(cls.source),
        ])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def pipeline(self):
        return VideoPipeline(work_dir=str(self.directory / "work"))

    def test_multi_segment_speed_mute_crop_watermark_and_decode(self):
        report = run_self_check(str(self.directory))
        self.assertEqual(report["status"], "passed")

    def test_silent_portrait_gets_compatible_audio_track(self):
        output = self.pipeline().process(str(self.source), [Segment(0, 1)],
                                         out_dir=str(self.directory), out_name="silent")
        info = ffmpeg_util.get_video_info(output)
        self.assertEqual((info["width"], info["height"]), (120, 160))
        self.assertTrue(info["has_audio"])
        self.assertAlmostEqual(info["duration"], 1, delta=0.15)
        ffmpeg_util.run_ffmpeg(["-v", "error", "-i", output, "-f", "null", "-"])

    def test_gif_is_animated_at_expected_size(self):
        output = self.pipeline().process(str(self.source), [Segment(0, 1)], out_format="gif",
                                         gif_scale=0.5, gif_fps=10, out_dir=str(self.directory))
        with Image.open(output) as image:
            self.assertEqual(image.size, (60, 80))
            self.assertGreater(image.n_frames, 1)

    def test_invalid_file_has_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, "无法读取视频时长"):
            self.pipeline().process(str(self.directory / "missing.mp4"), [Segment(0, 1)],
                                    out_dir=str(self.directory))

    def test_all_deleted_and_empty_ranges_are_rejected(self):
        for segments, message in [([Segment(0, 1, deleted=True)], "所有片段都被删除"),
                                  ([Segment(2, 3)], "没有有效的片段")]:
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                self.pipeline().process(str(self.source), segments, out_dir=str(self.directory))

    def test_failed_render_cleans_partial_intermediate(self):
        def fail(input_path, segment, output, **kwargs):
            Path(output).write_bytes(b"incomplete video")
            raise RuntimeError("simulated failure")
        with patch.object(editor, "render_segment", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "simulated failure"):
                self.pipeline().process(str(self.source), [Segment(0, 1)], out_dir=str(self.directory))
        self.assertEqual(list((self.directory / "work").iterdir()), [])

    def test_exports_in_same_second_have_distinct_paths(self):
        with patch("modules.pipeline.time.time", return_value=1234):
            first = self.pipeline().process(str(self.source), [Segment(0, 0.2)], out_dir=str(self.directory))
            second = self.pipeline().process(str(self.source), [Segment(0, 0.2)], out_dir=str(self.directory))
        self.assertNotEqual(first, second)
        self.assertTrue(Path(first).is_file() and Path(second).is_file())


if __name__ == "__main__":
    unittest.main()
