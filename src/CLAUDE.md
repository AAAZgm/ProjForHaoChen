# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

B站视频下载 + 处理工具:粘贴 B 站链接下载视频,再按"片段"做去水印 / 消音 / 变速 / 裁剪,导出为 mp4 或 gif。网页界面基于 Gradio,**所有处理逻辑都在 `modules/` 包中,不依赖 UI,可直接编程调用**。

## 常用命令

```bash
# 安装依赖(或双击 install.bat / bash install.sh,会创建 .venv)
pip install -r requirements.txt

# 运行(启动后自动打开浏览器;或 start.bat / bash start.sh)
python main.py

# 打包为单文件可执行程序(Windows: build.bat;Linux/macOS: bash build.sh)
python -m PyInstaller --noconfirm bili_video_tool.spec
```

- 打包配置在 `bili_video_tool.spec`;`.github/workflows/build-exe.yml` 提供 GitHub Actions 云端构建 Windows exe(手动触发或打 `v*` tag)。
- 无测试框架、无 lint 配置。验证方式就是跑 `python main.py` 走通下载→处理流程。
- ffmpeg 通过 `imageio-ffmpeg` 自带二进制,用户无需安装。

## 架构与数据流

### 分层

- **`main.py`** —— 纯 UI 层,只负责收集输入并调用 modules。片段的交互载体是 Gradio 表格(固定 14 列,见 `TABLE_HEADERS`)。
- **`modules/pipeline.py`** —— 处理管线总入口 `VideoPipeline.process()`:清洗校验片段 → 计算统一分辨率 `_common_size()` → 逐段 `editor.render_segment()` 渲染中间文件 → `exporter` 拼接导出 → 清理临时文件。
- **`modules/segmenter.py`** —— `Segment` dataclass(数据模型)+ 校验/清洗工具函数。
- **`modules/editor.py`** —— 单段渲染,用 `build_filter_chain()` 生成 ffmpeg 滤镜串。
- **`modules/exporter.py`** —— `concat_videos()` 拼接、`export_mp4()`、`export_gif()`(palettegen/paletteuse 两遍法)。
- **`modules/ffmpeg_util.py`** —— ffmpeg 二进制定位、命令执行、视频信息读取。
- **`modules/downloader.py`** —— `BiliDownloader` 封装 yt-dlp。

### 核心约定

- **片段数据模型**:`Segment(start, end, deleted, mute, speed, crop, watermark)`。crop 是 `(x, y, w, h)`,watermark 是 `{x, y, w, h, mode:"delogo"}`。通过 `to_dict()/from_dict()` 与表格/JSON 互转;`main.py` 里有对应的 `segments_to_table()/table_to_segments()`。
- **进度回调统一签名**:`callback(percent: float, message: str)`,类型别名 `ProgressCallback`(定义在 `ffmpeg_util.py`)。UI 侧通过 `gr.Progress()` 绑定。
- **所有 ffmpeg 命令都走 `ffmpeg_util.run_ffmpeg()`**(而不是直接 subprocess),进度靠 `-progress pipe:1` 解析 `out_time_us`。新增导出格式照 `export_mp4` 模式写即可。

### 拼接兼容性(改滤镜时必须遵守)

为了多片段 concat 不花屏/音画不同步,`editor.render_segment()` 会把每个片段**强制标准化**:

- 编码统一 `libx264 + yuv420p`,帧率 `DEFAULT_FPS = 30`,音频 `aac 44100Hz`
- 分辨率强制偶数(scale/pad 修正),并 `setsar=1` 统一像素宽高比
- **静音片段用 `anullsrc` 补静音音轨而不是去掉音轨**——保证所有片段都有音频流,concat 才能成功
- 变速音频用 `atempo` 链(单次只支持 0.5~2.0,超范围需串联)
- 有裁剪时 `pipeline._common_size()` 取第一个保留片段的裁剪尺寸作为统一输出分辨率,其余片段等比缩放 + 黑边补齐

### delogo 去水印限制

`delogo` 滤镜靠区域外侧像素做插值,区域四周必须留 `DELOGO_MARGIN = 2` 像素边距,**紧贴画面边缘会直接报错**。所有水印区域都要过 `editor.sanitize_watermark()` 修正(UI 框选时也用它)。

## 二次开发提示

- 编程方式调用:`from modules.pipeline import VideoPipeline; pipe.process("input.mp4", segments=[...], out_format="mp4")`。
- 扩展新导出格式、AI 去水印模型等:在对应模块加函数,并在 `pipeline.process()` 中挂载。
- 登录才能下载的视频:在 `BiliDownloader.download()` 给 yt-dlp 传 `cookiesfrombrowser`。
