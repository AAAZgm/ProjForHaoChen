# -*- coding: utf-8 -*-
"""
B站视频下载处理工具 - 主程序（网页界面）
========================================
启动方式：
    python main.py        # 或执行 start.sh / start.bat

启动后自动打开浏览器。ui.py 提供导入、编辑与导出的一体化界面；
此文件保留命令行入口与早期回调兼容接口。

界面层只负责收集用户的输入并调用 modules 里的核心模块，
所有处理逻辑都在 modules 目录下，便于二次开发。
"""

import argparse
import json
import multiprocessing
import os
import sys

# Keep the local interface usable without analytics/network access.
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

# 有系统代理（如 Clash 127.0.0.1:7890）的电脑上，Gradio 启动时会自检
# localhost 的 startup-events 端点；该请求被代理接管会返回 502 导致启动失败。
# 把 localhost 加入 no_proxy 强制走直连（合并保留用户已有的 no_proxy）。
_NO_PROXY = "localhost,127.0.0.1,::1"
if os.environ.get("NO_PROXY"):
    os.environ["NO_PROXY"] = _NO_PROXY + "," + os.environ["NO_PROXY"]
else:
    os.environ["NO_PROXY"] = _NO_PROXY
if os.environ.get("no_proxy"):
    os.environ["no_proxy"] = _NO_PROXY + "," + os.environ["no_proxy"]
else:
    os.environ["no_proxy"] = _NO_PROXY

# Windows 中文系统默认用 GBK 解码控制台/子进程输出，遇到 UTF-8 内容会报
# UnicodeDecodeError。这里把标准输出/错误统一改为 UTF-8（需配合启动脚本
# 中的 PYTHONUTF8=1 一起使用，后者对 yt-dlp 内部的 subprocess 生效）。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Windows 下若未通过 start.bat 启动（未设置 PYTHONUTF8），提示用户，
# 否则 yt-dlp 合并音视频时子进程输出会因 GBK 解码崩溃。
if os.name == "nt" and not sys.flags.utf8_mode:
    print("提示：请用 start.bat 启动本工具（已自动开启 UTF-8 模式），"
          "直接运行 python main.py 可能导致下载合并时报错。")

import gradio as gr

# 确保能以 "python main.py" 或 "python src/main.py" 方式运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules import downloader, ffmpeg_util, segmenter, runtime
from modules.editor import sanitize_watermark
from modules.pipeline import VideoPipeline

# ---------------------------------------------------------------------------
# 早期无状态回调的兼容对象；新界面状态由 ui.py 每个会话独立维护。
# ---------------------------------------------------------------------------
_downloader = downloader.BiliDownloader()
_pipeline = VideoPipeline()

from modules.links import extract_url


# ---------------------------------------------------------------------------
# 片段表格 <-> Segment 对象 转换（界面表格是核心交互方式）
# ---------------------------------------------------------------------------
from modules.table import (TABLE_HEADERS, TABLE_DATATYPE, segments_to_table, table_to_segments, _table_rows)


# ---------------------------------------------------------------------------
# 页面 ①：下载
# ---------------------------------------------------------------------------
def on_parse_url(url: str):
    """点击"解析视频"：返回视频标题、时长、封面等信息。"""
    url = extract_url(url)   # 支持粘贴"标题+链接"混合文字，自动提取 http 链接
    if not url:
        return "", 0, None, "", "请先粘贴 B 站视频链接"
    try:
        info = _downloader.parse_url(url)
        msg = (f"识别到链接：{url}\n\n视频：《{info['title']}》\nUP主：{info['uploader']}\n"
               f"时长：{info['duration']:.1f} 秒")
        return info["title"], info["duration"], info["thumbnail"], info["uploader"], msg
    except Exception as e:
        return "", 0, None, "", f"解析失败：{e}"


def on_download(url: str, progress=gr.Progress()):
    """点击"下载视频"：下载到 downloads/ 目录并返回路径。"""
    url = extract_url(url)   # 支持粘贴"标题+链接"混合文字，自动提取 http 链接
    if not url:
        return None, None, "请先粘贴 B 站视频链接"
    try:
        def cb(pct: float, msg: str):
            progress(pct / 100.0, desc=msg)
        path = _downloader.download(url, out_dir=str(runtime.data_dir() / "downloads"),
                                    on_progress=cb)
        return path, path, f"识别到链接：{url}\n下载成功！保存在：\n{path}\n（可到「② 处理导出」页使用）"
    except Exception as e:
        return None, None, f"下载失败：{e}"


# ---------------------------------------------------------------------------
# 页面 ②：处理与导出
# ---------------------------------------------------------------------------
def on_load_video(video_path):
    """读取视频时长并生成默认"整片"片段表格。"""
    if not video_path or not os.path.exists(video_path):
        return None, 0, "请先选择视频文件"
    try:
        info = ffmpeg_util.get_video_info(video_path)
        segs = segmenter.make_full_segment(info["duration"])
        rows = segments_to_table(segs)
        return rows, info["duration"], (
            f"视频时长 {info['duration']:.1f} 秒，"
            f"分辨率 {info['width']}×{info['height']}（宽×高，"
            f"水印/裁剪坐标都以这个像素坐标系为准），共 {len(rows)} 行片段"
        )
    except Exception as e:
        return None, 0, f"读取失败：{e}"


def on_reset_table(duration):
    """重置片段表格为整片。"""
    segs = segmenter.make_full_segment(float(duration or 0))
    return segments_to_table(segs), "已重置为整片（起点0 → 终点为视频时长）"


def on_add_segment(start, end, table):
    """在片段表格末尾新增一行片段。"""
    start, end = float(start or 0), float(end or 0)
    if end <= start:
        return gr.update(), "片段终点必须大于起点，未添加"
    rows = _table_rows(table)
    # 新片段：默认不做任何处理（变速1倍、不裁剪、不消音）
    rows.append([round(start, 3), round(end, 3), False, False, 1.0,
                 0, 0, 0, 0, 0, 0, 0, 0, "delogo"])
    return rows, f"已添加片段 {start:.1f}s ~ {end:.1f}s（共 {len(rows)} 行）"


# ---------------------------------------------------------------------------
def on_apply_wm(state, x, y, w, h, table):
    """把框选的水印区域应用到片段表格的所有行。"""
    if not state:
        return gr.update(), "请先点「提取画面，开始框选」"
    rows = table_to_segments(table)
    if not rows:
        return gr.update(), "片段表格为空，请先读取视频信息"
    _, W, H = state
    # delogo 模式要求避开画面边缘，这里钳制后把最终值填进表格
    wm = sanitize_watermark({"x": int(x), "y": int(y), "w": int(w), "h": int(h),
                             "mode": "delogo"}, W, H)
    if wm is None:
        return gr.update(), "水印区域过小或超出可处理范围，请调整选区"
    for seg in rows:
        seg.watermark = wm
    return segments_to_table(rows), \
        f"已把水印区域（X={wm['x']} Y={wm['y']} 宽={wm['w']} 高={wm['h']}）应用到全部 {len(rows)} 行片段"


def on_process(video_path, table, out_format, gif_fps, gif_scale,
               progress=gr.Progress()):
    """开始处理：按片段表执行 去水印/消音/变速/裁剪，导出 mp4 或 gif。"""
    if not video_path or not os.path.exists(video_path):
        return None, "请先选择视频文件"
    segments = table_to_segments(table)
    if not segments:
        return None, "片段表格为空，请先点击「读取视频信息」或手动填写片段"

    def cb(pct: float, msg: str):
        progress(pct / 100.0, desc=msg)

    try:
        out_path = _pipeline.process(
            input_path=video_path,
            segments=segments,
            out_format=out_format,
            out_dir=str(runtime.data_dir() / "output"),
            gif_fps=int(gif_fps),
            gif_scale=float(gif_scale),
            on_progress=cb,
        )
        return out_path, f"处理完成！文件保存在：\n{out_path}"
    except Exception as e:
        return None, f"处理失败：{e}"


# ---------------------------------------------------------------------------
# 组装 Gradio 界面
# ---------------------------------------------------------------------------
def build_ui():
    from ui import build_ui as build_editor
    return build_editor()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def entrypoint():
    if len(sys.argv) == 3 and sys.argv[1] == "--download-worker":
        from modules.download_job import worker
        worker(sys.argv[2])
        return
    parser = argparse.ArgumentParser(description="B站视频下载处理工具")
    parser.add_argument("--version", action="version", version=runtime.APP_VERSION)
    parser.add_argument("--no-browser", action="store_true", help="启动时不自动打开浏览器")
    parser.add_argument("--port", type=int, default=None, help="指定本地服务端口")
    parser.add_argument("--data-dir", help="指定下载与导出的保存目录")
    parser.add_argument("--self-test", metavar="DIRECTORY", help="离线生成测试视频并验证 MP4 导出")
    args = parser.parse_args()
    if args.data_dir:
        os.environ["BILI_VIDEO_HOME"] = os.path.abspath(args.data_dir)
    from modules import diagnostics, settings, storage, lifecycle, tasks, web_runtime
    # Each launch owns an isolated cache; configuration/logs stay outside resources.
    os.environ["GRADIO_TEMP_DIR"] = str(runtime.session_cache() / "gradio")
    if args.self_test:
        demo = build_ui()
        from modules.selfcheck import run_self_check
        report = run_self_check(args.self_test)
        report["ui_components"] = len(demo.blocks)
        report_path = os.path.join(report["directory"], "report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        storage.clean_current_run()
        return
    instance = lifecycle.Instance()
    if not instance.acquire():
        url = instance.existing_url()
        print(f"程序已在运行：{url}", flush=True)
        if not args.no_browser:
            import webbrowser
            webbrowser.open(url)
        return
    demo = None
    try:
        diagnostics.setup()
        options = settings.load()
        storage.clean_cache(options["cache_days"])
        demo = build_ui()
        port = lifecycle.available_port(args.port or 7860)
        print(f"成品保存位置：{options['output_dir']}\n配置与日志：{runtime.config_dir()}", flush=True)
        app, url, _ = demo.launch(
            inbrowser=False, server_name="127.0.0.1", server_port=port,
            prevent_thread_lock=True, allowed_paths=[],
            app_kwargs={"lifespan": web_runtime.lifespan}, footer_links=[],
            css=__import__("ui_layout").CSS,
            theme=gr.themes.Soft(primary_hue="teal", neutral_hue="slate", font=["system-ui", "sans-serif"],
                                 font_mono=["ui-monospace", "monospace"]),
        )
        @app.get("/bili-health")
        def health():
            return {"nonce": instance.nonce, "version": runtime.APP_VERSION}
        instance.publish(url)
        print(f"页面地址：{url}\n关闭浏览器后，可再次双击程序重开页面。退出请点击“设置与帮助 → 退出程序”。", flush=True)
        if not args.no_browser:
            lifecycle.reopen()
        lifecycle.shutdown.wait()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        diagnostics.error("startup", error)
        print(tasks.friendly_error(error), flush=True)
        raise
    finally:
        import time
        tasks.cancel_all()
        # Cancellation terminates child processes and removes partial results.
        while tasks.any_busy():
            time.sleep(.1)
        if demo is not None:
            demo.close()
        storage.clean_current_run()
        instance.close()
        diagnostics.LOG.info("Application stopped")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    entrypoint()
