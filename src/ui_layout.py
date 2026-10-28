"""Task-oriented layout; editing callbacks remain in ui.py."""
import gradio as gr
import ui as actions
from modules import runtime, settings, tasks, lifecycle, diagnostics, updates
from modules.workspace import Workspace
from modules.table import TABLE_HEADERS, TABLE_DATATYPE

CSS = """
.gradio-container {width:100% !important;max-width:1280px !important;box-sizing:border-box; margin:auto; padding:24px 22px !important;}
body, .gradio-container {background:#f4f7f8;}
.app-hero {display:flex;justify-content:space-between;gap:20px;align-items:center;margin:4px 0 24px;}
.app-hero h1 {font-size:30px;letter-spacing:-1px;color:#12343a;margin:0 0 7px;}
.app-hero p {color:#61767b;margin:0;font-size:14px;}
.app-badge {border:1px solid #cbdedc;border-radius:20px;padding:7px 12px;color:#36736b;font-size:12px;white-space:nowrap;}
.work-panel {background:var(--block-background-fill);border:1px solid var(--border-color-primary);border-radius:16px;padding:18px !important;}
.section-heading h3 {font-size:17px !important;margin:0 0 6px !important;}
.section-heading p {color:var(--body-text-color-subdued);font-size:13px;}
.status-note {border-left:3px solid #14b8a6;padding:9px 12px;background:var(--block-background-fill);border-radius:4px;}
.primary-action {min-height:46px !important;font-weight:650 !important;}
.compact-action {min-width:65px !important;}
.tab-container[role=tablist] {gap:8px;border-bottom:1px solid #d8e3e3 !important;margin-bottom:14px;}
.tab-container[role=tablist] button {border-radius:10px 10px 0 0 !important;padding:10px 16px !important;}
.tab-container[role=tablist] button.selected {color:#0f766e !important;background:#e5f3f0 !important;border-color:transparent !important;font-weight:650;}
.region-tool canvas {max-height:400px;object-fit:contain;}
.dark .gradio-container {background:#0f172a;}
.dark .app-hero h1 {color:#e2e8f0;}
.dark .app-hero p {color:#a4b8be;}
.dark .app-badge {color:#7dd3c7;border-color:#36615c;}
@media(max-width:700px) {.gradio-container{padding:12px !important}.app-hero{align-items:flex-start}.app-badge{display:none}.tab-container[role=tablist] button{padding:10px !important}.work-panel{padding:12px !important}}
"""


def build_ui():
    config = settings.load()
    with gr.Blocks(title="轻剪 · 视频下载与编辑", fill_width=True) as demo:
        state = gr.State(lambda: Workspace(), delete_callback=lambda p: tasks.cancel(p.id) if p else None)
        gr.HTML(f'<header class="app-hero"><div><h1>轻剪</h1><p>导入素材，留下需要的片段，保存成品。</p></div><span class="app-badge">本地视频工具 · {runtime.APP_VERSION}</span></header>')
        if settings.notice():
            gr.Markdown(settings.notice(), elem_classes="status-note")
        with gr.Tabs(selected="editor") as pages:
            with gr.Tab("1 · 剪辑工作台", id="editor"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=1, min_width=280):
                        with gr.Column(elem_classes="work-panel"):
                            gr.Markdown("### 导入素材\n选择一种方式，完成后自动载入。", elem_classes="section-heading")
                            with gr.Tabs():
                                with gr.Tab("本地视频"):
                                    upload = gr.File(label="拖入或选择本地视频", file_types=["video"], type="filepath", height=135)
                                with gr.Tab("B 站链接"):
                                    url = gr.Textbox(label="链接或分享文字", placeholder="粘贴 B 站链接", lines=2)
                                    quality = gr.Dropdown(["推荐（不超过 1080p）", "最高可用", "不超过 720p", "不超过 480p"], value="推荐（不超过 1080p）", label="下载清晰度上限")
                                    download = gr.Button("下载并载入", variant="primary")
                                    cancel_download = gr.Button("取消下载", size="sm")
                        with gr.Column(elem_classes="work-panel"):
                            gr.Markdown("### 片段列表\n从上到下，就是成品播放顺序。", elem_classes="section-heading")
                            selected = gr.Dropdown([], label="当前片段", interactive=True)
                            with gr.Row():
                                up = gr.Button("上移", size="sm", elem_classes="compact-action")
                                down = gr.Button("下移", size="sm", elem_classes="compact-action")
                                delete = gr.Button("删除", size="sm", elem_classes="compact-action")
                            with gr.Row():
                                undo = gr.Button("撤销", size="sm")
                                redo = gr.Button("重做", size="sm")
                            with gr.Accordion("重置与高级参数", open=False):
                                reset = gr.Button("重置为整片", size="sm")
                                gr.Markdown("高级表格修改后需应用；重复行会重复播放。")
                                table = gr.Dataframe(headers=TABLE_HEADERS, datatype=TABLE_DATATYPE, type="array", value=[], interactive=True, label="高级片段参数")
                                save_table = gr.Button("应用高级参数", size="sm")
                    with gr.Column(scale=3, min_width=460):
                        with gr.Column(elem_classes="work-panel"):
                            source = gr.Video(label="原视频", interactive=False, elem_id="source-player", height=340)
                            cursor = gr.Slider(0, 1, value=0, step=.01, label="播放位置（秒）")
                            with gr.Row():
                                capture = gr.Button("同步播放位置", size="sm")
                                split = gr.Button("在播放位置分割", size="sm")
                            gr.Markdown("### 截取当前片段", elem_classes="section-heading")
                            with gr.Row():
                                with gr.Column(min_width=130):
                                    start = gr.Number(label="起点（秒）", value=0)
                                    mark_start = gr.Button("播放位置设为起点", size="sm")
                                with gr.Column(min_width=130):
                                    end = gr.Number(label="终点（秒）", value=0)
                                    mark_end = gr.Button("播放位置设为终点", size="sm")
                            trim = gr.Button("应用起止时间", variant="primary")
                        with gr.Column(elem_classes="work-panel"):
                            scope = gr.Radio(["当前片段", "全部片段"], value="当前片段", label="下面的效果应用到")
                            with gr.Tabs():
                                with gr.Tab("声音与速度"):
                                    with gr.Row():
                                        mute = gr.Checkbox(label="消音", value=False)
                                        speed = gr.Dropdown([.25, .5, 1, 1.5, 2, 4], value=1, label="播放倍速", allow_custom_value=True)
                                    effects = gr.Button("应用声音与速度")
                                with gr.Tab("裁剪与水印"):
                                    gr.Markdown("拖动框选画面，再应用效果。水印淡化用周围像素填补，请先预览效果。")
                                    frame_button = gr.Button("提取当前画面，开始框选", size="sm")
                                    canvas = gr.HTML(actions.EMPTY_CANVAS, html_template=actions.CANVAS_HTML, js_on_load=actions.CANVAS_JS, elem_id="region-canvas")
                                    region_mode = gr.Radio(["裁剪画面", "水印淡化"], value="裁剪画面", label="选区用途")
                                    with gr.Row():
                                        apply_region = gr.Button("应用选区")
                                        clear_region = gr.Button("清除画面效果")
                            preview = gr.Button("预览当前片段效果 · 最多 5 秒")
                            short_video = gr.Video(label="效果预览", interactive=False, visible=False, height=250)
                status = gr.Markdown("先导入视频，再设置片段或画面效果。", elem_classes="status-note")
                go_export = gr.Button("下一步：导出成品 →", variant="primary", elem_classes="primary-action")

            with gr.Tab("2 · 导出成品", id="export") as export_page:
                with gr.Row(equal_height=False):
                    with gr.Column(scale=1, min_width=320, elem_classes="work-panel"):
                        gr.Markdown("### 导出选项\n选择格式与保存位置，随后开始导出。", elem_classes="section-heading")
                        preset = gr.Radio(actions.PRESETS, value=config["preset"], label="成品格式")
                        gr.Markdown("通用 MP4 保留画面尺寸；较小 MP4 适合分享；GIF 无声音。")
                        fps = gr.Slider(5, 30, value=config["gif_fps"], step=1, label="GIF 帧率", visible=config["preset"] == "GIF 动图")
                        scale = gr.Slider(.1, 1, value=config["gif_scale"], step=.05, label="GIF 缩放比例", visible=config["preset"] == "GIF 动图")
                        acceleration = gr.Dropdown([("自动加速（推荐）", "auto"), ("CPU 兼容模式", "cpu")], value=config["acceleration"], label="编码方式", info="可用时使用 NVIDIA 显卡编码，并为支持的 AV1 视频尝试显卡解码；失败自动回退 CPU。画面效果仍需 CPU 处理。")
                        output_name = gr.Textbox(label="成品文件名（不含扩展名）", placeholder="留空自动命名，同名文件会避重")
                        output_dir = gr.Textbox(value=config["output_dir"], label="成品保存文件夹", info="填写完整路径，导出时自动记住")
                        estimate = gr.Markdown(actions.summary(Workspace()), elem_classes="status-note")
                        export = gr.Button("开始导出", variant="primary", elem_classes="primary-action")
                        cancel = gr.Button("取消当前任务", size="sm")
                        back = gr.Button("← 返回剪辑", size="sm")
                    with gr.Column(scale=2, min_width=400, elem_classes="work-panel"):
                        gr.Markdown("### 导出结果", elem_classes="section-heading")
                        task_status = gr.Markdown("准备就绪。导出时会显示所用编码方式和进度。", elem_classes="status-note")
                        result_video = gr.Video(label="成品预览 · MP4", interactive=False, height=300)
                        result_gif = gr.Image(label="成品预览 · GIF", type="filepath", interactive=False, visible=False, height=300)
                        result_file = gr.File(label="保存成品副本", interactive=False)
                        with gr.Row():
                            open_file = gr.Button("打开成品")
                            open_folder = gr.Button("打开所在文件夹")

            with gr.Tab("设置与帮助", id="settings"):
                with gr.Row(equal_height=False):
                    with gr.Column(scale=2, min_width=350, elem_classes="work-panel"):
                        gr.Markdown("### 存储与缓存\n设置保存在当前用户目录，升级后继续使用。", elem_classes="section-heading")
                        download_dir = gr.Textbox(value=config["download_dir"], label="下载素材保存文件夹")
                        days = gr.Slider(1, 90, value=config["cache_days"], step=1, label="历史缓存保留天数")
                        with gr.Row():
                            save_settings = gr.Button("保存设置", variant="primary")
                            load_settings = gr.Button("重新读取设置")
                        settings_status = gr.Markdown("")
                        gr.Markdown("成品目录、格式和编码方式在“导出成品”页设置；点击保存也会记住这些选项。")
                        with gr.Row():
                            open_downloads = gr.Button("打开下载文件夹")
                            open_exports = gr.Button("打开成品文件夹")
                        clear_cache = gr.Button("清理历史缓存")
                        gr.Markdown("当前素材和预览受保护，退出时清理。下载素材和导出成品不会删除。")
                    with gr.Column(scale=1, min_width=300, elem_classes="work-panel"):
                        gr.Markdown("### 使用帮助\n1. 导入素材，设置起止时间或分割片段。\n2. 在对应分组中应用声音、速度或画面效果。\n3. 前往导出页，保存成品。\n\n**长视频提示**：水印与裁剪需逐帧处理；显卡加速支持的解码与编码环节，耗时也取决于视频长度与分辨率。", elem_classes="section-heading")
                        check_update = gr.Button("检查正式版更新")
                        update_status = gr.Markdown(f"版本 {runtime.APP_VERSION} · [版本与下载页面]({runtime.RELEASES_URL})")
                        with gr.Accordion("诊断信息", open=False):
                            gr.Markdown("复制前请检查路径中的用户名。链接和常见登录凭据会隐藏。")
                            diagnostic_button = gr.Button("生成诊断信息")
                            diagnostic_text = gr.Textbox(label="可复制的诊断信息", lines=8, buttons=["copy"], interactive=False)
                        reopen = gr.Button("重新打开页面")
                        exit_app = gr.Button("退出程序", variant="stop")
                        gr.Markdown("关闭浏览器不会退出程序。使用完毕请点击退出；再次双击会重开已有页面。")
        with gr.Accordion("错误详情", open=False):
            details = gr.Textbox(label="详情", interactive=False, lines=4, buttons=["copy"])

        edit_outputs = [state, selected, table, start, end, mute, speed, status]
        import_outputs = edit_outputs + [source, canvas, cursor]
        summary_inputs = [state, preset, fps, scale, output_dir]
        def refresh(event):
            event.then(actions.summary, summary_inputs, estimate, api_visibility="private")
            return event
        refresh(upload.upload(actions.import_video, [upload, state], import_outputs, api_name="import_video"))
        refresh(upload.clear(actions.clear_source, state, import_outputs, api_name="clear_source"))
        refresh(download.click(actions.download_video, [url, quality, state], import_outputs, concurrency_limit=None, api_name="download_video"))
        cancel_download.click(actions.cancel_task, state, status, queue=False, api_name="cancel_download", api_visibility="private")
        refresh(selected.input(actions.select_segment, [state, selected], edit_outputs, api_name="select_segment"))
        operations = [(split, "split", [cursor]), (trim, "trim", [start, end]), (up, "up", []), (down, "down", []),
            (delete, "delete", []), (undo, "undo", []), (redo, "redo", []), (reset, "reset", []),
            (effects, "effects", [mute, speed, scope]), (apply_region, "region", [canvas, region_mode, scope]),
            (clear_region, "clear", [scope]), (save_table, "table", [table])]
        for button, action, inputs in operations:
            def callback(project, *values, action=action): return actions.edit(project, action, *values)
            js = "(s,t) => [s, document.querySelector('#source-player video')?.currentTime ?? t]" if action == "split" else None
            refresh(button.click(callback, [state] + inputs, edit_outputs, api_name=action, concurrency_id="edit", js=js))
        read_time = "() => [document.querySelector('#source-player video')?.currentTime ?? 0]"
        capture.click(None, outputs=cursor, js=read_time)
        mark_start.click(None, outputs=start, js=read_time)
        mark_end.click(None, outputs=end, js=read_time)
        cursor.input(None, cursor, js="(t) => {const v=document.querySelector('#source-player video'); if(v) v.currentTime=t;}")
        frame_button.click(actions.prepare_frame, [state, cursor], [canvas, status], api_name="prepare_frame")
        preview.click(actions.preview_segment, state, [short_video, status, details], concurrency_limit=None, api_name="preview_segment")
        export.click(actions.export_video, [state, preset, fps, scale, output_name, output_dir, acceleration],
                     [result_video, result_gif, result_file, task_status, details], concurrency_limit=None,
                     show_progress_on=[task_status], api_name="export_video")
        cancel.click(actions.cancel_task, state, task_status, queue=False, api_name="cancel_task")
        preset.change(lambda p: (gr.update(visible=p == "GIF 动图"), gr.update(visible=p == "GIF 动图")), preset, [fps, scale], api_visibility="private")
        for control in (preset, fps, scale, output_dir):
            control.change(actions.summary, summary_inputs, estimate, api_visibility="private")
        refresh(go_export.click(lambda: gr.update(selected="export"), outputs=pages, api_visibility="private"))
        export_page.select(actions.summary, summary_inputs, estimate, api_visibility="private")
        back.click(lambda: gr.update(selected="editor"), outputs=pages, api_visibility="private")
        open_file.click(actions.open_output, state, task_status, api_name="open_output", api_visibility="private")
        open_folder.click(lambda p: actions.open_output(p, True), state, task_status, api_visibility="private")
        preferences = [output_dir, download_dir, preset, fps, scale, days]
        save_settings.click(actions.save_preferences, preferences + [acceleration], settings_status, api_name="save_settings")
        load_settings.click(actions.read_preferences, outputs=preferences + [settings_status], api_name="read_settings").then(
            lambda: settings.load()["acceleration"], outputs=acceleration, api_visibility="private")
        open_downloads.click(lambda: actions.open_saved_folder("download_dir"), outputs=settings_status, api_visibility="private")
        open_exports.click(lambda: actions.open_saved_folder("output_dir"), outputs=settings_status, api_visibility="private")
        clear_cache.click(actions.cleanup, outputs=settings_status, api_name="clean_cache")
        check_update.click(updates.check_update, outputs=update_status, api_name="check_update")
        diagnostic_button.click(diagnostics.report, outputs=diagnostic_text, api_name="diagnostics")
        reopen.click(lifecycle.reopen, outputs=settings_status, queue=False, api_visibility="private")
        exit_app.click(lifecycle.request_shutdown, outputs=settings_status, queue=False, api_name="exit_app")
    return demo
