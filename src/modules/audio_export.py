"""Audio-only export: trim/speed/mute without rendering video frames."""
from pathlib import Path
import tempfile

from . import editor, ffmpeg_util, storage, settings, tasks, runtime
from .pipeline import prepare_sources


def export_audio(sources, out_dir, out_name="", out_format="m4a", on_progress=None):
    if out_format not in ("m4a", "mp3", "wav"):
        raise ValueError("音频支持 M4A、MP3、WAV")
    directory = Path(settings.writable_directory(out_dir))
    storage.require_space(directory)
    root = runtime.session_cache() / "audio"
    root.mkdir(parents=True, exist_ok=True)
    storage.require_space(root)
    clips = [(p, s, info) for p, rows, info in prepare_sources(sources) for s in rows]
    total = sum(s.output_duration() for _, s, _ in clips)
    output = storage.reserve_output(directory, out_name, out_format)
    def report(p, message):
        tasks.check()
        if on_progress:
            on_progress(p, message)
    try:
        with tempfile.TemporaryDirectory(prefix="audio_", dir=root) as temp:
            work = Path(temp)
            lines, completed = ["ffconcat version 1.0"], 0.0
            for index, (path, seg, info) in enumerate(clips):
                tasks.check()
                duration = seg.output_duration()
                target = work / f"{index:04d}.wav"
                if seg.mute or not info["has_audio"]:
                    args = ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
                    filters = "anull"
                else:
                    args = ["-ss", str(seg.start), "-t", str(seg.duration()), "-i", path]
                    filters = ",".join(["asetpts=PTS-STARTPTS"] + editor.atempo_chain(seg.speed))
                args += ["-vn", "-map", "0:a:0", "-af", filters + f",aresample=44100,apad,atrim=duration={duration:.9f}",
                         "-t", str(duration), "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", str(target)]
                base, span = completed / total * 80, duration / total * 80
                ffmpeg_util.run_ffmpeg(args, total_duration=duration,
                    on_progress=lambda p, m: report(base + span * p / 100, m),
                    extra_message=f"提取音频 {index + 1}/{len(clips)}")
                lines.append(f"file '{target.name}'")
                completed += duration
            manifest = work / "audio.ffconcat"
            manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
            codec = {"m4a": ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"],
                     "mp3": ["-c:a", "libmp3lame", "-b:a", "192k"], "wav": ["-c:a", "pcm_s16le"]}[out_format]
            ffmpeg_util.run_ffmpeg(["-f", "concat", "-safe", "0", "-i", str(manifest), "-vn", *codec, output],
                total_duration=total, on_progress=lambda p, m: report(80 + p * .2, m), extra_message="保存音频")
            report(100, "音频导出完成")
        return output
    except BaseException:
        Path(output).unlink(missing_ok=True)
        raise
