"""The guided editor. Each browser session owns its source, segments and history."""
import base64
from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import time

import gradio as gr
from PIL import Image

from modules import download_job, ffmpeg_util, runtime, tasks, settings, storage, diagnostics, lifecycle, updates, encoding
from modules.pipeline import VideoPipeline
from modules.segmenter import make_full_segment, validate_segments
from modules.table import TABLE_HEADERS, TABLE_DATATYPE, segments_to_table, table_to_segments
from modules.workspace import Workspace

PRESETS = settings.PRESETS
EMPTY_CANVAS = json.dumps({"image": "", "rect": [], "media_id": ""})
CANVAS_HTML = '''<div class="region-tool">
<p>在画面上拖出矩形；框选后点击下方“应用选区”。</p>
<canvas aria-label="画面框选区域" style="display:block;max-width:100%;height:auto;touch-action:none;cursor:crosshair;background:#111827"></canvas>
<p class="region-label">导入视频后可提取画面</p></div>'''
CANVAS_JS = r'''
let payload = {}, img = new Image(), origin = null;
function draw() {
  const canvas = element.querySelector('canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  canvas.width = img.naturalWidth || 640; canvas.height = img.naturalHeight || 180;
  if (img.naturalWidth) ctx.drawImage(img, 0, 0);
  const r = payload.rect || [];
  if (r.length === 4) {
    const x = Math.min(r[0],r[2])*canvas.width, y = Math.min(r[1],r[3])*canvas.height;
    const w = Math.abs(r[2]-r[0])*canvas.width, h = Math.abs(r[3]-r[1])*canvas.height;
    ctx.fillStyle = 'rgba(20,184,166,.22)'; ctx.fillRect(x,y,w,h);
    ctx.strokeStyle = '#14b8a6'; ctx.lineWidth = 3; ctx.strokeRect(x,y,w,h);
    element.querySelector('.region-label').textContent = `选区：${Math.round(w)} × ${Math.round(h)}（预览像素；导出自动换算）`;
  } else element.querySelector('.region-label').textContent = img.naturalWidth ? '拖动鼠标或触屏框选' : '导入视频后可提取画面';
}
function position(e) {
  const r = e.target.getBoundingClientRect();
  return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)), Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];
}
function bind() {
  const c = element.querySelector('canvas');
  c.onpointerdown = e => { if (!img.naturalWidth) return; origin = position(e); c.setPointerCapture(e.pointerId); };
  c.onpointermove = e => { if (origin) { payload.rect = [...origin,...position(e)]; draw(); } };
  c.onpointerup = e => { if (!origin) return; payload.rect = [...origin,...position(e)]; origin = null; props.value = JSON.stringify(payload); draw(); };
  c.onpointercancel = () => { origin = null; };
}
function refresh() {
  try { payload = JSON.parse(props.value || '{}'); } catch { payload = {}; }
  bind();
  if (payload.image) { img.onload = draw; if (img.src !== payload.image) img.src = payload.image; else draw(); }
  else { img = new Image(); draw(); }
}
watch('value', refresh); refresh();
'''


def summary(project, preset="通用 MP4", fps=15, scale=.5, directory=""):
    if not project.path:
        return "导入视频后显示成品时长、尺寸和保存位置。"
    duration, w, h = project.estimate(preset)
    if preset == "GIF 动图":
        w, h = max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)
    return (f"**{len([s for s in project.segments if not s.deleted])} 个片段 · 成品时长约 {duration:.2f} 秒 · {w} × {h}**\n\n"
            f"{preset} · {'无声音' if preset == 'GIF 动图' else 'H.264 + AAC'} · 保存到 `{directory or settings.load()['output_dir']}`")


def allow_result(path):
    # Permit only files actually produced by this application, not arbitrary folders.
    from gradio.context import LocalContext
    blocks = LocalContext.blocks.get(None)
    if blocks is not None and str(path) not in blocks.allowed_paths:
        blocks.allowed_paths.append(str(path))
    return path


def render(project, message=""):
    choices = [(f"{i+1} · {s.start:.2f}–{s.end:.2f}s · {s.speed:g}×"
                + (" · 消音" if s.mute else "") + (" · 已排除" if s.deleted else ""), str(i))
               for i, s in enumerate(project.segments)]
    seg = project.current() if choices else None
    return (project, gr.update(choices=choices, value=str(project.selected) if choices else None),
            segments_to_table(project.segments), seg.start if seg else 0, seg.end if seg else 0,
            seg.mute if seg else False, seg.speed if seg else 1,
            message)


def ensure_idle(project):
    if tasks.busy(project.id):
        raise ValueError("任务进行中，请先取消或等待完成后再编辑")


def frame_payload(project, at=0):
    if not project.path:
        raise ValueError("请先导入视频")
    folder = runtime.session_cache() / "preview" / project.id
    folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="frame_", dir=folder) as directory:
        frame = str(Path(directory) / "frame.png")
        at = max(0, min(float(at or 0), max(0, project.info["duration"] - .1)))
        ffmpeg_util.extract_frame(project.path, at, frame)
        with Image.open(frame) as source:
            picture = source.convert("RGB")
        picture.thumbnail((900, 600))
        data = io.BytesIO()
        picture.save(data, format="JPEG", quality=85)
    return json.dumps(dict(image="data:image/jpeg;base64," + base64.b64encode(data.getvalue()).decode(),
                           media_id=project.media_id, rect=[]))


def import_video(path, project):
    project = project or Workspace()
    try:
        ensure_idle(project)
        if not path:
            raise ValueError("请先选择视频文件")
        with tasks.task(project.id):
            project.load(str(path), ffmpeg_util.get_video_info(str(path)))
            try:
                frame = frame_payload(project)
            except tasks.Cancelled:
                raise
            except Exception as error:
                diagnostics.error("source frame", error)
                frame = EMPTY_CANVAS
        info = project.info
        return (*render(project, f"已载入：{Path(path).name} · {info['duration']:.2f} 秒 · {info['width']}×{info['height']}"),
                project.path, frame, gr.update(value=0, maximum=max(.1, info["duration"])))
    except Exception as error:
        diagnostics.error("import", error)
        return (*render(project, tasks.friendly_error(error)), gr.skip(), gr.skip(), gr.skip())


def download_video(url, quality, project, progress=gr.Progress()):
    from modules.links import extract_url
    project = project or Workspace()
    path = None
    try:
        url = extract_url(url)
        if not url.lower().startswith(("https://", "http://")):
            raise ValueError("请粘贴有效的视频链接或分享文字")
        def cb(p, message):
            progress(p / 100, desc=message)
        with tasks.task(project.id, cb):
            height = {"推荐（不超过 1080p）": 1080, "不超过 720p": 720, "不超过 480p": 480}.get(quality, 0)
            folder = settings.writable_directory(settings.load()["download_dir"])
            storage.require_space(folder)
            path = allow_result(download_job.download(url, folder, height, cb))
            tasks.check()
        return import_video(path, project)
    except Exception as error:
        diagnostics.error("download", error)
        return (*render(project, tasks.friendly_error(error)), gr.skip(), gr.skip(), gr.skip())


def select_segment(project, selected):
    if selected is not None:
        project.selected = int(selected)
    return render(project)


def clear_source(project):
    try:
        ensure_idle(project)
        project = Workspace(id=project.id)
        return (*render(project, "已清除素材，可重新导入"), None, EMPTY_CANVAS,
                gr.update(value=0, maximum=1))
    except Exception as error:
        return (*render(project, tasks.friendly_error(error)), gr.skip(), gr.skip(), gr.skip())


def edit(project, action, *values):
    try:
        ensure_idle(project)
        if not project.path:
            raise ValueError("请先导入视频")
        if action == "split": project.split(values[0])
        elif action == "trim": project.trim(*values)
        elif action == "up": project.move(-1)
        elif action == "down": project.move(1)
        elif action == "delete": project.delete()
        elif action == "undo": project.history()
        elif action == "redo": project.history(redo=True)
        elif action == "reset": project.commit(make_full_segment(project.info["duration"]), 0)
        elif action == "effects": project.effects(values[0], values[1], values[2] == "全部片段")
        elif action == "region": project.region(json.loads(values[0]), values[1], values[2] == "全部片段")
        elif action == "clear": project.clear_region(values[0] == "全部片段")
        elif action == "table":
            rows = table_to_segments(values[0])
            errors = validate_segments(rows)
            if errors: raise ValueError("；".join(errors))
            if any(s.start < 0 or s.end > project.info["duration"] for s in rows):
                raise ValueError("片段起止时间超出视频范围")
            project.commit(rows)
        return render(project, "已更新；导出会严格按照片段列表顺序。可撤销本次操作。")
    except Exception as error:
        return render(project, tasks.friendly_error(error))


def prepare_frame(project, at, progress=gr.Progress()):
    try:
        with tasks.task(project.id):
            return frame_payload(project, at), "画面已更新，请拖动框选"
    except Exception as error:
        return gr.skip(), tasks.friendly_error(error)


def export_video(project, preset, fps, scale, name="", directory="", acceleration="auto", progress=gr.Progress()):
    started = time.monotonic()
    try:
        if not project.path:
            raise ValueError("请先导入视频")
        source, segments = project.path, deepcopy(project.segments)
        name = storage.filename(name)
        def cb(p, message): progress(p / 100, desc=message)
        ensure_idle(project)
        # Gradio may advance a sync generator in a different Context on each
        # iteration. Never suspend while tasks.task() owns its ContextVar token.
        yield gr.skip(), gr.skip(), gr.skip(), "正在准备导出，请稍候…", ""
        with tasks.task(project.id, cb):
            options = settings.save(output_dir=directory or settings.load()["output_dir"],
                                    preset=preset, gif_fps=fps, gif_scale=scale, acceleration=acceleration)
            pipeline = VideoPipeline()
            output = pipeline.process(source, segments,
                out_format="gif" if preset == "GIF 动图" else "mp4",
                out_dir=options["output_dir"], out_name=name, gif_fps=int(fps), gif_scale=float(scale),
                preset="small" if preset == "较小 MP4" else "standard", on_progress=cb, acceleration=acceleration)
            project.last_output = allow_result(output)
            diagnostics.LOG.info("Export completed: %s", output)
        gif = preset == "GIF 动图"
        yield (gr.update(value=None if gif else output, visible=not gif),
                gr.update(value=output if gif else None, visible=gif), output,
                f"导出完成 · {encoding.label(pipeline.last_engine, pipeline.last_decoder)} · 用时 {time.monotonic() - started:.1f} 秒\n\n文件保存在：{output}", "")
    except Exception as error:
        yield gr.skip(), gr.skip(), gr.skip(), tasks.friendly_error(error), diagnostics.error("export", error)


def preview_segment(project, progress=gr.Progress()):
    try:
        seg = deepcopy(project.current())
        if seg.deleted:
            raise ValueError("当前片段已排除，请选择保留的片段")
        seg = replace(seg, end=min(seg.end, seg.start + 5 * seg.speed))
        def cb(p, message): progress(p / 100, desc=message)
        with tasks.task(project.id, cb):
            output = VideoPipeline().process(project.path, [seg],
                out_dir=str(runtime.session_cache() / "preview" / project.id), preset="preview", on_progress=cb)
        return gr.update(value=allow_result(output), visible=True), "预览完成：当前片段开头最多 5 秒的处理效果", ""
    except Exception as error:
        return gr.skip(), tasks.friendly_error(error), diagnostics.error("preview", error)


def cancel_task(project):
    return "正在取消并清理，请等待任务结束…" if tasks.cancel(project.id) else "当前没有运行中的任务"


def save_preferences(output, download, preset, fps, scale, days, acceleration="auto"):
    try:
        settings.save(output_dir=output, download_dir=download, preset=preset,
                      gif_fps=fps, gif_scale=scale, cache_days=days, acceleration=acceleration)
        return "设置已保存，下次启动会自动恢复。已打开的其他页面可点击“重新读取设置”。"
    except Exception as error:
        diagnostics.error("settings", error)
        return tasks.friendly_error(error)


def read_preferences():
    config = settings.load()
    return (config["output_dir"], config["download_dir"], config["preset"], config["gif_fps"],
            config["gif_scale"], config["cache_days"], "已读取保存的设置。" + settings.notice())


def open_output(project, folder=False):
    try:
        if not project.last_output:
            raise ValueError("请先完成一次导出")
        storage.open_local(project.last_output, folder)
        return "已打开成品所在文件夹" if folder else "已请求系统打开成品文件"
    except Exception as error:
        return tasks.friendly_error(error)


def open_saved_folder(kind):
    try:
        folder = settings.writable_directory(settings.load()[kind])
        storage.open_local(folder, folder=True)
        return "已打开保存文件夹"
    except Exception as error:
        return tasks.friendly_error(error)


def cleanup():
    try:
        removed, size, skipped = storage.clean_cache()
        return (f"已清理 {removed} 组历史缓存，释放 {size / 1024 / 1024:.1f} MB。"
                f"本次运行的素材和预览受到保护，将在退出时清理；下载素材和导出成品不会删除。"
                + (f"{skipped} 组正在占用或含特殊链接的缓存已跳过。" if skipped else ""))
    except Exception as error:
        return tasks.friendly_error(error)



def build_ui():
    from ui_layout import build_ui as build_layout
    return build_layout()
