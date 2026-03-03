---
name: video-editing-skills
description: "使用本地 FLAMA 进行 AI 驱动的视频分析、分镜脚本生成，以及通过 compose_video.py 进行可选的最终视频合成的 Vlog 视频剪辑工作流。适用场景：(1) 用户提供包含视频文件的文件夹，要求创建 vlog 剪辑脚本/分镜脚本，(2) 用户请求对视频片段进行分析和选择以制作 vlog，(3) 用户希望生成指定时长（如30秒、60秒）的 JSON 格式视频剪辑方案，(4) 用户提到 'vlog剪辑'、'视频剪辑脚本'、'video storyboard' 或 'editing script' 等关键词，(5) 用户希望从 storyboard.json 自动渲染最终视频。本技能调用本地 flama.exe 工具，使用 VLM 分析视频片段，然后生成包含叙事结构、片段选择、旁白建议和时间信息的专业分镜脚本，并可调用 compose_video.py 渲染最终视频。"
---

# Vlog 分镜脚本生成器

AI 驱动的 vlog 剪辑工作流：视频分析 → 分镜脚本生成 → 最终视频合成。

---

## 快速参考

### 关键路径

| 组件 | 路径 | 说明 |
|------|------|------|
| **FLAMA** | `%FLAMA_PATH%` 或下方默认路径 | 可通过环境变量配置 |
| FLAMA 默认路径 | `D:\data\code\flama_code\flama\build\bin\Release\flama.exe` | 环境变量未设置时的回退路径 |
| **compose_video.py** | `<SKILL_DIR>\scripts\compose_video.py` | 相对于本技能目录 |
| **BGM 目录** | `<SKILL_DIR>\resource\bgm\` | 包含 51 个 BGM 文件 |
| **BGM 索引** | `<SKILL_DIR>\resource\bgm\bgm_style.json` | BGM 元数据 |
| **字体文件** | `<SKILL_DIR>\resource\font.ttf` | 字幕字体 |

**路径变量：**
- `<SKILL_DIR>` = `C:\Users\SAS\.claude\skills\video-editing-skills`
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
- `cloud_llm_name` - LLM 名称（如 "ClaudeOpus"）

**`audio_design.background_music` 中必须包含：**
- `file_path` - BGM 文件的**绝对路径**

**每个 `clips[]` 项目中必须包含：**
- `clip_id`、`sequence_order`、`source_video`
- `timecode.in_point`、`timecode.out_point`、`timecode.duration`
- `voiceover.text`（用于字幕）

### 命令模板

```bash
# 1. 验证 FLAMA 是否存在
dir "D:\data\code\flama_code\flama\build\bin\Release\flama.exe"

# 2. 运行 FLAMA 分析（始终重新运行，绝不复用 output_vlm.json）
cd /d "D:\data\code\flama_code\flama\build\bin\Release"
flama.exe --video_dir=<VIDEO_DIR> --mode=hw --json_file=<WORKSPACE_DIR>\output_vlm.json --prompt="<PROMPT>"

# 3. 合成最终视频
python "<SKILL_DIR>\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

---

## 工作流概览

```
阶段 1：准备          阶段 2：分析          阶段 3：创作          阶段 4：合成
┌─────────────────┐     ┌─────────────────┐    ┌─────────────────┐     ┌─────────────────┐
│ 1.1 验证        │     │ 2.1 查找 FLAMA  │    │ 3.1 故事        │     │ 4.1 运行        │
│     视频目录    │────►│ 2.2 运行 FLAMA  │───►│     大纲        │────►│     compose_    │
│ 1.2 创建        │     │ 2.3 验证并      │    │ 3.2 选择片段    │     │     video.py    │
│     工作区      │     │     解析输出    │    │ 3.3 旁白        │     └─────────────────┘
│ 1.3 保存输入    │     └─────────────────┘    │ 3.4 BGM         │
│ 1.4 提取        │                            │ 3.5 输出 JSON   │
│     需求        │                            └─────────────────┘
└─────────────────┘
```

---

## 阶段 1：准备

### 步骤 1.1 验证视频目录

验证目录存在且包含视频文件（`.mp4`、`.mov`、`.avi`、`.mkv`、`.webm`、`.m4v`、`.wmv`）。

```bash
dir "<VIDEO_DIR>\*.mp4" "<VIDEO_DIR>\*.mov" "<VIDEO_DIR>\*.avi" "<VIDEO_DIR>\*.mkv"
```

### 步骤 1.2 创建工作区

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

---

## 阶段 2：分析

### 步骤 2.1 查找 FLAMA

**查找顺序：**
1. 环境变量 `%FLAMA_PATH%`（如果已设置）
2. 默认路径：`D:\data\code\flama_code\flama\build\bin\Release\flama.exe`

验证命令：`dir "<FLAMA_PATH>"`

### 步骤 2.2 运行 FLAMA 分析

**关键规则：始终重新运行，绝不复用已有的 output_vlm.json。**

```bash
cd /d "D:\data\code\flama_code\flama\build\bin\Release"
flama.exe --video_dir=<VIDEO_DIR> --mode=hw --json_file=<WORKSPACE_DIR>\output_vlm.json --prompt="<PROMPT>"
```

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
| 节日喜庆 | `请重点识别节日元素、欢庆互动、热闘场景和轻快节奏的镜头...突出喜庆与活力。输出不超过100字。` |
| 日常诗意 | `请重点识别日常场景中的诗意细节、情绪留白、光影变化与细腻动作...突出温柔与故事感。输出不超过100字。` |
| 连贯动感 | `请重点识别可形成连贯动作链的镜头、运动方向、速度变化与节奏点...突出流畅衔接与动感。输出不超过100字。` |

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
      "seg_end": 3.003,
      "seg_dur": 3.003,
      "seg_desc": "AI生成的内容描述..."
    }]
  }]
}
```

提取信息：场景清单、拍摄对象、视觉主题、运镜方式、精彩瞬间。

---

## 阶段 3：创作

### 步骤 3.1 故事大纲开发

按叙事弧线构建结构：
- **开场钩子**（5-10%）：视觉冲击力强的瞬间
- **引入**（10-15%）：建立背景
- **递进**（30-40%）：主要叙事
- **高潮**（15-20%）：巅峰时刻
- **收尾**（10-15%）：总结回顾
- **结束**（5-10%）：最终印象

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

- 每 3 秒片段最多 10-15 个字
- 匹配 vlog 氛围（积极向上、深思感悟等）
- 与画面互补，而非描述画面

### 步骤 3.4 BGM 选择

**必需：必须选择恰好一首 BGM。**

1. 读取 `<SKILL_DIR>\resource\bgm\bgm_style.json`
2. 根据用户需求（主题、氛围、节奏）匹配 BGM
3. 将**绝对路径**写入分镜脚本

**BGM 路径构建：**
```
绝对路径 = <SKILL_DIR>\resource\bgm\ + JSON 中的 file_path
示例：C:\Users\SAS\.claude\skills\video-editing-skills\resource\bgm\0aa3bfd386bf595b301119302595aaf3.mp3
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
      "file_path": "C:\\Users\\SAS\\.claude\\skills\\video-editing-skills\\resource\\bgm\\xxx.mp3",
      "style_tag": "舒缓优美",
      "summary": "BGM描述"
    }
  }
}
```

**扩展字段（可选）：**
- `storyboard_metadata.version`、`generated_at`、`actual_duration_seconds`、`vlog_type`、`mood`、`user_requirements`
- `story_outline.title`、`synopsis`、`narrative_arc[]`
- `clips[].story_section`、`content_description`、`editorial_note`、`suggested_transition_in/out`、`music_note`
- `audio_design.background_music.mood`、`tempo`、`suggested_genres`、`volume_curve`
- `audio_design.sound_design.use_original_audio`、`ambient_enhancement`、`audio_ducking`
- `editing_notes.color_grading`、`pacing`、`special_effects`、`text_overlays[]`
- `export_recommendations.resolution`、`aspect_ratio`、`frame_rate`、`format`

---

## 阶段 4：合成

### 步骤 4.1 运行 compose_video.py

```bash
python "C:\Users\SAS\.claude\skills\video-editing-skills\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

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
| 找不到 FLAMA | 构建未完成 | 验证路径，运行 build.bat |
| 没有视频文件 | 路径或格式错误 | 检查路径和文件扩展名 |
| GPU 初始化失败 | 驱动/硬件问题 | 使用 `--mode=sw` |
| output_vlm.json 为空 | 处理失败 | 检查控制台错误信息 |
| storyboard.json 未创建 | 写入失败 | 检查文件权限 |
| 片段数量不足 | 视频太短 | 合并多个视频或调整目标时长 |
| BGM 路径无效 | 路径格式错误 | 使用绝对路径并正确转义 |

---

## 完整示例

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
python "C:\Users\SAS\.claude\skills\video-editing-skills\scripts\compose_video.py" --storyboard "D:\data\videoclips\phone2\007_input\editing_20250205_143000\storyboard.json"
```

**最终输出：**
```
D:\data\videoclips\phone2\007_input\editing_20250205_143000\连贯动感_30s_bgm_ClaudeOpus.mp4
```
