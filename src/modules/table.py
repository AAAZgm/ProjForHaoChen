"""Advanced table serialization shared by UI and compatibility callbacks."""
import math
from typing import List
from . import segmenter

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
        value = float(v)
        return value if math.isfinite(value) else default
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


