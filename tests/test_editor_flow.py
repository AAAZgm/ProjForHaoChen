"""Editing intent, real media order/orientation, cancellation and session isolation."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PIL import Image
from modules import ffmpeg_util, tasks
from modules.pipeline import VideoPipeline
from modules.segmenter import Segment, sanitize_segments
from modules.workspace import Workspace


class EditingModel(unittest.TestCase):
    def project(self):
        p = Workspace()
        p.load("sample.mp4", dict(duration=10, width=1920, height=1080))
        return p

    def test_split_replaces_original_and_preserves_effects(self):
        p = self.project()
        p.effects(True, 2)
        p.split(4)
        self.assertEqual([(s.start, s.end, s.mute, s.speed) for s in p.segments],
                         [(0, 4, True, 2), (4, 10, True, 2)])
        p.move(1)
        self.assertEqual([s.start for s in sanitize_segments(p.segments, 10)], [4, 0])
        p.history()
        self.assertEqual([s.start for s in p.segments], [0, 4])
        p.history(redo=True)
        self.assertEqual([s.start for s in p.segments], [4, 0])

    def test_trim_delete_undo_and_redo_branch(self):
        p = self.project()
        p.trim(2, 8)
        p.delete()
        self.assertEqual(p.segments, [])
        p.history()
        self.assertEqual(p.current().start, 2)
        p.effects(True, .5)
        with self.assertRaises(ValueError): p.history(redo=True)
        with self.assertRaises(ValueError): p.split(float("nan"))
        with self.assertRaises(ValueError): p.trim(0, 11)

    def test_two_sessions_and_source_change_are_isolated(self):
        p, q = self.project(), self.project()
        self.assertNotEqual(p.id, q.id)
        p.effects(True, 2, True)
        self.assertFalse(q.current().mute)
        self.assertEqual(q.current().speed, 1)
        p.load("new.mp4", dict(duration=2, width=80, height=60))
        self.assertFalse(p.undo_stack)
        self.assertFalse(p.current().mute)

    def test_normalized_selection_and_stale_frame(self):
        p = self.project()
        payload = dict(media_id=p.media_id, rect=[.1, .2, .6, .7])
        p.region(payload, "裁剪画面")
        self.assertEqual(p.current().crop, (192, 216, 960, 540))
        p.history()
        p.region(dict(media_id=p.media_id, rect=[0, 0, .1, .1]), "水印淡化")
        self.assertEqual(p.current().watermark["x"], 2)
        p.load("new.mp4", dict(duration=2, width=80, height=60))
        with self.assertRaisesRegex(ValueError, "过期"): p.region(payload, "裁剪画面")

    def test_sanitize_does_not_mutate_input(self):
        rows = [Segment(5, 20), Segment(-1, 3)]
        original = deepcopy(rows)
        fixed = sanitize_segments(rows, 10)
        self.assertEqual(rows, original)
        self.assertEqual([(s.start, s.end) for s in fixed], [(5, 10), (0, 3)])


class MediaFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="bili_flow_")
        cls.root = Path(cls.temp.name)
        cls.source = str(cls.root / "红蓝.mp4")
        ffmpeg_util.run_ffmpeg(["-f", "lavfi", "-i", "color=red:size=160x120:rate=30:duration=1",
                               "-f", "lavfi", "-i", "color=blue:size=160x120:rate=30:duration=1",
                               "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]",
                               "-c:v", "libx264", "-pix_fmt", "yuv420p", cls.source])

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_output_uses_reordered_segments_and_monotonic_progress(self):
        progress = []
        output = VideoPipeline().process(self.source, [Segment(1, 2), Segment(0, 1)],
                    out_dir=str(self.root), on_progress=lambda p, m: progress.append(p))
        frame = str(self.root / "first.png")
        ffmpeg_util.extract_frame(output, .1, frame)
        with Image.open(frame) as image:
            r, g, b = image.convert("RGB").getpixel((50, 50))
        self.assertGreater(b, r + 100)
        self.assertEqual(progress, sorted(progress))
        self.assertEqual(progress[-1], 100)

    def test_rotated_metadata_matches_extracted_frame_and_crop(self):
        rotated = str(self.root / "rotated.mp4")
        ffmpeg_util.run_ffmpeg(["-display_rotation", "90", "-i", self.source, "-c", "copy", rotated])
        info = ffmpeg_util.get_video_info(rotated)
        self.assertEqual((info["width"], info["height"]), (120, 160))
        frame = str(self.root / "rotated.png")
        ffmpeg_util.extract_frame(rotated, .2, frame)
        with Image.open(frame) as image: self.assertEqual(image.size, (120, 160))
        output = VideoPipeline().process(rotated, [Segment(0, 1, crop=(10, 20, 80, 100))],
                                         out_dir=str(self.root))
        info = ffmpeg_util.get_video_info(output)
        self.assertEqual((info["width"], info["height"]), (80, 100))

    def test_cancel_silent_child_and_release_slot(self):
        process = None
        timer = threading.Timer(.3, lambda: tasks.cancel("cancel-test"))
        begin = time.monotonic()
        with self.assertRaises(tasks.Cancelled):
            with tasks.task("cancel-test"):
                process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                timer.start()
                with tasks.watch_process(process): process.wait()
        timer.join()
        self.assertIsNotNone(process.poll())
        self.assertLess(time.monotonic() - begin, 5)
        with tasks.task("cancel-test"): tasks.check()

    def test_cancel_cleans_partial_output_and_can_export_again(self):
        from modules import exporter
        work = self.root / "cancel-work"
        def fail(files, output, **kwargs):
            Path(output).write_bytes(b"partial")
            tasks.cancel("partial")
            tasks.check()
        with patch.object(exporter, "export_mp4", side_effect=fail):
            with self.assertRaises(tasks.Cancelled), tasks.task("partial"):
                VideoPipeline(str(work)).process(self.source, [Segment(0, .2)],
                                                 out_dir=str(self.root), out_name="cancelled")
        self.assertFalse((self.root / "cancelled.mp4").exists())
        self.assertEqual(list(work.iterdir()), [])
        with tasks.task("partial"):
            result = VideoPipeline(str(work)).process(self.source, [Segment(0, .2)], out_dir=str(self.root))
        self.assertTrue(Path(result).is_file())

    def test_cancel_real_ffmpeg_without_waiting_for_next_progress(self):
        timer = threading.Timer(.4, lambda: tasks.cancel("real-ffmpeg"))
        begin = time.monotonic()
        try:
            with self.assertRaises(tasks.Cancelled), tasks.task("real-ffmpeg"):
                timer.start()
                ffmpeg_util.run_ffmpeg(["-re", "-f", "lavfi", "-i", "color=size=160x120:rate=30",
                                       "-t", "30", "-f", "null", "-"])
        finally:
            timer.join()
        self.assertLess(time.monotonic() - begin, 5)
        self.assertFalse(tasks.busy("real-ffmpeg"))

    def test_cancel_waiting_session_does_not_cancel_active_session(self):
        ready = threading.Event()
        result = []
        def waiting():
            try:
                with tasks.task("waiting", lambda p, m: ready.set()):
                    result.append("unexpected acquisition")
            except tasks.Cancelled:
                result.append("cancelled")
        with tasks.task("active"):
            thread = threading.Thread(target=waiting)
            thread.start()
            self.assertTrue(ready.wait(2))
            tasks.cancel("waiting")
            thread.join(timeout=3)
            tasks.check()
        self.assertEqual(result, ["cancelled"])


if __name__ == "__main__": unittest.main()
