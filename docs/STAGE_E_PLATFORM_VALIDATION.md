# E 阶段：macOS / Linux 发行包

日期：2026-11-07。候选版本：1.2.0-beta.1。状态：三个原生发行包已生成并通过自动化验证；桌面用户试用、Apple 签名/公证和公开发布尚未进行。

本轮仅开展用户指定的操作系统扩展；站点扩展与新增硬件编码不在本轮范围。

| 目标 | 原生构建环境 | 产物 | 当前验证 |
| --- | --- | --- | --- |
| macOS Apple Silicon | macOS 15.8.2 / arm64 | macos-arm64.tar.gz | 回归、冻结包及解压 API 流程通过 |
| macOS Intel | macOS 15.7.9 / x64 | macos-x64.tar.gz | 回归、冻结包及解压 API 流程通过 |
| Linux x64 | Ubuntu 22.04 / x64，glibc 2.35 | linux-x64.tar.gz | 回归、冻结包及解压 API 流程通过 |

## 构建证据

- 源码提交：`78384f397c674141444a3b2ca81a6d01170a1796`，分支 `stage-e/platform-packages`，基于已发布 D 阶段的 main。
- [原生构建运行 42358189222](https://github.com/AAAZgm/ProjForHaoChen/actions/runs/42358189222)：三个 job 全部成功。不是在 Windows 上交叉生成的包。
- 每个平台执行 95 项回归：91 项通过，4 项 Windows 专属测试跳过（3 项 Proactor 测试、1 项 Windows HighQoS 实测）。新增加的 Unix 进程组清理、无关进程保护、tar 执行权限与符号链接往返测试均实际执行并通过。
- Windows 本机原有 88 项回归通过；新增平台用例的本机可执行部分通过，2 项 POSIX 专属用例由原生运行器验证。首轮测试中的 home 目录 mock 问题已修正并复验；沙箱受限的首次测试不计为有效验证。
- 首轮 macOS 源码下载因连接/TLS 超时失败；补充逐一校验相同 SHA256 的官方地址及 MacPorts 备用镜像后，统一源码重新构建通过。首轮 Linux 包未作为最终交付包。

## 交付文件

文件位于仓库 `dist/`，每包另附 `.sha256` 和 `-verification.json`。下载时再次核对 GitHub artifact digest、压缩包 SHA256、字节数以及验证报告中的源码提交；未重新打包。

| 文件 | 字节数 | SHA256 |
| --- | ---: | --- |
| `bili-video-tool-1.2.0-beta.1-macos-arm64.tar.gz` | 112272246 | `60ef76a65cba9651a4ad6f75c90fa4c3b4f4d287982642a146cc69919ff7d047` |
| `bili-video-tool-1.2.0-beta.1-macos-x64.tar.gz` | 120434699 | `4632ce7f23210990f5057ea69ae9c83c2106e79eb3e33da842a06f3994606bbd` |
| `bili-video-tool-1.2.0-beta.1-linux-x64.tar.gz` | 152090983 | `498e840aef065cee0c11006fbeb58983111c25248181b76febee6b486d0827f0` |

本地下载与检查中间文件在忽略目录 `build/e-platform`；最终可用产物以上表及 `dist` 校验文件为准。

## 包内容与验证范围

所有包在本系统内构建，包含 Python、imageio-ffmpeg 及原生 ffprobe。ffprobe 8.1.2 源码来自 FFmpeg 官方站点，SHA256 为 `464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c`；配置命令、二进制校验值和 LGPL 许可随包记录。

构建执行源码回归，然后从候选 tar.gz 解压到中文/空格目录，检查执行权限、内部链接、冻结运行环境、随包媒体工具、编辑/导出、下载子进程及取消、跨会话隔离、方案恢复和正常退出。成功后才生成最终命名的包与 SHA256/verification.json。三个包都通过了 MP4/GIF、裁剪与水印预览、批量音频、混合素材拼接、退出时取消、重启恢复方案后导出等流程；没有可用 NVIDIA 编码器时自动使用 CPU。

运行器 API 检查不代表桌面 GUI 验收、Gatekeeper 公证或全部发行版兼容。macOS 当前未提供 Developer ID 签名/公证；没有实测 Finder 首次打开、默认浏览器及文件管理器的视觉交互。Linux 不支持 musl，未覆盖各发行版/桌面环境。未新增 Apple VideoToolbox 或 AMD/Intel 硬件编码。下载验证使用本地 HTTP 实际 yt-dlp 子进程及取消流程；没有在这三个平台复验真实 B 站联网下载，不将 D 阶段 Windows 实网验证直接计入新平台。

用户素材、旧发行包及 Windows 已有验收保持不变。未公开发布新版本。
