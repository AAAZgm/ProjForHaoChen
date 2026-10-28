# 源码使用与结构

普通用户请使用便携包，见 [使用说明](../docs/PORTABLE_README.md)。

## Windows 安装

安装 Python 3.10+（已验证 3.12），双击 `install.bat`。脚本创建本目录的 `.venv`、安装 `requirements.txt`，并通过根目录 `scripts/prepare_ffprobe.py` 下载校验 ffprobe。完成后双击 `start.bat`。所有启动均使用项目 `.venv`，不依赖个人 Conda 路径。

安装失败会停止并显示错误；如 `.venv` 不完整，关闭程序，将其改名备份后重新安装。首次源码安装需要联网；便携包首次运行不需要安装依赖。

Linux/macOS 需通过系统包管理器安装含 ffprobe 的 FFmpeg，再运行 `install.sh`、`start.sh`；尚未做这些平台的发布验收。

## 结构

- `main.py`：启动参数、实例管理、退出、自检、下载子进程入口。
- `ui.py`：导入、片段编辑、框选、导出和设置回调；`ui_layout.py`：工作台、导出与帮助页的布局和样式。
- `modules/workspace.py`：独立会话、片段顺序、历史。
- `modules/tasks.py`：队列、取消、子进程结束。
- `modules/pipeline.py`、`editor.py`、`exporter.py`：视频处理与导出。
- `modules/ffmpeg_util.py`：FFmpeg 执行、ffprobe JSON 媒体探测。
- `modules/encoding.py`：NVIDIA 编码探测与 CPU 回退策略；`web_runtime.py`：Windows 特定连接关闭异常的清理。
- `modules/runtime.py`、`settings.py`、`storage.py`：路径、偏好、缓存与文件保护。
- `modules/lifecycle.py`、`diagnostics.py`、`updates.py`：实例锁、日志、正式版本检查。

程序资源、用户配置、成品和临时文件各自定位，不依赖启动时的工作目录。`BILI_VIDEO_HOME` 指定默认下载/成品根目录，`BILI_CONFIG_HOME` 指定配置、日志和缓存目录；测试请设置独立目录。

## 验证与打包

在根目录使用项目解释器运行 `python -m unittest discover -s tests -v`。`scripts/build_portable.py` 会准备固定 ffprobe、运行回归、打包并验证解压后的 EXE；仅通过后生成最终 ZIP、校验值和报告。详见 [维护发布说明](../docs/RELEASING.md)。
