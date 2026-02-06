---
name: video-editing-skills
description: "Vlog video editing workflow using local FLAMA for AI-powered video analysis, storyboard generation, and optional final video composition via compose_video.py. Use this skill when: (1) User provides a folder containing video files and asks to create a vlog editing script/storyboard, (2) User requests video clip analysis and selection for vlog creation, (3) User wants to generate a JSON-format video editing plan with specified duration (e.g., 30 seconds, 60 seconds), (4) User mentions keywords like 'vlog剪辑', '视频剪辑脚本', 'video storyboard', or 'editing script', (5) User wants to automatically render a final video from storyboard.json. This skill invokes the local flama.exe tool to analyze video segments using VLM, then generates professional storyboards with narrative structure, clip selection, voiceover suggestions, and timing information, and can call compose_video.py to render the final video."
---

# Vlog Storyboard Generator

AI-powered vlog editing workflow: video analysis → storyboard generation → final video composition.

---

## Quick Reference

### Key Paths

| Component | Path | Notes |
|-----------|------|-------|
| **FLAMA** | `%FLAMA_PATH%` or default below | Configurable via environment variable |
| FLAMA Default | `D:\data\code\flama_code\flama\build\bin\Release\flama.exe` | Fallback if env not set |
| **compose_video.py** | `<SKILL_DIR>\scripts\compose_video.py` | Relative to this skill |
| **BGM Directory** | `<SKILL_DIR>\resource\bgm\` | Contains 51 BGM files |
| **BGM Index** | `<SKILL_DIR>\resource\bgm\bgm_style.json` | BGM metadata |
| **Font File** | `<SKILL_DIR>\resource\font.ttf` | Subtitle font |

**Path Variables:**
- `<SKILL_DIR>` = `C:\Users\SAS\.claude\skills\video-editing-skills`
- `<VIDEO_DIR>` = User-provided video directory
- `<WORKSPACE_DIR>` = `<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS`

### Workspace Output Structure

```
<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS\
├── user_input.txt                    # Original user request
├── output_vlm.json                   # FLAMA analysis results
├── storyboard.json                   # Generated storyboard
├── <THEME>_<DURATION>s_bgm_<LLM>.mp4 # Final output video
└── temp\                             # Intermediate files
    ├── clip_01_*.mp4
    ├── merged_no_bgm.mp4
    └── *.concat.txt
```

### Required Storyboard Fields

**Must include in `storyboard_metadata`:**
- `theme` - Video theme/title
- `target_duration_seconds` - Target duration (e.g., 30)
- `cloud_llm_name` - LLM name (e.g., "ClaudeOpus")

**Must include in `audio_design.background_music`:**
- `file_path` - **Absolute path** to BGM file

**Must include in each `clips[]` item:**
- `clip_id`, `sequence_order`, `source_video`
- `timecode.in_point`, `timecode.out_point`, `timecode.duration`
- `voiceover.text` (for subtitles)

### Command Templates

```bash
# 1. Verify FLAMA exists
dir "D:\data\code\flama_code\flama\build\bin\Release\flama.exe"

# 2. Run FLAMA analysis (always run fresh, never reuse output_vlm.json)
cd /d "D:\data\code\flama_code\flama\build\bin\Release"
flama.exe --video_dir=<VIDEO_DIR> --mode=hw --json_file=<WORKSPACE_DIR>\output_vlm.json --prompt="<PROMPT>"

# 3. Compose final video
python "<SKILL_DIR>\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

---

## Workflow Overview

```
Phase 1: Preparation     Phase 2: Analysis      Phase 3: Creation       Phase 4: Composition
┌─────────────────┐     ┌─────────────────┐    ┌─────────────────┐     ┌─────────────────┐
│ 1.1 Validate    │     │ 2.1 Find FLAMA  │    │ 3.1 Story       │     │ 4.1 Run         │
│     Video Dir   │────►│ 2.2 Run FLAMA   │───►│     Outline     │────►│     compose_    │
│ 1.2 Create      │     │ 2.3 Verify &    │    │ 3.2 Select Clips│     │     video.py    │
│     Workspace   │     │     Parse Output│    │ 3.3 Voiceover   │     └─────────────────┘
│ 1.3 Save Input  │     └─────────────────┘    │ 3.4 BGM         │
│ 1.4 Extract     │                            │ 3.5 Output JSON │
│     Requirements│                            └─────────────────┘
└─────────────────┘
```

---

## Phase 1: Preparation

### Step 1.1 Validate Video Directory

Verify directory exists and contains video files (`.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.m4v`, `.wmv`).

```bash
dir "<VIDEO_DIR>\*.mp4" "<VIDEO_DIR>\*.mov" "<VIDEO_DIR>\*.avi" "<VIDEO_DIR>\*.mkv"
```

### Step 1.2 Create Workspace

Create timestamped workspace folder:
```
<VIDEO_DIR>\editing_YYYYMMDD_HHMMSS
```

All outputs go into this workspace.

### Step 1.3 Save User Input

Write original user request to `<WORKSPACE_DIR>\user_input.txt`.

### Step 1.4 Extract User Requirements

Parse user request into:
- `target_duration_seconds` (default: 30)
- `theme` (e.g., 节日喜庆, 日常诗意)
- `mood` (e.g., 轻松活泼, 温暖治愈)
- `pacing` (e.g., 连贯流畅, 富有动感)
- `must_capture` (specific content priorities)

These requirements drive FLAMA prompting and storyboard creation.

---

## Phase 2: Analysis

### Step 2.1 Find FLAMA

**Search order:**
1. Environment variable `%FLAMA_PATH%` (if set)
2. Default: `D:\data\code\flama_code\flama\build\bin\Release\flama.exe`

Verify with: `dir "<FLAMA_PATH>"`

### Step 2.2 Run FLAMA Analysis

**CRITICAL: Always run fresh. Never reuse existing output_vlm.json.**

```bash
cd /d "D:\data\code\flama_code\flama\build\bin\Release"
flama.exe --video_dir=<VIDEO_DIR> --mode=hw --json_file=<WORKSPACE_DIR>\output_vlm.json --prompt="<PROMPT>"
```

**Prompt Selection:**

| Condition | Action |
|-----------|--------|
| User specified theme/mood/pacing | Use requirement-driven prompt |
| No specific requirements | Use default prompt |

**Default Prompt:**
```
准确的描述这个视频文件中的主要内容，包括：场景环境、人物动作、画面构图、光线氛围、运镜方式。输出不超过100字的简要描述。
```

**Requirement-Driven Prompt Template:**
```
请根据以下剪辑目标分析视频片段：主题是「<THEME>」，氛围是「<MOOD>」，节奏要求「<PACING>」。重点捕捉与「<MUST_CAPTURE>」相关的画面线索。描述中必须包含：场景环境、人物动作、画面构图、光线氛围、运镜方式，并突出与目标风格相关的信息。输出不超过100字。
```

**Example Prompts by Style:**

| Style | Prompt |
|-------|--------|
| 节日喜庆 | `请重点识别节日元素、欢庆互动、热闘场景和轻快节奏的镜头...突出喜庆与活力。输出不超过100字。` |
| 日常诗意 | `请重点识别日常场景中的诗意细节、情绪留白、光影变化与细腻动作...突出温柔与故事感。输出不超过100字。` |
| 连贯动感 | `请重点识别可形成连贯动作链的镜头、运动方向、速度变化与节奏点...突出流畅衔接与动感。输出不超过100字。` |

### Step 2.3 Verify & Parse Output

Verify `<WORKSPACE_DIR>\output_vlm.json` exists and read it.

**Output Structure:**
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

Extract: scene inventory, subjects, visual themes, camera work, highlight moments.

---

## Phase 3: Creation

### Step 3.1 Story Outline Development

Structure with narrative arc:
- **Opening Hook** (5-10%): Visually striking moment
- **Introduction** (10-15%): Establish context
- **Rising Action** (30-40%): Main narrative
- **Climax** (15-20%): Peak moment
- **Resolution** (10-15%): Wrap up
- **Outro** (5-10%): Final impression

### Step 3.2 Segment Selection & Sequencing

**Selection Criteria:**
1. Visual quality (well-lit, stable)
2. Content relevance to story
3. Variety (shot types)
4. Pacing balance
5. Requirement alignment

**Duration Guide:**
- 30s vlog → ~10 segments
- 60s vlog → ~20 segments
- 90s vlog → ~30 segments

**Rules:**
- Never reuse same segment (source_video + seg_id pair must be unique)
- Never start with static/boring shot
- Avoid similar shots consecutively

### Step 3.3 Voiceover/Caption Generation

- 10-15 words per 3-second segment max
- Match vlog mood (uplifting, reflective, etc.)
- Complement visuals, don't describe them

### Step 3.4 BGM Selection

**REQUIRED: Must select exactly one BGM.**

1. Read `<SKILL_DIR>\resource\bgm\bgm_style.json`
2. Match BGM to user requirements (theme, mood, pacing)
3. Write **absolute path** to storyboard

**BGM Path Construction:**
```
Absolute path = <SKILL_DIR>\resource\bgm\ + file_path from JSON
Example: C:\Users\SAS\.claude\skills\video-editing-skills\resource\bgm\0aa3bfd386bf595b301119302595aaf3.mp3
```

### Step 3.5 Output storyboard.json

**CRITICAL: Always write fresh. Never reuse existing storyboard.json.**

Write to: `<WORKSPACE_DIR>\storyboard.json`

**Minimal Required Schema:**
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

**Extended Fields (Optional):**
- `storyboard_metadata.version`, `generated_at`, `actual_duration_seconds`, `vlog_type`, `mood`, `user_requirements`
- `story_outline.title`, `synopsis`, `narrative_arc[]`
- `clips[].story_section`, `content_description`, `editorial_note`, `suggested_transition_in/out`, `music_note`
- `audio_design.background_music.mood`, `tempo`, `suggested_genres`, `volume_curve`
- `audio_design.sound_design.use_original_audio`, `ambient_enhancement`, `audio_ducking`
- `editing_notes.color_grading`, `pacing`, `special_effects`, `text_overlays[]`
- `export_recommendations.resolution`, `aspect_ratio`, `frame_rate`, `format`

---

## Phase 4: Composition

### Step 4.1 Run compose_video.py

```bash
python "C:\Users\SAS\.claude\skills\video-editing-skills\scripts\compose_video.py" --storyboard "<WORKSPACE_DIR>\storyboard.json"
```

**Script Behavior:**
1. Reads storyboard.json
2. Creates `<WORKSPACE_DIR>\temp\` folder
3. Extracts and processes each clip → saves to temp
4. Concatenates clips → `temp\merged_no_bgm.mp4`
5. Adds BGM from storyboard (falls back to random if path invalid)
6. Outputs final: `<WORKSPACE_DIR>\<THEME>_<DURATION>s_bgm_<LLM>.mp4`

**Output Naming:**
```
<theme>_<duration>s_bgm_<cloud_llm_name>.mp4
Example: 日常诗意瞬间_30s_bgm_ClaudeOpus.mp4
```

---

## Hard Requirements Summary

| Rule | Description |
|------|-------------|
| **Fresh Analysis** | Always run FLAMA fresh. NEVER reuse existing output_vlm.json |
| **Fresh Storyboard** | Always generate new storyboard. NEVER reuse existing storyboard.json |
| **No Duplicate Clips** | Each (source_video, source_segment_id) pair used at most once |
| **BGM Required** | Must select exactly one BGM with valid absolute path |
| **Workspace Output** | All files must be inside `<WORKSPACE_DIR>` |
| **Required Metadata** | theme, target_duration_seconds, cloud_llm_name must be present |
| **Absolute BGM Path** | `audio_design.background_music.file_path` must be absolute path |

---

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| FLAMA not found | Build not completed | Verify path, run build.bat |
| No video files | Wrong path/format | Check path and extensions |
| GPU init failed | Driver/hardware | Use `--mode=sw` |
| output_vlm.json empty | Processing failed | Check console errors |
| storyboard.json not created | Write failed | Check permissions |
| Insufficient segments | Short videos | Combine videos or adjust duration |
| BGM path invalid | Wrong path format | Use absolute path with proper escaping |

---

## Complete Example

**User Request:**
```
D:\data\videoclips\phone2\007_input 文件夹中包含多个视频，生成一个30秒vlog，连贯流畅、富有动感
```

**Execution:**

```bash
# 1. Validate
dir "D:\data\videoclips\phone2\007_input\*.mp4"

# 2. Create workspace
mkdir "D:\data\videoclips\phone2\007_input\editing_20250205_143000"

# 3. Save user input (via Write tool)

# 4. Run FLAMA
cd /d "D:\data\code\flama_code\flama\build\bin\Release"
flama.exe --video_dir=D:\data\videoclips\phone2\007_input --mode=hw --json_file=D:\data\videoclips\phone2\007_input\editing_20250205_143000\output_vlm.json --prompt="请重点识别可形成连贯动作链的镜头、运动方向、速度变化与节奏点，描述环境、动作、构图、光线和运镜，突出流畅衔接与动感。输出不超过100字。"

# 5. Read output_vlm.json, generate storyboard.json (via Write tool)

# 6. Compose
python "C:\Users\SAS\.claude\skills\video-editing-skills\scripts\compose_video.py" --storyboard "D:\data\videoclips\phone2\007_input\editing_20250205_143000\storyboard.json"
```

**Final Output:**
```
D:\data\videoclips\phone2\007_input\editing_20250205_143000\连贯动感_30s_bgm_ClaudeOpus.mp4
```
