---
name: video-editing-skills
description:
  提供 vlog 剪辑工作流：使用 FLAMA 分析视频、生成分镜脚本（storyboard.json）并合成最终视频。
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
| **FLAMA** | `%FLAMA_PATH%` 或下方默认路径 | 可通过环境变量配置 |
| FLAMA 默认路径 | `<SKILL_DIR>\bin\flama\flama.exe` | 由 setup_resources.py 部署；环境变量未设置时的回退路径 |
| **ffmpeg.exe** | `<SKILL_DIR>\bin\ffmpeg.exe` | v8.0.1，compose_video.py 自动检测 |
| **ffprobe.exe** | `<SKILL_DIR>\bin\ffprobe.exe` | v8.0.1，用于媒体信息探测 |
| **compose_video.py** | `<SKILL_DIR>\scripts\compose_video.py` | 相对于本技能目录 |
| **BGM 目录** | `<SKILL_DIR>\resource\bgm\` | 包含 56 个 BGM 文件 |
| **BGM 索引** | `<SKILL_DIR>\resource\bgm\bgm_style.json` | BGM 元数据 |
| **字体文件** | `<SKILL_DIR>\resource\font.ttf` | 字幕字体 |

**路径变量：**
- `<SKILL_DIR>` = `E:\data\agentkit\skills\video-editing-skills`
- `<VIDEO_DIR>` = 用户提供的视频目录
- `<WORKSPACE_DIR>` = `<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS`


### 工作区输出结构

```
<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS\
├── user_input.txt                    # 用户原始请求
├── output_vlm.json                   # FLAMA 分析结果
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
# 0a. 检查 ffmpeg（必做）：若 <SKILL_DIR>\bin\ffmpeg.exe 不存在，先运行：
#     python "<SKILL_DIR>\scripts\setup_resources.py"
# 0b. 检查模型路径（必做）：读取 config 的 genai.model_path，若目录不存在则**必须**执行模型下载，不得跳过：
#     (1) 在 <SKILL_DIR> 创建/激活虚拟环境；(2) pip install huggingface_hub；
#     (3) python "<SKILL_DIR>\scripts\setup_ov_model.py" --flama-dir "<FLAMA_DIR>" [--hf-mirror]
#     禁止在模型不存在时直接运行 FLAMA 或使用 ffprobe/其他方式绕过分析。

# 1. 验证 FLAMA 是否存在
dir "<SKILL_DIR>\bin\flama\flama.exe"

# 2. 运行 FLAMA 分析（始终重新运行，绝不复用 output_vlm.json）
cd /d "<SKILL_DIR>\bin\flama"
flama.exe --video_dir=<VIDEO_DIR> --mode=hw --json_file=<WORKSPACE_DIR>\output_vlm.json --prompt="<PROMPT>"
# 可选参数：--debug=1（输出调试日志）、--mode=sw（GPU 失败时回退为软件解码）

# 3. 合成最终视频
python "<SKILL_DIR>\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
# 可选参数：--ffmpeg <PATH>、--dry-run、--font-size 40、--max-line-len 16
```

### 环境准备（Python 与虚拟环境）

- **仅使用剪辑与合成**（compose_video.py、setup_resources.py）：使用系统 Python 或项目已有虚拟环境即可。
- **需要下载模型**（setup_ov_model.py）：**建议使用独立虚拟环境**，仅需安装 `huggingface_hub`。

**创建并激活虚拟环境**（在 `<SKILL_DIR>` 或项目根目录执行）：

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate
python.exe -m pip install --upgrade pip

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

**安装模型下载依赖**（仅当需要运行 setup_ov_model.py 时执行，只下载预转换好的 OpenVINO 模型）：

```bash
pip install huggingface_hub
```

之后在该虚拟环境下执行模型下载（国内推荐加 `--hf-mirror`）：

```bash
python scripts/setup_ov_model.py --hf-mirror
```

---

## 工作流概览

```
阶段 0：平台检查      阶段 1：准备          阶段 2：分析                    阶段 3：创作          阶段 4：合成
┌─────────────────┐  ┌─────────────────┐     ┌─────────────────────────┐    ┌─────────────────┐     ┌─────────────────┐
│ 0.1 检测 CPU    │  │ 1.1 验证        │     │ 2.1 查找 FLAMA          │    │ 3.1 故事        │     │ 4.1 运行        │
│     平台代号    │  │     视频目录    │────►│ 2.2 检查 config 模型路径 │───►│     大纲        │────►│     compose_    │
│ 0.2 检查集成    │  │ 1.2 创建        │     │     （不存在→setup_ov_  │    │ 3.2 选择片段    │     │     video.py    │
│     显卡        │─►│     工作区      │     │      model.py）         │    │ 3.3 旁白        │     └─────────────────┘
│ 0.3 检查内存    │  │ 1.3 保存输入    │     │ 2.3 运行 FLAMA          │    │ 3.4 BGM         │
│     > 16 GB     │  │ 1.4 提取需求    │     │ 2.4 验证并解析输出      │    │ 3.5 输出 JSON   │
│ [不满足则终止]  │  │ 1.5 检查 ffmpeg │     └─────────────────────────┘    └─────────────────┘
└─────────────────┘  └─────────────────┘
```

---

## 阶段 0：平台检查（必须最先执行，任一失败立即终止）

> **[AI 执行指令 — 最高优先级]**
> 本阶段是整个技能的**硬性前置门控（Hard Gate）**。
> - **必须**在执行任何其他步骤之前运行检查脚本。
> - **脚本退出码非 0（exit 1）时，立即终止，禁止执行阶段 1 至阶段 4 的任何步骤。**
> - **禁止**跳过检查、假设检查通过、或在未执行脚本的情况下继续。
> - 只有脚本以退出码 0 结束，才能进入阶段 1。

本技能需满足以下**硬件条件之一** + **Python 3.12.x**，检查脚本会自动完成所有验证和安装：

**硬件（满足任一）：**

| | 条件 | 要求 |
|-|------|------|
| **A** | Intel 白名单独显 | Arc A770（16 GB）或 Arc B580（12 GB），CPU 型号不限 |
| **B** | Intel iGPU 平台 | CPU 为 MTL/LNL/ARL/PTL + Intel iGPU + 系统内存 > 16 GB |

**Python：** >= 3.10（未安装时脚本自动安装 3.12.x 最新版）

### 步骤 0：运行环境检查脚本

```powershell
powershell -ExecutionPolicy Bypass -File "E:\data\agentkit\skills\video-editing-skills\scripts\check_platform.ps1"
```

**脚本执行的两个阶段：**

| 阶段 | 内容 | 失败行为 |
|------|------|----------|
| **阶段 1：硬件** | 检测独显白名单 / iGPU 平台 | 立即 exit 1，不继续 |
| **阶段 2：Python** | 检测 Python 3.12.x；未找到则自动安装（winget → 官方安装包） | 安装失败则 exit 1 |

### 结果判断规则（AI 必须严格遵守）

| 脚本退出码 | 输出特征 | AI 必须执行的动作 |
|-----------|---------|------------------|
| **0** | 末行含"所有检查通过" | 继续进入阶段 1 |
| **1** | 含 `❌ [FAIL]` | **立即终止。将失败原因原文转述给用户，不执行任何后续步骤，不询问是否继续** |
| 脚本报错/无法运行 | 任何异常 | **视为检查失败，立即终止** |

**[AI 行为约束]** 退出码为 1 时：
1. 将脚本输出的 `❌ [FAIL]` 行原文转述给用户
2. **不输出任何后续步骤，不询问是否继续，直接终止本次技能执行**

> **自定义配置：** 编辑 `scripts\check_platform.ps1` 顶部的 `$DGPU_WHITELIST`（扩展独显白名单）或 `$PYTHON_FALLBACK_VERSION`（指定离线安装的 Python 版本）。

**✅ 检查点 0→1（硬性门控）：** 脚本退出码为 0 时方可进入阶段 1；退出码为 1 则技能执行到此为止。

---

## 阶段 1：准备

### 步骤 1.1 验证视频目录

验证目录存在且包含视频文件（`.mp4`、`.mov`、`.avi`、`.mkv`、`.webm`、`.m4v`、`.wmv`），不要验证子目录下的文件。

```bash
dir "<VIDEO_DIR>\*.mp4" "<VIDEO_DIR>\*.mov" "<VIDEO_DIR>\*.avi" "<VIDEO_DIR>\*.mkv"
```

### 步骤 1.2 创建工作区

**每次任务都必须创建新的工作区文件夹，不得从已有工作区读取文件。**

- 使用**当前时间**生成新的时间戳，创建新目录：`<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS`
- **禁止**复用或读取同目录下已有文件夹（如 `editing_20260304_160522` 等）中的 `output_vlm.json`、`storyboard.json` 等文件；每次从阶段 1 开始，在本轮新建的工作区内完成分析、分镜与合成。

创建带时间戳的工作区文件夹：
```
<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS
```

所有输出均存放在此工作区中。

### 步骤 1.3 保存用户输入

将用户原始请求写入 `<WORKSPACE_DIR>\user_input.txt`。

### 步骤 1.4 提取用户需求

将用户请求解析为以下要素：
- `target_duration_seconds`（默认：30）
- `theme`（如：节日喜庆、日常诗意）
- `mood`（如：轻松活泼、温暖治愈）
- `pacing`（如：连贯流畅、富有动感）
- `must_capture`（特定内容优先级）

这些需求将驱动 FLAMA 提示词生成和分镜脚本创作。

### 步骤 1.5 检查 ffmpeg（执行命令前必做）

在运行依赖 ffmpeg 的命令（尤其是阶段 4 的 compose_video.py）之前，必须确认 **`<SKILL_DIR>\bin\ffmpeg.exe`** 存在。

1. **检查路径**：`<SKILL_DIR>\bin\ffmpeg.exe`（以及可选 `<SKILL_DIR>\bin\ffprobe.exe`）。
2. **验证方式**：`dir "<SKILL_DIR>\bin\ffmpeg.exe"`（Windows）或 `Test-Path "<SKILL_DIR>\bin\ffmpeg.exe"`（PowerShell）。
3. **若不存在**：先运行 **`setup_resources.py`** 下载并部署到 `bin/`：
   ```bash
   python "<SKILL_DIR>\scripts\setup_resources.py"
   ```
   强制重新下载：`python "<SKILL_DIR>\scripts\setup_resources.py" --force`
4. **说明**：compose_video.py 默认使用 `<SKILL_DIR>\bin\ffmpeg.exe`，若未部署则合成阶段会失败。

**✅ 检查点 1→2：** 工作区目录已创建；`<VIDEO_DIR>` 中至少存在 1 个视频文件；**`<SKILL_DIR>\bin\ffmpeg.exe` 已存在或已通过 setup_resources.py 完成部署。**

---

## 阶段 2：分析

### 步骤 2.1 查找 FLAMA

**查找顺序：**
1. 环境变量 `%FLAMA_PATH%`（如果已设置）
2. 默认路径：`<SKILL_DIR>\bin\flama\flama.exe`（由 setup_resources.py 部署）

验证命令：`dir "<FLAMA_PATH>"`（未设环境变量时用 `<SKILL_DIR>\bin\flama\flama.exe`）

**约定：** 下文中的 `<FLAMA_DIR>` 表示 flama.exe 所在目录；未设 `%FLAMA_PATH%` 时即为 `<SKILL_DIR>\bin\flama`。

### 步骤 2.2 检查模型路径（调用 FLAMA 前必做）

在运行 FLAMA 之前，必须确认其使用的 VLM 模型目录存在；若不存在则**必须立即执行模型下载**，不得跳过、不得先尝试运行 FLAMA、不得用 ffprobe 或手写分镜等方式绕过视频分析。

**硬性规则：模型路径不存在时，必须按顺序执行 (1)→(2)→(3)，不可省略：**
- **(1)** 在 `<SKILL_DIR>` 创建虚拟环境（若尚无 `.venv`）：`python -m venv .venv`，并激活；
- **(2)** 在虚拟环境中安装依赖：`pip install huggingface_hub`；
- **(3)** 运行下载脚本：`python "<SKILL_DIR>\scripts\setup_ov_model.py" --flama-dir "<FLAMA_DIR>"`（国内推荐加 `--hf-mirror`）。
- 下载完成后再次检查模型路径存在，再进入步骤 2.3 运行 FLAMA。

1. **读取配置中的模型路径**
   - 优先读取项目内 **`flama/config/config.json`**（即 `<FLAMA_DIR>\..\..\..\config\config.json` 或项目根下的 `flama/config/config.json`）。
   - 若该文件不存在，则读取 **`<FLAMA_DIR>\config.json`**（FLAMA 运行目录下的 config）。
   - 从 JSON 中取 **`genai.model_path`** 的值。

2. **解析为绝对路径**
   - 若 `model_path` 为相对路径（例如 `models/Qwen2.5-VL-7B-Instruct-int4`），则相对于 **`<FLAMA_DIR>`** 解析为绝对路径。
   - 若为绝对路径，则直接使用。

3. **检查路径是否存在**
   - 判断解析后的路径是否指向**已存在的目录**，且目录内包含有效模型文件（例如 OpenVINO 的 `.xml` 等）。
   - 可用命令快速检查目录是否存在：`dir "<解析后的模型路径>"`（Windows）或 `Test-Path "<解析后的模型路径>"`（PowerShell）。

4. **若模型路径不存在（必须执行，禁止跳过）**
   - **先**在 `<SKILL_DIR>` 创建并激活虚拟环境，**再**安装依赖，**最后**运行下载：
   ```bash
   # Windows（在 <SKILL_DIR> 下执行）
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install huggingface_hub
   python scripts\setup_ov_model.py --flama-dir "<FLAMA_DIR>"
   ```
   - 国内网络建议在最后一条命令加 **`--hf-mirror`**。
   - 脚本会将模型下载到 `<FLAMA_DIR>\models\` 下，并更新 `<FLAMA_DIR>\config.json` 中的 `genai.model_path`。若你读取的是 `flama/config/config.json`，下载完成后可手动将该 config 中的 `model_path` 改为与 FLAMA 实际使用的一致（或使用相对路径 `models/Qwen2.5-VL-7B-Instruct-int4` 并在 FLAMA 运行目录下保留一份 config）。
   - 仅校验不下载：`python "<SKILL_DIR>\scripts\setup_ov_model.py" --flama-dir "<FLAMA_DIR>" --check-only`

5. **依赖说明**
   - 运行 `setup_ov_model.py` 前**必须先**在虚拟环境中安装：`pip install huggingface_hub`（参见「环境准备」）。仅下载预转换好的 OpenVINO 模型，无需 optimum-intel、nncf 等。

**✅ 检查点 2.2：** 模型路径指向的目录存在且有效，或已成功执行 `setup_ov_model.py` 并完成下载。

### 步骤 2.3 运行 FLAMA 分析

**关键规则：** 仅在步骤 2.2 通过后执行；始终重新运行，绝不复用已有的 output_vlm.json；运行前必须确认当前工作区文件夹下没有output_vlm.json。

```bash
cd /d "<SKILL_DIR>\bin\flama"
flama.exe --video_dir=<VIDEO_DIR> --mode=hw --json_file=<WORKSPACE_DIR>\output_vlm.json --prompt="<PROMPT>"
```

**FLAMA 参数参考：**

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--video_dir` | 是 | — | 输入视频目录路径 |
| `--json_file` | 是 | — | 输出 JSON 文件路径 |
| `--prompt` | 是 | — | VLM 分析提示词 |
| `--mode` | 否 | `hw` | `hw`=GPU硬件加速，`sw`=CPU软件解码 |
| `--debug` | 否 | `0` | `1`=输出调试日志 |

**提示词选择：**

| 条件 | 操作 |
|------|------|
| 用户指定了主题/氛围/节奏 | 使用需求驱动的提示词 |
| 无特定需求 | 使用默认提示词 |

**默认提示词：**
```
准确的描述这个视频文件中的主要内容，包括：场景环境、人物动作、画面构图、光线氛围、运镜方式。输出不超过100字的简要描述。
```

**需求驱动的提示词模板：**
```
请根据以下剪辑目标分析视频片段：主题是「<THEME>」，氛围是「<MOOD>」，节奏要求「<PACING>」。重点捕捉与「<MUST_CAPTURE>」相关的画面线索。描述中必须包含：场景环境、人物动作、画面构图、光线氛围、运镜方式，并突出与目标风格相关的信息。输出不超过100字。
```

**按风格划分的提示词示例：**

| 风格 | 提示词 |
|------|--------|
| 节日喜庆 | `请重点识别节日元素、欢庆互动、热闹场景和轻快节奏的镜头...突出喜庆与活力。输出不超过100字。` |
| 日常诗意 | `请重点识别日常场景中的诗意细节、情绪留白、光影变化与细腻动作...突出温柔与故事感。输出不超过100字。` |
| 连贯动感 | `请重点识别可形成连贯动作链的镜头、运动方向、速度变化与节奏点...突出流畅衔接与动感。输出不超过100字。` |

### 步骤 2.4 验证并解析输出

验证 `<WORKSPACE_DIR>\output_vlm.json` 存在并读取内容。

**输出结构：**
```json
{
  "processed_videos": [{
    "input_video": "D:\\path\\video.mp4",
    "segments": [{
      "seg_id": 0,
      "seg_start": 0.0,
      "seg_end": 3.003,
      "seg_dur": 3.003,
      "seg_desc": "AI生成的内容描述..."
    }]
  }]
}
```

提取信息：场景清单、拍摄对象、视觉主题、运镜方式、精彩瞬间。

**✅ 检查点 2→3：** 模型路径已就绪；`output_vlm.json` 文件非空；至少包含 1 个 `processed_videos` 条目且含 `segments` 数据。

---

## 阶段 3：创作

### 步骤 3.1 故事大纲开发

#### 开场钩子策略（三选一）

| 策略 | 方法 | 适用场景 |
|------|------|----------|
| **视觉反差** | 以强烈视觉对比开场（暗→亮、静→动、远→近） | 风景、旅行、日常诗意 |
| **动作瞬间** | 以正在发生的动作中段切入 | 运动、节日、活泼欢快 |
| **悬念前置** | 先展示结果/高潮片段，再回到起点 | 叙事型、故事感强的 vlog |

#### 叙事弧线结构

| 段落 | 时长占比 | 目标 | 选片要点 |
|------|----------|------|----------|
| **开场钩子** | 5-10% | 3秒内抓住注意力 | 选最具视觉冲击力的画面 |
| **引入** | 10-15% | 建立场景与背景 | 广角/环境镜头，交代时间地点 |
| **递进** | 30-40% | 展开主要叙事 | 按逻辑推进，动静交替 |
| **高潮** | 15-20% | 情感或视觉巅峰 | 最精彩、最有感染力的画面 |
| **收尾** | 10-15% | 回味与总结 | 节奏放缓，情感沉淀 |
| **结束** | 5-10% | 留下余韵 | 意象化画面或呼应开场 |

#### 片段选择质量评估优先级

1. **稳定性** — 优先选择无明显抖动的片段
2. **光线** — 光线充足、曝光正确
3. **清晰度** — 对焦准确、画面不模糊
4. **运镜** — 有意义的镜头运动（推拉摇移）
5. **独特性** — 内容不与其他已选片段重复

#### 镜头组接规则

- **景别交替**：远→中→近交替排列，避免相同景别连排
- **动静交替**：运动镜头后接相对静态画面，形成节奏
- **方向一致**：相邻镜头中运动方向保持一致或有合理过渡

### 步骤 3.2 片段选择与排序

**选择标准：**
1. 画面质量（光线充足、画面稳定）
2. 内容与故事的相关性
3. 多样性（镜头类型）
4. 节奏平衡
5. 与需求的匹配度

**时长指南：**
- 30秒 vlog → 约 10 个片段
- 60秒 vlog → 约 20 个片段
- 90秒 vlog → 约 30 个片段

**规则：**
- 绝不重复使用同一片段（source_video + seg_id 组合必须唯一）
- 绝不以静态/无聊的镜头开场
- 避免相似镜头连续出现

### 步骤 3.3 旁白/字幕生成

**技术规格：**
- 每行最多 16 字符（超出时 compose_video.py 按 `--max-line-len` 自动换行）
- 特殊字符（单引号、双引号、反斜杠）由脚本自动转义，无需手动处理

**创作规则：**
- 每 3 秒片段最多 10-15 个字
- **补充情感，而非描述画面** — 字幕应表达画面无法传达的情绪和内心独白
- 匹配 vlog 氛围（积极向上、深思感悟等）

**反例对照：**

| ❌ 描述画面（避免） | ✅ 补充情感（推荐） |
|---------------------|---------------------|
| 这是一个美丽的湖泊 | 三年了，终于又见到你 |
| 阳光照在树叶上 | 这一刻什么都不想 |
| 小猫在沙发上睡觉 | 全世界最治愈的存在 |
| 我们走在街上 | 随便走走也很好 |

### 步骤 3.4 BGM 选择

**必需：必须选择恰好一首 BGM。始终使用绝对路径。**

#### BGM 氛围→分类决策表

| 视频氛围/风格 | 首选分类 | 备选分类 |
|---------------|----------|----------|
| 日常诗意、文艺清新 | 舒缓优美 | 温馨浪漫 |
| 温暖治愈、情感回忆 | 温馨浪漫 | 舒缓优美 |
| 中式古风、传统文化 | 民族古风 | 舒缓优美 |
| 轻松日常、休闲惬意 | 轻松愉悦 | 活泼欢快 |
| 感伤离别、深沉思考 | 低沉忧郁 | 舒缓优美 |
| 节日欢庆、活力动感 | 活泼欢快 | 轻松愉悦 |

#### BGM 选择流程

1. 读取 `<SKILL_DIR>\resource\bgm\bgm_style.json`
2. 根据上方决策表确定首选分类，从该分类中选择最匹配的曲目
3. 若首选分类无合适曲目，查看备选分类
4. 将**绝对路径**写入分镜脚本

**BGM 路径构建：**
```
绝对路径 = <SKILL_DIR>\resource\bgm\ + JSON 中的 file_path
示例：E:\data\agentkit\skills\video-editing-skills\resource\bgm\0aa3bfd386bf595b301119302595aaf3.mp3
```

### 步骤 3.5 输出 storyboard.json

**关键规则：始终重新生成，绝不复用已有的 storyboard.json。**

写入路径：`<WORKSPACE_DIR>\storyboard.json`

**最小必需 Schema：**
```json
{
  "storyboard_metadata": {
    "theme": "视频主题",
    "target_duration_seconds": 30,
    "cloud_llm_name": "XXXX"
    // 别名：llm_name 也可接受
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
      // 验证：out_point > in_point, duration > 0
    },
    "voiceover": {
      "text": "字幕文本"
    }
  }],
  "audio_design": {
    "background_music": {
      "file_path": "E:\\data\\agentkit\\skills\\video-editing-skills\\resource\\bgm\\xxx.mp3",
      // 别名：bgm_file 或 selected_bgm 也可接受
      "style_tag": "舒缓优美",
      "summary": "BGM描述"
    }
  }
}
```

**扩展字段（可选）：**

- **storyboard_metadata**: `version`、`generated_at`、`actual_duration_seconds`、`vlog_type`、`mood`、`user_requirements`
- **story_outline**: `title`、`synopsis`、`narrative_arc[]`
- **clips[]**: `story_section`、`content_description`、`editorial_note`、`suggested_transition_in/out`、`music_note`
- **audio_design.background_music**: `mood`、`tempo`、`suggested_genres`、`volume_curve`
- **audio_design.sound_design**: `use_original_audio`、`ambient_enhancement`、`audio_ducking`
- **editing_notes**: `color_grading`、`pacing`、`special_effects`、`text_overlays[]`
- **export_recommendations**: `resolution`、`aspect_ratio`、`frame_rate`、`format`

#### 写入前验证检查点

在将 storyboard.json 写入文件前，逐项自检：

1. ☐ `theme`、`target_duration_seconds`、`cloud_llm_name` 三个必需字段均存在
2. ☐ 每个 clip 的 `out_point > in_point` 且 `duration > 0`
3. ☐ 所有 `source_video` 路径指向 `<VIDEO_DIR>` 中实际存在的文件
4. ☐ 无重复的 `(source_video, source_segment_id)` 组合
5. ☐ `audio_design.background_music.file_path` 是绝对路径且文件存在
6. ☐ 片段总时长与 `target_duration_seconds` 偏差不超过 ±20%

**✅ 检查点 3→4：** storyboard.json 已通过上述 6 项验证；BGM 文件路径有效。

---

## 阶段 4：合成

**执行前确认：** 已通过步骤 1.5 检查，`<SKILL_DIR>\bin\ffmpeg.exe` 存在；否则先运行 `setup_resources.py`。

### 步骤 4.1 运行 compose_video.py

```bash
python "E:\data\agentkit\skills\video-editing-skills\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

**compose_video.py 参数参考：**

| 参数 | 必需 | 默认值 | 说明 |
|------|------|--------|------|
| `--storyboard` | 是 | — | storyboard.json 文件路径 |
| `--ffmpeg` | 否 | `<SKILL_DIR>\bin\ffmpeg.exe` | 自定义 ffmpeg 路径 |
| `--output-dir` | 否 | storyboard 所在目录 | 输出目录 |
| `--font-file` | 否 | `<SKILL_DIR>\resource\font.ttf` | 字幕字体文件 |
| `--font-size` | 否 | `40` | 字幕字号 |
| `--max-line-len` | 否 | `16` | 每行最大字符数 |
| `--dry-run` | 否 | `False` | 仅打印 ffmpeg 命令，不执行 |

> **排错建议：** 合成失败时，先加 `--dry-run` 查看生成的 ffmpeg 命令，检查路径和参数是否正确。

**脚本行为：**
1. 读取 storyboard.json
2. 创建 `<WORKSPACE_DIR>\temp\` 文件夹
3. 提取并处理每个片段 → 保存到 temp
4. 拼接所有片段 → `temp\merged_no_bgm.mp4`
5. 从分镜脚本添加 BGM（路径无效时回退为随机选择）
6. 输出最终视频：`<WORKSPACE_DIR>\<THEME>_<DURATION>s_bgm_<LLM>.mp4`

**输出命名规则：**
```
<theme>_<duration>s_bgm_<cloud_llm_name>.mp4
示例：日常诗意瞬间_30s_bgm_ClaudeOpus.mp4
```

---

## 硬性规则总结

| 规则 | 说明 |
|------|------|
| **平台检查必须最先执行** | 在执行任何步骤前，必须通过阶段 0 的三项检查（Intel MTL/LNL/ARL/PTL CPU + Intel iGPU 或白名单独显 Arc A770/B580 + 内存 > 16 GB）；任意一项不满足则立即终止，不得继续执行 |
| **每次新建工作区** | 每次任务必须创建新的工作区目录（新时间戳），不得从已有 `editing_*` 工作区读取 output_vlm.json、storyboard.json 等文件 |
| **模型不存在必须执行下载** | 步骤 2.2 发现模型路径不存在时，必须按顺序执行：创建/激活虚拟环境 → 安装 huggingface_hub → 运行 setup_ov_model.py；禁止跳过下载、禁止先运行 FLAMA、禁止用 ffprobe/手写分镜等方式绕过分析 |
| **始终重新分析** | 始终重新运行 FLAMA，绝不复用已有的 output_vlm.json |
| **始终重新生成分镜** | 始终生成新的分镜脚本，绝不复用已有的 storyboard.json |
| **禁止重复片段** | 每个 (source_video, source_segment_id) 组合最多使用一次 |
| **必须选择 BGM** | 必须选择恰好一首 BGM，并提供有效的绝对路径 |
| **工作区输出** | 所有文件必须在 `<WORKSPACE_DIR>` 内 |
| **必需元数据** | theme、target_duration_seconds、cloud_llm_name 必须存在 |
| **BGM 绝对路径** | `audio_design.background_music.file_path` 必须是绝对路径 |

---

## 错误处理

| 错误 | 原因 | 解决方案 |
|------|------|----------|
| 找不到 FLAMA | 构建未完成 | 验证路径，运行 `setup_resources.py` |
| 没有视频文件 | 路径或格式错误 | 检查路径和文件扩展名 |
| GPU 初始化失败 | 驱动/硬件问题 | 使用 `--mode=sw` |
| **模型路径不存在** | 模型未下载 | 必须按步骤 2.2 依次执行：创建虚拟环境 → 安装 `huggingface_hub` → 运行 `setup_ov_model.py`，禁止跳过或绕过 |
| output_vlm.json 为空 | 处理失败 | 检查控制台错误信息 |
| storyboard.json 未创建 | 写入失败 | 检查文件权限 |
| 片段数量不足 | 视频太短 | 合并多个视频或调整目标时长 |
| BGM 路径无效 | 路径格式错误 | 使用绝对路径并正确转义 |
| 合成失败 | ffmpeg 命令错误 | 对 compose_video.py 使用 `--dry-run` 检查命令 |

### LLM 常见错误预防

| 常见犯错模式 | 后果 | 护栏规则 |
|-------------|------|----------|
| `out_point` ≤ `in_point` | ffmpeg 报错，片段提取失败 | 写入前检查每个 clip 的时间码 |
| `duration` 与 `out_point - in_point` 不一致 | 片段时长不符预期 | duration 应等于 out_point - in_point |
| `source_video` 路径使用正斜杠 | Windows 下路径解析失败 | 始终使用反斜杠 `\\` |
| BGM `file_path` 使用相对路径 | 找不到 BGM 文件 | 始终拼接为绝对路径 |
| 重复使用同一 segment | 视频出现重复画面 | 写入前去重检查 (source_video, seg_id) |
| `cloud_llm_name` 字段缺失 | 输出文件名异常 | 始终填写，如 "ClaudeOpus" |
| 字幕文本过长（超过 30 字） | 字幕溢出画面或堆叠 | 每 3 秒片段控制在 10-15 字 |
| 选择了不存在的 seg_id | ffmpeg 时间码超出视频范围 | 选片时核对 output_vlm.json 中的实际 seg_id 范围 |

---

## 完整示例

用户提供视频目录（如 `D:\data\videoclips\phone2\007_input`）并请求「30秒 vlog、连贯动感」时：验证目录 → 创建工作区 `editing_YYYYMMDD_HHMMSS` → 运行 FLAMA 得到 output_vlm.json → 生成 storyboard.json（含 BGM 绝对路径与片段时间码）→ 运行 `python scripts/compose_video.py --storyboard <WORKSPACE_DIR>\storyboard.json`。输出文件：`<WORKSPACE_DIR>\<theme>_<duration>s_bgm_<cloud_llm_name>.mp4`。

**用户请求：**
```
D:\data\videoclips\phone2\007_input 文件夹中包含多个视频，生成一个30秒vlog，连贯流畅、富有动感
```

**执行过程：**

```bash
# 1. 验证
dir "D:\data\videoclips\phone2\007_input\*.mp4"

# 2. 创建工作区
mkdir "D:\data\videoclips\phone2\007_input\editing_20250205_143000"

# 3. 保存用户输入（通过 Write 工具）

# 4. 运行 FLAMA
cd /d "D:\data\code\flama_code\flama\build\bin\Release"
flama.exe --video_dir=D:\data\videoclips\phone2\007_input --mode=hw --json_file=D:\data\videoclips\phone2\007_input\editing_20250205_143000\output_vlm.json --prompt="请重点识别可形成连贯动作链的镜头、运动方向、速度变化与节奏点，描述环境、动作、构图、光线和运镜，突出流畅衔接与动感。输出不超过100字。"

# 5. 读取 output_vlm.json，生成 storyboard.json（通过 Write 工具）

# 6. 合成
python "E:\data\agentkit\skills\video-editing-skills\scripts\compose_video.py" --storyboard "D:\data\videoclips\phone2\007_input\editing_20250205_143000\storyboard.json"
```

**最终输出：**
```
D:\data\videoclips\phone2\007_input\editing_20250205_143000\连贯动感_30s_bgm_ClaudeOpus.mp4
```
