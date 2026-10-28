# 维护与发布

## 构建候选

1. 在 `src/modules/runtime.py` 更新版本，同步 `CHANGELOG.md`、根 README 和随包使用说明。
2. 使用锁定的 `requirements-build.txt`，执行 `scripts/build_portable.py`。构建会下载并校验固定 ffprobe；离线重复构建可复用 `.cache/ffprobe` 中已校验归档。
3. 仅使用成功生成的 ZIP、同名 `.sha256`、`-verification.json`；失败的 `.candidate.zip` 不能发布。
4. 将最终 ZIP 复制到独立 Windows 普通用户环境完成离线、在线和文件管理验收；记录 OS/架构、版本、校验值。清理 PATH 的本机测试不能替代干净系统实测。
5. 记录用户实际试用并修复阻断项，填写 `USER_TRIALS.md`。2026-10-28 用户确认两台不同电脑均达到理想效果，C 阶段按此完成当前范围验收；原三名新用户人数要求改为扩大覆盖的建议，不设固定人数门槛。

## 公开发布

当前工作流只上传 Actions 构建附件，不自动创建 GitHub Release。维护者确认验收通过后再创建版本标签和 Release：候选使用 prerelease，正式版去掉 rc 标记并重新构建验证。

发布附件包含 ZIP、SHA256、验证报告；说明包含解压双击步骤、系统支持范围、截图、版本变化、已知限制和许可证入口。不要把测试配置、日志、下载素材或用户文件放进压缩包。

检查更新读取本仓库最新正式 Release；未发布或仅有 prerelease 时，不应提示已有正式版。候选包可直接交付试用，无需先公开发布。

## 依赖来源与许可

- Python、Gradio、yt-dlp、Pillow、imageio-ffmpeg 等按锁定环境构建，版本和许可写入 `THIRD_PARTY_NOTICES.txt`，依赖许可保留在 `_internal` 元数据中。
- FFmpeg 7.1 来自 imageio-ffmpeg 0.6.0 的 Windows 二进制；构建信息以包内 `THIRD_PARTY_NOTICES.txt` 的 `ffmpeg -L` 输出及 [imageio 构建仓库](https://github.com/imageio/imageio-ffmpeg) 为准。
- ffprobe 8.1.2 来自 [Gyan Windows 构建](https://www.gyan.dev/ffmpeg/builds/)，归档 SHA256 固定为 `db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec`。随包保留供应方 GPL v3 文本、构建配置、源代码提交链接及校验记录。
- 项目源码 MIT 许可不替换依赖许可证。公开分发时应一并提供所选依赖要求的许可和对应源码获取信息。

yt-dlp 更新后先验证真实 B 站下载（完整链接、短链、分享文字、带分 P 参数链接），再重新打包；本地 HTTP 下载测试仅验证任务流程，不能替代站点兼容性验收。
