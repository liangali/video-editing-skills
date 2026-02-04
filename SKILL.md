---
name: video-editing-skills-vlog
description: "Vlog video editing workflow using local FLAMA for AI-powered video analysis, storyboard generation, and optional final video composition via compose_video.py. Use this skill when: (1) User provides a folder containing video files and asks to create a vlog editing script/storyboard, (2) User requests video clip analysis and selection for vlog creation, (3) User wants to generate a JSON-format video editing plan with specified duration (e.g., 30 seconds, 60 seconds), (4) User mentions keywords like 'vlog剪辑', '视频剪辑脚本', 'video storyboard', or 'editing script', (5) User wants to automatically render a final video from storyboard.json. This skill invokes the local flama.exe tool to analyze video segments using VLM, then generates professional storyboards with narrative structure, clip selection, voiceover suggestions, and timing information, and can call compose_video.py to render the final video."
---

# Vlog Storyboard Generator

This skill analyzes video footage using the local FLAMA tool and generates professional vlog editing storyboards in JSON format.

## Prerequisites

### Required Components

1. **FLAMA Executable**: Located at `D:\data\code\flama_code\flama\build\bin\Release\flama.exe`
2. **Supporting Files**: All required DLLs and `config.json` in the same directory
3. **VLM Model**: Qwen2.5-VL model configured in config.json (default: `D:/data/models/Qwen2.5-VL-7B-Instruct-int4-opt`)
4. **GPU**: Intel GPU with D3D11VA support for hardware acceleration

### Supported Video Formats

- MP4 (H.264/H.265)
- MOV
- AVI
- MKV
- Other FFmpeg-compatible formats

---

## Workflow Execution Steps

### Step 1: Validate Input Video Directory

**Objective**: Verify the user-provided directory contains valid video files.

**Actions**:
1. Check if the specified directory path exists
2. Scan for video files with common extensions: `.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.m4v`, `.wmv`
3. List all discovered video files with their sizes

**Validation Rules**:
- Directory must exist and be accessible
- At least one valid video file must be present
- Video files should have reasonable file sizes (> 1KB)

**Error Handling**:
```
ERROR: Invalid video directory
- Path: [user_provided_path]
- Reason: [directory not found | no video files found | access denied]
- Action: Please provide a valid directory containing video files.
```

**Success Output**:
```
VIDEO INVENTORY:
- Found [N] video files in [directory_path]
- Files:
  1. filename1.mp4 (XX MB, estimated duration)
  2. filename2.mp4 (XX MB, estimated duration)
  ...
- Proceeding to video analysis...
```

---

### Step 2: Check for Existing output_vlm.json

**Objective**: Reuse prior analysis results when valid, otherwise prepare to run FLAMA.

**Actions**:
1. Check if `<USER_VIDEO_DIRECTORY>\output_vlm.json` exists
2. If it exists, validate that:
   - The file is valid JSON
   - It has a top-level `processed_videos` array
   - Each entry includes `input_video` and `segments`
   - Each segment has `seg_start`, `seg_end`, and `seg_desc`
3. If validation passes, **skip running flama.exe** and reuse `output_vlm.json`
4. If validation fails or file is missing, proceed to Step 3 and run flama.exe to regenerate `output_vlm.json`

**Validation Note**: If `output_vlm.json` is empty, malformed, or missing required fields, treat it as invalid and rerun analysis.

---

### Step 3: Verify FLAMA Tool Availability

**Objective**: Ensure the FLAMA video analysis tool is properly installed and accessible.

**FLAMA Installation Path**:
```
D:\data\code\flama_code\flama\build\bin\Release\
```

**Required Files**:
- `flama.exe` - Main executable
- `config.json` - Configuration file
- Required DLLs (OpenVINO, OpenVINO GenAI, FFmpeg, oneVPL dependencies)

**Verification Commands** (for the LLM to execute):
```bash
# Check if flama.exe exists
dir "D:\data\code\flama_code\flama\build\bin\Release\flama.exe"

# Check if config.json exists
dir "D:\data\code\flama_code\flama\build\bin\Release\config.json"
```

**Error Handling**:
```
ERROR: FLAMA tool not found
- Expected path: D:\data\code\flama_code\flama\build\bin\Release\flama.exe
- Action: Please ensure FLAMA is properly built and installed.
- Build instructions: See D:\data\code\flama_code\flama\README.md
```

---

### Step 4: Execute FLAMA Video Analysis

**Objective**: Run FLAMA to analyze all video files and generate segment descriptions.

**FLAMA Command Syntax**:
```bash
flama.exe --video_dir=<video_directory> --mode=hw --prompt="<analysis_prompt>"
```

**Recommended Analysis Prompt** (Chinese, optimized for vlog content):
```
准确的描述这个视频文件中的主要内容，包括：场景环境、人物动作、画面构图、光线氛围、运镜方式。输出不超过100字的简要描述。
```

**Alternative Prompts by Vlog Type**:

| Vlog Type | Recommended Prompt |
|-----------|-------------------|
| Travel | `描述视频中的地点特征、景观元素、氛围感受，以及镜头运动方式。输出不超过100字。` |
| Daily Life | `描述视频中的人物活动、环境背景、情绪氛围和画面特点。输出不超过100字。` |
| Food | `描述视频中的食物外观、烹饪过程、环境氛围和拍摄角度。输出不超过100字。` |
| Sports | `描述视频中的运动类型、动作特征、速度感和画面动态。输出不超过100字。` |

**Complete Execution Command**:
```bash
cd /d "D:\data\code\flama_code\flama\build\bin\Release"
flama.exe --video_dir=<USER_VIDEO_DIRECTORY> --mode=hw --json_file=<USER_VIDEO_DIRECTORY>\output_vlm.json --prompt="准确的描述这个视频文件中的主要内容，包括：场景环境、人物动作、画面构图、光线氛围、运镜方式。输出不超过100字的简要描述。"
```

**Execution Parameters**:
- `--video_dir`: User-provided video directory path
- `--mode=hw`: Hardware-accelerated decoding (recommended) or `sw` for software decoding
- `--json_file`: Output JSON file path for VLM results (should be `<USER_VIDEO_DIRECTORY>\output_vlm.json`)
- `--prompt`: Custom prompt for video analysis

**Expected Runtime**:
- Processing speed depends on video length, GPU capability, and number of files
- Typical: 3-second segments, ~1-2 seconds per segment analysis

---

### Step 5: Verify Analysis Output

**Objective**: Confirm successful generation of video analysis results.

**Output File Location**:
```
<USER_VIDEO_DIRECTORY>\output_vlm.json
```

The `output_vlm.json` file is saved to the user-specified video directory via the `--json_file` parameter.

**Verification**:
```bash
# Check if output file exists and has content
dir "<USER_VIDEO_DIRECTORY>\output_vlm.json"
```

**Error Handling**:
```
ERROR: Video analysis failed
- Expected output: <USER_VIDEO_DIRECTORY>\output_vlm.json
- Possible causes:
  1. GPU driver issues
  2. Insufficient GPU memory
  3. Corrupted video files
  4. VLM model not found
- Action: Check FLAMA console output for detailed error messages.
```

---

### Step 6: Parse and Understand Video Content

**Objective**: Read and comprehensively analyze the output_vlm.json file.

**Output JSON Structure**:

```json
{
  "processed_videos": [
    {
      "input_video": "D:\\path\\to\\video1.mp4",
      "prompt": "analysis prompt used",
      "segments": [
        {
          "seg_id": 0,
          "seg_start": 0.0,
          "seg_end": 3.003,
          "seg_dur": 3.003,
          "seg_desc": "视频片段的AI生成描述..."
        },
        {
          "seg_id": 1,
          "seg_start": 3.003,
          "seg_end": 6.006,
          "seg_dur": 3.003,
          "seg_desc": "下一个片段的描述..."
        }
      ]
    },
    {
      "input_video": "D:\\path\\to\\video2.mp4",
      "prompt": "analysis prompt used",
      "segments": [...]
    }
  ]
}
```

**Data Structure Explanation**:

| Level | Field | Description |
|-------|-------|-------------|
| Root | processed_videos | Array of all analyzed video files |
| Video | input_video | Full path to source video file |
| Video | prompt | The prompt used for analysis |
| Video | segments | Array of video segments (default ~3 seconds each) |
| Segment | seg_id | Sequential segment identifier (0-indexed) |
| Segment | seg_start | Start timestamp in seconds |
| Segment | seg_end | End timestamp in seconds |
| Segment | seg_dur | Segment duration in seconds |
| Segment | seg_desc | AI-generated content description |

**Analysis Guidelines**:

When reading output_vlm.json, extract and categorize the following:

1. **Scene Inventory**: List all unique locations/environments
2. **Subject Tracking**: Identify recurring subjects (people, objects, landmarks)
3. **Visual Themes**: Note lighting conditions, color palettes, mood
4. **Camera Work**: Identify shot types (wide, close-up, tracking, static)
5. **Temporal Flow**: Map the progression of events across all footage
6. **Highlight Moments**: Flag visually striking or emotionally impactful segments

---

### Step 7: Generate Vlog Storyboard

**Objective**: Create a professional vlog editing storyboard based on video analysis.

This is the creative core of the skill. Follow these sub-steps carefully:

#### 6.1 Story Outline Development

**Process**:
1. Review all segment descriptions to understand available footage
2. Identify a coherent narrative theme that emerges from the content
3. Structure the story with classic narrative arc:
   - **Opening Hook** (5-10%): Visually striking moment to capture attention
   - **Introduction** (10-15%): Establish context, location, or subject
   - **Rising Action** (30-40%): Build the main narrative
   - **Climax** (15-20%): Peak moment or highlight
   - **Resolution** (10-15%): Wrap up and provide closure
   - **Outro** (5-10%): Final impression or call-to-action

**Narrative Approaches by Content Type**:

| Content Type | Recommended Structure |
|--------------|----------------------|
| Travel | Arrival → Exploration → Discovery → Reflection |
| Daily Vlog | Morning → Activities → Highlights → Evening |
| Event | Preparation → Beginning → Peak Moments → Conclusion |
| Tutorial | Hook → Problem → Process → Result |
| Montage | Theme Introduction → Variations → Crescendo → Resolution |

#### 6.2 Segment Selection and Sequencing

**Selection Criteria**:

1. **Visual Quality**: Prioritize well-lit, stable, properly framed shots
2. **Content Relevance**: Match segments to story outline sections
3. **Variety**: Balance different shot types (wide/medium/close)
4. **Pacing**: Alternate between dynamic and calm segments
5. **Continuity**: Ensure logical visual flow between segments
6. **Duration Fit**: Select segments to meet target duration constraint
7. **No Duplicates**: Never reuse the same source segment. A `(source_video, source_segment_id)` pair must appear at most once in `clips`.

**Sequencing Rules**:

- **Never** start with a static or boring shot
- **Avoid** placing similar shots consecutively
- **Use** transition-friendly segments at cut points
- **Build** visual momentum toward climax
- **End** with a memorable, complete moment
- **Do Not Repeat Segments**: If a segment is already used, choose a different segment even if it looks similar.

**Duration Calculation**:

```
Target Duration: User-specified (e.g., 30 seconds, 60 seconds)
Available Segments: From output_vlm.json
Segment Unit: ~3 seconds each

For 30-second vlog: Select ~10 segments
For 60-second vlog: Select ~20 segments
For 90-second vlog: Select ~30 segments
```

#### 6.3 Voiceover/Caption Generation

**Guidelines**:

1. **Tone**: Match the vlog's mood (uplifting, reflective, exciting, calm)
2. **Length**: 10-15 words per 3-second segment maximum
3. **Style**: Conversational, engaging, not overly descriptive
4. **Function**: Complement visuals, don't merely describe them
5. **Rhythm**: Vary sentence length for natural flow

**Voiceover Types**:

| Type | When to Use | Example |
|------|-------------|---------|
| Narrative | Story-driven vlogs | "那天早晨，阳光正好..." |
| Reflective | Travel, personal vlogs | "这一刻，时间仿佛静止了" |
| Informative | Tutorial, educational | "这里有个小技巧..." |
| Emotional | Highlights, montages | "每一帧都是回忆" |
| Minimal | Action-heavy content | [Music only, sparse text] |

**Language Quality Standards**:
- 文字优美，富有画面感
- 节奏流畅，朗朗上口
- 情感真挚，不矫揉造作
- 主题升华，点睛之笔

#### 6.4 Output Storyboard JSON Format

**IMPORTANT**: The final storyboard MUST be written to a file named `storyboard.json` in the user's video directory (`<USER_VIDEO_DIRECTORY>\storyboard.json`). **Even if a storyboard.json already exists, always regenerate a new storyboard and overwrite it. Do not reuse existing storyboard.json.** Use the Write tool to create this file after generating the complete storyboard JSON content.

**Output File Location**:
```
<USER_VIDEO_DIRECTORY>\storyboard.json
```

**Complete Storyboard Schema**:

```json
{
  "storyboard_metadata": {
    "version": "1.0",
    "generated_at": "ISO8601 timestamp",
    "target_duration_seconds": 30,
    "actual_duration_seconds": 31.5,
    "total_clips": 10,
    "source_videos_count": 5,
    "vlog_type": "travel",
    "theme": "山间晨光之旅",
    "mood": "peaceful, inspiring"
  },

  "story_outline": {
    "title": "Vlog标题",
    "synopsis": "一句话概述整个视频的主题和情感基调",
    "narrative_arc": [
      {"section": "hook", "description": "开场镜头设计意图"},
      {"section": "introduction", "description": "背景介绍意图"},
      {"section": "rising_action", "description": "主体内容发展"},
      {"section": "climax", "description": "高潮部分设计"},
      {"section": "resolution", "description": "结尾收束方式"}
    ]
  },

  "clips": [
    {
      "clip_id": 1,
      "sequence_order": 1,
      "source_video": "D:\\path\\to\\source_video.mp4",
      "source_segment_id": 0,
      "timecode": {
        "in_point": 0.0,
        "out_point": 3.003,
        "duration": 3.003
      },
      "story_section": "hook",
      "content_description": "来自output_vlm.json的原始描述",
      "editorial_note": "选择此片段的理由和剪辑意图",
      "suggested_transition_in": "cut",
      "suggested_transition_out": "dissolve",
      "voiceover": {
        "text": "在云端之上，山峦起伏如画",
        "style": "reflective",
        "timing": "sync_with_visual"
      },
      "music_note": "轻柔钢琴，渐入"
    },
    {
      "clip_id": 2,
      "sequence_order": 2,
      "source_video": "...",
      "...": "..."
    }
  ],

  "audio_design": {
    "background_music": {
      "mood": "uplifting, peaceful",
      "tempo": "slow to medium",
      "suggested_genres": ["acoustic", "ambient", "piano"],
      "volume_curve": "fade in at start, peak at climax, fade out at end"
    },
    "sound_design": {
      "use_original_audio": true,
      "ambient_enhancement": "nature sounds where applicable",
      "audio_ducking": "lower music during voiceover"
    }
  },

  "editing_notes": {
    "color_grading": "温暖色调，略微提升对比度",
    "pacing": "前慢后快，高潮处加速剪辑",
    "special_effects": "可选：轻微的光晕效果",
    "text_overlays": [
      {"timecode": 0.0, "text": "标题", "style": "title"},
      {"timecode": 28.0, "text": "THE END", "style": "outro"}
    ]
  },

  "export_recommendations": {
    "resolution": "1080p or 4K based on source",
    "aspect_ratio": "16:9 or 9:16 for vertical",
    "frame_rate": "match source or 30fps",
    "format": "MP4 H.264"
  }
}
```

---

### Step 8: Compose Final Video with FFmpeg

**Objective**: Use the generated `storyboard.json` to automatically cut clips, overlay subtitles, and concatenate the final video.

**Tool**: `compose_video.py` located in:
```
D:\data\code\flama_code\video-editing-skills\video-editing-skills-vlog\scripts\compose_video.py
```

**Critical Requirement (Strict Execution)**:
- The cloud LLM **must** run the compose step **exactly** with the command shown below.
- **Do not** alter or invent any arguments.
- **Do not** pass `--output-name` or `--output-dir`.
- **Do not** change the output naming convention defined in `compose_video.py`. The final file naming must remain exactly as implemented there.

**Strict Command (Must Use As-Is)**:
```bash
cd /d "D:\data\code\flama_code\video-editing-skills\video-editing-skills-vlog\scripts"
python compose_video.py --storyboard D:\data\videoclips\phone2\007_input\storyboard.json
```

**Inputs (Reference Only; Do Not Override in Cloud LLM)**:
- `--storyboard`: Full path to `storyboard.json`
- `--ffmpeg`: Path to ffmpeg executable. If omitted, `compose_video.py` uses `..\bin\ffmpeg.exe` when present, otherwise `ffmpeg` in PATH.

**Optional Inputs** (Manual Local Use Only; cloud LLM must not use):
- `--font_file`: Path to subtitle font. Use a relative path from `scripts\compose_video.py`:
  - `..\resource\font.ttf`
- If `--font_file` is not provided and no default font is found, subtitle overlay will be skipped.
- `--output-dir`: Output folder (default: `<SOURCE_VIDEO_FOLDER>\output`)
- `--output-name`: Final output filename (default: `storyboard_merged.mp4`)

**Command Example** (Local Override Only; do not use in cloud LLM):
```bash
cd /d "D:\data\code\flama_code\video-editing-skills\video-editing-skills-vlog\scripts"
python compose_video.py --storyboard D:\data\videoclips\phone2\007_input\storyboard.json --ffmpeg ..\bin\ffmpeg.exe --font_file ..\resource\font.ttf
```

**Expected Output**:
- Intermediate clip files and the final merged video are written to:
```
<SOURCE_VIDEO_FOLDER>\output
```
- Final merged file default name:
```
storyboard_merged.mp4
```

---

## Complete Example Workflow

### User Request
```
这是 D:\data\videoclips\phone2\007_input 本地文件夹中包含了多个视频文件，
帮我生成一个简单30秒时长的vlog视频剪辑脚本，使用json格式输出
```

### Step-by-Step Execution

#### 1. Validate Input Directory
```bash
dir "D:\data\videoclips\phone2\007_input\*.mp4"
```
Output: List of video files found

#### 2. Verify FLAMA
```bash
dir "D:\data\code\flama_code\flama\build\bin\Release\flama.exe"
```
Output: File exists

#### 3. Execute Analysis
```bash
cd /d "D:\data\code\flama_code\flama\build\bin\Release"
flama.exe --video_dir=D:\data\videoclips\phone2\007_input --mode=hw --json_file=D:\data\videoclips\phone2\007_input\output_vlm.json --prompt="准确的描述这个视频文件中的主要内容，包括：场景环境、人物动作、画面构图、光线氛围、运镜方式。输出不超过100字的简要描述。"
```

#### 4. Verify Output
```bash
dir "D:\data\videoclips\phone2\007_input\output_vlm.json"
```

#### 5. Read and Analyze
Read the complete output_vlm.json file and extract:
- Total number of source videos
- Total available segments
- Scene variety and themes
- Potential highlight moments

#### 6. Generate Storyboard
Apply creative judgment to produce the final JSON storyboard.

#### 7. Save Storyboard to File
Write the complete storyboard JSON to the user's video directory:
```bash
# The storyboard.json file should be saved to:
D:\data\videoclips\phone2\007_input\storyboard.json
```
Use the Write tool to create the `storyboard.json` file in `<USER_VIDEO_DIRECTORY>`. **Always overwrite existing storyboard.json; never reuse it.**

#### 8. Compose Final Video
Run the compose script to generate the final video:
```bash
cd /d "D:\data\code\flama_code\video-editing-skills\video-editing-skills-vlog\scripts"
python compose_video.py --storyboard D:\data\videoclips\phone2\007_input\storyboard.json
```
Output will be saved to:
```
D:\data\videoclips\phone2\007_input\output\storyboard_merged.mp4
```

---

## Error Recovery Procedures

### Common Issues and Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| "flama.exe not found" | Build not completed | Run build.bat in flama directory |
| "No video files" | Wrong path or format | Verify path and file extensions |
| "GPU initialization failed" | Driver/hardware issue | Use --mode=sw for software decode |
| "Model not found" | VLM model missing | Check config.json model_path |
| "output_vlm.json empty" | Processing failed | Check console for specific errors |
| "storyboard.json not created" | Write tool failed | Verify write permissions to user directory |
| "Insufficient segments" | Short video files | Adjust prompt or combine videos |

### Fallback Strategies

1. **Hardware Decode Fails**: Switch to `--mode=sw`
2. **Model Loading Fails**: Verify model path in config.json
3. **Insufficient Content**: Request user provide more footage
4. **Quality Issues**: Suggest re-shooting or alternative clips

---

## Quality Assurance Checklist

Before delivering the final storyboard, verify:

- [ ] Total duration matches user request (±10% tolerance)
- [ ] All source video paths are valid and accessible
- [ ] Segment timecodes are accurate and non-overlapping
- [ ] Story has clear beginning, middle, and end
- [ ] Voiceover text is grammatically correct and engaging
- [ ] No duplicate segments used consecutively
- [ ] Transitions are appropriate for content type
- [ ] JSON is valid and well-formatted
- [ ] `output_vlm.json` saved to `<USER_VIDEO_DIRECTORY>\output_vlm.json`
- [ ] `storyboard.json` saved to `<USER_VIDEO_DIRECTORY>\storyboard.json`

---

## Advanced Usage Notes

### Custom Prompts for Specialized Analysis

For specific vlog types, customize the FLAMA prompt:

```bash
# Cinematic/Artistic Analysis
--prompt="分析画面的构图美学、光影质感、色彩情绪和视觉张力。输出专业影像描述，不超过100字。"

# Action/Sports Content
--prompt="描述画面中的动态元素、运动轨迹、速度感和能量氛围。输出动感描述，不超过100字。"

# Emotional/Personal Content
--prompt="捕捉画面中的情感瞬间、人物表情、氛围感受和故事性元素。输出情感化描述，不超过100字。"
```

### Multi-Language Voiceover

The storyboard can include multiple language options:

```json
"voiceover": {
  "zh": "中文旁白文字",
  "en": "English voiceover text",
  "style": "reflective"
}
```

### Vertical Video (Short-form) Adaptation

For TikTok/Reels/Shorts format:
- Target duration: 15-60 seconds
- Aspect ratio: 9:16
- Faster pacing: 1.5-2.5 second clips
- Hook within first 3 seconds
- Text-heavy for muted viewing

---

## Technical Reference

### FLAMA Command Reference

```bash
flama.exe [OPTIONS]

OPTIONS:
  --video_dir=PATH      Directory of video files (sorted by filename)
  --mode=hw|sw          Decode mode: hw (GPU) or sw (CPU)
  --config=PATH         Custom config file path
  --json_file=PATH      Output JSON file path (default: ./output_vlm.json)
  --prompt=TEXT         Override default VLM prompt
  --debug=0|1           Enable debug logging
```

### Config.json Key Settings

```json
{
  "common": {
    "decode_mode": "hw",           // "hw" or "sw"
    "vpp_downscaling": {
      "width": 448,                // VLM input width
      "height": 448                // VLM input height
    }
  },
  "genai": {
    "model_path": "path/to/vlm",   // VLM model location
    "device": "GPU"                // "GPU" or "CPU"
  }
}
```
