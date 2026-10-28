# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

B站视频下载 + 处理工具:粘贴 B 站链接下载视频,再按"片段"做去水印 / 消音 / 变速 / 裁剪,导出为 mp4 或 gif。网页界面基于 Gradio,**所有处理逻辑都在 `modules/` 包中,不依赖 UI,可直接编程调用**。

## 常用命令

```bash
# 安装依赖(或双击 install.bat / bash install.sh,会创建 .venv)
pip install -r requirements.txt
python ../scripts/prepare_ffprobe.py

# 运行(启动后自动打开浏览器;或 start.bat / bash start.sh)
python main.py

# 在仓库根目录运行离线回归（使用项目虚拟环境）
python -m unittest discover -s tests -v

# 在仓库根目录测试、构建并验证便携 ZIP（或在 src 双击 build.bat）
python scripts/build_portable.py
```

- 打包配置在 `src/bili_video_tool.spec`；仓库根目录 `.github/workflows/build-exe.yml` 提供 Windows 构建。目录式便携 ZIP 位于根目录 `dist/`。
- 使用标准库 unittest。测试覆盖输入、UI 回调与真实 FFmpeg 生成/处理的素材；打包后还需验证解压产物的本地服务、上传、处理、下载。
- 运行和构建依赖分别锁定在 `requirements.txt`、`requirements-build.txt`；升级直接依赖时从 `.in` 重新解析并验证。
- ffmpeg 通过 `imageio-ffmpeg` 自带二进制,用户无需安装。
- ffprobe 8.1.2 通过 `scripts/prepare_ffprobe.py` 固定来源并校验 SHA256；随包放在 `_internal/vendor/ffprobe`，媒体信息只解析 JSON。

## 架构与数据流

### 分层

- **`main.py`** —— 命令行、便携包自检和下载子进程入口；保留早期回调兼容接口。
- **`ui.py`** —— 导入、编辑、导出回调；每个页面使用独立的 `gr.State(Workspace)`，高级表格保留固定 14 列。
- **`ui_layout.py`** —— 工作台、导出、设置三页布局及 CSS；不要用 Gradio 自身的 `panel` 等状态类名作为自定义样式类。
- **`modules/workspace.py`** —— 会话素材、片段选择、分割/重排、效果及最多 50 步撤销/重做；不会修改其他会话。
- **`modules/tasks.py`** —— 每会话取消令牌、单个重型任务执行槽及子进程终止。所有长任务须进入 `tasks.task()`；取消按钮通过非排队回调设置令牌。
- **`modules/download_job.py`** —— 下载在独立子进程中运行，取消时连同合并进程结束，独立临时目录自动清理。
- **`modules/pipeline.py`** —— 处理管线总入口 `VideoPipeline.process()`:清洗校验片段 → 计算统一分辨率 `_common_size()` → 逐段 `editor.render_segment()` 渲染中间文件 → `exporter` 拼接导出 → 清理临时文件。
- **`modules/segmenter.py`** —— `Segment` dataclass(数据模型)+ 校验/清洗工具函数。
- **`modules/editor.py`** —— 单段渲染,用 `build_filter_chain()` 生成 ffmpeg 滤镜串。
- **`modules/encoding.py`** —— 实际试编码检测 NVENC，UI 默认 auto，编程调用默认 cpu；显卡失败由管线全任务回退，取消不重试。
- **AV1 解码**：仅 NVENC 配合未旋转 8 位 yuv420p AV1 尝试 av1_cuvid。失败先整任务回退软件解码，若仍有 NVENC 错误再整任务回退 CPU 编码；不得把取消当作回退原因。
- **`modules/web_runtime.py`** —— 在实际服务循环安装窄范围异常处理器；仅完成 Windows Proactor 关闭连接时 WinError 10054 遗漏的清理，保留其他异常。
- **`modules/exporter.py`** —— `concat_videos()` 拼接、`export_mp4()`、`export_gif()`(palettegen/paletteuse 两遍法)。
- **`modules/ffmpeg_util.py`** —— ffmpeg 二进制定位、命令执行、视频信息读取。
- **`modules/process_performance.py`** —— 对本次 FFmpeg 子进程尽力请求 Windows HighQoS，保留非执行速度策略；API 不支持或权限不足只记录日志，不得阻断处理/清理。不得改全局电源、优先级类别或显卡设置。
- **`modules/downloader.py`** —— `BiliDownloader` 封装 yt-dlp。
- **`modules/settings.py`** —— 当前用户的原子 JSON 配置，损坏备份恢复；目录、导出预设、GIF 和缓存保留天数。
- **`modules/storage.py`** —— 独占创建防覆盖、文件名校验、剩余空间检查，以及只针对已退出运行目录的缓存清理。
- **`modules/lifecycle.py`** —— 用户配置级实例锁、已运行实例验证、可用端口与退出；不得通过猜测 PID 结束进程。
- **`modules/diagnostics.py` / `updates.py`** —— 有容量上限且隐藏凭据的日志、只读 GitHub 正式版本检查。

### 核心约定

- **片段数据模型**:`Segment(start, end, deleted, mute, speed, crop, watermark)`。crop 是 `(x, y, w, h)`,watermark 是 `{x, y, w, h, mode:"delogo"}`。通过 `to_dict()/from_dict()` 与表格/JSON 互转；`modules/table.py` 提供表格转换。片段校验保留输入顺序，不得再按起点排序。
- **画面坐标**：以 FFmpeg 自动旋转后的画面尺寸为准，浏览器框选传归一化坐标及素材 ID，由 Workspace 校验并换算。旧素材选区必须拒绝。
- **进度与清理**：管线统一映射各片段和导出阶段的进度；失败/取消时清理中间目录和本次半成品。成功输出命名避重，保留输入素材。
- **文件边界**：配置/日志/缓存位于用户目录；上传和预览位于本次运行的独立缓存，运行期间不能按时间直接删除。清理不得跟随 symlink/junction 或删除下载/成品。界面只允许访问实际生成的文件，不将整个自定义目录加入 Gradio 文件白名单。
- **进度回调统一签名**:`callback(percent: float, message: str)`,类型别名 `ProgressCallback`(定义在 `ffmpeg_util.py`)。UI 侧通过 `gr.Progress()` 绑定。
- **媒体处理命令走 `ffmpeg_util.run_ffmpeg()`**，进度靠 `-progress pipe:1` 解析 `out_time_us`；编码器检测是有 12 秒超时的独立小样例，不产生文件。
- **截取时间**：渲染在输入前使用准确 `-ss` 和有界 `-t`，滤镜使用相对 0 起点，避免每段解码整条源视频；测试须校验靠后片段首帧及变速时长。
- **帧筛选**：trim/setpts/倍速/fps 先于静态画面滤镜，避免缩放最终丢弃的帧。帧校验覆盖裁剪、水印、缩放的渲染像素一致性；新增涉及时间或帧历史的滤镜时须重新评估顺序。
- **导出状态**：UI 导出回调为生成器，先 yield 新任务状态，再 yield 最终 5 项结果；API 客户端取最后一项。进度仅绑定 task_status，避免每个成品组件重复展示。

### 拼接兼容性(改滤镜时必须遵守)

为了多片段 concat 不花屏/音画不同步,`editor.render_segment()` 会把每个片段**强制标准化**:

- 同一次任务统一 `libx264` 或 `h264_nvenc`，像素格式 `yuv420p`，帧率 `DEFAULT_FPS = 30`，音频 `aac 44100Hz` 双声道；禁止混用两种编码器的片段直接复制拼接
- 分辨率强制偶数(scale/pad 修正),并 `setsar=1` 统一像素宽高比
- **静音片段用 `anullsrc` 补静音音轨而不是去掉音轨**——保证所有片段都有音频流,concat 才能成功
- 变速音频用 `atempo` 链(单次只支持 0.5~2.0,超范围需串联)
- 有裁剪时 `pipeline._common_size()` 取第一个保留片段的裁剪尺寸作为统一输出分辨率,其余片段等比缩放 + 黑边补齐
- `normalized=True` 仅供管线自身标准片段使用，concat demuxer 复制视频流，清单用视频时长；AAC 合并时重新对齐并编码，补齐/裁去尾部到总视频时长。其他调用保留原 concat 滤镜路径。

### delogo 去水印限制

`delogo` 滤镜靠区域外侧像素做插值,区域四周必须留 `DELOGO_MARGIN = 2` 像素边距,**紧贴画面边缘会直接报错**。所有水印区域都要过 `editor.sanitize_watermark()` 修正(UI 框选时也用它)。

## 二次开发提示

- 编程方式调用:`from modules.pipeline import VideoPipeline; pipe.process("input.mp4", segments=[...], out_format="mp4")`。
- 扩展新导出格式、AI 去水印模型等:在对应模块加函数,并在 `pipeline.process()` 中挂载。
- 登录才能下载的视频:在 `BiliDownloader.download()` 给 yt-dlp 传 `cookiesfrombrowser`。
