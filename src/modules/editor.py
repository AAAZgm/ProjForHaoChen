# -*- coding: utf-8 -*-
"""
视频处理引擎（单段处理）
======================
职责：
  把"一个片段 + 它的处理参数"渲染成一个标准化的中间视频文件，
  支持的处理：
    - 去水印（delogo 插值填补）
    - 消除声音
    - 变速（0.25x ~ 4x）
    - 裁剪画面
    - 分辨率/帧率/采样率标准化（保证后续拼接无参数冲突）

所有片段统一输出为：
  编码 H.264 + yuv420p，帧率 DEFAULT_FPS，
  音频 aac 44100Hz。没有音频的片段输出静音音轨（保证拼接一致）。

滤镜实现说明：
  所有滤镜（trim/delogo/crop/setpts 等）都是单输入单输出，
  统一走 ffmpeg 的简单滤镜图（-vf）。

二次开发提示：
  如果想把处理逻辑改成"AI 去水印"或"加滤镜"，只需替换
  build_filter_chain() 中生成的滤镜字符串。
"""

import os
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from . import ffmpeg_util
from .ffmpeg_util import ProgressCallback
from .segmenter import Segment

# 输出编码参数（统一，保证拼接兼容）
_AUDIO_ARGS = ["-c:a", "aac", "-b:a", "128k", "-ar", str(ffmpeg_util.DEFAULT_SAMPLE_RATE), "-ac", "2"]


# ---------------------------------------------------------------------------
# 滤镜生成
# ---------------------------------------------------------------------------
# delogo 滤镜要求水印区域四周至少留出 band 像素（默认1px）的插值带，
# 紧贴画面边缘会直接报错。统一留出安全边距。
DELOGO_MARGIN = 2


def sanitize_watermark(wm: Dict, width: int, height: int) -> Optional[Dict]:
    """把水印区域限制在画面内且不贴边，返回修正后的区域（无效则返回 None）。

    delogo 滤镜需要靠区域外侧的像素做插值，因此区域**四周**（上下左右）
    都必须留出 DELOGO_MARGIN 像素边距，紧贴任何一条边都会直接报错。
    原区域在角落时整体向内平移。
    """
    if not wm:
        return None
    x = max(0, min(int(wm["x"]), width - 1))
    y = max(0, min(int(wm["y"]), height - 1))
    w = max(1, min(int(wm["w"]), width - x))
    h = max(1, min(int(wm["h"]), height - y))
    # 四周让出边距（左/上边缘不够时整体向内平移）
    x = min(max(DELOGO_MARGIN, x), width - 1)
    y = min(max(DELOGO_MARGIN, y), height - 1)
    w = min(w, width - x - DELOGO_MARGIN)
    h = min(h, height - y - DELOGO_MARGIN)
    if w < 1 or h < 1:
        return None
    return {"x": x, "y": y, "w": w, "h": h, "mode": "delogo"}


def atempo_chain(rate: float) -> List[str]:
    """生成音频变速滤镜链。

    ffmpeg 的 atempo 只支持 0.5~2.0 倍，超出范围需要串联多个。
    例如 4x = atempo=2,atempo=2。
    """
    chain = []
    r = rate
    while r > 2.0:
        chain.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        chain.append("atempo=0.5")
        r /= 0.5
    chain.append(f"atempo={r:.6f}")
    return chain


def build_filter_chain(
    source_width: int,
    source_height: int,
    seg: Segment,
    common_size: Optional[Tuple[int, int]] = None,
) -> Tuple[str, str, bool]:
    """根据片段参数生成视频滤镜描述 + 音频滤镜链。

    参数：
      source_width / source_height  原视频分辨率
      seg                           片段（含处理参数）
      common_size                   统一输出分辨率 (W, H)（用于拼接对齐）；
                                    传 None 时使用裁剪后的分辨率

    返回：
      (video_graph, audio_filter, need_audio)
        video_graph   视频滤镜描述（简单滤镜图，单输入单输出）
        audio_filter  音频滤镜（无音频时为 ""）
        need_audio    是否需要音频输出（消音时为 False）

    时间裁剪后先变速并筛选输出帧，再处理画面，避免缩放最终会丢弃的帧。
    render_segment 在输入端定位，传入的片段时间已转换为相对起点。
    """
    # ---------- 基础滤镜阶段（按顺序排列） ----------
    stages: List[str] = []
    # 0. 时间裁剪（起点 -> 终点），重置时间戳从 0 开始
    stages.append(f"trim=start={seg.start:.3f}:end={seg.end:.3f},setpts=PTS-STARTPTS")
    if seg.speed and seg.speed != 1.0:
        stages.append(f"setpts=PTS/{seg.speed}")
    stages.append(f"fps={ffmpeg_util.DEFAULT_FPS}")

    # 1. 去水印（delogo 插值填补，区域自动避开画面边缘）
    if seg.watermark:
        wm = sanitize_watermark(seg.watermark, source_width, source_height)
        if wm:
            stages.append(f"delogo=x={wm['x']}:y={wm['y']}:w={wm['w']}:h={wm['h']}:show=0")

    # 2. 裁剪
    if seg.crop:
        x, y, w, h = seg.crop
        # 裁剪区域限制在画面内
        x = max(0, min(x, source_width - 1))
        y = max(0, min(y, source_height - 1))
        w = max(1, min(w, source_width - x))
        h = max(1, min(h, source_height - y))
        stages.append(f"crop={w}:{h}:{x}:{y}")

    # 4. 分辨率标准化：等比缩放 + 黑边补齐（不拉伸变形）
    if common_size:
        W, H = common_size
        stages.append(
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    elif seg.crop:
        # 仅裁剪时，宽高可能为奇数（libx264 要求偶数），修正
        stages.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")

    # 6. 像素宽高比统一为 1:1
    #    不同路径（scale/pad/crop）会产生不同的 SAR，导致 concat 拼接时报
    #    "Error reinitializing filters"。统一 setsar=1 保证拼接不失败。
    stages.append("setsar=1")

    # 组装视频滤镜图（简单滤镜图：逗号连接，单输入单输出）
    video_graph = ",".join(stages)

    # ---------- 音频滤镜 ----------
    need_audio = not seg.mute
    audio_filter = ""
    if need_audio:
        parts = [f"atrim=start={seg.start:.3f}:end={seg.end:.3f}",
                 "asetpts=PTS-STARTPTS"]
        if seg.speed and seg.speed != 1.0:
            parts += atempo_chain(seg.speed)   # 音频变速
        parts.append(f"aresample={ffmpeg_util.DEFAULT_SAMPLE_RATE}")
        audio_filter = ",".join(parts)

    return video_graph, audio_filter, need_audio


# ---------------------------------------------------------------------------
# 片段渲染
# ---------------------------------------------------------------------------
def render_segment(
    input_path: str,
    seg: Segment,
    out_path: str,
    common_size: Optional[Tuple[int, int]] = None,
    on_progress: ProgressCallback = None,
    seg_index: int = 0,
    seg_total: int = 1,
    crf: int = 20,
    encoder: str = "cpu",
    source_info: Optional[Dict] = None,
    decoder: str = "cpu",
) -> str:
    """把一个片段渲染为标准化中间视频文件。

    参数：
      input_path  原视频路径
      seg         片段（含处理参数）
      out_path    中间文件输出路径（.mp4）
      common_size 统一输出分辨率 (W, H)，保证拼接兼容
      on_progress 进度回调
      seg_index/seg_total  当前是第几段（用于进度消息）

    返回：out_path
    """
    # 读取原视频信息（分辨率等）
    from . import encoding, tasks
    info = source_info or ffmpeg_util.get_video_info(input_path)
    # Input accurate seeking skips unused prefixes; a bounded input also avoids
    # decoding the entire remaining video after the selected interval.
    relative_segment = replace(seg, start=0, end=seg.duration())
    video_graph, audio_filter, need_audio = build_filter_chain(
        info["width"], info["height"], relative_segment, common_size
    )

    # 音频处理：本片段"最终无声音"的情况有两种：
    #   1. 用户勾选了"消除声音"
    #   2. 原视频本身没有音频流
    # 统一处理方式：给该片段补一条"静音音轨"（而不是完全去掉音频流），
    # 这样后续 concat 拼接时所有片段都有音频流，不会因参数不一致而失败。
    effective_mute = seg.mute or not info["has_audio"]

    # 构建命令（视频输入永远是 input 0）
    args = ["-ss", f"{seg.start:.6f}", "-t", f"{seg.duration():.6f}", "-i", str(input_path)]
    if decoder == "av1_cuvid":
        args = ["-hwaccel", "cuda", "-c:v", "av1_cuvid"] + args
    if effective_mute:
        # 追加静音音频源（时长 = 片段处理后时长），音频输入为 input 1
        silence_dur = seg.duration() / seg.speed
        args += ["-f", "lavfi", "-t", f"{silence_dur:.3f}",
                 "-i", "anullsrc=r=44100:cl=stereo"]

    # 视频滤镜：简单滤镜图（单输入单输出）
    args += ["-vf", video_graph]

    # 音频流映射与滤镜
    if effective_mute:
        # 显式 -map 会关闭自动映射，必须同时把视频流(0:v)和静音音轨(1:a)都映射出来
        args += ["-map", "0:V:0", "-map", "1:a:0"]
    elif audio_filter:
        # 音频滤镜（含 atrim 时间裁剪 / atempo 变速 / aresample 采样率统一）
        args += ["-map", "0:V:0", "-map", "0:a:0", "-af", audio_filter]

    # 统一编码参数
    video_args = encoding.video_args(encoder, crf)
    args += video_args + _AUDIO_ARGS + [str(out_path)]

    total = seg.output_duration()
    msg = f"{encoding.label(encoder, decoder)} · 片段 {seg_index + 1}/{seg_total}"
    try:
        ffmpeg_util.run_ffmpeg(args, total_duration=total, on_progress=on_progress, extra_message=msg)
    except tasks.Cancelled:
        raise
    except RuntimeError as error:
        if decoder != "cpu":
            raise encoding.HardwareDecodingError(str(error)) from error
        if encoder == "nvenc":
            raise encoding.HardwareEncodingError(str(error)) from error
        raise
    return out_path
