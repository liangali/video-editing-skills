---
name: video-editing-skills
description:
  提供 vlog 剪辑工作流：使用 analyze_video.py (OpenVINO GenAI) 分析视频、
  生成分镜脚本（storyboard.json）并合成最终视频。
  当用户提供视频目录要求制作 vlog、生成分镜或剪辑脚本，或提及 vlog剪辑、视频剪辑脚本、
  video storyboard、editing script，或需要从 storyboard.json 渲染成片时使用。
---

# Vlog 分镜脚本生成器

AI 驱动的 vlog 剪辑工作流：视频分析 → 分镜脚本生成 → 最终视频合成。

---

## 快速参考

### 关键路径

| 组件 | 路径 | 说明 |
|------|------|------|
| **analyze_video.py** | `<SKILL_DIR>\scripts\analyze_video.py` | 视频分析脚本（替代 FLAMA） |
| **prepare_workspace.py** | `<SKILL_DIR>\scripts\prepare_workspace.py` | 工作区准备脚本 |
| **compose_video.py** | `<SKILL_DIR>\scripts\compose_video.py` | 视频合成脚本 |
| **VLM 模型** | `<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4` | OpenVINO VLM 模型 |
| **ffmpeg / ffprobe** | `<SKILL_DIR>\bin\ffmpeg.exe` | v8.0.1，compose_video.py 自动检测 |
| **BGM 目录** | `<SKILL_DIR>\resource\bgm\` | 含 BGM 文件 |
| **BGM 索引** | `<SKILL_DIR>\resource\bgm\bgm_style.json` | BGM 元数据 |
| **字体文件** | 自动检测系统字体 | Windows: 微软雅黑/黑体/宋体 |

**路径变量：**
- `<SKILL_DIR>` = **本 SKILL.md 文件所在目录**（AI 在运行时根据本文件路径自动解析）
- `<VIDEO_DIR>` = 用户提供的视频目录
- `<WORKSPACE_DIR>` = `<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS`

### 工作区输出结构

```
<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS\
├── user_input.txt                    # 用户原始请求
├── output_vlm.json                   # 视频分析结果
├── storyboard.json                   # 生成的分镜脚本
├── <THEME>_<DURATION>s_bgm_<LLM>.mp4 # 最终输出视频
└── temp\                             # 中间文件
    ├── clip_01_*.mp4
    ├── merged_no_bgm.mp4
    └── *.concat.txt
```

### 必需的分镜脚本字段

**`storyboard_metadata` 中必须包含：**
- `theme` - 视频主题/标题
- `target_duration_seconds` - 目标时长（如 30）
- `cloud_llm_name` - LLM 名称（如 "ClaudeOpus"）；别名：`llm_name`

**`audio_design.background_music` 中必须包含：**
- `file_path` - BGM 文件的**绝对路径**；别名：`bgm_file`、`selected_bgm`

**每个 `clips[]` 项目中必须包含：**
- `clip_id`、`sequence_order`、`source_video`
- `timecode.in_point`、`timecode.out_point`、`timecode.duration`
- `voiceover.text`（用于字幕）

### 命令模板

```bash
# 0. 平台检查
powershell -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\check_platform.ps1"

# 1. 准备工作区
python "<SKILL_DIR>\scripts\prepare_workspace.py" --video-dir <VIDEO_DIR> --user-request "<USER_REQUEST>" --check-ffmpeg

# 2. 视频分析（始终重新运行，绝不复用 output_vlm.json）
python "<SKILL_DIR>\scripts\analyze_video.py" --video-dir <VIDEO_DIR> --output <WORKSPACE_DIR>\output_vlm.json --model-dir "<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4" --prompt "<PROMPT>"

# 3. 生成 storyboard.json（AI 创作，通过 Write 工具写入）

# 4. 合成最终视频
python "<SKILL_DIR>\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

### 环境准备

**安装 Python 依赖：**
```bash
pip install -r "<SKILL_DIR>\requirements.txt"
```

依赖包括：opencv-python, numpy, Pillow, openvino, openvino-genai, huggingface_hub

**下载 ffmpeg 和资源：**
```bash
python "<SKILL_DIR>\scripts\setup_resources.py"
```

**下载 VLM 模型（约 4-6 GB）：**
```bash
python "<SKILL_DIR>\scripts\setup_ov_model.py"
```

默认使用 hf-mirror.com 镜像，海外直连加 `--no-mirror`，自定义镜像用 `--hf-mirror <URL>`。

---

## 工作流概览

```
阶段 0：平台检查      阶段 1：准备          阶段 2：分析                    阶段 3：创作          阶段 4：合成
┌─────────────────┐  ┌─────────────────┐     ┌─────────────────────────┐    ┌─────────────────┐     ┌─────────────────┐
│ 0.1 检测 CPU    │  │ 1.1 验证        │     │ 2.1 检查模型路径        │    │ 3.1 故事        │     │ 4.0 时长校验    │
│     平台代号    │  │     视频目录    │────►│ 2.2 运行                │───►│     大纲        │────►│ 4.1 运行        │
│ 0.2 检查集成    │  │ 1.2 创建        │     │     analyze_video.py    │    │ 3.2 选择片段    │     │     compose_    │
│     显卡        │─►│     工作区      │     │ 2.3 验证并解析输出      │    │ 3.3 旁白        │     │     video.py    │
│ 0.3 检查内存    │  │ 1.3 保存输入    │     └─────────────────────────┘    │ 3.4 BGM         │     │ 4.2 最终时长    │
│     > 16 GB     │  │ 1.4 提取需求    │                                   │ 3.5 输出 JSON   │     │     校验        │
│ [不满足则终止]  │  │ 1.5 检查 ffmpeg │                                   └─────────────────┘     └─────────────────┘
└─────────────────┘  └─────────────────┘
```

---

## 阶段 0：平台检查（必须最先执行，任一失败立即终止）

> **[AI 执行指令 — 最高优先级]**
> 本阶段是整个技能的**硬性前置门控**。
> - **必须**在执行任何其他步骤之前运行检查脚本。
> - **脚本退出码非 0 时，立即终止，禁止执行后续任何步骤。**

```powershell
powershell -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\check_platform.ps1"
```

**硬件要求（满足任一）：**

| 条件 | 要求 |
|------|------|
| **A** Intel 白名单独显 | Arc A770（16 GB）或 Arc B580（12 GB），CPU 不限 |
| **B** Intel iGPU 平台 | CPU 为 MTL/LNL/ARL/PTL + Intel iGPU + 系统内存 > 16 GB |

**Python：** >= 3.10（未安装时脚本自动安装 3.12.x）

| 脚本退出码 | AI 必须执行的动作 |
|-----------|------------------|
| **0** | 继续进入阶段 1 |
| **1** | **立即终止。将失败原因转述给用户，不执行任何后续步骤** |

**✅ 检查点 0→1：** 脚本退出码为 0 方可进入阶段 1。

---

## 阶段 1：准备

可使用 `prepare_workspace.py` 自动完成，或手动执行以下步骤。

### 步骤 1.1 验证视频目录

验证目录存在且包含视频文件（`.mp4`、`.mov`、`.avi`、`.mkv`、`.webm`、`.m4v`、`.wmv`），不验证子目录。

### 步骤 1.2 创建工作区

**每次任务都必须创建新的工作区文件夹，不得从已有工作区读取文件。**

```
<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS
```

### 步骤 1.3 保存用户输入

将用户原始请求写入 `<WORKSPACE_DIR>\user_input.txt`。

### 步骤 1.4 提取用户需求

将用户请求解析为以下要素：
- `target_duration_seconds`（默认：30）
- `theme`（如：节日喜庆、日常诗意）
- `mood`（如：轻松活泼、温暖治愈）
- `pacing`（如：连贯流畅、富有动感）
- `must_capture`（特定内容优先级）

### 步骤 1.5 检查 ffmpeg

确认 `<SKILL_DIR>\bin\ffmpeg.exe` 存在，不存在则运行 `setup_resources.py`。

**自动化命令：**
```bash
python "<SKILL_DIR>\scripts\prepare_workspace.py" --video-dir <VIDEO_DIR> --user-request "<用户请求>" --check-ffmpeg
```

**✅ 检查点 1→2：** 工作区已创建；视频文件存在；ffmpeg 已就绪。

---

## 阶段 2：分析

### 步骤 2.1 检查模型路径

确认 VLM 模型目录存在：`<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4`

**校验命令：**
```bash
python "<SKILL_DIR>\scripts\setup_ov_model.py" --check-only
```

若模型不存在，执行下载：
```bash
python "<SKILL_DIR>\scripts\setup_ov_model.py"
```

### 步骤 2.2 运行视频分析

**关键规则：** 始终重新运行，绝不复用已有的 output_vlm.json。

```bash
python "<SKILL_DIR>\scripts\analyze_video.py" --video-dir <VIDEO_DIR> --output <WORKSPACE_DIR>\output_vlm.json --model-dir "<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4" --prompt "<PROMPT>"
```

**analyze_video.py 参数参考：**

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--video-dir` | 是 | — | 输入视频目录路径 |
| `--output` | 是 | — | 输出 JSON 文件路径 |
| `--prompt` | 否 | 默认中文提示词 | VLM 分析提示词 |
| `--model-dir` | 否 | `<SKILL_DIR>/models/Qwen2.5-VL-7B-Instruct-int4` | 模型目录 |
| `--device` | 否 | `GPU` | `GPU` 或 `CPU` |
| `--seg-duration` | 否 | `3.0` | 段时长（秒） |
| `--frames-per-seg` | 否 | `4` | 每段提取帧数 |
| `--scale` | 否 | `0.25` | 帧缩放比例 |
| `--max-tokens` | 否 | `100` | VLM 最大生成 token 数 |

**提示词选择：**

| 条件 | 操作 |
|------|------|
| 用户指定了主题/氛围/节奏 | 使用需求驱动的提示词 |
| 无特定需求 | 使用默认提示词 |

**默认提示词：**
```
准确的描述这个视频片段中的主要内容，包括：场景环境、人物动作、画面构图、光线氛围、运镜方式。输出不超过100字的简要描述。
```

**需求驱动的提示词模板：**
```
请根据以下剪辑目标分析视频片段：主题是「<THEME>」，氛围是「<MOOD>」，节奏要求「<PACING>」。重点捕捉与「<MUST_CAPTURE>」相关的画面线索。描述中必须包含：场景环境、人物动作、画面构图、光线氛围、运镜方式，并突出与目标风格相关的信息。输出不超过100字。
```

### 步骤 2.3 验证并解析输出

验证 `<WORKSPACE_DIR>\output_vlm.json` 存在并读取内容。

**输出结构：**
```json
{
  "processed_videos": [{
    "input_video": "D:\\path\\video.mp4",
    "segments": [{
      "seg_id": 0,
      "seg_start": 0.0,
      "seg_end": 3.0,
      "seg_dur": 3.0,
      "seg_desc": "AI生成的内容描述..."
    }]
  }]
}
```

**✅ 检查点 2→3：** 模型已就绪；output_vlm.json 非空且含 segments 数据。

---

## 阶段 3：创作

### 步骤 3.1 故事大纲开发

#### 开场钩子策略（三选一）

| 策略 | 方法 | 适用场景 |
|------|------|----------|
| **视觉反差** | 以强烈视觉对比开场 | 风景、旅行、日常诗意 |
| **动作瞬间** | 以正在发生的动作中段切入 | 运动、节日、活泼欢快 |
| **悬念前置** | 先展示结果/高潮片段 | 叙事型、故事感强的 vlog |

#### 叙事弧线结构

| 段落 | 时长占比 | 目标 |
|------|----------|------|
| **开场钩子** | 5-10% | 3秒内抓住注意力 |
| **引入** | 10-15% | 建立场景与背景 |
| **递进** | 30-40% | 展开主要叙事 |
| **高潮** | 15-20% | 情感或视觉巅峰 |
| **收尾** | 10-15% | 回味与总结 |
| **结束** | 5-10% | 留下余韵 |

#### 片段选择质量评估优先级

1. **稳定性** — 无明显抖动
2. **光线** — 光线充足、曝光正确
3. **清晰度** — 对焦准确
4. **运镜** — 有意义的镜头运动
5. **独特性** — 不与其他已选片段重复

#### 镜头组接规则

- **景别交替**：远→中→近交替排列
- **动静交替**：运动镜头后接静态画面
- **方向一致**：相邻镜头中运动方向一致或有合理过渡

### 步骤 3.2 片段选择与排序

**时长指南：**
- 30秒 vlog → 约 10 个片段
- 60秒 vlog → 约 20 个片段
- 90秒 vlog → 约 30 个片段

**规则：**
- 绝不重复使用同一片段（source_video + seg_id 组合必须唯一）
- 绝不以静态/无聊的镜头开场
- 避免相似镜头连续出现
- 最短片段时长建议 ≥ 1.5 秒

### 步骤 3.3 旁白/字幕生成

- 每行最多 16 字符
- 每 3 秒片段最多 10-15 个字
- **补充情感，而非描述画面**
- 30-40% 的片段可不加字幕

| ❌ 描述画面（避免） | ✅ 补充情感（推荐） |
|---------------------|---------------------|
| 这是一个美丽的湖泊 | 三年了，终于又见到你 |
| 阳光照在树叶上 | 这一刻什么都不想 |
| 小猫在沙发上睡觉 | 全世界最治愈的存在 |

### 步骤 3.4 BGM 选择

**必需：必须选择恰好一首 BGM。始终使用绝对路径。**

| 视频氛围/风格 | 首选分类 | 备选分类 |
|---------------|----------|----------|
| 日常诗意、文艺清新 | 舒缓优美 | 温馨浪漫 |
| 温暖治愈、情感回忆 | 温馨浪漫 | 舒缓优美 |
| 中式古风、传统文化 | 民族古风 | 舒缓优美 |
| 轻松日常、休闲惬意 | 轻松愉悦 | 活泼欢快 |
| 感伤离别、深沉思考 | 低沉忧郁 | 舒缓优美 |
| 节日欢庆、活力动感 | 活泼欢快 | 轻松愉悦 |

**选择流程：**
1. 读取 `<SKILL_DIR>\resource\bgm\bgm_style.json`
2. 根据决策表匹配分类
3. 构建**绝对路径**：`<SKILL_DIR>\resource\bgm\` + JSON 中的 `file_path`

### 步骤 3.5 输出 storyboard.json

**关键规则：始终重新生成，绝不复用已有的 storyboard.json。**

写入路径：`<WORKSPACE_DIR>\storyboard.json`

**最小必需 Schema：**
```json
{
  "storyboard_metadata": {
    "theme": "视频主题",
    "target_duration_seconds": 30,
    "cloud_llm_name": "ClaudeOpus"
  },
  "clips": [{
    "clip_id": 1,
    "sequence_order": 1,
    "source_video": "D:\\path\\video.mp4",
    "source_segment_id": 0,
    "timecode": {
      "in_point": 0.0,
      "out_point": 3.0,
      "duration": 3.0
    },
    "voiceover": {
      "text": "字幕文本"
    }
  }],
  "audio_design": {
    "background_music": {
      "file_path": "D:\\absolute\\path\\to\\bgm.mp3",
      "style_tag": "舒缓优美",
      "summary": "BGM描述"
    }
  }
}
```

#### 写入前验证检查点

1. ☐ `theme`、`target_duration_seconds`、`cloud_llm_name` 三个必需字段均存在
2. ☐ 每个 clip 的 `out_point > in_point` 且 `duration > 0`
3. ☐ 所有 `source_video` 路径指向 `<VIDEO_DIR>` 中实际存在的文件
4. ☐ 无重复的 `(source_video, source_segment_id)` 组合
5. ☐ `audio_design.background_music.file_path` 是绝对路径且文件存在
6. ☐ 片段总时长偏差 ≤ target × 20%

**✅ 检查点 3→4：** storyboard.json 通过验证；BGM 路径有效。

---

## 阶段 4：合成

### 步骤 4.0 ffmpeg 执行前时长校验（硬性门控）

重新读取 storyboard.json，计算片段总时长偏差。**偏差 > target × 20% 时禁止执行 compose_video.py**。

```python
import json
with open("<WORKSPACE_DIR>/storyboard.json", encoding="utf-8") as f:
    sb = json.load(f)
target = sb["storyboard_metadata"]["target_duration_seconds"]
total_duration = sum(c["timecode"]["duration"] for c in sb["clips"])
deviation = abs(total_duration - target)
threshold = target * 0.20
print(f"target={target}s total={total_duration:.1f}s deviation={deviation:.1f}s threshold={threshold:.1f}s")
```

### 步骤 4.1 运行 compose_video.py

```bash
python "<SKILL_DIR>\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--storyboard` | — | storyboard.json 路径（必需） |
| `--font-size` | `40` | 字幕字号 |
| `--max-line-len` | `16` | 每行最大字符数 |
| `--dry-run` | — | 仅打印命令不执行 |

**输出命名：** `<theme>_<duration>s_bgm_<cloud_llm_name>.mp4`

### 步骤 4.2 最终时长校验（交付前必做）

用 ffprobe 测量实际视频时长。偏差 > target × 20% 时**禁止交付**，返回步骤 3.2 调整，最多重试 2 次。

---

## 硬性规则总结

| 规则 | 说明 |
|------|------|
| **平台检查必须最先执行** | 阶段 0 退出码非 0 则终止全部流程 |
| **每次新建工作区** | 禁止从已有 `editing_*` 工作区读取任何文件 |
| **模型不存在必须下载** | 运行 `setup_ov_model.py` 下载 |
| **始终重新分析** | 始终重新运行 analyze_video.py |
| **始终重新生成分镜** | 始终生成新的 storyboard.json |
| **禁止重复片段** | (source_video, source_segment_id) 组合必须唯一 |
| **必须选择 BGM** | 恰好一首 BGM，提供有效绝对路径 |
| **BGM 绝对路径** | file_path 必须是绝对路径 |
| **时长偏差 ≤ 20%** | 写入前、ffmpeg 执行前、交付前三次校验 |

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 模型目录不存在 | 模型未下载 | `python scripts/setup_ov_model.py` |
| 找不到 ffmpeg | 未部署 | `python scripts/setup_resources.py` |
| GPU 初始化失败 | 驱动/硬件问题 | 使用 `--device CPU` |
| output_vlm.json 为空 | 处理失败 | 检查控制台错误信息 |
| 片段数量不足 | 视频太短 | 合并多个视频或调整目标时长 |
| BGM 路径无效 | 路径格式错误 | 使用绝对路径 |
| 合成失败 | ffmpeg 命令错误 | `--dry-run` 检查命令 |

### LLM 常见错误预防

| 常见犯错模式 | 护栏规则 |
|-------------|----------|
| `out_point` ≤ `in_point` | 写入前检查每个 clip 的时间码 |
| `source_video` 路径使用正斜杠 | 始终使用反斜杠 `\\` |
| BGM `file_path` 使用相对路径 | 始终拼接为绝对路径 |
| 重复使用同一 segment | 写入前去重检查 (source_video, seg_id) |
| `cloud_llm_name` 字段缺失 | 始终填写 |
| 字幕文本过长 | 每 3 秒片段控制在 10-15 字 |
| 选择了不存在的 seg_id | 核对 output_vlm.json 中的实际 seg_id 范围 |

---

## 完整示例

**用户请求：**
```
D:\data\videoclips\phone2\007_input 文件夹中包含多个视频，生成一个30秒vlog，连贯流畅、富有动感
```

**执行过程：**

```bash
# 0. 平台检查
powershell -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\check_platform.ps1"

# 1. 准备工作区
python "<SKILL_DIR>\scripts\prepare_workspace.py" --video-dir "D:\data\videoclips\phone2\007_input" --user-request "生成一个30秒vlog，连贯流畅、富有动感" --check-ffmpeg

# 2. 视频分析
python "<SKILL_DIR>\scripts\analyze_video.py" --video-dir "D:\data\videoclips\phone2\007_input" --output "<WORKSPACE_DIR>\output_vlm.json" --prompt "请重点识别可形成连贯动作链的镜头、运动方向、速度变化与节奏点，描述环境、动作、构图、光线和运镜，突出流畅衔接与动感。输出不超过100字。"

# 3. 读取 output_vlm.json，生成 storyboard.json（通过 Write 工具）

# 4. 合成
python "<SKILL_DIR>\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

**最终输出：** `<WORKSPACE_DIR>\连贯动感_30s_bgm_ClaudeOpus.mp4`
