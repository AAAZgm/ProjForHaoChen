# -*- coding: utf-8 -*-
"""
B站视频下载模块
==============
职责：
  1. 解析用户输入的网址（支持 b23.tv 短链、完整视频页链接），
     返回视频标题、时长、封面等信息
  2. 下载视频（视频流 + 音频流自动合并为一个 mp4 文件），支持进度回调

实现方式：封装 yt-dlp 库。yt-dlp 会自动跟随 b23.tv 短链跳转到
真正的 B 站视频页。合并音视频需要 ffmpeg，这里自动复用
ffmpeg_util.get_ffmpeg_exe() 找到的二进制，无需用户额外安装。

二次开发提示：
  如需登录后才能下载的视频，可在 download() 中给 yt-dlp 传入
  cookiesfrombrowser 参数（参考 yt-dlp 文档）。
"""

import os
from typing import Callable, Dict, Optional

import yt_dlp

from . import ffmpeg_util

# 进度回调函数签名：callback(percent: float, message: str)
ProgressCallback = Optional[Callable[[float, str], None]]


# ---------------------------------------------------------------------------
# 核心下载类
# ---------------------------------------------------------------------------
class BiliDownloader:
    """B 站视频下载器（yt-dlp 封装）"""

    def __init__(self, ffmpeg_location: Optional[str] = None):
        # ffmpeg 路径：默认自动定位（imageio-ffmpeg 自带二进制）
        self.ffmpeg_location = ffmpeg_location or ffmpeg_util.get_ffmpeg_exe()

    # ------------------------------------------------------------------
    def _base_opts(self) -> Dict:
        """yt-dlp 公共配置项。"""
        return {
            # 合并视频+音频时使用的 ffmpeg
            "ffmpeg_location": self.ffmpeg_location,
            # 下载重试与网络相关
            "retries": 5,
            "socket_timeout": 30,
            # 出错时输出更详细日志
            "verbose": False,
            "noplaylist": True,          # 只处理当前视频，不处理整个合集
        }

    # ------------------------------------------------------------------
    def parse_url(self, url: str) -> Dict:
        """解析视频链接，不下载，只返回视频信息。

        返回示例：
          {
            "title":   "视频标题",
            "duration": 123.5,          # 时长（秒）
            "thumbnail": "https://...", # 封面图地址（可能为空）
            "uploader": "UP主名",
            "video_id": "BV1xxxx",
            "page":     1,              # 第几P
            "page_count": 1,            # 共几P
          }
        """
        opts = self._base_opts()
        opts.update({
            "skip_download": True,   # 只解析信息，不下载
            "quiet": True,
        })
        with yt_dlp.YoutubeDL(opts) as ydl:
            # extract_info 会跟随短链跳转并解析出视频信息
            info = ydl.extract_info(url, download=False)
            if info is None:
                raise RuntimeError("解析失败：无法获取视频信息")

            # 多P视频：info 会带 entries，这里取第 1P
            if info.get("_type") == "playlist" and info.get("entries"):
                entries = [e for e in info["entries"] if e]
                if not entries:
                    raise RuntimeError("解析失败：未找到视频分P")
                info = entries[0]

            return {
                "title": info.get("title", "未命名视频"),
                "duration": float(info.get("duration") or 0),
                "thumbnail": info.get("thumbnail") or "",
                "uploader": info.get("uploader") or "",
                "video_id": info.get("id") or "",
                "page": info.get("page") or 1,
                "page_count": info.get("n_entries") or 1,
            }

    # ------------------------------------------------------------------
    def download(
        self,
        url: str,
        out_dir: str = "downloads",
        on_progress: ProgressCallback = None,
        max_height: int = 0,
    ) -> str:
        """下载视频为 mp4，返回保存的文件路径。

        参数：
          url          视频链接（短链/完整链接均可）
          out_dir      保存目录（自动创建）
          on_progress  进度回调 callback(percent, message)
          max_height   限制最高画质高度（如 720），0 表示不限（默认最高画质）

        说明：下载进度和合并进度都会通过 on_progress 汇报，
        下载占 0~100%，自动合并音视频在最后再补报一次 100%。
        """
        os.makedirs(out_dir, exist_ok=True)

        # 格式选择：
        #   优先 mp4 视频流 + m4a 音频流（用 ffmpeg 合并成 mp4）
        #   若无法合并则退化为单文件
        if max_height and max_height > 0:
            video_fmt = f"bestvideo[ext=mp4][height<={max_height}]"
        else:
            video_fmt = "bestvideo[ext=mp4]"
        format_spec = f"{video_fmt}+bestaudio[ext=m4a]/best[ext=mp4]/best"

        opts = self._base_opts()
        opts.update({
            "format": format_spec,
            "merge_output_format": "mp4",          # 合并输出为 mp4
            "outtmpl": os.path.join(out_dir, "%(title)s [%(id)s].%(ext)s"),
            "progress_hooks": [self._make_hook(on_progress)],
            # 下载时也需要 ffmpeg（用于合并），已通过 _base_opts 传入
        })

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise RuntimeError("下载失败：无法获取视频信息")
            # 多P取第1P的文件路径
            if info.get("_type") == "playlist" and info.get("entries"):
                info = info["entries"][0]
            path = ydl.prepare_filename(info)
            if not os.path.exists(path):
                # 合并后扩展名可能是 mp4，prepare_filename 可能仍是 .fXXX
                # 兜底：在输出目录里找一个最晚修改的视频文件
                candidates = [
                    f for f in os.listdir(out_dir)
                    if f.lower().endswith(".mp4")
                ]
                candidates.sort(key=lambda f: os.path.getmtime(os.path.join(out_dir, f)))
                if candidates:
                    path = os.path.join(out_dir, candidates[-1])
                else:
                    raise RuntimeError("下载失败：找不到输出文件")
            if on_progress:
                on_progress(100.0, "下载完成")
            return path

    # ------------------------------------------------------------------
    @staticmethod
    def _make_hook(on_progress: ProgressCallback) -> Callable:
        """把 yt-dlp 的进度钩子转换为统一的 percent/message 回调。"""
        def hook(d: Dict):
            if on_progress is None:
                return
            status = d.get("status")
            if status == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                downloaded = d.get("downloaded_bytes") or 0
                if total > 0:
                    on_progress(downloaded / total * 100, "正在下载视频")
            elif status == "finished":
                on_progress(99.0, "下载完成，正在合并音视频…")
        return hook
