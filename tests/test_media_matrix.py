"""Additional release media cases using generated, redistributable fixtures."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from modules import ffmpeg_util
from modules.pipeline import VideoPipeline
from modules.segmenter import Segment


class MediaMatrix(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="媒体矩阵 ")
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def process(self, path, segments):
        output = VideoPipeline(str(self.root / "work")).process(str(path), segments, out_dir=str(self.root))
        ffmpeg_util.run_ffmpeg(["-v", "error", "-i", output, "-f", "null", "-"])
        return output

    def test_odd_dimensions_export_even_decodable_video(self):
        source = self.root / "奇数.mp4"
        ffmpeg_util.run_ffmpeg(["-f", "lavfi", "-i", "testsrc=size=161x121:rate=24", "-t", "1",
                               "-c:v", "libx264", "-pix_fmt", "yuv444p", str(source)])
        self.assertEqual(ffmpeg_util.get_video_info(source)["width"], 161)
        output = self.process(source, [Segment(0, 1)])
        info = ffmpeg_util.get_video_info(output)
        self.assertEqual((info["width"], info["height"]), (160, 120))

    def test_variable_frame_rate_and_half_normal_double_speed_av_alignment(self):
        source = self.root / "可变帧率 有声.mp4"
        ffmpeg_util.run_ffmpeg(["-f", "lavfi", "-i", "testsrc2=size=160x120:rate=30:duration=3",
            "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=44100:duration=3",
            "-vf", "select='if(lt(t,1.5),not(mod(n,2)),1)'", "-fps_mode", "vfr",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source)])
        original = ffmpeg_util.probe(source)["streams"][0]
        self.assertNotEqual(original["r_frame_rate"], original["avg_frame_rate"])
        for speed in (.5, 1, 2):
            with self.subTest(speed=speed):
                output = self.process(source, [Segment(.5, 2.5, speed=speed)])
                streams = ffmpeg_util.probe(output)["streams"]
                durations = {s["codec_type"]: float(s["duration"]) for s in streams}
                starts = [float(s.get("start_time", 0)) for s in streams]
                self.assertAlmostEqual(durations["video"], 2 / speed, delta=.15)
                self.assertLess(abs(durations["video"] - durations["audio"]), .12)
                self.assertLess(max(starts) - min(starts), .05)

    def test_corrupted_file_and_audio_only_rejected(self):
        corrupt = self.root / "损坏.mp4"
        corrupt.write_bytes(b"not a video")
        with self.assertRaisesRegex(RuntimeError, "损坏"):
            ffmpeg_util.get_video_info(corrupt)
        audio = self.root / "audio.m4a"
        ffmpeg_util.run_ffmpeg(["-f", "lavfi", "-i", "sine=duration=0.2", "-c:a", "aac", str(audio)])
        with self.assertRaisesRegex(RuntimeError, "视频画面"):
            ffmpeg_util.get_video_info(audio)
