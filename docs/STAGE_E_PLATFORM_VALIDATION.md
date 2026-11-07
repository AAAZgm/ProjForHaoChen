# E 阶段：macOS / Linux 发行包

日期：2026-11-07。候选版本：1.2.0-beta.1。状态：实施及验证中。

本轮仅开展用户指定的操作系统扩展；站点扩展与新增硬件编码不在本轮范围。

| 目标 | 原生构建环境 | 产物 | 当前验证 |
| --- | --- | --- | --- |
| macOS Apple Silicon | macos-15 / arm64 | macos-arm64.tar.gz | 待构建 |
| macOS Intel | macos-15-intel / x64 | macos-x64.tar.gz | 待构建 |
| Linux x64 | ubuntu-22.04 / x64 | linux-x64.tar.gz | 待构建 |

所有包在本系统内构建，包含 Python、imageio-ffmpeg 及原生 ffprobe。ffprobe 8.1.2 源码来自 FFmpeg 官方站点，SHA256 为 `464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c`；配置命令、二进制校验值和 LGPL 许可随包记录。

构建执行源码回归，然后从候选 tar.gz 解压到中文/空格目录，检查执行权限、内部链接、冻结运行环境、随包媒体工具、编辑/导出、下载子进程及取消、跨会话隔离、方案恢复和正常退出。成功后才生成最终命名的包与 SHA256/verification.json。

运行器 API 检查不代表桌面 GUI 验收、Gatekeeper 公证或全部发行版兼容。macOS 当前未提供 Developer ID 签名/公证；Linux 不支持 musl，最低兼容范围以实际构建依赖及记录为准。真实 B 站联网下载需与本地 HTTP 下载子进程检查区分。

用户素材、旧发行包及 Windows 已有验收保持不变。未公开发布新版本。
