# B站视频下载处理工具

一个开箱即用的 B 站视频下载 + 处理工具，**全程网页操作，无需命令行**。

- 输入 B 站链接（支持 `b23.tv` 短链）即可下载视频
- 支持对视频做**整体或按片段**处理：去水印 / 消除声音 / 变速 / 裁剪画面
- 支持片段分割、拼接、删除
- 导出为 **mp4** 或 **gif**

---

## 一、快速安装（小白版）

### Windows
1. 安装 [Python 3.10+](https://www.python.org/downloads/)（安装时勾选 **Add to PATH**）
2. 双击运行 **`install.bat`**，等待依赖安装完成
3. 双击运行 **`start.bat`**，浏览器会自动打开操作页面

### Linux / macOS
```bash
bash install.sh   # 一键安装
bash start.sh     # 启动（自动打开浏览器）
```

> 工具自带 ffmpeg（通过 `imageio-ffmpeg`），**无需手动安装 ffmpeg**。

---

## 二、使用教程

### ① 下载视频
1. 打开页面后，粘贴 B 站视频链接（短链也可以），如：
   `https://b23.tv/7hLWYrn`
   > **可以直接粘贴别人发的分享文字**，如 `【你看这个古振兴他饿不饿-哔哩哔哩】 https://b23.tv/7hLWYrn`，工具会自动从 `http` 开始提取链接
2. 点击「解析视频」可先查看标题、时长、封面
3. 点击「下载视频（mp4）」，等待进度条完成
4. 下载好的视频自动保存到 `downloads/` 目录

### ② 处理导出
1. 上传本地视频，或点击「使用刚下载的视频」
2. 点击「读取视频信息」，会自动生成"整片"片段（起点 0 → 终点为总时长）
3. 在**片段表格**中编辑（一行 = 一个片段）：

   | 列 | 含义 |
   |---|---|
   | 起点 / 终点（秒） | 片段的时间范围，如 `0`~`10` 表示前 10 秒 |
   | 删除 | 勾选后该片段不进最终视频 |
   | 消音 | 勾选后该片段没有声音 |
   | 变速(x) | 播放速度，`2`=两倍速，`0.5`=慢放 |
   | 裁剪 X/Y/宽/高 | 裁剪画面区域（全为 0 表示不裁剪） |
   | 水印 X/Y/宽/高 | 去水印区域（填了宽高即启用，智能插值填补） |

   - **添加片段**：在「片段起点/终点」输入框填秒数，点「➕ 添加片段」即可（多个片段自动按顺序拼接）
   - **删除片段**：在对应行勾选「删除」
   - 常用按钮：「重置为整片」
4. **框选水印（不用记坐标）**：
   1. 点「🖱 提取画面，开始框选」，会显示视频中间一帧画面
   2. 拖动 **X / Y / 宽 / 高** 四个滑块，直到画面上的**红色框正好罩住水印**
   3. 点「✓ 把框选区域应用到表格」，坐标自动填入
5. 选择导出格式（mp4 / gif）、GIF 帧率与缩放比例
6. 点击「开始处理」，完成后可预览结果，文件保存在 `output/` 目录

### 示例：用测试链接走通全流程
```text
链接：https://b23.tv/7hLWYrn
操作：
  1. 下载视频
  2. 读取视频信息
  3. 加两行片段：0~15、15~29.8，第 2 行勾选删除
  4. 第 1 行：变速填 2，勾选消音
  5. 导出格式选 mp4，点击开始处理
```

---

## 三、常见问题

| 问题 | 解决 |
|---|---|
| 下载失败/网络错误 | 重新点一次下载；确保电脑能访问 B 站 |
| 提示找不到 ffmpeg | 执行 `pip install imageio-ffmpeg` 后重启 |
| 某些视频需要登录 | 暂不支持登录下载，属正常限制 |
| 导出 gif 太大 | 降低 GIF 帧率、减小缩放比例 |
| 处理时长较长 | 片段时间越短处理越快；处理进度条会实时显示 |

---

## 四、二次开发（模块化说明）

所有处理逻辑都在 `modules/` 目录，**界面层（main.py）只是调用者**，可以直接在 Python 中调用核心模块：

```python
from modules.pipeline import VideoPipeline
from modules.segmenter import Segment

# 0~10秒：1.5倍速 + 消音；10~20秒：去掉右下角水印
segments = [
    Segment(0, 10, speed=1.5, mute=True),
    Segment(10, 20, watermark={"x": 1700, "y": 900, "w": 180, "h": 60, "mode": "delogo"}),
]
pipe = VideoPipeline()
out = pipe.process("input.mp4", segments, out_format="mp4")
print(out)
```

| 模块 | 职责 |
|---|---|
| `modules/downloader.py` | 解析并下载 B 站视频（yt-dlp 封装） |
| `modules/segmenter.py` | 片段数据模型：时间范围 + 处理参数 |
| `modules/editor.py` | 单段处理滤镜：去水印 / 消音 / 变速 / 裁剪 |
| `modules/exporter.py` | 片段拼接 + 导出 mp4 / gif |
| `modules/ffmpeg_util.py` | ffmpeg 定位、执行、进度读取 |
| `modules/pipeline.py` | 处理管线总调度（入口） |

扩展思路：新增导出格式（如 webm）、AI 去水印模型、多 P 批量下载等，
只需在对应模块中增加函数并在 `pipeline.py` 中挂载。

---

## 五、项目结构

```
├── main.py               # 网页界面入口
├── install.sh/.bat       # 一键安装脚本
├── start.sh/.bat         # 一键启动脚本
├── requirements.txt      # 依赖清单
├── modules/              # 核心模块（可脱离界面单独使用）
│   ├── downloader.py
│   ├── segmenter.py
│   ├── editor.py
│   ├── exporter.py
│   ├── ffmpeg_util.py
│   └── pipeline.py
├── downloads/            # 下载的视频
└── output/               # 处理导出的视频
```
