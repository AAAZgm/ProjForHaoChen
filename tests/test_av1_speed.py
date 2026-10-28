"""Media correctness and recovery for early frame selection and AV1 decoding."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from modules import editor, encoding, ffmpeg_util as f, tasks
from modules.pipeline import VideoPipeline
from modules.segmenter import Segment


class AV1Speed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.source = cls.root / 'sample.mp4'
        f.run_ffmpeg(['-f','lavfi','-i','testsrc2=size=320x240:rate=60:duration=2',
            '-f','lavfi','-i','sine=duration=2','-c:v','libaom-av1','-cpu-used','8',
            '-threads','2','-crf','38','-c:a','aac',str(cls.source)])

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_av1_speed_audio_duration_and_decode(self):
        for mode, speed, mute in [('auto',4,True),('cpu',4,False),('auto',.5,False)]:
            with self.subTest(mode=mode, speed=speed):
                pipe = VideoPipeline(str(self.root/'work'))
                output = pipe.process(str(self.source), [Segment(.4,1.6,speed=speed,mute=mute)],
                    out_dir=str(self.root), acceleration=mode)
                streams = f.probe(output)['streams']
                durations = {s['codec_type']:float(s['duration']) for s in streams}
                self.assertAlmostEqual(durations['video'], 1.2/speed, delta=.08)
                self.assertAlmostEqual(durations['audio'], durations['video'], delta=.08)
                f.run_ffmpeg(['-v','error','-i',output,'-f','null','-'])

    def test_frame_selection_preserves_rendered_pixels(self):
        seg = Segment(0,2,speed=4,mute=True,crop=(4,4,300,220),watermark={'x':20,'y':20,'w':30,'h':20})
        new,_,_ = editor.build_filter_chain(320,240,seg,(240,180))
        old = new.replace('setpts=PTS/4,fps=30,','').replace(',setsar=1',',setpts=PTS/4,fps=30,setsar=1')
        hashes=[]
        for index,vf in enumerate((old,new)):
            target=self.root/f'{index}.md5'
            f.run_ffmpeg(['-i',str(self.source),'-an','-vf',vf,'-f','framemd5',str(target)])
            hashes.append([line for line in target.read_text().splitlines() if not line.startswith('#')])
        self.assertEqual(hashes[0],hashes[1])

    def test_decode_then_encode_failure_retries_and_cleans(self):
        original, calls = editor.render_segment, []
        def render(*args,**kwargs):
            calls.append((kwargs['decoder'], kwargs['encoder']))
            if kwargs['decoder'] != 'cpu':
                Path(args[2]).write_bytes(b'partial')
                raise encoding.HardwareDecodingError('driver codec unavailable')
            if kwargs['encoder'] != 'cpu':
                raise encoding.HardwareEncodingError('encoder unavailable')
            return original(*args,**kwargs)
        pipe=VideoPipeline(str(self.root/'fallback'))
        with patch.object(encoding,'select',return_value='nvenc'), patch.object(editor,'render_segment',side_effect=render):
            output=pipe.process(str(self.source),[Segment(0,1,speed=4,mute=True)],out_dir=str(self.root),acceleration='auto')
        self.assertEqual(calls,[('av1_cuvid','nvenc'),('cpu','nvenc'),('cpu','cpu')])
        self.assertFalse(list((self.root/'fallback').iterdir()))
        f.run_ffmpeg(['-v','error','-i',output,'-f','null','-'])

    def test_decoder_cancel_does_not_retry(self):
        with patch.object(encoding,'select',return_value='nvenc'), patch.object(editor,'render_segment',side_effect=tasks.Cancelled('cancel')) as render:
            with self.assertRaises(tasks.Cancelled):
                VideoPipeline(str(self.root/'cancel')).process(str(self.source),[Segment(0,1)],out_dir=str(self.root),out_name='cancel',acceleration='auto')
        self.assertEqual(render.call_count,1)
        self.assertFalse((self.root/'cancel.mp4').exists())

    def test_unsupported_format_stays_on_software_decode(self):
        info=f.get_video_info(self.source)
        self.assertEqual(encoding.select_decoder('cpu',info),'cpu')
        for changes in ({'rotation':90},{'pixel_format':'yuv420p10le'},{'codec':'h264'}):
            self.assertEqual(encoding.select_decoder('nvenc',{**info,**changes}),'cpu')

    def test_export_stream_keeps_task_context_within_one_iteration(self):
        from contextvars import Context
        from modules.workspace import Workspace
        import ui
        for cancelled in (False, True):
            project=Workspace()
            project.load(str(self.source),f.get_video_info(self.source))
            def process(*args,**kwargs):
                self.assertIsNotNone(tasks.CURRENT.get())
                self.assertTrue(tasks.busy(project.id))
                if cancelled:
                    tasks.cancel(project.id)
                    tasks.check()
                return str(self.source)
            with patch.object(ui,'VideoPipeline') as pipeline, patch.object(ui.settings,'save',return_value={'output_dir':str(self.root)}), patch.object(ui,'allow_result',side_effect=lambda p:p):
                pipeline.return_value.process.side_effect=process
                pipeline.return_value.last_engine='cpu'
                pipeline.return_value.last_decoder='cpu'
                stream=ui.export_video(project,'通用 MP4',15,.5,progress=lambda *a,**k:None)
                first=Context().run(next,stream)
                self.assertIn('正在准备',first[3])
                self.assertFalse(tasks.busy(project.id))
                result=Context().run(next,stream)
                self.assertIn('已取消' if cancelled else '导出完成',result[3])
                self.assertFalse(tasks.busy(project.id))
                stream.close()
