# E 阶段 beta.2：独立审计问题修订

日期：2026-11-07。版本：1.2.0-beta.2。状态：开发完成，原生构建与发行包验证待执行。

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
