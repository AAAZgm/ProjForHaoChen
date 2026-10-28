"""Time an export without uploading media; record metadata and decode the result."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from modules import ffmpeg_util, runtime
from modules.pipeline import VideoPipeline
from modules.segmenter import Segment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--mode", choices=["auto", "cpu"], default="auto")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    info = ffmpeg_util.get_video_info(args.source)
    pipe = VideoPipeline(str(args.output / "work"))
    last = [0]
    def progress(percent, message):
        if time.monotonic() - last[0] > 25:
            print(f"{percent:.1f}% {message}", flush=True)
            last[0] = time.monotonic()
    start = time.perf_counter()
    result = pipe.process(str(args.source), [Segment(0, info['duration'], speed=4, mute=True)],
        preset="small", acceleration=args.mode, out_dir=str(args.output), on_progress=progress)
    seconds = time.perf_counter() - start
    output_info = ffmpeg_util.get_video_info(result)
    if abs(output_info['duration'] - info['duration'] / 4) > .15:
        raise RuntimeError("Unexpected output duration")
    ffmpeg_util.run_ffmpeg(["-v", "error", "-i", result, "-f", "null", "-"])
    report = dict(version=runtime.APP_VERSION, seconds=seconds, encoder=pipe.last_engine,
        decoder=pipe.last_decoder, source=info, output=result, media=output_info,
        full_decode="passed", bytes=Path(result).stat().st_size)
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    main()
