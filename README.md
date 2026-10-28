# 轻剪 · 视频下载与编辑

把本地视频或 B 站视频剪成需要的片段，再导出 MP4 / GIF。支持消音、倍速、裁剪、水印区域淡化、分割重排和撤销重做。

## Windows 便携版

当前候选：**1.0.0-rc.4**。本地交付包位于 `dist/bili-video-tool-1.0.0-rc.4-windows-x64.zip`。

rc.4 修复部分 Windows 启动环境中导出进程自动降档导致的性能差异；见 [rc.4 验证记录](docs/RC4_VALIDATION.md)。保留 rc.3 的 AV1 显卡解码、倍速处理优化和进度显示修正。

1. 解压整个 ZIP。
2. 双击 `BiliVideoTool.exe`。
3. 在剪辑工作台拖入视频，设置片段与效果，再到导出页保存成品。

无需安装 Python、FFmpeg、ffprobe 或 Git；本地编辑可离线使用。请保留 `_internal` 文件夹。目标平台为 Windows 10/11 x64，具体已验收环境见 [验证记录](docs/STAGE_C_VALIDATION.md)。

[完整使用说明](docs/PORTABLE_README.md) · [版本记录](CHANGELOG.md) · [GitHub 发布页](https://github.com/AAAZgm/ProjForHaoChen/releases)

候选版增加了保存位置与偏好记忆、文件打开、缓存管理、诊断日志、更新检查、重复启动处理和退出入口。rc.2 按首次试用反馈重排界面，增加 NVIDIA 编码与 CPU 回退，优化片段处理并处理特定 Windows 连接清理异常；[性能与验证记录](docs/RC2_VALIDATION.md) 列出实际效果与限制。当前 C 阶段开发与约定范围验收已完成：rc.4 自动验证通过，用户确认两台不同电脑均达到理想效果；更多新用户试用作为后续建议，不设固定人数门槛。源码仓库不包含构建产物；GitHub Actions 成功后可从运行的 Artifacts 下载，工作流不会自动公开发布。

## 从源码运行

Windows：安装 Python 3.10+（推荐已验证的 3.12），依次双击 `src/install.bat`、`src/start.bat`。安装脚本创建 `src/.venv`、安装锁定依赖，并下载及校验固定版本的 ffprobe。

Linux/macOS：自行安装包含 ffprobe 的 FFmpeg，再运行 `src/install.sh`、`src/start.sh`。目前仅提供 Windows 发行包；其他平台尚未验收。

## 开发与构建

在仓库根目录运行：

```powershell
src\.venv\Scripts\python.exe -m pip install -r src\requirements-build.txt
src\.venv\Scripts\python.exe scripts\prepare_ffprobe.py
src\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
src\.venv\Scripts\python.exe -X utf8 scripts\build_portable.py
```

或双击 `src/build.bat`。构建流程运行回归、打包、ZIP 解压验证，再生成 ZIP、SHA256 和 JSON 报告。解压验证覆盖本地服务、编辑导出、取消、保存设置、端口占用、重复启动、重启恢复和退出。

依赖锁定在 `src/requirements.txt` 和 `src/requirements-build.txt`；直接依赖见 `.in`。ffprobe 来源、版本及 SHA256 固定于 `scripts/prepare_ffprobe.py`，构建时校验，用户首次运行无需下载。

升级依赖后需重新验证。锁定文件维护命令：

```powershell
uv pip compile src\requirements.in --universal --python-version 3.10 -o src\requirements.txt
uv pip compile src\requirements-build.in --universal --python-version 3.10 -o src\requirements-build.txt
```

## 文档与许可

- [项目规划](PROJECT_PLAN.md)
- [A 阶段验证](docs/STAGE_A_VALIDATION.md) · [B 阶段验证](docs/STAGE_B_VALIDATION.md) · [C 阶段验证](docs/STAGE_C_VALIDATION.md)
- [用户实测记录](docs/USER_TRIALS.md) · [维护与发布步骤](docs/RELEASING.md)
- [源码结构与使用](src/README.md)

项目源码采用 [MIT](LICENSE) 许可证。FFmpeg、ffprobe 和其他依赖使用各自的许可证，随包保留声明、许可文本及来源信息，见 `THIRD_PARTY_NOTICES.txt`。
