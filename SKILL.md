---
name: video-editing-skills
description:
  提供 vlog 剪辑工作流：使用 analyze_video.py (OpenVINO GenAI 或局域网 Ollama) 分析视频、
  生成分镜脚本（storyboard.json）并合成最终视频。
  当用户提供视频目录要求制作 vlog、生成分镜或剪辑脚本，或提及 vlog剪辑、视频剪辑脚本、
  video storyboard、editing script，或需要从 storyboard.json 渲染成片时使用。
---

# 全自动视频剪辑 Agent

AI 驱动的 vlog 剪辑工作流：视频分析 → 分镜脚本生成 → 最终视频合成。

---

## 快速参考

### 关键路径

| 组件 | 路径 | 说明 |
|------|------|------|
| **analyze_video.py** | `<SKILL_DIR>\scripts\analyze_video.py` | 视频分析（OpenVINO GenAI / 局域网 Ollama） |
| **prepare_workspace.py** | `<SKILL_DIR>\scripts\prepare_workspace.py` | 工作区准备 |
| **select_clips.py** | `<SKILL_DIR>\scripts\select_clips.py` | 主题感知片段预选器（阶段 2.5） |
| **compose_video.py** | `<SKILL_DIR>\scripts\compose_video.py` | 视频合成 |
| **VLM 模型** | `<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4` | OpenVINO VLM 模型 |
| **ffmpeg / ffprobe** | `<SKILL_DIR>\bin\ffmpeg.exe` | 视频编解码 |
| **BGM 目录** | `<SKILL_DIR>\resource\bgm\` | 背景音乐文件 |
| **BGM 索引** | `<SKILL_DIR>\resource\bgm\bgm_style.json` | BGM 分类元数据 |

### 路径变量（必须准确解析）

| 变量 | 含义 |
|------|------|
| `<SKILL_DIR>` | 本 SKILL.md 文件所在目录（非工作目录，非 git 根目录） |
| `<VIDEO_DIR>` | 用户提供的视频目录 |
| `<WORKSPACE_DIR>` | `<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS` |
| `<VENV_PYTHON>` | `<SKILL_DIR>\.venv\Scripts\python.exe` |

**时间戳格式：** 年(4位)月(2位)日(2位)\_时(24h,2位)分(2位)秒(2位)，示例：`editing_20260326_143045`

### 命令模板

```bash
# （可选）根目录启用局域网 VLM 卸载模式（lan_vlm.json）
# {
#   "enabled": true,
#   "backend": "ollama",
#   "base_url": "http://192.168.1.202:11434",
#   "model": "qwen2.5vl:7b",
#   "timeout_sec": 120,
#   "retry": 2
# }
#
# 阶段 0: 平台检查
powershell -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\check_platform.ps1"

# （推荐）先在当前命令行会话设置 HuggingFace 镜像
$env:HF_ENDPOINT = "https://hf-mirror.com"

# 阶段 1: 准备工作区
python "<SKILL_DIR>\scripts\prepare_workspace.py" --video-dir "<VIDEO_DIR>" --user-request "<USER_REQUEST>"

# 阶段 2: 视频分析（--theme 与阶段 2.5 一致；不传 --prompt 时使用内置「主题判定+画面」模板）
"<VENV_PYTHON>" "<SKILL_DIR>\scripts\analyze_video.py" --video-dir "<VIDEO_DIR>" --output "<WORKSPACE_DIR>\output_vlm.json" --model-dir "<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4" --theme "<THEME>"
# 可选：追加 --prompt "自定义分析要求…"（与默认提示词不同时，会在自定义内容前附加同样的首行判定格式）
# 若存在 <SKILL_DIR>\lan_vlm.json 且 enabled=true/backend=ollama，则自动切换为局域网 Ollama 推理

# 阶段 2.5: 片段预选（必须执行；N_SEGS/MIN_VIDEOS 由阶段 2.5 参数推导公式计算）
"<VENV_PYTHON>" "<SKILL_DIR>\scripts\select_clips.py" --output-vlm "<WORKSPACE_DIR>\output_vlm.json" --theme "<THEME>" --output "<WORKSPACE_DIR>\candidate_clips.json" --min-videos <MIN_VIDEOS> --n-segs <N_SEGS> [--negative-keywords "自定义词"]

# 阶段 3: AI 生成 storyboard.json → 写入后立即执行 Guard 校验（见全局规范）

# 阶段 4: 合成
"<VENV_PYTHON>" "<SKILL_DIR>\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

---

## 全局规范

> **所有阶段均须遵守，不在各阶段重复说明。**

### 路径规范

- 命令行参数和 JSON 中的路径一律使用 Windows 反斜杠 `\\`
- `source_video` 和 BGM `file_path` 必须是**绝对路径**
- BGM 路径 = `<SKILL_DIR>\resource\bgm\` + `bgm_style.json` 中的文件名

### Clip 约束（C1–C9）

| 编号 | 规则 |
|------|------|
| C1 | `(source_video, source_segment_id)` 组合全局唯一，不可重复 |
| C2 | 若存在 `candidate_clips.json`：先保证每个已入选 `source_video` 至少使用 1 段（受总片段数上限约束）；若总片段数不足以覆盖全部已入选视频，按 `video_score` 从高到低优先覆盖 |
| C3 | 同一 `source_video` 最多使用 1 段 |
| C4 | 相邻两个 clip 不得来自同一 `source_video` |
| C5 | `in_point` = 起始段 `seg_start`，`out_point` = 末段 `seg_end`，`duration = out_point − in_point > 0`；一个 clip 覆盖 N_SEGS 个连续段（约 N_SEGS×3s，由阶段 2.5 推导） |
| C6 | `source_segment_id` 必须是 output_vlm.json 对应视频的有效 `seg_id`（指起始段） |
| C7 | `source_video` 必须是 `<VIDEO_DIR>` 中实际存在的文件 |
| C8 | 单片段时长：最短 ≥ 5s，最长 ≤ 目标时长的 30% |
| C9 | 若存在 `candidate_clips.json`，`storyboard.json` 的每个 `(source_video, source_segment_id)` 必须来自 `candidate_clips`，禁止引入候选池外片段 |

**实际输出时长公式：** `sum(clip.duration) − sum(有转场片段的 transition.duration)`
例（60s 目标，N_SEGS=3）：7 个 9s 片段 + 6 个 0.8s 转场 → 63 − 4.8 = 58.2s ≈ 60s

### 字幕约束（S1–S5）

| 编号 | 规则 |
|------|------|
| S1 | 每个片段必须有字幕，`voiceover.text` 不可为空 |
| S2 | **硬约束**：字幕必须每 3 秒至少切换一次。设 `N_PARTS = ceil(clip.duration / 3.0)`，则 `voiceover.text` 必须写成 `N_PARTS` 句并使用 `\|` 分隔（如 6s→2 句，9s→3 句，12s→4 句）；**每段必须是独立完整的句子**（能单独成立、有完整含义），绝对禁止将一句话拆成碎片填入各段。每段 ≥ 5 字且 ≤ 16 字（中文）、第一人称。❌ 错误示例：`"一直想知道\|路的尽头\|是什么"`（一句话被劈成3段碎片）✅ 正确示例：`"路越走越远，心越来越静\|不知道终点在哪里\|但每一步都算数"`（3句独立表达）。任一 clip 不满足该格式即判为不合格，必须整版重写 storyboard |
| S3 | 字幕说**感受和想法**，不描述观众能直接看到的画面内容 |
| S4 | 所有字幕连续读必须是**有头有尾、有情感弧线的完整叙事**，不是散句 |
| S5 | **叙事先行**：先写完整字幕文案，再为每句选画面 |

### Guard 校验规范

写入 `storyboard.json` 后**必须立即执行**：

```bash
"<VENV_PYTHON>" "<SKILL_DIR>\scripts\storyboard_guard.py" --storyboard "<WORKSPACE_DIR>\storyboard.json" --output-vlm "<WORKSPACE_DIR>\output_vlm.json" --candidate-clips "<WORKSPACE_DIR>\candidate_clips.json" --mode validate --per-video-max 1 --min-clip-duration 5.0 --min-unique-videos <MIN_VIDEOS> --subtitle-switch-interval-sec 3.0
# <MIN_VIDEOS> 使用阶段 2.5 推导的值
```

| 退出码 | 动作 |
|--------|------|
| `0` | 通过，进入阶段 4 |
| 非 `0` | **返回步骤 3.2/3.3 重新选片与重排，禁止进入阶段 4** |

> `storyboard_guard.py` 只做检查，不做自动修复。若 validate 失败，必须回到阶段 3 依据 `validation_errors` 重新选片、重排、重写 `storyboard.json`，再重新 `--mode validate`；只有 validate=0 才允许合成。

---

## 工作流概览

```
阶段 0：平台检查      阶段 1：准备          阶段 2：分析                    阶段 3：创作          阶段 4：合成
┌─────────────────┐  ┌─────────────────┐     ┌─────────────────────────┐    ┌─────────────────┐     ┌─────────────────┐
│ 检测硬件平台    │  │ 验证视频目录    │     │ 运行 analyze_video.py   │    │ 故事大纲        │     │ 时长校验        │
│ 检查宿主Python  │─►│ 创建工作区      │────►│ 验证 output_vlm.json    │───►│ 选择片段+排序   │────►│ compose_video   │
│ [失败→终止]     │  │ 准备 .venv      │     └─────────────────────────┘    │ 旁白/字幕       │     │ 最终时长校验    │
│                 │  │ 安装依赖/资源   │                                    │ BGM + JSON输出  │     └─────────────────┘
└─────────────────┘  └─────────────────┘                                   └─────────────────┘
```

每个阶段必须按顺序执行。前一阶段未通过检查点时，禁止进入下一阶段。

---

## 阶段 0：平台检查（硬性门控）

> **脚本退出码非 0 时，立即终止全部流程。不询问用户是否继续，直接停止。**
> 若检测到 `<SKILL_DIR>\lan_vlm.json` 且配置启用 `backend=ollama`，脚本会自动跳过硬件/GPU门禁，仅保留 Python 版本检查。

```powershell
powershell -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\check_platform.ps1"
```

| 退出码 | 动作 |
|--------|------|
| `0` | 进入阶段 1 |
| 任何非 0 值 | **立即终止，将错误信息转述给用户** |

**✓ 自检：** 脚本输出包含"所有检查通过"且退出码 = 0

---

## 阶段 1：准备

### 自动化方式（推荐）

先在**当前命令行窗口**设置 HuggingFace 镜像（仅对当前会话生效）：

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
```

若你使用 `cmd.exe`：

```bat
set HF_ENDPOINT=https://hf-mirror.com
```

然后执行：

```bash
python "<SKILL_DIR>\scripts\prepare_workspace.py" --video-dir "<VIDEO_DIR>" --user-request "<用户原始请求>"
```

脚本最后一行输出工作区绝对路径，后续用作 `<WORKSPACE_DIR>`。阶段 1 会同时：
- 检查 / 创建 `<SKILL_DIR>\.venv` 并安装 requirements
- 检查 / 下载 `ffmpeg.exe` 与 `ffprobe.exe`
- 检查 / 下载 VLM 模型（若启用局域网 VLM 配置则自动跳过）
- 写入 `<WORKSPACE_DIR>\runtime_env.json`

### 手动方式

1. **验证视频目录**：确认目录存在且含视频文件（`.mp4/.mov/.avi/.mkv/.webm/.m4v/.wmv`），**仅检查顶层，不递归**。
2. **创建工作区**：`<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS`（当前本地时间，每次新建）
3. **保存用户输入**：写入 `<WORKSPACE_DIR>\user_input.txt`
4. **提取需求**：

| 要素 | 默认值（用户未指定时） |
|------|----------------------|
| `target_duration_seconds` | `30` |
| `theme` | 根据视频内容自动推断 |
| `mood` | `轻松自然` |
| `pacing` | `连贯流畅` |
| `must_capture` | 留空 |

> 若用户提供了 theme/mood/pacing/must_capture 中任意一个，使用需求驱动提示词模板；全部未提供时使用默认提示词。

5. **写入 `runtime_env.json`**：后续阶段优先参考其中的 `venv_python` / `ffmpeg` / `ffprobe` / `model_dir`

**✓ 自检：** 工作区已创建 · 视频文件 ≥ 1 · `.venv` 就绪 · `ffmpeg.exe`/`ffprobe.exe` 存在 · 模型目录完整 · `runtime_env.json` 已写入

---

## 阶段 2：分析

### 快速模式

检查 `<VIDEO_DIR>\output_vlm.json` 是否存在：
- **存在** → 直接复制到 `<WORKSPACE_DIR>\output_vlm.json`，跳过分析，进入阶段 3
- **不存在** → 执行完整分析流程

### 步骤 2.1 确认阶段 1 已完成

确认 `<WORKSPACE_DIR>` 已存在、`.venv` 就绪、模型目录完整。

### 步骤 2.2 运行分析

```bash
"<VENV_PYTHON>" "<SKILL_DIR>\scripts\analyze_video.py" --video-dir "<VIDEO_DIR>" --output "<WORKSPACE_DIR>\output_vlm.json" --model-dir "<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4" --theme "<THEME>"
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--device` | `GPU` | GPU 失败时可回退 `CPU` |
| `--seg-duration` | `3.0` | 段时长（秒） |
| `--frames-per-seg` | `8` | 每段提取帧数 |
| `--model-dir` | `<SKILL_DIR>\\models\\Qwen2.5-VL-7B-Instruct-int4` | 仅 OpenVINO 模式使用；局域网模式下忽略本机模型目录 |
| `--theme` | 无 | **强烈建议传入**，与阶段 2.5 `--theme` 一致；触发「首行主题判定总结 + 标签」输出，便于 `select_clips.py` 解析 |
| `--prompt` | 见下 | 不传或与脚本内置默认相同时，在提供 `--theme` 下使用**主题感知模板**（首行判定 + 画面描述） |

**无 `--theme` 时的默认提示词（仅画面描述）：**
```
准确的描述这个视频片段中的主要内容，包括：场景环境、人物动作、画面构图、光线氛围、运镜方式。输出不超过100字的简要描述。
```

**有 `--theme` 时的输出约定（写入 `seg_desc`，供选片）：**

1. 第 1 行：先写一句基于画面的主题判定总结，句末括号中给出且只给出一个最终标签。标准格式示例：`主题判定: 画面以节庆灯笼为主体，节日氛围明确（符合）`
2. 标签只能是 `符合` / `部分符合` / `不符合` 之一；禁止输出 `符合/部分符合/不符合` 这种候选项列表
3. 第 2 行起：按默认画面描述要求输出（场景环境、人物动作、画面构图、光线氛围、运镜方式，不超过100字）

**需求驱动自定义 `--prompt`**（用户指定了 mood/pacing/must_capture 等需额外强调时）：仍建议保留 `--theme`；将 `--prompt` 设为例如：

```
请根据以下剪辑目标补充分析：氛围是「<MOOD>」，节奏要求「<PACING>」。重点捕捉与「<MUST_CAPTURE>」相关的画面线索；在遵守首行“主题判定总结 + 唯一标签”格式前提下，画面描述须突出与目标风格相关的信息，并包含场景环境、人物动作、画面构图、光线氛围、运镜方式，输出不超过100字。
```

（脚本会在自定义 `--prompt` 前自动附加「主题 + 首行判定格式」说明。）

### 步骤 2.3 验证输出

读取 `<WORKSPACE_DIR>\output_vlm.json`，确认格式：

```json
{
  "processed_videos": [{
    "input_video": "<VIDEO_DIR>\\video01.mp4",
    "segments": [{ "seg_id": 0, "seg_start": 0.0, "seg_end": 3.0, "seg_dur": 3.0, "seg_desc": "..." }]
  }]
}
```

**✓ 自检：** output_vlm.json > 0 bytes · `processed_videos` 非空 · 每个视频有 `segments`

---

## 阶段 2.5：片段预选（必须执行）

> **目的：** 在 AI 创作前，用脚本把全量素材压缩为与主题最相关的候选池，减轻阶段 3 负担。

### 参数自动推导（执行前必须计算）

在调用 `select_clips.py` 之前，**根据 `target_duration_seconds` 计算所需片段数和候选视频数**：

```
trans_dur  = 0.8       # 默认转场时长（秒）
seg_dur    = 3.0       # 每个分析段的时长（秒，与 analyze_video.py --seg-duration 一致）

# 根据目标时长自动推导每 clip 的段数（时长越长，每段越宽）
N_SEGS     = max(2, round((target_duration / 8 + 0.8) / seg_dur))
clip_dur   = N_SEGS * seg_dur                  # 每个 clip 的实际时长（秒）
N_CLIPS    = ceil(target_duration / (clip_dur - trans_dur))
MIN_VIDEOS = max(6, N_CLIPS)                   # 每个视频贡献 1 个 clip
```

| 目标时长 | N_SEGS | clip_dur | N_CLIPS | MIN_VIDEOS |
|---------|--------|----------|---------|-----------|
| 30s     | 2      | 6s       | 6       | 6         |
| 45s     | 2      | 6s       | 9       | 9         |
| 60s     | 3      | 9s       | 7       | 7         |
| 90s     | 4      | 12s      | 8       | 8         |

> **注：** 若可用视频数量不足 MIN_VIDEOS，select_clips.py 会自动从非主题视频补充至该数量。
> 将推导出的 `N_SEGS` / `N_CLIPS` / `MIN_VIDEOS` 保存，阶段 3 和 Guard 校验时复用。

### 运行 select_clips.py

```bash
"<VENV_PYTHON>" "<SKILL_DIR>\scripts\select_clips.py" \
    --output-vlm  "<WORKSPACE_DIR>\output_vlm.json" \
    --theme       "<THEME>" \
    --output      "<WORKSPACE_DIR>\candidate_clips.json" \
    --min-videos  <MIN_VIDEOS> \
    --n-segs      <N_SEGS> \
    [--extra-keywords "灯笼,烟花,喜庆"] \
    [--negative-keywords "自定义负面词1,自定义负面词2"]
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--min-videos` | `6` | 主题相关不足时从非相关视频补充至此数量（使用推导值） |
| `--n-segs` | `2` | 每个候选 clip 覆盖的连续段数（使用推导值；2≈6s，3≈9s，4≈12s） |
| `--min-clip-duration` | `1.5` | 单段最短时长阈值（秒）；配对后 clip 约 n_segs×3s，无需在此提高 |
| `--extra-keywords` | 空 | 额外主题关键词，逗号分隔 |
| `--negative-keywords` | 空 | 额外负面内容词，逗号分隔；命中则扣分（与内置默认词表叠加） |
| `--no-default-negatives` | 关闭 | 禁用内置负面词表，只使用 `--negative-keywords` 指定的词 |

**内置负面词表**（默认生效，无需手动填写）：

| 类别 | 词条 |
|------|------|
| 不看镜头 | 背对镜头、低头、没有看镜头 |
| 整理衣物 | 整理衣服/裤带/扣子、系扣子、系鞋带 |
| 使用设备 | 看手机、玩手机 |
| 画面质量 | 画面模糊、严重过曝、严重欠曝 |

> 用户有特殊场景（如 vlog 主题允许整理装备的慢镜头）可用 `--no-default-negatives` 关闭默认词表。

### 脚本执行逻辑

1. 从 `--theme` 生成整词 + 2-字 bigram 关键词列表
2. 逐片段评分：若 `seg_desc` 首行含 `主题判定: <总结>（符合/部分符合/不符合）`，**优先采用括号中的最终标签**（符合保底分、不符合强制 0 分、部分符合中间档；兼容旧版英文与旧版中文判定头），否则仅用句子级关键词与否定词匹配
3. 视频总分 = 所有片段得分之和；按总分降序排列
4. 选出全部 `video_score > 0` 的视频；不足 `--min-videos` 时用片段最丰富的剩余视频补充
5. 两轮选片：第 1 轮每视频取最高分 1 段（广覆盖），第 2 轮再取第 2 段
6. 两轮打散：第 1 轮全部排前（轮转，相邻不同源），第 2 轮紧随其后
7. 写出 `candidate_clips.json`

### candidate_clips.json 结构

```json
{
  "selection_metadata": {
    "theme": "节日庆典",
    "total_candidate_clips": 18,
    "selected_videos_count": 6,
    ...
  },
  "candidate_clips": [{
    "source_video": "<VIDEO_DIR>\\VID_xxx.mp4",
    "source_segment_id": 0,
    "timecode": { "in_point": 0.0, "out_point": 3.0, "duration": 3.0 },
    "seg_desc": "...",
    "theme_score": 4.0,
    "video_rank": 1,
    "paired_with_segment_id": 1  // paired 模式下额外字段：结束段 seg_id（source_segment_id 为起始段）
  }]
}
```

### 在阶段 3 中使用

若 `candidate_clips.json` 存在，**步骤 3.1 改为读取 candidate_clips.json**（而非 output_vlm.json）：
- `source_video` / `source_segment_id` / `timecode` 直接复制到 storyboard.json
- `seg_desc`、`theme_score`、`video_rank` 等辅助字段**不**写入 storyboard.json
- AI 可调整顺序或选取子集，但**不应从候选池以外引入新片段**
- 视为硬规则：若引入候选池外片段，`storyboard_guard.py --candidate-clips ...` 校验必然失败

**✓ 自检：** candidate_clips.json 已生成 · `total_candidate_clips` ≥ 6

---

## 阶段 3：创作

> **核心理念：叙事先行（字幕约束 S5）。** 先从素材中发现故事，再写完整字幕文案，最后为每句字幕匹配画面。

### 步骤 3.1 素材审阅与故事发现

逐条阅读 output_vlm.json（或 candidate_clips.json）的 `seg_desc`，将片段归入以下类别，并**过滤**内容重复、< 10 字或无实质信息的片段：

| 类别 | 识别特征 | 叙事作用 |
|------|---------|---------|
| **环境/全景** | 风景、建筑、天空、道路、山水 | 交代背景、营造氛围 |
| **人物/互动** | 人、动作、表情、穿着、互动 | 推进叙事、传递情感 |
| **运动/动态** | 运镜、移动、速度变化、行驶 | 营造节奏感 |
| **细节/局部** | 特定物体、局部画面、仪表盘、手部 | 点缀过渡、情绪强调 |
| **安静/静态** | 相对静止的画面、停歇 | 留白、情感沉淀 |

**问自己：**
- 这些素材讲的是什么体验？
- 最打动人的瞬间是哪几个 `seg_desc`？
- 用一句话概括这个 vlog 是什么？

**确定叙事角度：**

| 叙事角度 | 适用素材 | 示例主题句 |
|----------|---------|-----------|
| **感官沉浸** | 旅行、户外、美食 | "风吹过山谷的那一刻 世界安静了" |
| **情感回忆** | 日常、亲友、宠物 | "这些平凡的日子 原来就是幸福" |
| **成长发现** | 挑战、运动、学习 | "翻过那座山 才知道自己能走多远" |
| **自由释放** | 摩旅、极限、派对 | "引擎的声音里 所有烦恼都被甩在身后" |

**输出：** 一句话主题 + 叙事角度 + 情感弧线（如：`主题"公路尽头的答案" / 自由释放 / 好奇→沉浸→领悟`）

---

### 步骤 3.2 叙事脚本与画面匹配

#### 3.2.1 规划叙事节拍

**直接使用阶段 2.5 推导的 `N_CLIPS`，不要重新硬编码。**

片段数 = `ceil(target / (6.0 − transition_duration))`，例：`ceil(30/5.2)` = **6**，`ceil(60/5.2)` = **12**，每片段约 6s，来自不同视频，相邻片段均加转场

| 节拍 | 占比（参考 N_CLIPS） | 情感曲线 | 字幕功能 |
|------|---------------------|---------|---------|
| **开篇点题** | ~15%（≥2片） | 好奇/期待 | 抛出主题，制造悬念 |
| **铺陈展开** | ~25% | 渐入 | 展开体验 |
| **情感递进** | ~35% | 升温 | 层层深入 |
| **高潮时刻** | ~15% | 最强 | 最有力量的一句话 |
| **余韵收尾** | ~10%（≥1片） | 回落/升华 | 总结点睛，呼应开篇 |

#### 3.2.2 一气呵成写出全部字幕

按节拍表写出所有字幕，遵循字幕约束 **S1–S5**。

**字幕质量自检（写完后必须执行）：**
1. 所有字幕连续读——脱离画面是否仍是有意义的叙述？
2. 能感受到从起点到终点的情感弧线？
3. 第一句是否引发悬念？最后一句是否留有余韵？
4. 有没有在直白描述画面内容？（有则必须重写）
5. 有没有两句表达相同意思？（有则删/改）

**示例——同一组摩旅素材的好与坏：**

**差**（各说各话，重复，无故事）：
```
"出发，向着远方" → "风从耳边呼啸而过" → "山川湖海皆是风景"
→ "心之所向" → "阳光洒在山路上" → "此刻什么都不想"
→ "路在脚下" → "出发就是自由" → "风景在眼前流转"
```

**好**（完整叙事，有弧线）：
```
"一直想知道 公路尽头是什么"     ← 开篇：好奇，抛出悬念
"今天终于骑上了车"              ← 铺陈：出发
"引擎声代替了闹钟"              ← 铺陈：进入体验
"两旁的树 拼命往后退"           ← 递进：速度感
"风很大 什么都听不见"           ← 递进：沉浸
"但脑子从来没这么安静过"         ← 递进→转折：核心感悟
"远处那座山 越来越近了"          ← 递进：接近高潮
"原来只要一直往前 就真的能到"    ← 高潮：领悟
"停下来的时候 天已经变色了"      ← 收尾：时间流逝
"公路没有尽头 但每一段都值得"    ← 结尾：呼应开篇，升华
```

#### 3.2.3 为每句字幕匹配最佳片段

对每条字幕选 `seg_desc` 意境最匹配的片段，遵循 **Clip 约束 C1–C9**。

| 字幕情绪 | 应匹配的 seg_desc 类型 |
|----------|---------------------|
| 好奇/出发/期待 | 出发、加速、道路前方 |
| 自由/释放/沉浸 | 快速运动、开阔场景 |
| 安静/感悟 | 静态、柔和光线、远景 |
| 惊喜/发现 | 新场景出现、画面变化 |
| 温暖/治愈 | 人物互动、柔和环境 |

**选片附加规则：**
- 字幕与画面**互补**：字幕说感受，画面给证据
- 优先选 `seg_desc` 内容丰富的片段
- 避免连续 3+ 个同类场景；动静交替排列
- 当存在 `candidate_clips.json` 时，严格按以下顺序选片：
  1) 先做“首轮覆盖”：只从“存在 `主题判定: <总结>（符合）` 片段”的 `source_video` 中取，每个视频先取 1 段（且该段最终标签必须为“符合”）
  2) 若首轮后仍未达到目标片段数，再做“第二轮补齐”：从“仅有部分符合、无符合片段”的视频中按 `video_score` 从高到低补 1 段
  3) 若第二轮后仍不够，再允许重复 `source_video`，按 `video_score` 从高到低补第 2 段、第 3 段
  4) 在满足上面规则后，再做叙事情绪与节奏微调（不得破坏 C1/C3/C4）
- 即使当前时长已经满足，只要仍可先覆盖更多高优先级不同视频，也**不得过早重复 `source_video`**

#### 3.2.4 字幕-画面二次对齐（必做）

**选片完成后**，逐条对照每个 clip 的 `seg_desc` 与其字幕，执行以下检查：

| 矛盾类型 | 判定标准 | 修复方式 |
|---------|---------|---------|
| **动静矛盾** | 字幕描述速度/风/运动感，但 seg_desc 显示人物静止/停车/站立 | 改写字幕为与"静"对应的感受（等待、蓄力、出发前的安静） |
| **场景矛盾** | 字幕说"一个人"，画面有多人；或反之 | 字幕去掉人称冲突的描述 |
| **环境矛盾** | 字幕说夜晚/下雨，画面是晴天/白昼 | 字幕改为与实际画面一致的环境感受 |
| **情绪矛盾** | 字幕轻松愉快，画面是快速激烈的运动镜头 | 允许互补，但方向不可对立（不能用沉重悲伤配轻快画面） |

**自检问题（逐片段回答）：**
> "如果观众同时看到这段画面和这句字幕，会觉得违和吗？"
> 若答案是"会"，必须改写字幕，字幕服从画面——画面不可更改，字幕可改。

**改写原则：** 字幕仍须说感受和想法（S3），但感受必须能从该画面中合理生发。
- ✅ 画面：男人静止站在路边看摩托 → 字幕可写："出发前的那一刻最安静" / "站在这里望着前方，心早已在路上"
- ❌ 画面：男人静止站在路边看摩托 → 字幕写："两旁的树拼命往后退"（画面没有速度感）

---

### 步骤 3.3 整体审视与迭代

| 维度 | 检查点 |
|------|--------|
| 叙事连贯 | 相邻字幕情感跳跃是否过大？有断裂则插入过渡 |
| 画面节奏 | 是否有动静交替？连续单调则调换顺序或替换 |
| 字幕-画面一致 | **无动静矛盾、场景矛盾、环境矛盾**（已在 3.2.4 处理） |
| 开头/结尾质量 | 这两个位置最重要，不理想优先替换 |

发现问题则回到 3.2.2/3.2.3/3.2.4 调整，通常迭代 1-2 轮即可。

#### 3.3.1 Guard 失败后的重选与重写

`storyboard_guard.py` 只负责报告问题，**不做自动修复**。因此当 validate 返回非 0 时，必须按下述流程重新生成一版完整的 `storyboard.json`：

1. 先完整阅读 `validation_errors`
2. 判断错误属于哪一类：非法片段 / 覆盖不足 / 相邻同源 / 每源过多 / 时长偏差 / 时码或 seg_id 非法 / 字幕为空
3. 回到 `candidate_clips.json` 重新选片或重排；必要时重写全部字幕，不要只局部打补丁
4. **始终重新生成整个 `storyboard.json`**，不要在旧文件上做零散修补
5. 写入后重新运行 `storyboard_guard.py --mode validate`
6. 只有 validate 返回 `0`，才允许进入阶段 4

**重写原则：**
- 优先保留叙事主线，再修正局部选片
- 若一个片段被替换，必须重新检查它前后两句字幕是否仍连贯
- 若错误涉及覆盖率或时长，通常应整体重排片段顺序，而不是只替换单个 clip
- 若错误涉及 candidate 约束，所有片段必须重新以 `candidate_clips.json` 为唯一来源检查一遍

**`validation_errors` -> 处理动作对照表：**

| 错误特征 | 处理动作 |
|------|------|
| `片段不在 candidate_clips 中` | 删除该非法片段；只从 `candidate_clips.json` 中重选替代片段；重写该片段及其相邻 1-2 句字幕，确保叙事不断裂 |
| `source_video 覆盖不足` | 回到 `candidate_clips.json`，优先补入尚未使用的视频；按“先符合、后部分符合、最后才重复来源”的规则整体重排 |
| `相邻片段来自同一 source_video` | 优先交换顺序打散；若无法打散，则替换其中一段为别的候选视频；然后重读整段字幕，确认情绪过渡自然 |
| `超过每源上限` | 从超额视频中删去低优先级片段；优先补入未使用或使用更少的候选视频；必要时同步压缩重复表达的字幕 |
| `时长偏差过大` 且 **过长** | 优先删去 `video_score` 低、叙事贡献弱、与前后表达重复的片段；删片后必须重排顺序并重写结尾或过渡句 |
| `时长偏差过大` 且 **过短** | 优先从未使用的高分候选视频补 1 段；若已覆盖充分，再补重复来源的第 2/3 段；补片后重写新增位置前后字幕 |
| `存在过早重复来源` | 优先移除重复来源中的后续片段，补入尚未覆盖的高优先级候选视频；保持叙事主线不变，并重写被替换片段前后 1-2 句字幕 |
| `seg_id 不在 output_vlm` / `source_video 不在 output_vlm` | 视为非法引用；该片段整段废弃，重新从候选池中选择合法片段 |
| `duration != out-in` / `out_point <= in_point` | 不手工修数值；直接废弃该片段并从候选池中换一段合法片段 |
| `voiceover.text 为空` | 补写该句字幕；同时检查前后字幕是否仍满足 S1-S5，而不是只填一个空字符串 |

**重选顺序硬规则：**
- 第 1 轮：先从“存在 `主题判定: <总结>（符合）` 片段”的不同视频中，每视频取 1 段
- 第 2 轮：若还不够，再从“只有 `部分符合`、无 `符合`”的视频中，每视频取 1 段
- 第 3 轮：仍不够时，才允许重复来源，补第 2 段、第 3 段
- 即使时长已满足，只要仍有更高优先级且未覆盖的不同视频，重复来源也视为错误选片，应先补覆盖再允许重复
- 若当前时长已满足且 `unique_source_videos >= min_unique_videos`，不要为了覆盖率再主动引入新来源；只修非法片段、相邻同源或字幕问题

**重写 storyboard 的最小检查清单：**
- 所有 `(source_video, source_segment_id)` 均存在于 `candidate_clips.json`
- 相邻片段不同源
- 每源片段数不超过上限
- 实际时长大致落在 target 容差内
- 每句字幕不空、少描述画面、多表达感受
- 最终顺序仍然有开篇、展开、递进、收尾

---

### 步骤 3.4 BGM 选择

1. 读取 `<SKILL_DIR>\resource\bgm\bgm_style.json`
2. 先按主题匹配 `theme_tags`（每首 2-3 个主题），再用 `style_tag` 做兜底
3. 至少选出 2-3 首候选，优先避免与最近一次视频使用同一首
4. 构建绝对路径：`<SKILL_DIR>\resource\bgm\<file_path>`（见路径规范）

| 视频氛围 | 首选分类 | 备选分类 |
|----------|----------|----------|
| 早晨咖啡、轻松日常 | 清新明快 | 温暖治愈 |
| 城市出行、街头记录 | 都市活力 | 清新明快 |
| 山野旅行、风景大片 | 史诗壮阔 | 阳光热带 |
| 居家治愈、烹饪收纳 | 温暖治愈 | 慵懒治愈 |
| 海边假日、夏日出行 | 阳光热带 | 清新明快 |
| 冥想放松、护肤瑜伽 | 空灵舒缓 | 慵懒治愈 |
| 健身运动、速度感画面 | 高能激燃 | 都市活力 |
| 秋冬文艺、安静叙事 | 忧郁诗意 | 空灵舒缓 |
| 节庆、年味、热闹场景 | 欢腾热闹 / 红火喜庆 | 温馨雪夜 |
| 美食探店、烟火气 | 慵懒爵士 | 清新明快 |
| 科技产品、数码展示 | 极简未来 | 都市活力 |
| 广告视频（品牌/产品/促销） | 极简未来 / 都市活力 / 清新明快 | 慵懒爵士 / 欢腾热闹 |
| 其他氛围 | 温暖治愈 | 清新明快 |

BGM 自动循环、淡入 1s + 淡出 1.5s，与原视频音频 amix 混合（compose_video.py 自动处理）。
匹配优先级：`theme_tags` 命中 > `style_tag` 首选 > `style_tag` 备选 > 任选一首。

---

### 步骤 3.5 转场效果选择

| 转场 | 适用场景 |
|------|----------|
| `fade` | **主力**（80%+），万能 |
| `fadeblack` | 时间流逝、章节分隔、递进→高潮、收尾→结束 |
| `fadewhite` | 梦幻/回忆感 |
| `smoothleft/right` | 镜头有方向运动（空间延续） |
| `smoothup` | 情感升华 |
| `smoothdown` | 节奏放缓 |
| `circleopen/close` | 现代感点缀，整片最多 1-2 次 |
| `dissolve` | 尽量少用 |

**规则：** 默认 `transition.duration = 0.8s`；`smooth*` 仅在镜头有方向运动时使用；最后一个片段**不加**转场。

---

### 步骤 3.6 输出 storyboard.json

**始终重新生成，绝不复用。** 写入 `<WORKSPACE_DIR>\storyboard.json`。

**写入前验证：**
1. `theme`、`target_duration_seconds` 存在
2. Clip 约束 **C1–C9** 全部满足
3. 字幕约束 **S1-S4** 全部满足（特别是 S2：`voiceover.text` 必须使用 `|` 分段，且段数 = `ceil(duration/3.0)`）
4. `transition.type` 是有效值；最后一个片段无 transition
5. 粗估实际时长与 target 大致匹配（见全局规范时长公式）
6. BGM `file_path` 是绝对路径且文件存在

**写入后立即执行 Guard 校验（见全局规范）。**

**✓ 自检：** 6 项验证通过 · storyboard.json 已写入 · guard validate 返回 0

**完整 Schema：**
```json
{
  "storyboard_metadata": {
    "theme": "摩旅自由行",
    "target_duration_seconds": 30
  },
  "clips": [
    {
      "clip_id": 1,
      "sequence_order": 1,
      "source_video": "<VIDEO_DIR>\\test(01).mp4",
      "source_segment_id": 0,
      "timecode": { "in_point": 0.0, "out_point": 3.0, "duration": 3.0 },
      "voiceover": { "text": "风从耳边呼啸而过" },
      "transition": { "type": "fade", "duration": 0.8 }
    },
    {
      "clip_id": 2,
      "sequence_order": 2,
      "source_video": "<VIDEO_DIR>\\test(00).mp4",
      "source_segment_id": 3,
      "timecode": { "in_point": 9.0, "out_point": 12.0, "duration": 3.0 },
      "voiceover": { "text": "这一刻什么都不想" }
    }
  ],
  "audio_design": {
    "background_music": {
      "file_path": "<SKILL_DIR>\\resource\\bgm\\xxx.mp3",
      "style_tag": "舒缓优美",
      "theme_tags": ["日常旅游", "城市漫游"]
    }
  }
}
```

---

## 阶段 4：合成

### 步骤 4.0 Guard 校验 + 时长粗检

进入阶段 4 前必须先执行 Guard 校验（见全局规范），返回 0 后再粗估时长是否与 target 大致匹配；差距明显则回到步骤 3.6 调整。

### 步骤 4.1 运行合成

```bash
"<VENV_PYTHON>" "<SKILL_DIR>\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--font-size` | `55` | 字幕字号 |
| `--max-line-len` | `16` | 每行最大字符数 |
| `--target-resolution` | 自动 | 多数竖屏→`1080x1920`，否则→`1920x1080`；需固定画幅时传入 `WxH`（如 `3840x2160`） |
| `--dry-run` | — | 仅打印命令不执行（调试用） |

**输出文件：** `<WORKSPACE_DIR>\<theme>_<duration>s_bgm.mp4`

合成失败时先加 `--dry-run` 检查生成的 ffmpeg 命令。

### 步骤 4.2 最终时长校验

```bash
"<SKILL_DIR>\bin\ffprobe.exe" -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "<OUTPUT_VIDEO>"
```

| 结果 | 动作 |
|------|------|
| 与 target 大致匹配 | 报告视频路径和时长，任务完成 |
| 差距明显 | 告知用户实际时长，由用户决定是否调整 |

**✓ 自检：** 最终视频文件存在 · 已向用户报告实际时长

---

## 错误处理

| 错误 | 解决方案 |
|------|----------|
| `.venv` 缺失或依赖不完整 | 重新运行 `prepare_workspace.py` |
| 模型目录不存在 | 重新运行阶段 1，或单独执行 `bootstrap.py` |
| 已启用 LAN VLM 但仍检查 GPU | 确认 `<SKILL_DIR>\\lan_vlm.json` 存在且 `enabled=true`、`backend=\"ollama\"` |
| LAN VLM 连接失败 | 检查 `base_url`（默认 `http://192.168.1.202:11434`）、局域网连通性、Ollama 服务状态 |
| LAN VLM 模型不存在 | 在局域网主机执行 `ollama list`，确认 `qwen2.5vl:7b` 已安装 |
| ffmpeg 未找到 | 重新运行阶段 1，或单独执行 `bootstrap.py` |
| GPU 初始化失败 | 添加 `--device CPU` 重试 |
| output_vlm.json 为空 | 检查控制台错误；可尝试 `--device CPU` |
| 可用段数 < 目标片段数 | 降低 `target_duration_seconds` 或告知用户补充素材 |
| compose_video.py 失败 | 加 `--dry-run` 检查命令；确认 `source_video` 路径正确 |
| BGM 路径无效 | 确认使用绝对路径：`<SKILL_DIR>\resource\bgm\` + 文件名 |

---

## 双路径验收清单（本机 / 局域网）

### A. 本机 OpenVINO 路径（无 `lan_vlm.json`）

1. 执行阶段 0，`check_platform.ps1` 按原逻辑做硬件检查。  
2. 执行阶段 1，模型目录会被检查/下载。  
3. 执行阶段 2，日志显示 OpenVINO 模型目录与设备信息。  
4. `output_vlm.json` 能被 `select_clips.py` 和 `storyboard_guard.py` 正常消费。  

### B. 局域网 Ollama 路径（有 `lan_vlm.json`）

1. 根目录放置 `lan_vlm.json`，并设置：
   - `enabled=true`
   - `backend=\"ollama\"`
   - `base_url=\"http://192.168.1.202:11434\"`
   - `model=\"qwen2.5vl:7b\"`
2. 执行阶段 0，日志应显示“跳过硬件门禁，仅保留 Python 检查”。  
3. 执行阶段 1，日志应显示“自动跳过本机模型准备”。  
4. 执行阶段 2，日志应显示后端为 Ollama，并成功生成 `output_vlm.json`。  
5. 阶段 2.5 / 3 / 4 全流程可继续，输出结构与本机路径保持一致。  
