"""Stage D: mixed media, audio, cancellation, isolation and portable projects."""
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from modules import studio, project_file, ffmpeg_util, tasks, encoding, editor, settings
from modules.pipeline import VideoPipeline
from modules.segmenter import Segment
from modules.audio_export import export_audio
from modules.downloader import BiliDownloader


class StudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="轻剪 D_")
        cls.root = Path(cls.temp.name)
        cls.red, cls.blue = cls.root / "红 横屏.mp4", cls.root / "蓝 竖屏.mp4"
        ffmpeg_util.run_ffmpeg(["-f", "lavfi", "-i", "color=red:s=160x120:r=24", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000", "-t", "1.2", "-c:v", "libx264", "-c:a", "aac", str(cls.red)])
        ffmpeg_util.run_ffmpeg(["-f", "lavfi", "-i", "color=blue:s=90x160:r=15", "-t", "1.2", "-c:v", "libx264", str(cls.blue)])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory(dir=self.root)
        self.directory = Path(self.work.name)
        self.env = patch.dict(os.environ, BILI_CONFIG_HOME=str(self.directory / "config"))
        self.env.start()
        self.s = studio.Studio()
        self.s.add_path(self.red)
        self.s.add_path(self.blue)

    def tearDown(self):
        self.env.stop()
        self.work.cleanup()

    def test_editor_and_other_session_are_isolated(self):
        project = self.s.items[0].project
        other = studio.Studio()
        other.add(project)
        project.segments[0].speed = 4
        self.assertEqual(other.items[0].project.segments[0].speed, 1)
        self.assertNotEqual(project.media_id, other.items[0].project.media_id)
        self.assertNotEqual(self.s.id, other.id)

    def test_mixed_portrait_audio_rates_and_order_merge(self):
        from PIL import Image
        paths = [(i.project.path, [Segment(0, .6)]) for i in self.s.items]
        output = VideoPipeline(str(self.directory / "work")).process_many(paths, out_dir=str(self.directory))
        info = ffmpeg_util.get_video_info(output)
        self.assertEqual((info["width"], info["height"], info["fps"]), (160, 120, 30))
        self.assertAlmostEqual(info["duration"], 1.2, delta=.08)
        self.assertTrue(info["has_audio"])
        for at, color in ((.2, 0), (.9, 2)):
            frame = str(self.directory / f"{at}.png")
            ffmpeg_util.extract_frame(output, at, frame)
            with Image.open(frame) as im:
                rgb = im.convert("RGB").getpixel((80, 60))
                self.assertGreater(rgb[color], 180)
                if color == 2:
                    self.assertLess(max(im.convert("RGB").getpixel((5, 60))), 10)

    def test_mixed_gpu_failure_restarts_every_source_on_cpu(self):
        original, calls = editor.render_segment, []
        def render(path, *args, **kwargs):
            calls.append((path, kwargs["encoder"]))
            if kwargs["encoder"] == "nvenc":
                if path == str(self.blue):
                    raise encoding.HardwareEncodingError("test")
                kwargs["encoder"] = "cpu"
            return original(path, *args, **kwargs)
        pipe = VideoPipeline(str(self.directory / "work"))
        with patch.object(encoding, "select", return_value="nvenc"), patch.object(editor, "render_segment", side_effect=render):
            pipe.process_many([(i.project.path, [Segment(0, .2)]) for i in self.s.items], out_dir=str(self.directory))
        self.assertEqual([c[1] for c in calls], ["nvenc", "nvenc", "cpu", "cpu"])
        self.assertEqual(pipe.last_engine, "cpu")

    def test_audio_formats_duration_and_no_video(self):
        sources = [(str(self.red), [Segment(.2, 1, speed=2)]), (str(self.blue), [Segment(0, .4)])]
        for fmt in ("m4a", "mp3", "wav"):
            output = export_audio(sources, self.directory, out_format=fmt)
            metadata = ffmpeg_util.probe(output)
            self.assertEqual([s["codec_type"] for s in metadata["streams"]], ["audio"])
            self.assertAlmostEqual(float(metadata["format"]["duration"]), .8, delta=.07)
            ffmpeg_util.run_ffmpeg(["-v", "error", "-i", output, "-f", "null", "-"])

    def test_audio_mute_and_silent_source_are_actual_silence(self):
        output = export_audio([(str(self.red), [Segment(0, .4, mute=True)]),
                               (str(self.blue), [Segment(0, .4, speed=2)])], self.directory, out_format="wav")
        with wave.open(output) as audio:
            self.assertEqual(audio.getnframes(), round(.6 * 44100))
            self.assertFalse(any(audio.readframes(audio.getnframes())))

    def test_batch_failure_does_not_block_next_item(self):
        self.s.items[0].project.path = str(self.directory / "missing.mp4")
        with tasks.task(self.s.id):
            result = studio.run(self.s, False, "较小 MP4", str(self.directory), acceleration="cpu")
        self.assertIn("成功 1 项，失败 1 项", result)
        self.assertEqual(self.s.items[1].status, "已完成")
        self.assertEqual(self.s.items[0].output, "")

    def test_cancel_retains_completed_files_and_resume_skips_them(self):
        saved = self.directory / "done.mp4"
        saved.write_bytes(b"done")
        with patch.object(studio, "export_sources", side_effect=[str(saved), tasks.Cancelled("cancel")]):
            with tasks.task(self.s.id), self.assertRaises(tasks.Cancelled):
                studio.run(self.s, False, "通用 MP4", str(self.directory))
        self.assertEqual([i.status for i in self.s.items], ["已完成", "已取消"])
        with patch.object(studio, "export_sources", return_value=str(saved)) as export:
            with tasks.task(self.s.id):
                studio.run(self.s, False, "通用 MP4", str(self.directory), resume=True)
        self.assertEqual(export.call_count, 1)
        self.assertEqual(saved.read_bytes(), b"done")

    def test_portable_project_roundtrip_embeds_media_and_preserves_order(self):
        self.s.edit("up")
        self.s.items[1].project.segments = [Segment(.1, .9, mute=True, speed=2, crop=(2, 2, 100, 80),
                                                  watermark=dict(x=10, y=10, w=20, h=20, mode="delogo"))]
        path = project_file.save(self.s, self.directory, export_options=dict(format="MP3 音频", merge=True))
        loaded, opts = project_file.load(path)
        self.assertEqual(opts["format"], "MP3 音频")
        self.assertTrue(opts["merge"])
        self.assertEqual([i.name for i in self.s.items], [i.name for i in loaded.items])
        for old, new in zip(self.s.items, loaded.items):
            self.assertEqual(old.project.segments, new.project.segments)
            self.assertNotEqual(old.project.path, new.project.path)
            self.assertEqual(Path(old.project.path).read_bytes(), Path(new.project.path).read_bytes())
            self.assertNotEqual(old.project.media_id, new.project.media_id)
        with tasks.task(loaded.id):
            studio.run(loaded, True, "M4A 音频", str(self.directory))
        self.assertTrue(Path(loaded.merged_output).is_file())

    def test_unsafe_or_corrupted_project_cleans_restore_and_keeps_current(self):
        good = project_file.save(self.s, self.directory)
        with zipfile.ZipFile(good) as z:
            content = {name: z.read(name) for name in z.namelist()}
        for case in ("path", "hash", "parameters", "version"):
            changed = deepcopy(content)
            manifest = json.loads(changed["project.json"])
            if case == "path":
                changed["../outside.txt"] = b"bad"
            elif case == "hash":
                manifest["media"][next(iter(manifest["media"]))] = "0" * 64
            elif case == "parameters":
                manifest["items"][0]["segments"][0]["speed"] = 0
            else:
                manifest["schema"] = 999
            changed["project.json"] = json.dumps(manifest).encode()
            path = self.directory / f"{case}.qjproj"
            with zipfile.ZipFile(path, "w") as z:
                for name, data in changed.items():
                    z.writestr(name, data)
            with self.subTest(case=case), self.assertRaises(ValueError):
                project_file.load(path)
            self.assertEqual(len(self.s.items), 2)
            self.assertFalse(list((project_file.runtime.session_cache() / "projects").iterdir()))

    def test_cancel_project_save_removes_partial_only(self):
        with tasks.task(self.s.id):
            with self.assertRaises(tasks.Cancelled):
                project_file.save(self.s, self.directory, "cancelled", progress=lambda p, m: tasks.cancel(self.s.id))
        self.assertFalse(list(self.directory.glob("*.qjproj")))
        self.assertTrue(self.red.is_file())

    def test_parts_preserve_part_urls_and_remove_input_part_filter(self):
        info = {"entries": [{"url": "https://www.bilibili.com/video/BV1234567890?p=1"},
                             {"url": "https://www.bilibili.com/video/BV1234567890?p=2", "title": "第二节"}]}
        with patch.object(BiliDownloader, "_part_metadata", return_value=None), patch("modules.downloader.yt_dlp.YoutubeDL") as factory:
            ydl = factory.return_value.__enter__.return_value
            ydl.extract_info.return_value = info
            parts = BiliDownloader().parts("https://www.bilibili.com/video/BV1234567890?p=2")
        self.assertEqual(ydl.extract_info.call_args.args[0], "https://www.bilibili.com/video/BV1234567890")
        self.assertEqual([p["page"] for p in parts], ["1", "2"])
        self.assertTrue(parts[1]["url"].endswith("?p=2"))

    def test_part_metadata_titles_and_selected_download_order(self):
        import io
        import studio_ui
        data = dict(code=0, data=[dict(page=1, part="开场"), dict(page=2, part="结尾")])
        with patch("modules.downloader.urllib.request.urlopen", return_value=io.BytesIO(json.dumps(data).encode())):
            parts = BiliDownloader().parts("https://www.bilibili.com/video/BV1234567890?p=2")
        self.assertEqual(parts[1]["title"], "结尾")
        self.s.parts = parts
        with patch.object(studio_ui.download_job, "download", return_value=str(self.red)) as download:
            studio_ui.download_parts(["1"], "720", self.s, progress=lambda *a, **k: None)
        self.assertEqual(download.call_args.args[:3], (parts[1]["url"], settings.load()["download_dir"], 720))
        self.assertEqual(len(self.s.items), 3)

    def test_parts_reject_non_bilibili_urls(self):
        with self.assertRaises(ValueError):
            BiliDownloader().parts("https://bilibili.com.example.org/video/BV1234567890")


if __name__ == "__main__":
    unittest.main()
