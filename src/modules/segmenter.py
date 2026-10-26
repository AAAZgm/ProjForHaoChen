# -*- coding: utf-8 -*-
"""
片段时间轴模块
==============
职责：
  1. 定义"片段"数据模型：一段视频 = 起点 + 终点 + 一系列处理参数
  2. 提供片段的校验、排序、默认整片生成等工具函数

片段支持的"处理"动作（可单独对每一段设置）：
  - deleted     删除该片段（拼接时跳过）
  - mute        消除声音
  - speed       变速（0.25x ~ 4.0x）
  - crop        裁剪画面 (x, y, w, h)
  - watermark   去水印区域 {x, y, w, h, mode}，mode 固定为 delogo
                    （用周围画面插值填补，效果自然）

二次开发提示：
  直接构造 Segment 列表即可编程使用，例如：
    seg = Segment(10, 20, speed=1.5, mute=True)
  片段列表可通过 Segment.to_dict / from_dict 与 JSON/表格互相转换，
  方便界面层（Gradio 表格）读写。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
@dataclass
class Segment:
    """一个处理片段：从 start 秒到 end 秒，附带该片段的处理参数。"""

    start: float                     # 起点（秒）
    end: float                       # 终点（秒）
    deleted: bool = False            # 是否删除（拼接时跳过该段）
    mute: bool = False               # 是否消除声音
    speed: float = 1.0               # 变速倍率（0.25 ~ 4.0）
    crop: Optional[Tuple[int, int, int, int]] = None  # 裁剪 (x, y, w, h)
    watermark: Optional[Dict] = None # 去水印区域，见模块顶部说明

    # ------------------------------------------------------------------
    def duration(self) -> float:
        """片段原始时长（秒）。"""
        return max(0.0, self.end - self.start)

    def output_duration(self) -> float:
        """处理后的时长（秒，变速会改变时长）。"""
        return self.duration() / self.speed if self.speed > 0 else 0.0

    # ------------------------------------------------------------------
    def to_dict(self) -> Dict:
        """转换为普通字典（便于界面表格/JSON 使用）。"""
        d = {
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "deleted": self.deleted,
            "mute": self.mute,
            "speed": self.speed,
            "crop_x": self.crop[0] if self.crop else 0,
            "crop_y": self.crop[1] if self.crop else 0,
            "crop_w": self.crop[2] if self.crop else 0,
            "crop_h": self.crop[3] if self.crop else 0,
            "wm_x": (self.watermark or {}).get("x", 0),
            "wm_y": (self.watermark or {}).get("y", 0),
            "wm_w": (self.watermark or {}).get("w", 0),
            "wm_h": (self.watermark or {}).get("h", 0),
            "wm_mode": (self.watermark or {}).get("mode", "delogo"),
        }
        return d

    # ------------------------------------------------------------------
    @staticmethod
    def from_dict(d: Dict) -> "Segment":
        """从字典构建 Segment（与 to_dict 互逆）。"""
        crop = None
        if d.get("crop_w", 0) > 0 and d.get("crop_h", 0) > 0:
            crop = (int(d.get("crop_x", 0)), int(d.get("crop_y", 0)),
                    int(d.get("crop_w", 0)), int(d.get("crop_h", 0)))
        watermark = None
        if d.get("wm_w", 0) > 0 and d.get("wm_h", 0) > 0:
            watermark = {
                "x": int(d.get("wm_x", 0)),
                "y": int(d.get("wm_y", 0)),
                "w": int(d.get("wm_w", 0)),
                "h": int(d.get("wm_h", 0)),
                "mode": d.get("wm_mode", "delogo"),
            }
        return Segment(
            start=float(d.get("start", 0)),
            end=float(d.get("end", 0)),
            deleted=bool(d.get("deleted", False)),
            mute=bool(d.get("mute", False)),
            speed=float(d.get("speed", 1.0) or 1.0),
            crop=crop,
            watermark=watermark,
        )


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
def make_full_segment(duration: float) -> List[Segment]:
    """生成默认"整片"片段：覆盖 [0, 总时长]，不做任何处理。"""
    return [Segment(start=0.0, end=max(0.0, duration))]


def sanitize_segments(segments: List[Segment], duration: float) -> List[Segment]:
    """清洗片段列表：
      1. 限制 start/end 在 [0, duration] 范围内
      2. 剔除空片段（start >= end）
      3. 按 start 排序
    """
    result = []
    for seg in segments:
        start = min(max(0.0, seg.start), duration)
        end = min(max(0.0, seg.end), duration)
        if end - start < 0.05:   # 不足 0.05 秒的片段视为无效
            continue
        seg.start, seg.end = start, end
        result.append(seg)
    result.sort(key=lambda s: s.start)
    return result


def validate_segments(segments: List[Segment]) -> List[str]:
    """校验片段参数，返回错误信息列表（空列表 = 全部合法）。"""
    errors = []
    for i, seg in enumerate(segments):
        label = f"片段{i + 1}({seg.start:.1f}s-{seg.end:.1f}s)"
        if seg.end <= seg.start:
            errors.append(f"{label}: 终点必须大于起点")
        if not 0.25 <= seg.speed <= 4.0:
            errors.append(f"{label}: 变速倍数需在 0.25~4.0 之间")
        if seg.crop:
            x, y, w, h = seg.crop
            if w <= 0 or h <= 0:
                errors.append(f"{label}: 裁剪宽高必须大于 0")
        if seg.watermark:
            if seg.watermark["w"] <= 0 or seg.watermark["h"] <= 0:
                errors.append(f"{label}: 水印区域宽高必须大于 0")
    return errors


def estimate_output_duration(segments: List[Segment]) -> float:
    """估算处理后视频的总时长（秒）= 各保留片段处理后的时长之和。"""
    return sum(seg.output_duration() for seg in segments if not seg.deleted)
