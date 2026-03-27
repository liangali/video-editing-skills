---
name: video-editing-skills
description:
  提供 vlog 剪辑工作流：使用 analyze_video.py (OpenVINO GenAI) 分析视频、
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
| `<SKILL_DIR>` | 本 SKILL.md 文件所在目录 | 运行时动态解析，见下方伪代码 |
| `<VIDEO_DIR>` | 用户提供的视频目录 | 用户传入的实际路径 |
| `<WORKSPACE_DIR>` | 工作区 = `<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS` | 由 `<VIDEO_DIR>` + 时间戳派生 |
| `<VENV_PYTHON>` | 统一 Python = `<SKILL_DIR>\.venv\Scripts\python.exe` | 由 `<SKILL_DIR>` 派生 |

**解析 `<SKILL_DIR>` 的伪代码：**
```
如果 SKILL.md 位于 X:\path\to\video-editing-skills\SKILL.md
则 <SKILL_DIR> = X:\path\to\video-editing-skills
不是 X:\path\to，不是当前工作目录，不是 git 根目录
```

**时间戳格式 `YYYYMMDD_HHMMSS`：** 年(4位)月(2位)日(2位)\_时(24h,2位)分(2位)秒(2位)。示例：`editing_20260326_143045`

### 命令模板

```bash
# 阶段 0: 平台检查
powershell -ExecutionPolicy Bypass -File "<SKILL_DIR>\scripts\check_platform.ps1"

# 阶段 1: 准备工作区 + 统一 bootstrap
python "<SKILL_DIR>\scripts\prepare_workspace.py" --video-dir "<VIDEO_DIR>" --user-request "<USER_REQUEST>"

# 阶段 2: 视频分析（始终重新运行）
"<VENV_PYTHON>" "<SKILL_DIR>\scripts\analyze_video.py" --video-dir "<VIDEO_DIR>" --output "<WORKSPACE_DIR>\output_vlm.json" --model-dir "<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4" --prompt "<PROMPT>"

# 阶段 3: AI 生成 storyboard.json（通过当前代理可用的文件写入工具写入）

# 阶段 4: 合成最终视频
"<VENV_PYTHON>" "<SKILL_DIR>\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

### 环境准备

```bash
python "<SKILL_DIR>\scripts\bootstrap.py"                # 统一准备 .venv / requirements / ffmpeg / 模型
```

---

## 工作流概览

```
阶段 0：平台检查      阶段 1：准备          阶段 2：分析                    阶段 3：创作          阶段 4：合成
┌─────────────────┐  ┌─────────────────┐     ┌─────────────────────────┐    ┌─────────────────┐     ┌─────────────────┐
│ 检测硬件平台    │  │ 验证视频目录    │     │ 运行 analyze_video.py   │    │ 故事大纲        │     │ 时长校验        │
│ 检查宿主Python  │─►│ 创建工作区      │────►│ 验证 output_vlm.json    │───►│ 选择片段+排序   │────►│ compose_video   │
│ [失败→终止]     │  │ 准备 .venv      │     └─────────────────────────┘    │ 旁白/字幕       │     │ 最终时长校验    │
│                 │  │ 安装依赖/资源   │                                  │ BGM + JSON输出  │     └─────────────────┘
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

** 自检：** 脚本输出包含"所有检查通过"且退出码 = 0

---

## 阶段 1：准备

### 自动化方式（推荐）

```bash
python "<SKILL_DIR>\scripts\prepare_workspace.py" --video-dir "<VIDEO_DIR>" --user-request "<用户原始请求>"
```

脚本最后一行输出工作区绝对路径，后续用作 `<WORKSPACE_DIR>`。阶段 1 会同时：
- 检查 / 创建 `<SKILL_DIR>\.venv`
- 按 `<SKILL_DIR>\requirements.txt` 安装依赖到统一 `.venv`
- 检查 / 下载 `<SKILL_DIR>\bin\ffmpeg.exe` 与 `ffprobe.exe`
- 检查 / 下载 `<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4`
- 写入 `<WORKSPACE_DIR>\runtime_env.json`

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

5. **准备统一运行时**：创建 `.venv` 并安装 requirements，确认 `ffmpeg.exe` / `ffprobe.exe` 存在，确认模型目录完整有效
6. **写入运行时清单**：写入 `<WORKSPACE_DIR>\runtime_env.json`，后续阶段优先参考其中的 `venv_python` / `ffmpeg` / `ffprobe` / `model_dir`

** 自检：**  工作区目录已创建  视频文件 ≥ 1  `.venv` 已就绪  `ffmpeg.exe` / `ffprobe.exe` 存在  模型目录完整  `runtime_env.json` 已写入

---

## 阶段 2：分析

### 快速模式判断

检查 `<VIDEO_DIR>\output_vlm.json` 是否存在：
- **存在** → 用户明确提供了已分析结果，**跳过阶段 2**，直接复制到 `<WORKSPACE_DIR>\output_vlm.json` 并进入阶段 3
- **不存在** → 执行下方完整分析流程

> 快速模式用于避免重复 VLM 分析（耗时较长）。用户必须自行确保该 JSON 与当前视频目录匹配。

### 步骤 2.1 确认阶段 1 已完成

确认 `<WORKSPACE_DIR>` 已存在、`.venv` 已就绪、模型目录完整。若阶段 1 未执行，必须返回阶段 1。

### 步骤 2.2 运行分析

```bash
"<VENV_PYTHON>" "<SKILL_DIR>\scripts\analyze_video.py" --video-dir "<VIDEO_DIR>" --output "<WORKSPACE_DIR>\output_vlm.json" --model-dir "<SKILL_DIR>\models\Qwen2.5-VL-7B-Instruct-int4" --prompt "<PROMPT>"
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
    "input_video": "<VIDEO_DIR>\\video01.mp4",
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

** 自检：**  output_vlm.json 文件大小 > 0  processed_videos 数组非空  每个视频有 segments

---

## 阶段 3：创作

> **核心理念：叙事先行。** 先从素材中发现故事，再用字幕构建完整叙事，最后为每一句叙事匹配画面。
> 字幕文案是视频的灵魂和主线——不是给画面"配字"，而是先写好一段完整的故事，再用画面去"演"这个故事。

### 步骤 3.1 素材审阅与故事发现

**目标**：通读全部 VLM 分析结果，理解素材全貌，找到隐藏在素材中的"故事"。

#### 1. 通读与分类

逐条阅读 output_vlm.json 中每个视频每个段的 `seg_desc`，将片段归入以下类别：

| 类别 | 从 seg_desc 中识别 | 叙事作用 |
|------|-------------------|---------|
| **环境/全景** | 提到风景、建筑、天空、道路、山水等大场景 | 交代背景、营造氛围 |
| **人物/互动** | 提到人、动作、表情、穿着、互动 | 推进叙事、传递情感 |
| **运动/动态** | 提到运镜、移动、速度变化、行驶 | 营造节奏感、动感 |
| **细节/局部** | 提到特定物体、局部画面、仪表盘、手部等 | 点缀过渡、情绪强调 |
| **安静/静态** | 描述相对静止的画面、停歇 | 呼吸留白、情感沉淀 |

同时**过滤低质量片段**：跳过 seg_desc 内容重复（VLM 循环输出）、过于简短（< 10 字）或无实质信息的片段。

#### 2. 提炼故事主线

问自己三个问题：
- 这些素材**讲的是什么体验**？（一次旅行？一次聚会？一个日常？）
- 这段体验中**最打动人的瞬间**是哪几个 seg_desc？
- 如果用**一句话**概括这个 vlog，那句话是什么？

#### 3. 确定叙事角度

从以下角度中选择最匹配素材内容的一种：

| 叙事角度 | 适用素材 | 叙事核心 | 示例主题句 |
|----------|---------|---------|-----------|
| **感官沉浸** | 旅行、户外、美食 | "我感受到了..." | "风吹过山谷的那一刻 世界安静了" |
| **情感回忆** | 日常、亲友、宠物 | "我想起了..." | "这些平凡的日子 原来就是幸福" |
| **成长发现** | 挑战、运动、学习 | "我发现了..." | "翻过那座山 才知道自己能走多远" |
| **自由释放** | 摩旅、极限、派对 | "我终于..." | "引擎的声音里 所有烦恼都被甩在身后" |

#### 4. 规划情感弧线

确定情感走向：从什么情绪出发 → 经历什么变化 → 落在什么情绪上。
例如：好奇/期待 → 兴奋/沉浸 → 感悟/平静

**输出**：一句话主题 + 叙事角度 + 情感弧线（如：`主题"公路尽头的答案" / 自由释放 / 好奇→沉浸→领悟`）

---

### 步骤 3.2 叙事脚本与画面匹配

> **先写完整的字幕文案，再为每句话选画面。** 这是本流程最核心的步骤。

#### 3.2.1 规划叙事节拍

根据目标时长和节奏（默认每片段约 3s），确定总片段数，然后按以下节拍分配：

| 节拍 | 片段数（30s 约 10 片段） | 情感曲线 | 字幕功能 |
|------|------------------------|---------|---------|
| **开篇点题** | 1-2 个 | 好奇/期待 | 抛出主题，制造悬念或引发共鸣 |
| **铺陈展开** | 2-3 个 | 渐入 | 展开体验，描述出发/过程中的感受 |
| **情感递进** | 3-4 个 | 升温 | 内心感受层层深入，逐步靠近核心情感 |
| **高潮时刻** | 1-2 个 | 最强 | 全篇最有力量的一句话 |
| **余韵收尾** | 1-2 个 | 回落/升华 | 总结、点睛、呼应开篇 |

#### 3.2.2 一气呵成写出全部字幕

按节拍表写出**所有片段的字幕文案**，核心要求：

- **完整叙事**：所有字幕连续读起来必须是一段**有头有尾、有情感弧线的完整独白**
- **每条 ≤ 15 字**（中文），第一人称
- **绝不描述画面**（观众自己能看到画面，字幕要说的是画面背后的感受和想法）
- **前后衔接**：相邻两条字幕之间必须有逻辑连接或情绪递进，不能各说各话
- **不重复**：同一个意思不要用不同的话说两遍

**字幕质量自检**（写完后必须执行）：

1. 把所有字幕按顺序连起来读——**脱离画面是否仍然是一段有意义的叙述**？
2. 能否感受到**情感从起点到终点的变化弧线**？
3. 第一句是否**引发好奇或制造悬念**？最后一句是否**留有余韵**？
4. 有没有任何一句在**直白描述画面内容**？（如有，必须重写）
5. 有没有两句字幕**表达了相同的意思**？（如有，删除或改写其中一句）

**示例——同一组摩旅素材的好与坏：**

**差的字幕**（各说各话，没有故事）：
```
"出发，向着远方" → "风从耳边呼啸而过" → "山川湖海皆是风景"
→ "心之所向" → "阳光洒在山路上" → "此刻什么都不想"
→ "路在脚下" → "出发就是自由" → "风景在眼前流转"
→ "这就是生活" → "下一站更远的地方"
```
问题：前后不连贯，"出发""自由""风景"各重复两次，#5 在描述画面，整体像一堆随机拼凑的鸡汤。

 **好的字幕**（完整叙事，有弧线）：
```
"一直想知道 公路尽头是什么"          ← 开篇：好奇，抛出悬念
"今天终于骑上了车"                   ← 铺陈：出发
"引擎声代替了闹钟"                   ← 铺陈：进入体验
"两旁的树 拼命往后退"                ← 递进：速度感
"风很大 什么都听不见"                ← 递进：沉浸
"但脑子从来没这么安静过"              ← 递进→转折：核心感悟
"远处那座山 越来越近了"               ← 递进：接近高潮
"原来只要一直往前 就真的能到"          ← 高潮：领悟
"停下来的时候 天已经变色了"            ← 收尾：时间流逝
"公路没有尽头 但每一段都值得"          ← 结尾：呼应开篇，升华
```
特点：连续读就是一个完整故事（好奇→出发→沉浸→领悟→感慨），每句都在推进叙事，没有重复。

#### 3.2.3 为每句字幕匹配最佳片段

对每一条字幕，从 output_vlm.json 的可用片段中选择 seg_desc **意境最匹配**的片段：

| 字幕情绪/内容 | 应匹配的 seg_desc 类型 |
|--------------|---------------------|
| 好奇/出发/期待 | 描述出发、加速、道路前方的片段 |
| 自由/释放/沉浸 | 描述快速运动、开阔场景的片段 |
| 安静/沉思/感悟 | 描述静态、柔和光线、远景的片段 |
| 惊喜/发现 | 描述新场景出现、画面变化的片段 |
| 温暖/治愈 | 描述人物互动、柔和环境的片段 |

**匹配原则**：
- 字幕和画面**互补**而非重复——字幕说感受，画面给证据
- 同一 `(source_video, source_segment_id)` 不可复用
- 优先选 seg_desc 内容丰富的片段，跳过内容贫乏或重复的片段
- `source_segment_id` 必须是 output_vlm.json 中对应视频的有效 `seg_id`
- `in_point` = 该 seg_id 的 `seg_start`，`out_point` = `seg_end`，`duration` = `out_point - in_point`

**画面节奏**：
- 避免连续 3+ 个 seg_desc 描述同类场景的片段
- 动态描述与静态描述的片段交替排列
- 片段时长：最短 ≥ 1.5s，最长 ≤ 目标时长的 25%

---

### 步骤 3.3 整体审视与迭代

> **这一步决定成片质量。** 把字幕+片段作为一个整体审视，发现问题就回到 3.2 调整。

#### 审视维度

1. **叙事连贯性**：按 sequence_order 读所有字幕——有没有断裂感？相邻字幕情感跳跃是否过大？如有断裂，插入过渡性的字幕+片段。

2. **画面节奏**：连续片段的 seg_desc 是否单调？是否有动静交替？如果连续多个都是同类场景，调换顺序或替换片段。

3. **字幕-画面一致性**：每条字幕的情绪基调是否与对应 seg_desc 描述的场景氛围**方向一致**？（不要求完全匹配，但不能明显矛盾，如字幕说"安静"而画面是激烈运动）

4. **开头和结尾质量**：开头片段的 seg_desc 是否有吸引力？结尾片段是否适合收束？这两个位置最重要，如不理想优先替换。

**如果发现问题**：回到 3.2.2 调整字幕文案或 3.2.3 重新匹配片段，然后再次审视。通常迭代 1-2 轮即可。

### 步骤 3.4 BGM 选择

**必须选择恰好一首 BGM，使用绝对路径。**

**步骤：**
1. 读取 `<SKILL_DIR>\resource\bgm\bgm_style.json`（注意编码是 UTF-8-sig）
2. 根据下表匹配分类，选择该分类中的一首曲目
3. 构建绝对路径：`<SKILL_DIR>\resource\bgm\<file_path>`

**当前 BGM 库覆盖 3 个分类**（舒缓优美 1 首、温馨浪漫 2 首、轻松愉悦 7 首）：

| 视频氛围 | 首选分类 | 备选分类 |
|----------|----------|----------|
| 日常诗意、文艺清新 | 舒缓优美 | 温馨浪漫 |
| 温暖治愈、情感回忆 | 温馨浪漫 | 舒缓优美 |
| 轻松日常、休闲惬意、旅行出行 | 轻松愉悦 | 温馨浪漫 |
| 节日欢庆、活力动感 | 轻松愉悦 | 温馨浪漫 |
| 其他氛围 | 舒缓优美 | 轻松愉悦 |

**BGM 音频行为**（compose_video.py 自动处理）：
- BGM 循环播放至视频结束，自动淡入 1s + 淡出 1.5s
- 如原视频含音频（人声/环境音），自动混合保留
- BGM 通过 amix 与原视频音频混合

**无匹配时回退**：首选分类无合适曲目 → 查备选分类 → 仍无 → 任选一首

### 步骤 3.5 转场效果选择

为每个片段（除最后一个）选择到下一个片段的转场效果。转场应自然流畅，不生硬突兀。

**可用转场类型：**

| 转场 | 效果 | 适用场景 |
|------|------|----------|
| `fade` | 淡入淡出 | **主力**，万能，任何场景（80%+） |
| `fadeblack` | 经黑色过渡 | 时间流逝、章节分隔 |
| `fadewhite` | 经白色过渡 | 梦幻/回忆感 |
| `smoothleft` | 平滑左移 | 空间延续、方向性运动 |
| `smoothright` | 平滑右移 | 空间延续、方向性运动 |
| `smoothup` | 平滑上移 | 情感升华 |
| `smoothdown` | 平滑下移 | 节奏放缓 |
| `dissolve` | 溶解 | 少用，效果不够自然 |
| `circleopen` | 圆形展开 | 现代感点缀（少用） |
| `circleclose` | 圆形收缩 | 聚焦/收束（少用） |

**按叙事位置选择转场：**

| 位置 | 推荐转场 | 原因 |
|------|----------|------|
| 开场→引入 | `fade` | 柔和进入 |
| 引入→递进 | `fade` | 自然衔接 |
| 递进段之间 | `fade` 为主 | 保持流畅 |
| 递进→高潮 | `fadeblack` | 情感升华 |
| 高潮→收尾 | `fade` | 情感过渡 |
| 收尾→结束 | `fadeblack` | 留下余韵 |

**规则：**
- 默认 `transition.duration` = `0.8` 秒
- 80%+ 片段使用 `fade`，其余可用 `fadeblack`/`smooth*` 偶尔点缀
- `dissolve` 尽量少用（效果不够自然）
- `smooth*` 仅在镜头有方向运动时使用
- `circle*` 整个视频最多 1-2 次
- 最后一个片段**不加**转场（无后续片段）
- 注意：转场会使总时长缩短（每个 0.8s 转场减少 0.8s 总时长）

### 步骤 3.6 输出 storyboard.json

**始终重新生成，绝不复用。** 写入 `<WORKSPACE_DIR>\storyboard.json`。

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
      "timecode": {
        "in_point": 0.0,
        "out_point": 3.0,
        "duration": 3.0
      },
      "voiceover": {
        "text": "风从耳边呼啸而过"
      },
      "transition": {
        "type": "fade",
        "duration": 0.8
      }
    },
    {
      "clip_id": 2,
      "sequence_order": 2,
      "source_video": "<VIDEO_DIR>\\test(00).mp4",
      "source_segment_id": 3,
      "timecode": {
        "in_point": 9.0,
        "out_point": 12.0,
        "duration": 3.0
      },
      "voiceover": {
        "text": "这一刻什么都不想"
      }
    }
  ],
  "audio_design": {
    "background_music": {
      "file_path": "<SKILL_DIR>\\resource\\bgm\\xxx.mp3",
      "style_tag": "舒缓优美"
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
- `voiceover.text`：字幕文本，**每个片段必须有字幕**（不可为空）
- `transition.type`：转场类型（见上表），最后一个片段省略此字段
- `transition.duration`：转场时长，默认 0.8 秒
- `file_path`：BGM 的**绝对路径**

#### 写入前必须验证

1. `theme`、`target_duration_seconds` 两个必需字段存在
2. 每个 clip：`out_point > in_point` 且 `duration == out_point - in_point` 且 `duration > 0`
3. 每个 `source_video` 路径指向 `<VIDEO_DIR>` 中实际存在的文件
4. 每个 `source_segment_id` 在 output_vlm.json 对应视频的 seg_id 范围内
5. 无重复的 `(source_video, source_segment_id)` 组合
6. 每个 clip 的 `voiceover.text` 非空（每个片段必须有字幕）
7. 所有字幕连续读起来是一段完整连贯的叙事（非独立的散句）
8. `file_path` 是绝对路径且 BGM 文件存在
9. `transition.type` 必须是上表中的有效值
10. 最后一个片段不含 transition
11. 粗略估算实际输出时长是否与 target 大致匹配（实际时长 ≈ sum(durations) - 转场重叠总量，偏差合理即可）

**实际输出时长计算**：`sum(clip durations) - sum(有转场的片段的 transition.duration)`
即：逐个累加每个片段的 duration，再减去除最后一个片段外所有设置了 transition 的片段的 transition.duration。
例如：10 个 3s 片段 + 9 个 0.8s 转场 → 30 - 7.2 = 22.8s

> **注意**：compose_video.py 在运行时会自动将转场时长限制为相邻两个片段中较短者的一半。
> 如果某个转场 duration 超过此限制，实际时长会比上述公式计算值略长。

**时长偏差参考**：如果实际输出时长与 target 差距较大，可考虑：
- 总时长偏长 → 酌情移除叙事贡献较低的片段
- 总时长偏短 → 酌情添加与叙事匹配的新片段

** 自检：**  11 项验证全部通过  storyboard.json 已写入

---

## 阶段 4：合成

### 步骤 4.0 时长粗检

重新读取 storyboard.json 粗略估算片段总时长，确认与 target 大致匹配。如差距明显，可回到步骤 3.6 酌情调整。

粗算公式：`actual ≈ sum(clip durations) - sum(transition durations)`，与 target 对比即可。

### 步骤 4.1 运行合成

```bash
"<VENV_PYTHON>" "<SKILL_DIR>\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--storyboard` | — | storyboard.json 路径（必需） |
| `--font-size` | `60` | 字幕字号 |
| `--max-line-len` | `16` | 每行最大字符数 |
| `--dry-run` | — | 仅打印命令不执行（调试用） |

**输出文件：** `<WORKSPACE_DIR>\<theme>_<duration>s_bgm.mp4`
例如：`摩旅自由行_30s_bgm.mp4`

**合成失败时**：先加 `--dry-run` 检查生成的 ffmpeg 命令，确认路径和参数正确。

### 步骤 4.2 最终时长校验

用 ffprobe 测量实际视频时长：
```bash
"<SKILL_DIR>\bin\ffprobe.exe" -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "<OUTPUT_VIDEO>"
```

| 结果 | 动作 |
|------|------|
| 时长与 target 大致匹配 | 向用户报告视频路径和时长，任务完成 |
| 时长差距明显 | 告知用户实际时长，由用户决定是否需要调整 |

** 自检：**  最终视频文件存在  已向用户报告实际时长  视频可播放

---

## 硬性规则

| 规则 | 说明 |
|------|------|
| 平台检查最先 | 退出码非 0 则终止全部 |
| 每次新建工作区 | 禁止从已有 `editing_*` 工作区读取任何文件 |
| 阶段 1 统一准备 | `.venv` / requirements / ffmpeg / 模型必须在阶段 1 完成 |
| 后续统一解释器 | 阶段 2 / 4 必须使用 `<SKILL_DIR>\.venv\Scripts\python.exe` |
| VLM 分析 | 默认重新运行；快速模式下可复用 `<VIDEO_DIR>\output_vlm.json` |
| 始终重新生成分镜 | 绝不复用 storyboard.json |
| 叙事先行 | 先写完整字幕叙事，再选画面匹配，不是先选片段再配文字 |
| 每个片段必须有字幕 | voiceover.text 不可为空 |
| 字幕必须是连贯叙事 | 所有字幕连续读必须是有头有尾的完整故事，不是散句 |
| 禁止重复片段 | (source_video, source_segment_id) 必须唯一 |
| BGM 绝对路径 | file_path 必须是绝对路径 |
| 时长大致匹配 | 以 target 为参考，无需精确卡阈值，差距明显时告知用户 |
| 路径用反斜杠 | 命令行参数和 JSON 中都用 `\\` |

---

## 错误处理

| 错误 | 解决方案 |
|------|----------|
| `.venv` 缺失或依赖不完整 | 重新运行 `python scripts/prepare_workspace.py --video-dir "<VIDEO_DIR>"` |
| 模型目录不存在 | 重新运行阶段 1，或单独执行 `python scripts/bootstrap.py` |
| ffmpeg 未找到 | 重新运行阶段 1，或单独执行 `python scripts/bootstrap.py` |
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
| 字幕文本过长 | 每 3s 控制在 10-15 个中文字 |
| 字幕空缺 | 每个片段必须有字幕，不可为空 |
| 字幕像散句/鸡汤 | 所有字幕连续读必须是完整叙事，不是独立的句子 |
| 字幕直白描述画面 | 字幕说感受和想法，不要描述观众能看到的内容 |
| seg_id 超出范围 | 核对 output_vlm.json 中的实际 seg_id |
| duration ≠ out_point - in_point | 三者必须一致 |
