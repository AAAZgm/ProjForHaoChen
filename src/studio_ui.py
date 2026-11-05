"""Multi-file workflow with session-owned state and cancellable operations."""
from copy import deepcopy
from pathlib import Path
import gradio as gr

import ui
from modules import tasks, settings, runtime, download_job, project_file, diagnostics, studio as model
from modules.links import extract_url


def render(studio, message=""):
    choices = [(f"{i + 1} · {item.name}", item.id) for i, item in enumerate(studio.items)]
    rows = [[i + 1, item.name, len([s for s in item.project.segments if not s.deleted]),
             round(sum(s.output_duration() for s in item.project.segments if not s.deleted), 2), item.status]
            for i, item in enumerate(studio.items)]
    return studio, gr.update(choices=choices, value=studio.selected or None), rows, message


def report(progress):
    return lambda p, m: progress(p / 100, desc=m)


def add_files(paths, studio, progress=gr.Progress()):
    messages = []
    try:
        with tasks.task(studio.id, report(progress)):
            if not paths:
                raise ValueError("请先选择视频，可一次选择多个")
            for i, path in enumerate(paths):
                tasks.check()
                try:
                    studio.add_path(path)
                except tasks.Cancelled:
                    raise
                except Exception as error:
                    messages.append(f"{Path(path).name}：{tasks.friendly_error(error)}")
                progress((i + 1) / len(paths), desc="读取素材")
    except Exception as error:
        messages.append(tasks.friendly_error(error))
    return render(studio, "\n\n".join(messages) or f"已添加素材，列表共有 {len(studio.items)} 项")


def from_editor(project, studio, replace=False):
    try:
        ui.ensure_idle(project)
        ui.ensure_idle(studio)
        if replace:
            item = studio.current()
            if not item:
                raise ValueError("请先选择要更新的列表素材")
            item.project = model.clone(project)
            item.status, item.output, item.signature = "待处理", "", ()
            studio.merged_output = ""
        else:
            studio.add(project)
        return render(studio, "当前剪辑已更新到列表" if replace else "当前剪辑已加入列表，可继续添加其他素材")
    except Exception as error:
        return render(studio, tasks.friendly_error(error))


def to_editor(studio, project):
    try:
        ui.ensure_idle(project)
        ui.ensure_idle(studio)
        item = studio.current()
        if not item:
            raise ValueError("请先选择列表素材")
        with tasks.task(project.id):
            loaded = model.clone(item.project)
            loaded.id = project.id
            frame = ui.frame_payload(loaded)
        ui.allow_result(loaded.path)
        return (*ui.render(loaded, f"已载入列表素材：{item.name}。编辑后到批量页点击“用当前剪辑更新所选项”。"),
                loaded.path, frame, gr.update(value=0, maximum=max(.1, loaded.info["duration"])), gr.update(selected="editor"))
    except Exception as error:
        return (*ui.render(project, tasks.friendly_error(error)), gr.skip(), gr.skip(), gr.skip(), gr.skip())


def change(studio, action, selected=None):
    try:
        ui.ensure_idle(studio)
        if action == "select":
            if any(item.id == selected for item in studio.items):
                studio.selected = selected
        elif action == "clear":
            studio.items.clear()
            studio.selected, studio.merged_output = "", ""
        else:
            studio.edit(action)
        return render(studio, "列表已更新")
    except Exception as error:
        return render(studio, tasks.friendly_error(error))


def run(studio, mode, format_name, directory, name, acceleration, fps, scale, resume=False, progress=gr.Progress()):
    if tasks.busy(studio.id):
        yield (*render(studio, "已有任务，请等待完成或取消"), gr.skip())
        return
    yield (*render(studio, "准备处理；已完成的成品会保留，可随时取消"), gr.skip())
    try:
        with tasks.task(studio.id, report(progress)):
            message = model.run(studio, mode == "按顺序拼接", format_name, directory, name, acceleration,
                                int(fps), float(scale), resume, report(progress))
    except Exception as error:
        diagnostics.error("batch export", error)
        message = tasks.friendly_error(error)
    outputs = [ui.allow_result(p) for p in studio.outputs()]
    yield (*render(studio, message), outputs or None)


def parse_parts(url, studio, progress=gr.Progress()):
    try:
        with tasks.task(studio.id, report(progress)):
            studio.parts = []
            studio.parts = download_job.parts(extract_url(url), report(progress))
        choices = [(f"P{p['page']} · {p['title']}", str(i)) for i, p in enumerate(studio.parts)]
        return (*render(studio, f"已识别 {len(choices)} 个分 P，请勾选后下载"), gr.update(choices=choices, value=[]))
    except Exception as error:
        return (*render(studio, tasks.friendly_error(error)), gr.update(choices=[], value=[]))


def download_parts(selected, quality, studio, progress=gr.Progress()):
    messages = []
    try:
        with tasks.task(studio.id, report(progress)):
            indices = sorted(set(int(value) for value in selected or []))
            if not indices or any(i < 0 or i >= len(studio.parts) for i in indices):
                raise ValueError("请先识别分 P 并勾选要下载的项目")
            if len(indices) + len(studio.items) > model.MAX_ITEMS:
                raise ValueError("加入后超过 100 项，请分批下载")
            folder = settings.load()["download_dir"]
            for index, chosen in enumerate(indices):
                tasks.check()
                part = studio.parts[chosen]
                try:
                    path = download_job.download(part["url"], folder, int(quality),
                        lambda p, m: progress((index + p / 100) / len(indices), desc=f"P{part['page']} · {m}"))
                    ui.allow_result(path)
                    studio.add_path(path, f"P{part['page']} · {part['title']}")
                except tasks.Cancelled:
                    raise
                except Exception as error:
                    messages.append(f"P{part['page']}：{tasks.friendly_error(error)}")
    except Exception as error:
        messages.append(tasks.friendly_error(error))
    return render(studio, "\n\n".join(messages) or "所选分 P 已下载并加入列表，可分别导出或拼接")


def save_plan(studio, directory, name, mode, format_name, fps, scale, progress=gr.Progress()):
    try:
        with tasks.task(studio.id, report(progress)):
            path = project_file.save(studio, directory, name,
                dict(merge=mode == "按顺序拼接", format=format_name, fps=fps, scale=scale), report(progress))
        return ui.allow_result(path), "方案已保存，包含原素材和编辑设置；可以重启或换电脑后恢复"
    except Exception as error:
        return gr.skip(), tasks.friendly_error(error)


def load_plan(path, studio, progress=gr.Progress()):
    try:
        with tasks.task(studio.id, report(progress)):
            restored, options = project_file.load(path, report(progress))
            # Commit only after all media, parameters and checksums have passed.
            studio.items, studio.selected, studio.parts = restored.items, restored.selected, []
            studio.merged_output = ""
        return (*render(studio, "方案已恢复。可直接导出，或载入所选素材继续编辑。"),
                "按顺序拼接" if options["merge"] else "分别导出", options["format"], options["fps"], options["scale"], None,
                gr.update(choices=[], value=[]))
    except Exception as error:
        return (*render(studio, tasks.friendly_error(error)), *[gr.skip() for _ in range(6)])


def build_panel(config):
    c = {}
    c["state"] = gr.State(lambda: model.Studio(), delete_callback=lambda s: tasks.cancel(s.id))
    gr.Markdown("### 批量与拼接\n添加多个素材，或把剪辑工作台的结果加入列表。选择“分别导出”或“按顺序拼接”，也可以只保存音频。")
    with gr.Row(equal_height=False):
        with gr.Column(scale=1, min_width=320, elem_classes="work-panel"):
            c["files"] = gr.File(label="添加本地视频（可多选）", file_count="multiple", type="filepath",
                                 file_types=[".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".ts"])
            c["add"] = gr.Button("加入列表", variant="primary")
            c["from_editor"] = gr.Button("将当前剪辑加入列表")
            with gr.Accordion("B 站多 P 下载", open=False):
                c["url"] = gr.Textbox(label="视频链接或分享文字")
                c["parse"] = gr.Button("识别分 P")
                c["parts"] = gr.CheckboxGroup(label="选择要下载的分 P", choices=[])
                c["quality"] = gr.Dropdown([("最高可用", "0"), ("1080P", "1080"), ("720P", "720")], value="0", label="清晰度上限")
                c["download"] = gr.Button("下载所选分 P 并加入列表")
        with gr.Column(scale=2, min_width=420, elem_classes="work-panel"):
            c["table"] = gr.Dataframe(headers=["顺序", "素材", "保留片段", "成品时长（秒）", "状态"],
                                      datatype=["number", "str", "number", "number", "str"], interactive=False, value=[])
            c["selected"] = gr.Dropdown(choices=[], label="选择要操作的素材")
            with gr.Row():
                for key, label in (("up", "上移"), ("down", "下移"), ("delete", "移除"), ("clear", "清空列表")):
                    c[key] = gr.Button(label, size="sm")
            c["to_editor"] = gr.Button("载入所选素材到剪辑工作台")
            c["replace"] = gr.Button("用当前剪辑更新所选项")
            gr.Markdown("列表保留加入时的剪辑设置。修改后请点击“用当前剪辑更新所选项”。移除列表项不会删除原素材或已有成品。")
    with gr.Row(equal_height=False):
        with gr.Column(elem_classes="work-panel"):
            c["mode"] = gr.Radio(["分别导出", "按顺序拼接"], value="分别导出", label="处理方式")
            c["format"] = gr.Dropdown(model.FORMATS, value="通用 MP4", label="成品格式")
            gr.Markdown("拼接按列表顺序，以首个素材的画面尺寸（含裁剪）统一，其他画面等比缩放并补边。音频导出保留截取、倍速和消音；无声素材补静音。")
            with gr.Row():
                c["fps"] = gr.Slider(5, 30, value=15, step=1, label="GIF 帧率", visible=False)
                c["scale"] = gr.Slider(.1, 1, value=.5, step=.05, label="GIF 缩放", visible=False)
            c["acceleration"] = gr.Dropdown([("自动加速", "auto"), ("CPU 兼容模式", "cpu")], value=config["acceleration"], label="视频编码方式")
            c["directory"] = gr.Textbox(value=config["output_dir"], label="成品与方案保存文件夹")
            c["name"] = gr.Textbox(label="成品名称或批量前缀（可留空）")
            with gr.Row():
                c["run"] = gr.Button("开始处理列表", variant="primary")
                c["resume"] = gr.Button("继续未完成任务")
            c["cancel"] = gr.Button("取消批量任务", variant="stop")
        with gr.Column(elem_classes="work-panel"):
            c["status"] = gr.Markdown("先添加素材。", elem_classes="status-note")
            c["results"] = gr.File(label="已完成成品（可分别下载）", file_count="multiple", interactive=False)
            with gr.Accordion("保存与恢复编辑方案", open=True):
                gr.Markdown("方案包含列表顺序、片段设置和原素材，可换电脑恢复。文件大小接近原素材总量，最多 100 个素材、20 GB。")
                c["plan_name"] = gr.Textbox(value="轻剪方案", label="方案名称")
                c["save"] = gr.Button("保存整个列表为方案")
                c["saved"] = gr.File(label="已保存方案", interactive=False)
                c["plan"] = gr.File(label="选择已有方案", file_types=[".qjproj"], type="filepath")
                c["load"] = gr.Button("恢复方案并替换当前列表")
    return c


def bind(c, editor_state, import_outputs, pages):
    state = c["state"]
    outputs = [state, c["selected"], c["table"], c["status"]]
    def bind_button(key, fn, inputs, result=outputs, api=None):
        return c[key].click(fn, inputs, result, api_name=api or "studio_" + key,
                            concurrency_id="studio", show_progress_on=c["status"])
    bind_button("add", add_files, [c["files"], state])
    bind_button("from_editor", from_editor, [editor_state, state])
    bind_button("replace", lambda p, s: from_editor(p, s, True), [editor_state, state])
    bind_button("to_editor", to_editor, [state, editor_state], import_outputs + [pages])
    for key in ("up", "down", "delete", "clear"):
        bind_button(key, lambda s, action=key: change(s, action), state)
    c["selected"].input(lambda s, v: change(s, "select", v), [state, c["selected"]], outputs, concurrency_id="studio", api_name="studio_select")
    inputs = [state] + [c[k] for k in ("mode", "format", "directory", "name", "acceleration", "fps", "scale")]
    bind_button("run", run, inputs, outputs + [c["results"]])
    def resume(s, mode, fmt, directory, name, acceleration, fps, scale, progress=gr.Progress()):
        yield from run(s, mode, fmt, directory, name, acceleration, fps, scale, True, progress)
    bind_button("resume", resume, inputs, outputs + [c["results"]])
    c["cancel"].click(lambda s: "正在取消；已完成成品会保留" if tasks.cancel(s.id) else "当前没有进行中的批量任务",
                       state, c["status"], queue=False, api_name="studio_cancel")
    bind_button("parse", parse_parts, [c["url"], state], outputs + [c["parts"]])
    bind_button("download", download_parts, [c["parts"], c["quality"], state])
    bind_button("save", save_plan, [state] + [c[k] for k in ("directory", "plan_name", "mode", "format", "fps", "scale")], [c["saved"], c["status"]])
    bind_button("load", load_plan, [c["plan"], state], outputs + [c[k] for k in ("mode", "format", "fps", "scale", "results", "parts")])
    c["format"].change(lambda f: [gr.update(visible=f == "GIF 动图")] * 2,
                       c["format"], [c["fps"], c["scale"]], api_visibility="private")
