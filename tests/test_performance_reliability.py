"""Regression checks for seek bounds, encoder recovery, joins and socket cleanup."""
import asyncio
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from modules import editor, encoding, ffmpeg_util, tasks, web_runtime
from modules.pipeline import VideoPipeline
from modules.segmenter import Segment


class EncodingRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="编码 回归_")
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / "source.mp4"
        ffmpeg_util.run_ffmpeg(["-f", "lavfi", "-i", "color=red:s=320x240:r=30:d=1",
            "-f", "lavfi", "-i", "color=blue:s=320x240:r=30:d=1", "-f", "lavfi", "-i", "sine=duration=2",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
            "-c:v", "libx264", "-c:a", "aac", str(cls.source)])

    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()

    def test_seek_bounded_input_and_relative_filters(self):
        with patch.object(ffmpeg_util, "run_ffmpeg") as run:
            editor.render_segment(str(self.source), Segment(1, 1.8, mute=True), str(self.root / "out.mp4"))
        args = run.call_args.args[0]
        self.assertEqual(args[:6], ["-ss", "1.000000", "-t", "0.800000", "-i", str(self.source)])
        self.assertIn("trim=start=0.000:end=0.800", args[args.index("-vf") + 1])

    def test_late_cut_has_correct_first_frame_and_duration(self):
        from PIL import Image
        for speed in (.5, 1, 2):
            with self.subTest(speed=speed):
                path = VideoPipeline(str(self.root / "work")).process(str(self.source), [Segment(1.2, 1.8, speed=speed)], out_dir=str(self.root))
                info = ffmpeg_util.get_video_info(path)
                self.assertAlmostEqual(info["duration"], .6 / speed, delta=.08)
                frame = self.root / "frame.png"
                ffmpeg_util.extract_frame(path, .05, str(frame))
                with Image.open(frame) as picture:
                    r, g, b = picture.convert("RGB").getpixel((80, 80))
                self.assertGreater(b, r + 100)

    def test_many_short_reordered_cuts_keep_audio_and_video_aligned(self):
        segments = [Segment(1.2, 1.4, mute=True), Segment(.2, .4)] * 10
        path = VideoPipeline(str(self.root / "work")).process(str(self.source), segments, out_dir=str(self.root))
        streams = ffmpeg_util.probe(path)["streams"]
        durations = {s["codec_type"]: float(s["duration"]) for s in streams}
        self.assertAlmostEqual(durations["video"], 4, delta=.08)
        self.assertLess(abs(durations["video"] - durations["audio"]), .08)
        starts = [float(s.get("start_time", 0)) for s in streams]
        self.assertLess(max(starts) - min(starts), .05)
        ffmpeg_util.run_ffmpeg(["-v", "error", "-i", path, "-f", "null", "-"])

    def test_failed_gpu_retries_all_segments_on_cpu(self):
        real_render, calls = editor.render_segment, []
        def render(*args, **kwargs):
            calls.append(kwargs["encoder"])
            if kwargs["encoder"] == "nvenc":
                Path(args[2]).write_bytes(b"partial")
                raise encoding.HardwareEncodingError("simulated driver failure")
            return real_render(*args, **kwargs)
        pipeline = VideoPipeline(str(self.root / "fallback"))
        with patch.object(encoding, "select", return_value="nvenc"), patch.object(editor, "render_segment", side_effect=render):
            output = pipeline.process(str(self.source), [Segment(0, .4), Segment(1, 1.4)], out_dir=str(self.root), acceleration="auto")
        self.assertEqual(calls, ["nvenc", "cpu", "cpu"])
        self.assertEqual(pipeline.last_engine, "cpu")
        self.assertFalse(list((self.root / "fallback").iterdir()))
        self.assertAlmostEqual(ffmpeg_util.get_video_info(output)["duration"], .8, delta=.08)

    def test_gpu_cancellation_does_not_trigger_retry(self):
        with patch.object(encoding, "select", return_value="nvenc"), patch.object(editor, "render_segment", side_effect=tasks.Cancelled("cancel")) as render:
            with self.assertRaises(tasks.Cancelled):
                VideoPipeline(str(self.root / "cancel")).process(str(self.source), [Segment(0, 1)], out_dir=str(self.root), out_name="gpu_cancel", acceleration="auto")
        self.assertEqual(render.call_count, 1)
        self.assertFalse((self.root / "gpu_cancel.mp4").exists())

    def test_real_nvenc_or_clean_cpu_fallback(self):
        pipeline = VideoPipeline(str(self.root / "auto"))
        output = pipeline.process(str(self.source), [Segment(.2, .8, mute=True, watermark={"x":20,"y":20,"w":30,"h":20})], out_dir=str(self.root), acceleration="auto")
        self.assertIn(pipeline.last_engine, ("nvenc", "cpu"))
        self.assertAlmostEqual(ffmpeg_util.get_video_info(output)["duration"], .6, delta=.1)
        ffmpeg_util.run_ffmpeg(["-v", "error", "-i", output, "-f", "null", "-"])


@unittest.skipUnless(sys.platform == "win32", "Windows Proactor transport")
class WindowsConnectionReset(unittest.TestCase):
    def test_exact_shutdown_reset_finishes_socket_cleanup(self):
        from asyncio.proactor_events import _ProactorBasePipeTransport
        transport = object.__new__(_ProactorBasePipeTransport)
        transport._called_connection_lost = False
        transport._protocol = Mock()
        transport._server = Mock()
        server = transport._server
        # A real disconnected Windows TCP socket raises 10054 at shutdown();
        # use the actual stdlib callback and equivalent error to make it deterministic.
        transport._sock = Mock()
        sock = transport._sock
        reset = ConnectionResetError(10054, "connection reset")
        reset.winerror = 10054
        sock.shutdown.side_effect = reset
        try:
            transport._call_connection_lost(None)
        except ConnectionResetError as exc:
            context = dict(exception=exc, handle=Mock(_callback=transport._call_connection_lost))
            # Mock adds a traceback frame; real shutdown() is a C method. Recreate
            # the actual traceback ending at the stdlib callback for this fixture.
            trace = exc.__traceback__
            while trace and trace.tb_frame.f_code.co_name != "_call_connection_lost":
                trace = trace.tb_next
            import types
            exc.__traceback__ = types.TracebackType(None, trace.tb_frame, trace.tb_lasti, trace.tb_lineno)
            self.assertTrue(web_runtime.finish_reset_connection(context))
        else:
            self.fail("Expected reset")
        sock.close.assert_called_once()
        server._detach.assert_called_once()
        self.assertTrue(transport._called_connection_lost)
        self.assertIsNone(transport._sock)

    def test_other_application_errors_are_not_hidden(self):
        for error in (RuntimeError("render failed"), ConnectionResetError(10054, "different callback")):
            self.assertFalse(web_runtime.finish_reset_connection(dict(exception=error, handle=Mock(_callback=lambda: None))))

    def test_lifespan_preserves_previous_handler(self):
        async def check():
            loop = asyncio.get_running_loop()
            previous = Mock()
            loop.set_exception_handler(previous)
            async with web_runtime.lifespan(None):
                context = {"exception": RuntimeError("not benign")}
                loop.call_exception_handler(context)
                previous.assert_called_once_with(loop, context)
            self.assertIs(loop.get_exception_handler(), previous)
        asyncio.run(check())
