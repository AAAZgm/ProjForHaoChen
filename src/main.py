# -*- coding: utf-8 -*-
"""
B站视频下载处理工具 - 主程序（网页界面）
========================================
启动方式：
    python main.py        # 或执行 start.sh / start.bat

启动后会自动打开浏览器，页面包含两个功能页：
  ① 下载视频   —— 粘贴 B 站链接（支持短链）即可下载为 mp4
  ② 处理导出   —— 选择视频，按片段做 去水印/消音/变速/裁剪，
                  支持片段拼接/删除，导出为 mp4 或 gif

界面层只负责收集用户的输入并调用 modules 里的核心模块，
所有处理逻辑都在 modules 目录下，便于二次开发。
"""

import os
import re
import sys
import tempfile
from typing import List, Optional

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
from PIL import Image, ImageDraw

# 确保能以 "python main.py" 或 "python src/main.py" 方式运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules import downloader, ffmpeg_util, segmenter
from modules.editor import sanitize_watermark
from modules.pipeline import VideoPipeline

# ---------------------------------------------------------------------------
# 全局对象（下载器 / 处理管线 / 状态）
# ---------------------------------------------------------------------------
_downloader = downloader.BiliDownloader()
_pipeline = VideoPipeline()

# 当前刚下载的视频路径（供"带入处理页"使用）
_current_video_path: str = ""


def extract_url(text) -> str:
    """从一段文字中提取 http(s) 开头的链接。

    适用场景：别人发的分享是"标题 + 链接"混合的文字，例如：
      【你看这个古振兴他饿不饿-哔哩哔哩】 https://b23.tv/7hLWYrn
    会提取出：https://b23.tv/7hLWYrn

    截断规则：从 http 开始，到第一个空白字符 / 中文 / 中文标点为止；
    如果文字里没有 http，则原样返回（可能用户只粘贴了链接）。
    """
    if not text:
        return ""
    text = str(text).strip()
    # 找第一个 http:// 或 https:// 的位置
    m = re.search(r"https?://", text)
    if not m:
        return text
    url = text[m.start():]
    # 在空白、中文、中文/半角标点处截断（B站链接本身不含这些字符）
    cut = re.search(r"[\s，。；、！？（）【】〔〕,;!?()\u4e00-\u9fff]", url)
    if cut:
        url = url[:cut.start()]
    return url.strip()


# ---------------------------------------------------------------------------
# 片段表格 <-> Segment 对象 转换（界面表格是核心交互方式）
# ---------------------------------------------------------------------------
TABLE_HEADERS = [
    "起点(秒)", "终点(秒)", "删除", "消音", "变速(x)",
    "裁剪X", "裁剪Y", "裁剪宽", "裁剪高",
    "水印X", "水印Y", "水印宽", "水印高", "水印方式",
]
TABLE_DATATYPE = [
    "number", "number", "bool", "bool", "number",
    "number", "number", "number", "number",
    "number", "number", "number", "number", "str",
]


def _to_float(v, default=0.0) -> float:
    """把表格单元格安全地转成浮点数（空值/非法值给默认值）。"""
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _to_bool(v) -> bool:
    """把表格单元格安全地转成布尔值（兼容 True/'True'/1/勾选等）。"""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    return str(v).strip().lower() in ("true", "1", "yes", "是")


def _table_rows(table) -> List[list]:
    """把界面表格统一转成"行列表"格式。

    Gradio 表格可能以两种格式传入：
      - pandas DataFrame（默认）
      - 二维 list（设置了 type="array" 时）
    这里统一转成 list of list，避免 DataFrame 的"真值歧义"问题。
    """
    if table is None:
        return []
    # pandas DataFrame：取数值矩阵转成 list
    if hasattr(table, "values") and hasattr(table, "to_numpy"):
        try:
            return table.to_numpy().tolist()
        except Exception:
            pass
    if not isinstance(table, (list, tuple)):
        return []
    return list(table)


def segments_to_table(segments: List[segmenter.Segment]) -> List[List]:
    """Segment 列表 -> 表格行数据（界面表格行）。"""
    rows = []
    for seg in segments:
        crop = seg.crop or (0, 0, 0, 0)
        wm = seg.watermark or {}
        rows.append([
            round(seg.start, 3), round(seg.end, 3),
            seg.deleted, seg.mute, seg.speed,
            crop[0], crop[1], crop[2], crop[3],
            wm.get("x", 0), wm.get("y", 0), wm.get("w", 0), wm.get("h", 0),
            wm.get("mode", "delogo"),
        ])
    return rows


def table_to_segments(table) -> List[segmenter.Segment]:
    """表格行数据 -> Segment 列表（字段缺失/非法时使用默认值）。"""
    segments = []
    rows = _table_rows(table)
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        seg = segmenter.Segment(start=_to_float(row[0]), end=_to_float(row[1]))
        if len(row) > 2:
            seg.deleted = _to_bool(row[2])
        if len(row) > 3:
            seg.mute = _to_bool(row[3])
        if len(row) > 4:
            seg.speed = max(0.25, min(4.0, _to_float(row[4], 1.0) or 1.0))
        # 裁剪列 5~8
        if len(row) > 8:
            cw, ch = _to_float(row[7]), _to_float(row[8])
            if cw > 0 and ch > 0:
                seg.crop = (int(_to_float(row[5])), int(_to_float(row[6])),
                            int(cw), int(ch))
        # 水印列 9~13
        if len(row) > 13:
            ww, wh = _to_float(row[11]), _to_float(row[12])
            if ww > 0 and wh > 0:
                seg.watermark = {
                    "x": int(_to_float(row[9])),
                    "y": int(_to_float(row[10])),
                    "w": int(ww), "h": int(wh),
                    "mode": "delogo",
                }
        segments.append(seg)
    return segments


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
    global _current_video_path
    url = extract_url(url)   # 支持粘贴"标题+链接"混合文字，自动提取 http 链接
    if not url:
        return None, None, "请先粘贴 B 站视频链接"
    try:
        def cb(pct: float, msg: str):
            progress(pct / 100.0, desc=msg)
        path = _downloader.download(url, out_dir="downloads", on_progress=cb)
        _current_video_path = path
        return path, path, f"识别到链接：{url}\n下载成功！保存在：\n{path}\n（可到「② 处理导出」页使用）"
    except Exception as e:
        return None, None, f"下载失败：{e}"


def on_use_downloaded():
    """把刚下载的视频带入处理页。"""
    if _current_video_path and os.path.exists(_current_video_path):
        return gr.update(value=_current_video_path), f"已载入：{_current_video_path}"
    return gr.update(), "还没有下载过视频，请先到「① 下载视频」页下载"


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
# 可视化框选水印（提取画面 -> 拖动滑块让红框罩住水印 -> 应用到表格）
# ---------------------------------------------------------------------------
# 预览缓存：frame_path -> (缩略图, 原图宽/缩略图宽 比例因子)。拖动滑块时
# 直接复用缩略图画红框，避免每次重新读盘解码全分辨率帧（否则画面大时红框
# 拖动明显卡顿不灵敏）。
_WM_PREVIEW_MAX = 1000   # 预览缩略图最长边像素
_wm_thumb_cache: dict = {}


def _make_wm_thumb(frame_path: str):
    """读取帧并生成预览缩略图，返回 (缩略图, factor)。

    factor = 原图宽 / 缩略图宽，用于把滑块里的原始像素坐标换算到缩略图上。
    """
    img = Image.open(frame_path).convert("RGB")
    w, h = img.size
    scale = _WM_PREVIEW_MAX / max(w, h)
    if scale < 1.0:
        thumb = img.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    else:
        thumb = img
    return thumb, w / thumb.size[0]


def _wm_ui_outputs(video_path, preset):
    """提取中间帧并设置默认水印框，返回 UI 输出元组（state, 4个滑块, 预览, 提示）。

    preset：
      "right-bottom" 默认右下角（约占画面宽16%、高5%）
      "right-top"    一键右上角（宽30%、高15%）
    未选择视频 / 异常由调用方处理。
    """
    info = ffmpeg_util.get_video_info(video_path)
    w, h = info["width"], info["height"]
    if w <= 0 or h <= 0:
        raise RuntimeError("无法读取分辨率")

    if preset == "right-top":
        wm = sanitize_watermark({"x": w - int(w * 0.3), "y": 0,
                                 "w": int(w * 0.3), "h": int(h * 0.15),
                                 "mode": "delogo"}, w, h)
    else:
        wm = sanitize_watermark({"x": w - int(w * 0.16), "y": h - int(h * 0.05),
                                 "w": int(w * 0.16), "h": int(h * 0.05),
                                 "mode": "delogo"}, w, h)
    wm_x, wm_y, wm_w, wm_h = wm["x"], wm["y"], wm["w"], wm["h"]

    # 提取中间帧画面
    frame_path = os.path.join(tempfile.gettempdir(), "bili_wm_frame.png")
    ffmpeg_util.extract_frame(video_path, info["duration"] * 0.5, frame_path)
    # 解码一次并缓存缩略图，拖动滑块时不再读盘
    _wm_thumb_cache[frame_path] = _make_wm_thumb(frame_path)
    state = (frame_path, w, h)
    preview = _draw_wm_preview(state, wm_x, wm_y, wm_w, wm_h)
    return state, \
        gr.update(minimum=0, maximum=max(0, w - 1), value=wm_x), \
        gr.update(minimum=0, maximum=max(0, h - 1), value=wm_y), \
        gr.update(minimum=1, maximum=w, value=wm_w), \
        gr.update(minimum=1, maximum=h, value=wm_h), \
        preview, \
        f"已提取画面（分辨率 {w}×{h}）。\n拖动滑块，让**红色框正好罩住水印**，然后点「应用到表格」。"


def on_prepare_wm(video_path):
    """提取画面，默认把水印框放在右下角。"""
    if not video_path or not os.path.exists(video_path):
        return None, gr.update(), gr.update(), gr.update(), gr.update(), \
            gr.update(), "请先选择视频文件"
    try:
        return _wm_ui_outputs(video_path, "right-bottom")
    except Exception as e:
        return None, gr.update(), gr.update(), gr.update(), gr.update(), \
            gr.update(), f"提取画面失败：{e}"


def on_prepare_wm_corner(video_path):
    """提取画面，一键把水印框放到右上角（宽30%、高15%）。"""
    if not video_path or not os.path.exists(video_path):
        return None, gr.update(), gr.update(), gr.update(), gr.update(), \
            gr.update(), "请先选择视频文件"
    try:
        return _wm_ui_outputs(video_path, "right-top")
    except Exception as e:
        return None, gr.update(), gr.update(), gr.update(), gr.update(), \
            gr.update(), f"提取画面失败：{e}"


def on_wm_preview(state, x, y, w, h):
    """滑块变化时实时更新预览（红框随滑块移动）。"""
    if not state:
        return gr.update()
    return _draw_wm_preview(state, int(x), int(y), int(w), int(h))


def _draw_wm_preview(state, x, y, w, h):
    """在预览缩略图上画红色半透明框，返回 PIL 图片用于预览。"""
    frame_path, W, H = state
    thumb, factor = _wm_thumb_cache.get(frame_path, (None, 1.0))
    if thumb is None:
        thumb, factor = _make_wm_thumb(frame_path)
        _wm_thumb_cache[frame_path] = (thumb, factor)
    tw, th = thumb.size
    # 滑块给的原始像素坐标 -> 缩略图坐标
    tx, ty = x / factor, y / factor
    tx2, ty2 = min((x + w) / factor, tw), min((y + h) / factor, th)
    # 红框 + 半透明红色填充，便于看清区域
    overlay = Image.new("RGBA", thumb.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    if tx2 > tx and ty2 > ty:
        od.rectangle([int(tx), int(ty), int(tx2), int(ty2)],
                     fill=(255, 0, 0, 40), outline=(255, 0, 0, 255),
                     width=max(2, min(tw, th) // 200))
    return Image.alpha_composite(thumb.convert("RGBA"), overlay).convert("RGB")


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
    for seg in rows:
        seg.watermark = wm
    return segments_to_table(rows), \
        f"已把水印区域（X={wm['x']} Y={wm['y']} 宽={wm['w']} 高={wm['h']}）应用到全部 {len(rows)} 行片段"


def on_process(video_path, table, out_format, gif_fps, gif_scale,
               progress=gr.Progress()):
    """开始处理：按片段表执行 去水印/消音/变速/裁剪，导出 mp4 或 gif。"""
    if not video_path or not os.path.exists(video_path):
        return None, None, "请先选择视频文件"
    segments = table_to_segments(table)
    if not segments:
        return None, None, "片段表格为空，请先点击「读取视频信息」或手动填写片段"

    def cb(pct: float, msg: str):
        progress(pct / 100.0, desc=msg)

    try:
        out_path = _pipeline.process(
            input_path=video_path,
            segments=segments,
            out_format=out_format,
            out_dir="output",
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
    with gr.Blocks(title="B站视频下载处理工具") as demo:
        gr.Markdown(
            "# B站视频下载处理工具\n"
            "**① 下载视频 → ② 处理导出**，全程在浏览器中操作，无需命令行。"
        )

        with gr.Tabs():
            # ================= 页面①：下载 =================
            with gr.Tab("① 下载视频"):
                gr.Markdown(
                    "粘贴 B 站视频链接（支持短链，如 `https://b23.tv/7hLWYrn`）。\n"
                    "**直接粘贴别人发的分享文字也行**（如 `【视频标题-哔哩哔哩】 https://b23.tv/xxxx`），"
                    "会自动识别其中的 http 链接。"
                )
                with gr.Row():
                    url_box = gr.Textbox(
                        label="B站视频链接",
                        placeholder="https://b23.tv/xxxxxx",
                        scale=4,
                    )
                    parse_btn = gr.Button("解析视频", variant="secondary")
                info_md = gr.Markdown("等待解析…")
                with gr.Row():
                    thumb_img = gr.Image(label="封面", height=200, type="filepath")
                    with gr.Column():
                        title_box = gr.Textbox(label="标题", interactive=False)
                        uploader_box = gr.Textbox(label="UP主", interactive=False)
                        duration_box = gr.Number(label="时长（秒）", interactive=False)
                download_btn = gr.Button("⬇ 下载视频（mp4）", variant="primary")
                download_msg = gr.Markdown()
                dl_video = gr.Video(label="下载结果预览", interactive=False)
                video_state = gr.State("")   # 保存刚下载的视频路径

                parse_btn.click(on_parse_url, [url_box],
                                [title_box, duration_box, thumb_img, uploader_box, info_md])
                download_btn.click(on_download, [url_box],
                                   [dl_video, video_state, download_msg])

            # ================= 页面②：处理导出 =================
            with gr.Tab("② 处理导出"):
                gr.Markdown(
                    "### 1. 选择视频\n"
                    "上传本地视频，或点击「使用刚下载的视频」。"
                )
                with gr.Row():
                    src_video = gr.Video(label="待处理视频", sources=["upload"], scale=3)
                    with gr.Column(scale=1):
                        use_dl_btn = gr.Button("使用刚下载的视频")
                        load_info_btn = gr.Button("读取视频信息")
                        info_out = gr.Markdown("等待读取…")

                gr.Markdown(
                    "### 2. 片段与处理参数\n"
                    "表格中**一行 = 一个片段**，多行会**按顺序拼接成同一个视频**导出。\n"
                    "**添加片段**：① 点击表格下方的「＋ 添加行」按钮；② 或直接用下面的「添加片段」输入框。\n"
                    "**删除片段**：在对应行勾选「删除」列。\n"
                    "各列含义：\n"
                    "- **起点/终点**：片段时间范围（秒），如 `0`~`10` 表示前10秒\n"
                    "- **删除**：勾选后该片段不进入最终视频\n"
                    "- **消音**：勾选后该片段没有声音\n"
                    "- **变速**：播放速度倍数，如 `2` 表示2倍速，`0.5` 表示慢放\n"
                    "- **裁剪**：X/Y 为左上角坐标，宽/高为裁剪尺寸（0 表示不裁剪）\n"
                    "- **水印**：X/Y/W/H 为水印区域（填了宽高即启用，用智能插值填补）\n\n"
                    "> 提示：水印区域可以用下方的「🖱 提取画面，开始框选」在画面上框选。"
                )
                with gr.Row():
                    table = gr.Dataframe(
                        headers=TABLE_HEADERS,
                        datatype=TABLE_DATATYPE,
                        value=[[0, 0, False, False, 1.0, 0, 0, 0, 0,
                                0, 0, 0, 0, "delogo"]],
                        interactive=True,
                        row_count=3,          # 初始显示行数
                        type="array",         # 传给处理函数的直接是列表，避免 pandas 歧义
                        label="片段表（可编辑）",
                    )
                duration_state = gr.State(0.0)   # 保存视频时长（秒）
                with gr.Row():
                    seg_start = gr.Number(label="片段起点(秒)", value=0)
                    seg_end = gr.Number(label="片段终点(秒)", value=0)
                    with gr.Column():
                        add_seg_btn = gr.Button("➕ 添加片段(新片段起点要大于旧片段重点哦)", variant="secondary")
                        reset_btn = gr.Button("重置为整片")
                with gr.Row():
                    tbl_msg = gr.Markdown()

                gr.Markdown(
                    "### 去水印辅助：在画面上框选水印\n"
                    "**不用记坐标**：点「提取画面」→ 拖动 4 个滑块让**红色框正好罩住水印** → 点「应用到表格」。\n"
                    "**B 站水印常在右上角**：点「↗ 右上角水印」即可一键框选（宽30%、高15%），再微调。"
                )
                with gr.Row():
                    with gr.Column(scale=1):
                        prepare_wm_btn = gr.Button("🖱 提取画面，开始框选", variant="secondary")
                        wm_corner_btn = gr.Button("↗ 右上角水印（宽30% 高15%）", variant="secondary")
                        apply_wm_btn = gr.Button("✓ 把框选区域应用到表格", variant="secondary")
                        wm_helper_msg = gr.Markdown("尚未提取画面")
                        wm_x = gr.Slider(0, 1000, value=0, step=1, label="水印 X（左边界）")
                        wm_y = gr.Slider(0, 1000, value=0, step=1, label="水印 Y（上边界）")
                        wm_w = gr.Slider(1, 1000, value=100, step=1, label="水印 宽")
                        wm_h = gr.Slider(1, 1000, value=30, step=1, label="水印 高")
                    with gr.Column(scale=2):
                        wm_frame = gr.Image(label="画面预览（红色框=水印区域）", height=380,
                                            interactive=False)
                wm_state = gr.State(None)   # (画面文件路径, 视频宽, 视频高)

                gr.Markdown("### 3. 导出设置与开始")
                with gr.Row():
                    fmt_radio = gr.Radio(["mp4", "gif"], value="mp4", label="导出格式")
                    gif_fps = gr.Slider(5, 30, value=15, step=1, label="GIF 帧率")
                    gif_scale = gr.Slider(0.25, 1.0, value=0.5, step=0.05,
                                          label="GIF 缩放比例")
                process_btn = gr.Button("⚡ 开始处理", variant="primary")
                proc_msg = gr.Markdown()
                result_video = gr.Video(label="处理结果", interactive=False)

                # 事件绑定
                use_dl_btn.click(on_use_downloaded, None, [src_video, info_out])
                load_info_btn.click(on_load_video, [src_video],
                                    [table, duration_state, info_out])
                reset_btn.click(on_reset_table, [duration_state], [table, tbl_msg])
                add_seg_btn.click(on_add_segment, [seg_start, seg_end, table],
                                  [table, tbl_msg])
                # 可视化框选水印
                prepare_wm_btn.click(on_prepare_wm, [src_video],
                                     [wm_state, wm_x, wm_y, wm_w, wm_h,
                                      wm_frame, wm_helper_msg])
                wm_corner_btn.click(on_prepare_wm_corner, [src_video],
                                    [wm_state, wm_x, wm_y, wm_w, wm_h,
                                     wm_frame, wm_helper_msg])
                wm_x.input(on_wm_preview, [wm_state, wm_x, wm_y, wm_w, wm_h], [wm_frame])
                wm_y.input(on_wm_preview, [wm_state, wm_x, wm_y, wm_w, wm_h], [wm_frame])
                wm_w.input(on_wm_preview, [wm_state, wm_x, wm_y, wm_w, wm_h], [wm_frame])
                wm_h.input(on_wm_preview, [wm_state, wm_x, wm_y, wm_w, wm_h], [wm_frame])
                apply_wm_btn.click(on_apply_wm,
                                   [wm_state, wm_x, wm_y, wm_w, wm_h, table],
                                   [table, tbl_msg])
                process_btn.click(on_process, [src_video, table, fmt_radio, gif_fps, gif_scale],
                                  [result_video, proc_msg])

    return demo


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    demo = build_ui()
    # inbrowser=True：启动后自动打开浏览器
    demo.launch(inbrowser=True, theme=gr.themes.Soft())
