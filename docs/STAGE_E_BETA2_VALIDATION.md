# E 阶段 beta.2：独立审计问题修订

日期：2026-11-07。版本：1.2.0-beta.2。状态：审计修复完成，三个原生发行包的回归、最终解压验证和下载后独立校验全部通过；未公开发布。

## 本轮范围

依据用户提供的独立静态审计并自行复核：修复 macOS 旧系统启动提示缺失，以及 ffprobe 清单哈希与最终文件不符。最低支持范围仍为 macOS 15.0、Linux x64 的 Ubuntu 22.04 / glibc 2.35 基线。本轮不下调系统要求，不增加站点或新硬件编码。

Apple Silicon 包内 ffprobe 与 orjson 都要求 macOS 15，因此仅降低 ffprobe 编译目标无法承诺兼容旧系统。报告中的“界面一定能启动，导入时才失败”未经旧系统实测，不作为确认复现。

## 实现与检查

- `Start.command` 使用系统 `sw_vers`，在运行冻结二进制前拒绝低于 15 或无法确认的系统版本；交互终端保留提示到用户回车。
- 直接启动程序时，在 Gradio/orjson 等依赖导入前运行标准库版本检查；不提供环境变量绕过。
- PyInstaller 完成后写入最终 ffprobe 的 `binary_sha256`，保存 `sha256_before_freeze`。不修改已签名二进制，仅更新清单和说明。
- 最终归档解压后重新计算哈希；macOS 扫描全部 Mach-O，校验架构及最低系统要求不高于 15.0，将逐文件结果写入 verification.json 的 `package_audit`。
- 验证保留编辑、拼接、音频、方案恢复、取消及退出流程。Mac 自检经实际启动脚本进入，服务测试经直接可执行文件进入。

## 边界

模拟旧版本的拒绝启动测试不等于在旧 macOS 实机运行。当前 macOS 15 原生运行器验证不能替代 Finder/Gatekeeper 首次启动和桌面用户试用；仍为 ad-hoc 签名，无 Developer ID 签名/公证。

Linux 构建路径清理、macOS .app 与 Linux .desktop 的体验改进尚未开展。旧 beta.1 包及其历史记录保留，不覆盖旧产物。未公开发布或合并主分支。

## 本轮验证证据

- 源码提交：`638941a38825827f81924869af31692586856a34`。原生构建：[Actions 42382325936](https://github.com/AAAZgm/ProjForHaoChen/actions/runs/42382325936)。
- Windows 本机运行 103 项测试，100 项通过、3 项 POSIX 专属测试跳过；随后补充非 macOS Mach-O/非 64 位格式拒绝测试，重新执行全部 9 项审计用例，8 项通过、1 项 POSIX shell 测试跳过。
- Linux x64：完整 104 项测试中 100 项通过、4 项 Windows 专属用例跳过；冻结包与解压后的功能流程通过。
- macOS Apple Silicon：完整 104 项测试中 100 项通过、4 项 Windows 专属用例跳过；实际 Start.command 自检、直接程序服务流程、解压哈希及 151 个 Mach-O 检查全部通过。
- macOS Intel：完整 104 项测试中 100 项通过、4 项 Windows 专属用例跳过；实际 Start.command 自检、直接程序服务流程、解压哈希及 151 个 Mach-O 检查全部通过。
- 模拟 macOS 14.7、未知版本等场景确认启动脚本不运行程序，版本 15.0/26.1 保留参数正常执行；入口测试确认低版本在导入 Gradio/orjson 前退出。这些测试在原生 POSIX 任务执行，仍不等于在 macOS 14 实机运行。
- 下载后单独读取实际 tar.gz 内 ffprobe 和 source.json，核对交付文件哈希、GitHub artifact digest、整包字节数及 SHA256，保存原附件字节而不重新打包。接收记录在本地 `build/e-platform/*beta.2*-received.json`。

## 审计发现的处理结果

- macOS 15 是本轮明确保留的支持基线；旧系统提示缺失已修复。Apple Silicon 的 orjson 15.0 要求已纳入逐文件检查，不能通过仅修改 ffprobe 编译目标降低全包要求。
- ffprobe 清单区分 `sha256_before_freeze` 与最终 `binary_sha256`，解压后严格验证；旧 beta.1 中的清单不一致仍作为历史问题保留，不覆写旧包。
- 包内架构、最低系统版本及最终 ffprobe 哈希记录在各包旁的 verification.json → package_audit。

## 最终交付

所有文件位于仓库 `dist/`，每包另附 `.sha256` 和 `-verification.json`，旧 beta.1 不覆盖。运行器环境分别为 macOS 15.8.2 arm64、macOS 15.7.9 x64、Ubuntu 22.04 x64 / glibc 2.35。

| 包 | 字节数 | SHA256 |
| --- | ---: | --- |
| `bili-video-tool-1.2.0-beta.2-macos-arm64.tar.gz` | 112269773 | `0549ba1d3272194c3829298cc9aaf63a634a1ae2624daa42b04543bf44b1d15c` |
| `bili-video-tool-1.2.0-beta.2-macos-x64.tar.gz` | 120435984 | `4a7e0c2602629131cb81940d5e8b10452e72eacb18ea961398ef3c5cd0850bbc` |
| `bili-video-tool-1.2.0-beta.2-linux-x64.tar.gz` | 152089842 | `a65f6351dc6e3bd5e1edabaa4215cc411f887f3bab84b6082a9f8ddf6c0fac51` |

下载后从实际压缩包重新计算的 ffprobe SHA256，与 source.json / verification.json 均一致：

| 平台 | 最终 ffprobe SHA256 |
| --- | --- |
| macOS arm64 | `87f53d1ade7894eb49181c151aa0729196b0f3ee50684e3dc7e61616a29bb461` |
| macOS x64 | `070fe62959620c20eba47dd6efe1f1cc7db371fc9164a34aa422562c06c6426c` |
| Linux x64 | `8d520127946ec478aa015dbeea58325459c39e83b3d303d80663260d96275c8d` |

两个 Mac 包的 ffprobe 字节与 beta.1 相同；本次修复其校验清单，并未为修正元数据改写已签名二进制。三个包的编辑、MP4/GIF、混合拼接、音频、方案跨会话与重启恢复、取消后继续导出及退出清理验证仍全部通过。
