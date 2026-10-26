# ============================================================
# modules 包：B站视频下载处理工具的核心模块
#
# 模块结构（每个模块都可独立二次开发）：
#   ffmpeg_util.py  - ffmpeg 二进制定位、命令执行、时长/进度读取
#   downloader.py   - 解析并下载 B 站视频（基于 yt-dlp）
#   segmenter.py    - 片段时间轴模型（起点/终点 + 处理参数）
#   editor.py       - 单段视频处理：去水印 / 消音 / 变速 / 裁剪
#   exporter.py     - 片段拼接 + 导出 mp4 / gif
#   pipeline.py     - 处理管线编排（串联以上所有模块）
#
# 二次开发提示：这些模块不依赖网页界面，可直接在 Python 中调用，
# 例如：
#   from modules.pipeline import VideoPipeline
#   pipe = VideoPipeline()
#   pipe.process("input.mp4", segments=[...], out_format="mp4")
# ============================================================
