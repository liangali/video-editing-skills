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
| **analyze_video.py** | `<SKILL_DIR>\scripts\analyze_video.py` | 视频分析（OpenVINO GenAI VLM） |
| **prepare_workspace.py** | `<SKILL_DIR>\scripts\prepare_workspace.py` | 工作区准备 |
| **compose_video.py** | `<SKILL_DIR>\scripts\compose_video.py` | 视频合成 |
| **VLM 模型** | `<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4` | OpenVINO VLM 模型 |
| **ffmpeg / ffprobe** | `<SKILL_DIR>\bin\ffmpeg.exe` | 视频编解码 |
| **BGM 目录** | `<SKILL_DIR>\resource\bgm\` | 背景音乐文件 |
| **BGM 索引** | `<SKILL_DIR>\resource\bgm\bgm_style.json` | BGM 分类元数据（UTF-8-sig 编码） |

### 路径变量（必须准确解析）

| 变量 | 含义 | 示例 |
|------|------|------|
| `<SKILL_DIR>` | 本 SKILL.md 文件所在目录 | `D:\tools\video-editing-skills` |
| `<VIDEO_DIR>` | 用户提供的视频目录 | `D:\data\my_clips` |
| `<WORKSPACE_DIR>` | 工作区 = `<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS` | `D:\data\my_clips\editing_20260326_143045` |

**解析 `<SKILL_DIR>` 的伪代码：**
```
如果 SKILL.md 位于 D:\tools\video-editing-skills\SKILL.md
则 <SKILL_DIR> = D:\tools\video-editing-skills
不是 D:\tools，不是当前工作目录，不是 git 根目录
```

**时间戳格式 `YYYYMMDD_HHMMSS`：** 年(4位)月(2位)日(2位)\_时(24h,2位)分(2位)秒(2位)。示例：`editing_20260326_143045`

### 命令模板

```bash
# 阶段 0: 平台检查
powershell -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\check_platform.ps1"

# 阶段 1: 准备工作区
python "<SKILL_DIR>\scripts\prepare_workspace.py" --video-dir "<VIDEO_DIR>" --user-request "<USER_REQUEST>" --check-ffmpeg

# 阶段 2: 视频分析（始终重新运行）
python "<SKILL_DIR>\scripts\analyze_video.py" --video-dir "<VIDEO_DIR>" --output "<WORKSPACE_DIR>\output_vlm.json" --model-dir "<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4" --prompt "<PROMPT>"

# 阶段 3: AI 生成 storyboard.json（通过 Write 工具写入）

# 阶段 4: 合成最终视频
python "<SKILL_DIR>\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

### 环境准备

```bash
pip install -r "<SKILL_DIR>\requirements.txt"           # Python 依赖
python "<SKILL_DIR>\scripts\setup_resources.py"          # 下载 ffmpeg + BGM 资源
python "<SKILL_DIR>\scripts\setup_ov_model.py"           # 下载 VLM 模型（约 4-6 GB）
```

---

## 工作流概览

```
阶段 0：平台检查      阶段 1：准备          阶段 2：分析                    阶段 3：创作          阶段 4：合成
┌─────────────────┐  ┌─────────────────┐     ┌─────────────────────────┐    ┌─────────────────┐     ┌─────────────────┐
│ 检测硬件平台    │  │ 验证视频目录    │     │ 检查模型路径            │    │ 故事大纲        │     │ 时长校验        │
│ 检查 GPU        │─►│ 创建工作区      │────►│ 运行 analyze_video.py   │───►│ 选择片段+排序   │────►│ compose_video   │
│ 检查内存        │  │ 检查 ffmpeg     │     │ 验证输出                │    │ 旁白/字幕       │     │ 最终时长校验    │
│ [失败→终止]     │  │ 保存用户请求    │     └─────────────────────────┘    │ BGM + JSON输出  │     └─────────────────┘
└─────────────────┘  └─────────────────┘                                   └─────────────────┘
```

每个阶段必须按顺序执行。前一阶段未通过检查点时，禁止进入下一阶段。

---

## 阶段 0：平台检查（硬性门控）

> **任何 LLM 必须遵守：脚本退出码非 0 时，立即终止全部流程。不询问用户是否继续，直接停止。**

```powershell
powershell -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\check_platform.ps1"
```

| 退出码 | 动作 |
|--------|------|
| `0` | 进入阶段 1 |
| 任何非 0 值 | **立即终止，将错误信息转述给用户** |

**✅ 自检：** 脚本输出包含"所有检查通过"且退出码 = 0

---

## 阶段 1：准备

### 自动化方式（推荐）

```bash
python "<SKILL_DIR>\scripts\prepare_workspace.py" --video-dir "<VIDEO_DIR>" --user-request "<用户原始请求>" --check-ffmpeg
```

脚本最后一行输出工作区绝对路径，后续用作 `<WORKSPACE_DIR>`。

### 手动方式

1. **验证视频目录**：确认目录存在且包含视频文件（`.mp4`/`.mov`/`.avi`/`.mkv`/`.webm`/`.m4v`/`.wmv`）。**仅检查顶层文件，不递归子目录。**
2. **创建工作区**：`<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS`（使用当前本地时间，每次必须新建）
3. **保存用户输入**：写入 `<WORKSPACE_DIR>\user_input.txt`
4. **提取需求**：

| 要素 | 说明 | 用户未指定时的默认值 |
|------|------|---------------------|
| `target_duration_seconds` | 目标时长 | `30` |
| `theme` | 主题 | 根据视频内容自动推断（如"日常记录"） |
| `mood` | 氛围 | `轻松自然` |
| `pacing` | 节奏 | `连贯流畅` |
| `must_capture` | 必选内容 | 留空 |

> **规则：** 如果用户提供了 theme/mood/pacing/must_capture 中的任何一个，就使用需求驱动的提示词模板。全部未提供时使用默认提示词。

5. **检查 ffmpeg**：确认 `<SKILL_DIR>\bin\ffmpeg.exe` 存在，不存在则运行 `setup_resources.py`

**✅ 自检：** □ 工作区目录已创建 □ 视频文件 ≥ 1 □ `ffmpeg.exe` 存在

---

## 阶段 2：分析

### 步骤 2.1 检查模型

```bash
python "<SKILL_DIR>\scripts\setup_ov_model.py" --check-only
```

输出 `✓ 模型目录完整有效` → 继续。否则运行 `python "<SKILL_DIR>\scripts\setup_ov_model.py"` 下载。

### 步骤 2.2 运行分析

**规则：始终重新运行，绝不复用已有的 output_vlm.json。**

```bash
python "<SKILL_DIR>\scripts\analyze_video.py" --video-dir "<VIDEO_DIR>" --output "<WORKSPACE_DIR>\output_vlm.json" --model-dir "<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4" --prompt "<PROMPT>"
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--video-dir` | — | 输入视频目录（必需） |
| `--output` | — | 输出 JSON 路径（必需） |
| `--prompt` | 内置默认 | VLM 分析提示词 |
| `--model-dir` | `<SKILL_DIR>/models/Qwen2.5-VL-7B-Instruct-int4` | 模型目录 |
| `--device` | `GPU` | `GPU` 或 `CPU`（GPU 失败时可回退 CPU） |
| `--seg-duration` | `3.0` | 段时长（秒） |
| `--frames-per-seg` | `8` | 每段提取帧数（视频模式） |

**默认提示词：**
```
准确的描述这个视频片段中的主要内容，包括：场景环境、人物动作、画面构图、光线氛围、运镜方式。输出不超过100字的简要描述。
```

**需求驱动的提示词模板**（用户指定了任何 theme/mood/pacing/must_capture 时使用）：
```
请根据以下剪辑目标分析视频片段：主题是「<THEME>」，氛围是「<MOOD>」，节奏要求「<PACING>」。重点捕捉与「<MUST_CAPTURE>」相关的画面线索。描述中必须包含：场景环境、人物动作、画面构图、光线氛围、运镜方式，并突出与目标风格相关的信息。输出不超过100字。
```

### 步骤 2.3 验证输出

读取 `<WORKSPACE_DIR>\output_vlm.json`，确认非空且含 `processed_videos[].segments[]` 数据。

**output_vlm.json 格式：**
```json
{
  "processed_videos": [{
    "input_video": "D:\\data\\my_clips\\video01.mp4",
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

**✅ 自检：** □ output_vlm.json 文件大小 > 0 □ processed_videos 数组非空 □ 每个视频有 segments

---

## 阶段 3：创作

> **这是 AI 发挥创造力的核心阶段。** 基于 output_vlm.json 的分析结果，构建叙事、选择片段、撰写字幕、选配 BGM，输出 storyboard.json。

### 步骤 3.1 故事大纲

#### 开场策略（根据内容选择最合适的一种）

| 策略 | 方法 | 适用场景 | 示例 |
|------|------|----------|------|
| **视觉冲击** | 最具冲击力的画面开场 | 风景、旅行 | 壮观日落、城市夜景 |
| **动作切入** | 动作进行中直接切入 | 运动、节日、活力型 | 摩托车飞驰、人群欢呼 |
| **悬念前置** | 先展示高潮/结果 | 叙事型 vlog | 山顶合影，然后回到起点 |
| **人物反应** | 以表情/反应镜头开场 | 日常、生活 | 惊喜表情、开心笑容 |

#### 叙事弧线

| 段落 | 时长占比 | 目标 | 30s示例(时间) |
|------|----------|------|--------------|
| **开场** | 5-10% | 3秒内抓住注意力 | 0-2s |
| **引入** | 10-15% | 建立场景背景 | 2-6s |
| **递进** | 30-40% | 展开主要叙事，动静交替 | 6-18s |
| **高潮** | 15-20% | 最精彩/最有感染力的画面 | 18-24s |
| **收尾** | 10-15% | 节奏放缓，情感沉淀 | 24-28s |
| **结束** | 5-10% | 留下余韵（可呼应开场） | 28-30s |

#### 不同内容类型的叙事重点

| 类型 | 开场 | 递进 | 高潮 | 结尾 |
|------|------|------|------|------|
| **旅行** | 目的地标志画面 | 探索过程、沿途风景 | 最壮观的景色/体验 | 回望/远去的身影 |
| **日常** | 日常温暖瞬间 | 生活片段流转 | 最触动人心的时刻 | 安静/治愈的画面 |
| **活动** | 最激烈的动作镜头 | 准备→行动→变化 | 最精彩的完成瞬间 | 疲惫但满足的表情 |

### 步骤 3.2 片段选择与排序

#### 选择标准（按优先级）

1. **叙事匹配** — 片段内容是否服务于当前故事段落
2. **画面质量** — 稳定、光线好、对焦准确
3. **内容多样性** — 避免相似画面连续
4. **节奏需要** — 动感段落用短片段，安静段落用长片段

#### 节奏密度（根据 pacing 调整）

| 节奏 | 平均片段时长 | 30s 片段数 | 适用场景 |
|------|-------------|-----------|----------|
| **动感/活力** | 1.5-2.5s | 12-18 个 | 运动、节日、快节奏 |
| **连贯流畅**（默认） | 2.5-3.5s | 8-12 个 | 旅行、日常 |
| **安静/诗意** | 3.5-5.0s | 6-8 个 | 文艺、回忆、治愈 |

#### 镜头组接规则

- **景别交替**：远→中→近交替，避免相同景别连续 3 个以上
- **动静交替**：运动镜头后接相对静态画面
- **方向一致**：相邻镜头运动方向保持一致
- **片段时长**：最短 ≥ 1.5s，最长 ≤ 目标时长的 25%（30s vlog 最长单段 ≤ 7.5s）

#### 规则

- **绝不重复**：`(source_video, source_segment_id)` 组合必须唯一，同一段不可复用
- **开场必精彩**：第一个片段必须是视觉冲击力最强的画面
- **段落完整性**：`source_segment_id` 必须是 output_vlm.json 中对应视频的有效 `seg_id`
- **时间码一致**：`in_point` = 该 seg_id 的 `seg_start`，`out_point` = 该 seg_id 的 `seg_end`，`duration` = `out_point - in_point`

### 步骤 3.3 旁白/字幕

**核心原则：补充情感，不要描述画面。**

| 规则 | 说明 |
|------|------|
| 密度 | 50-60% 的片段加字幕，40-50% 留白让画面呼吸 |
| 长度 | 每 3s 片段最多 10-15 个中文字 |
| 空字幕 | 不加字幕的片段设 `"text": ""`（空字符串） |
| 开场 | 第一个片段建议加字幕（设置基调） |
| 高潮 | 高潮片段可不加字幕（让画面说话） |
| 结尾 | 最后一个片段建议加字幕（留下回味） |

**示例对比：**

| ❌ 描述画面 | ✅ 补充情感 |
|------------|------------|
| 一个人骑着摩托车 | 风从耳边呼啸而过 |
| 山上的风景很美 | 这一刻什么都不想 |
| 两个人在拍照 | 有些人 见面就是快乐 |

### 步骤 3.4 BGM 选择

**必须选择恰好一首 BGM，使用绝对路径。**

**步骤：**
1. 读取 `<SKILL_DIR>\resource\bgm\bgm_style.json`（注意编码是 UTF-8-sig）
2. 根据下表匹配分类，选择该分类中的一首曲目
3. 构建绝对路径：`<SKILL_DIR>\resource\bgm\<file_path>`

| 视频氛围 | 首选分类 | 备选分类 |
|----------|----------|----------|
| 日常诗意、文艺清新 | 舒缓优美 | 温馨浪漫 |
| 温暖治愈、情感回忆 | 温馨浪漫 | 舒缓优美 |
| 中式古风、传统文化 | 民族古风 | 舒缓优美 |
| 轻松日常、休闲惬意 | 轻松愉悦 | 活泼欢快 |
| 感伤离别、深沉思考 | 低沉忧郁 | 舒缓优美 |
| 节日欢庆、活力动感 | 活泼欢快 | 轻松愉悦 |

**BGM 音频行为**（compose_video.py 自动处理）：
- BGM 循环播放至视频结束，自动淡入 1s + 淡出 1.5s
- 如原视频含音频（人声/环境音），自动混合保留
- 默认 BGM 音量 0.3（可通过 `--bgm-volume` 调整）

**无匹配时回退**：首选分类无合适曲目 → 查备选分类 → 仍无 → 任选一首

### 步骤 3.5 输出 storyboard.json

**始终重新生成，绝不复用。** 写入 `<WORKSPACE_DIR>\storyboard.json`。

**完整 Schema：**
```json
{
  "storyboard_metadata": {
    "theme": "摩旅自由行",
    "target_duration_seconds": 30,
    "cloud_llm_name": "ClaudeOpus"
  },
  "clips": [
    {
      "clip_id": 1,
      "sequence_order": 1,
      "source_video": "D:\\data\\my_clips\\test(01).mp4",
      "source_segment_id": 0,
      "timecode": {
        "in_point": 0.0,
        "out_point": 3.0,
        "duration": 3.0
      },
      "voiceover": {
        "text": "风从耳边呼啸而过"
      }
    },
    {
      "clip_id": 2,
      "sequence_order": 2,
      "source_video": "D:\\data\\my_clips\\test(00).mp4",
      "source_segment_id": 3,
      "timecode": {
        "in_point": 9.0,
        "out_point": 12.0,
        "duration": 3.0
      },
      "voiceover": {
        "text": ""
      }
    }
  ],
  "audio_design": {
    "background_music": {
      "file_path": "D:\\tools\\video-editing-skills\\resource\\bgm\\4e6976bc4aaacf27d6f89767c3aaf63e.mp3",
      "style_tag": "活泼欢快"
    }
  }
}
```

**字段说明：**
- `clip_id`：唯一整数，从 1 开始递增
- `sequence_order`：播放顺序，从 1 开始递增
- `source_video`：**绝对路径**，Windows 反斜杠 `\\`
- `source_segment_id`：对应 output_vlm.json 中该视频的 `segments[N].seg_id`
- `in_point`：该 seg_id 的 `seg_start` 值
- `out_point`：该 seg_id 的 `seg_end` 值
- `duration`：必须等于 `out_point - in_point`，且 > 0
- `voiceover.text`：字幕文本，不加字幕时设为空字符串 `""`
- `file_path`：BGM 的**绝对路径**

#### 写入前必须验证

1. ☐ `theme`、`target_duration_seconds`、`cloud_llm_name` 三个必需字段存在
2. ☐ 每个 clip：`out_point > in_point` 且 `duration == out_point - in_point` 且 `duration > 0`
3. ☐ 每个 `source_video` 路径指向 `<VIDEO_DIR>` 中实际存在的文件
4. ☐ 每个 `source_segment_id` 在 output_vlm.json 对应视频的 seg_id 范围内
5. ☐ 无重复的 `(source_video, source_segment_id)` 组合
6. ☐ `file_path` 是绝对路径且 BGM 文件存在
7. ☐ 片段总时长偏差 ≤ target × 20%

**时长偏差恢复**：如果 `abs(sum(durations) - target) > target * 0.2`：
- 总时长偏长 → 移除叙事贡献最低的 1-2 个片段
- 总时长偏短 → 添加 1-2 个与叙事匹配的新片段
- 调整后重新验证，直到偏差 ≤ 20%

**✅ 自检：** □ 7 项验证全部通过 □ storyboard.json 已写入

---

## 阶段 4：合成

### 步骤 4.0 时长校验（硬性门控）

重新读取 storyboard.json 计算片段总时长。**偏差 > target × 20% 时禁止执行 compose_video.py**，返回步骤 3.5 调整。

```python
import json
with open("<WORKSPACE_DIR>/storyboard.json", encoding="utf-8") as f:
    sb = json.load(f)
target = sb["storyboard_metadata"]["target_duration_seconds"]
total_duration = sum(c["timecode"]["duration"] for c in sb["clips"])
deviation = abs(total_duration - target)
threshold = target * 0.20
print(f"target={target}s total={total_duration:.1f}s deviation={deviation:.1f}s threshold={threshold:.1f}s")
print("PASS" if deviation <= threshold else "FAIL")
```

### 步骤 4.1 运行合成

```bash
python "<SKILL_DIR>\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--storyboard` | — | storyboard.json 路径（必需） |
| `--font-size` | `40` | 字幕字号 |
| `--max-line-len` | `16` | 每行最大字符数 |
| `--bgm-volume` | `0.3` | BGM 音量（0.0-1.0） |
| `--dry-run` | — | 仅打印命令不执行（调试用） |

**输出文件：** `<WORKSPACE_DIR>\<theme>_<duration>s_bgm_<cloud_llm_name>.mp4`
例如：`摩旅自由行_30s_bgm_ClaudeOpus.mp4`

**合成失败时**：先加 `--dry-run` 检查生成的 ffmpeg 命令，确认路径和参数正确。

### 步骤 4.2 最终时长校验

用 ffprobe 测量实际视频时长：
```bash
"<SKILL_DIR>\bin\ffprobe.exe" -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "<OUTPUT_VIDEO>"
```

| 结果 | 动作 |
|------|------|
| 偏差 ≤ target × 20% | 向用户报告视频路径和时长，任务完成 |
| 偏差 > target × 20% | 返回步骤 3.2 调整片段，最多重试 2 次 |
| 重试 2 次仍不通过 | 告知用户视频素材时长不足，建议补充素材 |

**✅ 自检：** □ 最终视频文件存在 □ 时长偏差 ≤ 20% □ 视频可播放

---

## 硬性规则

| 规则 | 说明 |
|------|------|
| 平台检查最先 | 退出码非 0 则终止全部 |
| 每次新建工作区 | 禁止从已有 `editing_*` 工作区读取任何文件 |
| 模型不存在必须下载 | 禁止在模型缺失时运行 analyze_video.py |
| 始终重新分析 | 绝不复用 output_vlm.json |
| 始终重新生成分镜 | 绝不复用 storyboard.json |
| 禁止重复片段 | (source_video, source_segment_id) 必须唯一 |
| BGM 绝对路径 | file_path 必须是绝对路径 |
| 时长偏差 ≤ 20% | 写入前 + 合成前 + 交付前三次校验 |
| 路径用反斜杠 | 命令行参数和 JSON 中都用 `\\` |

---

## 错误处理

| 错误 | 解决方案 |
|------|----------|
| 模型目录不存在 | `python scripts/setup_ov_model.py` |
| ffmpeg 未找到 | `python scripts/setup_resources.py` |
| GPU 初始化失败 | 添加 `--device CPU` 重试 |
| output_vlm.json 为空 | 检查控制台错误；若反复失败可尝试 `--device CPU` |
| 可用段数 < 目标片段数 | 降低 `target_duration_seconds` 或告知用户补充素材 |
| compose_video.py 失败 | 添加 `--dry-run` 检查命令；检查 source_video 路径是否正确 |
| BGM 路径无效 | 确认使用绝对路径拼接 `<SKILL_DIR>\resource\bgm\` + 文件名 |

### LLM 常见错误预防

| 错误模式 | 防护 |
|----------|------|
| `out_point ≤ in_point` | 写入前检查每个 clip 时间码 |
| 路径使用正斜杠 | 始终使用 `\\` 反斜杠 |
| BGM 用相对路径 | 始终拼接绝对路径 |
| 重复使用同一 segment | 写入前去重检查 |
| `cloud_llm_name` 缺失 | 始终填写（如 "ClaudeOpus"、"GPT4o"） |
| 字幕文本过长 | 每 3s 控制在 10-15 个中文字 |
| seg_id 超出范围 | 核对 output_vlm.json 中的实际 seg_id |
| duration ≠ out_point - in_point | 三者必须一致 |
