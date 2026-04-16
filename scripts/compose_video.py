from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from skill_runtime import (
    DEFAULT_COMPOSE_TARGET_RESOLUTION,
    ensure_skill_requirements,
    get_video_dimensions,
    infer_compose_target_resolution_from_dims,
    maybe_reexec_in_skill_venv,
    parse_resolution,
    read_workspace_compose_target_resolution,
)


VALID_XFADE_TRANSITIONS = {
    "fade", "dissolve", "fadeblack", "fadewhite",
    "smoothleft", "smoothright", "smoothup", "smoothdown",
    "circleopen", "circleclose",
}


@dataclass
class ClipSpec:
    clip_id: int
    sequence_order: int
    source_video: Path
    in_point: float
    out_point: float
    duration: float
    subtitle: str
    transition: str = ""
    transition_duration: float = 0.8


@dataclass
class StoryboardMeta:
    theme: str
    target_duration: Optional[float]
    actual_duration: Optional[float]


def coerce_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sanitize_filename_component(
    value: str,
    fallback: str,
    max_len: int = 48,
) -> str:
    safe = str(value or "").strip()
    if not safe:
        safe = fallback
    safe = re.sub(r'[<>:"/\\|?*]', "_", safe)
    safe = re.sub(r"\s+", "_", safe)
    safe = safe.strip("._ ")
    if not safe:
        safe = fallback
    if len(safe) > max_len:
        safe = safe[:max_len]
    return safe


def format_duration_component(
    target: Optional[float],
    actual: Optional[float],
    clips: List[ClipSpec],
) -> str:
    duration = target or actual
    if duration is None:
        duration = sum(clip.duration for clip in clips)
    if not duration or duration <= 0:
        return "unknown"
    return f"{int(round(duration))}s"


def resolve_storyboard_bgm_path(
    raw_value: str,
    storyboard_path: Path,
) -> Optional[Path]:
    if not raw_value:
        return None
    candidate = Path(str(raw_value))
    if candidate.is_absolute():
        return candidate

    relative_candidate = (storyboard_path.parent / candidate).resolve()
    if relative_candidate.exists():
        return relative_candidate

    script_dir = Path(__file__).resolve().parent
    bgm_dir = script_dir.parent / "resource" / "bgm"
    if bgm_dir.exists():
        nested_candidate = bgm_dir / candidate
        if nested_candidate.exists():
            return nested_candidate

        fallback_candidate = bgm_dir / candidate.name
        if fallback_candidate.exists():
            return fallback_candidate

        recursive_matches = sorted(bgm_dir.rglob(candidate.name))
        if recursive_matches:
            return recursive_matches[0]
    return relative_candidate


def load_storyboard(
    path: Path,
) -> Tuple[List[ClipSpec], Optional[Path], StoryboardMeta]:
    if not path.exists():
        raise FileNotFoundError(f"Storyboard not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    storyboard_metadata = data.get("storyboard_metadata") or {}
    story_outline = data.get("story_outline") or {}
    theme_value = (
        storyboard_metadata.get("theme")
        or story_outline.get("title")
        or "video"
    )
    meta = StoryboardMeta(
        theme=str(theme_value).strip() or "video",
        target_duration=coerce_float(
            storyboard_metadata.get("target_duration_seconds")
        ),
        actual_duration=coerce_float(
            storyboard_metadata.get("actual_duration_seconds")
        ),
    )

    audio_design = data.get("audio_design") or {}
    background_music = audio_design.get("background_music") or {}
    bgm_value = (
        background_music.get("file_path")
        or background_music.get("bgm_file")
        or background_music.get("selected_bgm")
    )
    bgm_path = resolve_storyboard_bgm_path(str(bgm_value), path) if bgm_value else None

    clips = data.get("clips", [])
    if not clips:
        raise ValueError("Storyboard has no 'clips' entries.")

    specs: List[ClipSpec] = []
    for idx, clip in enumerate(clips, start=1):
        timecode = clip.get("timecode", {})
        in_point = float(timecode.get("in_point", 0.0))
        out_point = float(timecode.get("out_point", 0.0))
        duration = timecode.get("duration")
        if duration is None:
            duration = max(0.0, out_point - in_point)
        duration = float(duration)

        if out_point <= in_point or duration <= 0:
            raise ValueError(
                f"Invalid timecode for clip_id={clip.get('clip_id')}: "
                f"in_point={in_point}, out_point={out_point}, duration={duration}"
            )

        voiceover = clip.get("voiceover") or {}
        subtitle = str(voiceover.get("text", "")).strip()

        source_path = Path(clip["source_video"])
        if not source_path.exists():
            raise FileNotFoundError(
                f"clip {idx} 的 source_video 文件不存在：{source_path}"
            )

        trans_obj = clip.get("transition") or {}
        trans_type = str(trans_obj.get("type", "")).strip().lower()
        trans_dur = float(trans_obj.get("duration", 0.8))
        if trans_type and trans_type not in VALID_XFADE_TRANSITIONS:
            print(f"Warning: clip {idx} transition '{trans_type}' not supported, ignoring.")
            trans_type = ""

        specs.append(
            ClipSpec(
                clip_id=int(clip.get("clip_id", idx)),
                sequence_order=int(clip.get("sequence_order", idx)),
                source_video=source_path,
                in_point=in_point,
                out_point=out_point,
                duration=duration,
                subtitle=subtitle,
                transition=trans_type,
                transition_duration=trans_dur,
            )
        )

    return sorted(specs, key=lambda c: c.sequence_order), bgm_path, meta


def build_scale_pad_filter(width: int, height: int) -> str:
    """构建 scale+pad 归一化滤镜，保持原始宽高比，不足部分填黑边。"""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
        f"setsar=1"
    )


def wrap_text(text: str, max_len: int) -> str:
    if not text:
        return ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if "\n" in normalized:
        return normalized
    if max_len <= 0:
        return normalized

    # 优先在空格/标点处断行，避免“单字落行”或语义被硬切断。
    break_chars = set(" \t,.;:!?，。！？、；：）)]}>】》」』")
    lines: List[str] = []
    i = 0
    n = len(normalized)
    while i < n:
        remaining = n - i
        if remaining <= max_len:
            lines.append(normalized[i:])
            break

        window = normalized[i : i + max_len]
        cut = -1
        for j in range(len(window) - 1, -1, -1):
            if window[j] in break_chars:
                cut = j + 1
                break
        if cut <= 0:
            cut = max_len

        line = normalized[i : i + cut].rstrip()
        if not line:
            line = normalized[i : i + cut]
        lines.append(line)
        i += cut

        # 下一行跳过前导空白，避免行首出现“空格占位”。
        while i < n and normalized[i] in (" ", "\t"):
            i += 1

    if len(lines) >= 2 and len(lines[-1]) == 1 and len(lines[-2]) > 2:
        # 避免最后一行只剩 1 个字，提升观感。
        moved = lines[-2][-1]
        lines[-2] = lines[-2][:-1]
        lines[-1] = moved + lines[-1]
    return "\n".join(lines)


def escape_drawtext_text(value: str) -> str:
    # Escape text for drawtext.
    value = value.replace("\\", r"\\")
    value = value.replace(":", r"\:")
    value = value.replace(",", r"\,")
    value = value.replace("'", r"\'")
    return value


def escape_drawtext_path(value: str) -> str:
    # For drawtext fontfile/textfile: use forward slashes (Windows ffmpeg accepts them),
    # and escape only ':' so it is not treated as filter option separator.
    value = value.replace("\\", "/")
    value = value.replace(":", "\\\\:")
    return value


def quote_concat_path(path: Path) -> str:
    # Concat demuxer accepts file "path" lines.
    safe = str(path).replace("\\", "/").replace('"', r"\"")
    return f'file "{safe}"'


def find_default_font() -> Optional[Path]:
    system_font_candidates = [
        Path(r"C:\Windows\Fonts\msyh.ttc"),       # 微软雅黑
        Path(r"C:\Windows\Fonts\simhei.ttf"),      # 黑体
        Path(r"C:\Windows\Fonts\simsun.ttc"),      # 宋体
    ]
    for candidate in system_font_candidates:
        if candidate.exists():
            print(f"Info: Using system font: {candidate}")
            return candidate
    return None


def normalize_filter_path(path: Path) -> Path:
    if not path.is_absolute():
        return path
    try:
        return path.relative_to(Path.cwd())
    except ValueError:
        try:
            rel = Path(os.path.relpath(path, Path.cwd()))
            if ":" not in rel.as_posix():
                return rel
        except Exception:
            pass
    return path


def run_cmd(cmd: List[str], dry_run: bool) -> None:
    print(" ".join(cmd))
    if dry_run:
        return
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(cmd)
            + "\n\n"
            + (result.stderr or result.stdout or "")
        )


def _is_valid_clip(ffmpeg: str, output_path: Path) -> bool:
    """检查输出文件是否包含有效流（Duration 不为 N/A）。"""
    if not output_path.exists() or output_path.stat().st_size == 0:
        return False
    ffprobe = Path(ffmpeg).with_name("ffprobe.exe")
    probe_bin = str(ffprobe) if ffprobe.exists() else "ffprobe"
    result = subprocess.run(
        [probe_bin, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(output_path)],
        capture_output=True, text=True,
    )
    value = result.stdout.strip()
    return bool(value) and value.lower() not in ("n/a", "")


def extract_clip(
    ffmpeg: str,
    source_video: Path,
    output_path: Path,
    in_point: float,
    duration: float,
    dry_run: bool,
) -> None:
    # 模式1：输入侧 seek（-ss 在 -i 之前），速度快，从最近关键帧开始
    cmd_input_seek = [
        ffmpeg, "-y",
        "-ss", f"{in_point}",
        "-i", str(source_video),
        "-t", f"{duration}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(output_path),
    ]
    # 模式2：输出侧 seek（-ss 在 -i 之后），帧精确但非关键帧时可能产生 Duration:N/A
    cmd_output_seek = [
        ffmpeg, "-y",
        "-i", str(source_video),
        "-ss", f"{in_point}",
        "-t", f"{duration}",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        str(output_path),
    ]

    if dry_run:
        print(" ".join(cmd_input_seek))
        return

    print(" ".join(cmd_input_seek))
    result = subprocess.run(cmd_input_seek, capture_output=True, text=True)
    if result.returncode == 0 and _is_valid_clip(ffmpeg, output_path):
        return

    print(f"[extract_clip] 输入侧 seek 失败或输出无效，切换到输出侧 seek 模式重试...")
    print(" ".join(cmd_output_seek))
    result2 = subprocess.run(cmd_output_seek, capture_output=True, text=True)
    if result2.returncode != 0 or not _is_valid_clip(ffmpeg, output_path):
        raise RuntimeError(
            "Command failed (both seek modes):\n"
            + " ".join(cmd_output_seek)
            + "\n\n"
            + (result2.stderr or result2.stdout or "")
        )


def find_default_ffmpeg() -> str:
    script_dir = Path(__file__).resolve().parent
    candidate = script_dir.parent / "bin" / "ffmpeg.exe"
    if candidate.exists():
        return str(candidate)
    return "ffmpeg"


def resolve_ffprobe(ffmpeg: str) -> str:
    ffmpeg_path = Path(ffmpeg)
    if ffmpeg_path.exists():
        candidate = ffmpeg_path.with_name("ffprobe.exe")
        if candidate.exists():
            return str(candidate)
    return "ffprobe"


def parse_duration_from_ffmpeg_output(output: str) -> Optional[float]:
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", output)
    if not match:
        return None
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = float(match.group(3))
    return hours * 3600 + minutes * 60 + seconds


def get_media_duration(
    ffprobe: str,
    ffmpeg: str,
    media_path: Path,
) -> Optional[float]:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=nw=1:nk=1",
        str(media_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return float(result.stdout.strip())
    except Exception:
        pass

    cmd = [ffmpeg, "-i", str(media_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return parse_duration_from_ffmpeg_output(result.stderr or result.stdout)


def compute_content_area(
    src_w: int, src_h: int,
    tgt_w: int, tgt_h: int,
) -> Tuple[int, int, int, int]:
    """计算 scale+pad 归一化后，源视频内容在目标帧中的位置。

    返回 (content_w, content_h, pad_x, pad_y)：
    - content_w/h：内容实际占据的像素尺寸（偶数，兼容 yuv420p）
    - pad_x/y：内容左上角相对于目标帧的偏移量（letterbox/pillarbox 边距）
    """
    scale = min(tgt_w / src_w, tgt_h / src_h)
    cw = int(src_w * scale)
    ch = int(src_h * scale)
    cw -= cw % 2  # 保证偶数
    ch -= ch % 2
    px = (tgt_w - cw) // 2
    py = (tgt_h - ch) // 2
    return cw, ch, px, py


def has_audio_stream(
    ffprobe: str,
    ffmpeg: str,
    media_path: Path,
) -> bool:
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(media_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return bool(result.stdout.strip())
    except Exception:
        pass

    cmd = [ffmpeg, "-i", str(media_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    text = (result.stderr or "") + (result.stdout or "")
    return "Audio:" in text


def find_bgm_file() -> Optional[Path]:
    script_dir = Path(__file__).resolve().parent
    bgm_dir = script_dir.parent / "resource" / "bgm"
    if not bgm_dir.exists():
        return None
    candidates = list(bgm_dir.rglob("*.mp3")) + list(bgm_dir.rglob("*.MP3"))
    if not candidates:
        return None
    return random.choice(candidates)


def add_bgm_to_video(
    ffmpeg: str,
    ffprobe: str,
    input_video: Path,
    output_video: Path,
    bgm_file: Path,
    dry_run: bool,
    expected_duration: Optional[float] = None,
    fade_in: float = 1.0,
    fade_out: float = 1.5,
) -> None:
    measured_duration = get_media_duration(ffprobe, ffmpeg, input_video)
    duration = measured_duration
    # Prefer storyboard/clip-based duration to avoid overlong output caused by
    # container metadata drift after concat/copy.
    if expected_duration and expected_duration > 0:
        duration = float(expected_duration)
        if measured_duration and measured_duration > expected_duration + 0.05:
            print(
                f"Info: measured duration {measured_duration:.3f}s > expected "
                f"{expected_duration:.3f}s, using expected duration for BGM mux."
            )
    if not duration or duration <= 0:
        print("Warning: Unable to determine video duration. Skipping BGM.")
        return

    fade_out_start = max(0.0, duration - fade_out)
    bgm_filter = (
        f"afade=t=in:st=0:d={fade_in},"
        f"afade=t=out:st={fade_out_start}:d={fade_out}"
    )

    if has_audio_stream(ffprobe, ffmpeg, input_video):
        filter_complex = (
            f"[1:a]{bgm_filter}[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )
        map_audio = ["-map", "[a]"]
    else:
        filter_complex = f"[1:a]{bgm_filter}[a]"
        map_audio = ["-map", "[a]"]

    # Explicit -t so the muxer writes correct duration metadata; otherwise with
    # -stream_loop -1 + -shortest the container duration can be wrong (e.g. 2+ min).
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_video),
        "-stream_loop",
        "-1",
        "-i",
        str(bgm_file),
        "-filter_complex",
        filter_complex,
        "-map",
        "0:v:0",
        *map_audio,
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-t",
        str(duration),
        str(output_video),
    ]
    run_cmd(cmd, dry_run=dry_run)

def render_subtitle(
    ffmpeg: str,
    source_video: Path,
    output_video: Path,
    in_point: float,
    clip_duration: float,
    subtitle_text: str,
    font_file: Optional[Path],
    font_size: int,
    max_line_len: int,
    dry_run: bool,
    target_resolution: Optional[Tuple[int, int]] = None,
    src_dims: Optional[Tuple[int, int]] = None,
) -> None:
    """从源视频直接提取+渲染字幕，单步完成。

    使用 input-side seek（-ss 在 -i 之前）配合 re-encode，ffmpeg 的 accurate_seek
    会从关键帧解码但只编码 in_point 之后的帧，彻底避免 copy 模式的 pre-roll 问题。
    """
    subtitle_text = wrap_text(subtitle_text, max_line_len)
    subtitle_lines = subtitle_text.split("\n") if subtitle_text else []
    if not subtitle_lines:
        subtitle_lines = [""]

    if target_resolution and src_dims:
        tgt_w, tgt_h = target_resolution
        src_w, src_h = src_dims
        cw, ch, px, py = compute_content_area(src_w, src_h, tgt_w, tgt_h)
        sub_x_expr = f"{px}+(({cw})-text_w)/2"
        sub_y_base_expr = str(py + int(ch * 0.85))
    else:
        sub_x_expr = "(w-text_w)/2"
        sub_y_base_expr = "h*0.85"

    line_step = max(1, int(font_size * 1.2))
    line_count = len(subtitle_lines)
    drawtext_filters: List[str] = []
    for idx, line in enumerate(subtitle_lines):
        escaped_line = escape_drawtext_text(line)
        filter_parts = []
        if font_file:
            font_value = escape_drawtext_path(str(font_file))
            filter_parts.append(f"fontfile={font_value}")
        filter_parts.extend(
            [
                f"text='{escaped_line}'",
                f"x={sub_x_expr}",
                (
                    "y="
                    f"({sub_y_base_expr})-(({line_count - 1})*{line_step}/2)+({idx}*{line_step})"
                ),
                f"fontsize={font_size}",
                "fontcolor=white",
                "box=1",
                "boxcolor=black@0.5",
            ]
        )
        drawtext_filters.append("drawtext=" + ":".join(filter_parts))

    if target_resolution:
        w, h = target_resolution
        vf = ",".join([build_scale_pad_filter(w, h), *drawtext_filters])
    else:
        vf = ",".join(drawtext_filters)

    cmd = [
        ffmpeg,
        "-y",
        "-ss", f"{in_point}",
        "-i", str(source_video),
        "-t", f"{clip_duration}",
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        str(output_video),
    ]
    run_cmd(cmd, dry_run=dry_run)


def transcode_clip(
    ffmpeg: str,
    source_video: Path,
    output_video: Path,
    in_point: float,
    clip_duration: float,
    dry_run: bool,
    target_resolution: Optional[Tuple[int, int]] = None,
) -> None:
    """从源视频直接提取+转码，单步完成（无字幕版本）。"""
    vf_args: List[str] = []
    if target_resolution:
        w, h = target_resolution
        vf_args = ["-vf", build_scale_pad_filter(w, h)]

    cmd = [
        ffmpeg,
        "-y",
        "-ss", f"{in_point}",
        "-i", str(source_video),
        "-t", f"{clip_duration}",
        *vf_args,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-ac", "2",
        str(output_video),
    ]
    run_cmd(cmd, dry_run=dry_run)


def concat_videos_with_xfade(
    ffmpeg: str,
    input_videos: List[Path],
    clips: List[ClipSpec],
    output_video: Path,
    dry_run: bool,
) -> None:
    """使用 xfade 转场效果拼接视频片段。

    每个 clip 的 transition 字段指定该片段到下一个片段之间的转场类型。
    最后一个片段的 transition 会被忽略（没有下一个片段可过渡）。
    音频使用 acrossfade 同步过渡。
    """
    n = len(input_videos)
    if n < 2:
        raise ValueError("xfade requires at least 2 clips")

    inputs = []
    for video in input_videos:
        inputs.extend(["-i", str(video)])

    # 构建视频 xfade 链
    video_filters = []

    # 统一时基和帧率
    for i in range(n):
        video_filters.append(f"[{i}:v]settb=AVTB,fps=30[v{i}]")

    # 逐对构建 xfade
    current_offset = 0.0
    v_label = "v0"

    for i in range(n - 1):
        clip = clips[i]
        trans_type = clip.transition or "fade"
        trans_dur = clip.transition_duration

        # 确保转场时长不超过任一片段时长的一半
        max_dur = min(clip.duration, clips[i + 1].duration) / 2
        if trans_dur > max_dur:
            trans_dur = round(max_dur, 2)

        current_offset += clip.duration - trans_dur

        next_v = f"v{i + 1}"
        out_v = f"xf{i}" if i < n - 2 else "vout"

        video_filters.append(
            f"[{v_label}][{next_v}]xfade=transition={trans_type}"
            f":duration={trans_dur:.3f}:offset={current_offset:.3f}[{out_v}]"
        )
        v_label = out_v

    filter_complex = ";".join(video_filters)

    # xfade 只处理视频，音频由后续 BGM 步骤统一处理
    # 这样更可靠：避免无音频片段导致 acrossfade 失败
    cmd = [
        ffmpeg, "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        str(output_video),
    ]

    print(f"\n== Concatenating {n} clips with xfade transitions ==")
    run_cmd(cmd, dry_run=dry_run)


def concat_videos(
    ffmpeg: str,
    input_videos: List[Path],
    output_video: Path,
    temp_dir: Optional[Path],
    dry_run: bool,
) -> None:
    if temp_dir:
        concat_list = temp_dir / f"{output_video.stem}.concat.txt"
    else:
        concat_list = output_video.with_suffix(".concat.txt")
    concat_list.write_text(
        "\n".join(quote_concat_path(p) for p in input_videos),
        encoding="utf-8",
    )

    cmd_copy = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-c",
        "copy",
        str(output_video),
    ]

    try:
        run_cmd(cmd_copy, dry_run=dry_run)
        return
    except RuntimeError:
        pass

    cmd_reencode = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(output_video),
    ]
    try:
        run_cmd(cmd_reencode, dry_run=dry_run)
        return
    except RuntimeError:
        pass

    inputs = []
    for video in input_videos:
        inputs.extend(["-i", str(video)])

    n = len(input_videos)
    concat_av = "".join(
        f"[{idx}:v:0][{idx}:a:0]" for idx in range(n)
    ) + f"concat=n={n}:v=1:a=1[v][a]"

    cmd_filter_av = [
        ffmpeg,
        "-y",
        *inputs,
        "-filter_complex",
        concat_av,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-ac",
        "2",
        str(output_video),
    ]

    try:
        run_cmd(cmd_filter_av, dry_run=dry_run)
        return
    except RuntimeError:
        pass

    concat_v = "".join(
        f"[{idx}:v:0]" for idx in range(n)
    ) + f"concat=n={n}:v=1:a=0[v]"

    cmd_filter_v = [
        ffmpeg,
        "-y",
        *inputs,
        "-filter_complex",
        concat_v,
        "-map",
        "[v]",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        str(output_video),
    ]
    run_cmd(cmd_filter_v, dry_run=dry_run)


def resolve_output_dir(storyboard_path: Path, override: Optional[str]) -> Path:
    if override:
        return Path(override)
    return storyboard_path.parent

def build_final_output_name(meta: StoryboardMeta, clips: List[ClipSpec]) -> str:
    theme = sanitize_filename_component(meta.theme, "video")
    duration = sanitize_filename_component(
        format_duration_component(meta.target_duration, meta.actual_duration, clips),
        "unknown",
    )
    return f"{theme}_{duration}_bgm.mp4"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract storyboard clips, render subtitles, and concat output."
    )
    parser.add_argument(
        "--storyboard",
        default="007_input/storyboard.json",
        help="Path to storyboard.json",
    )
    parser.add_argument(
        "--ffmpeg",
        default=None,
        help="Path to ffmpeg.exe (default: ../bin/ffmpeg.exe if present, else ffmpeg in PATH)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for temp and final files (default: storyboard folder)",
    )
    parser.add_argument(
        "--output-name",
        default=None,
        help=(
            "Deprecated. Ignored. Final output is always named "
            "'{theme}_{duration}_bgm.mp4' in the output folder."
        ),
    )
    parser.add_argument(
        "--font_file",
        "--font-file",
        dest="font_file",
        default=None,
        help=(
            "Font file path for subtitles (default: ../resource/font.ttf relative to this script)"
        ),
    )
    parser.add_argument(
        "--font-size",
        type=int,
        default=55,
        help="Subtitle font size",
    )
    parser.add_argument(
        "--max-line-len",
        type=int,
        default=16,
        help="Max characters per subtitle line",
    )
    parser.add_argument(
        "--target-resolution",
        default=None,
        help=(
            "Normalize all clips to this resolution before concatenation. "
            "Preserves aspect ratio and adds black letterbox/pillarbox padding. "
            "Format: WxH (e.g. '1920x1080', '1080x1920'). "
            "If omitted: skill_runtime.DEFAULT_COMPOSE_TARGET_RESOLUTION if set; else "
            "runtime_env.json compose_target_resolution next to storyboard (from prepare_workspace); "
            "else same majority rule on storyboard source videos."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print ffmpeg commands without executing",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        ensure_skill_requirements(force=False)
        maybe_reexec_in_skill_venv(Path(__file__).resolve())
    except Exception as exc:
        print(f"Error: failed to prepare shared .venv: {exc}", file=sys.stderr)
        return 1
    if not args.ffmpeg:
        args.ffmpeg = find_default_ffmpeg()
    storyboard_path = Path(args.storyboard)
    clips, storyboard_bgm, meta = load_storyboard(storyboard_path)

    output_dir = resolve_output_dir(storyboard_path, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = output_dir / "temp"
    temp_dir.mkdir(parents=True, exist_ok=True)

    if meta.theme == "video":
        print(
            "Warning: storyboard_metadata.theme is missing. "
            "Using default value 'video' for output naming."
        )
    if meta.target_duration is None and meta.actual_duration is None:
        print(
            "Warning: storyboard_metadata.target_duration_seconds is missing. "
            "Using sum of clip durations for output naming."
        )

    if args.output_name:
        print(
            "Warning: --output-name is ignored. "
            "Final output name is derived from storyboard metadata."
        )

    ffprobe = resolve_ffprobe(args.ffmpeg)

    # 尝试从 Stage 1 写入的 runtime_env.json 加载 video_dims_cache，避免重复调用 ffprobe
    workspace_dir = storyboard_path.resolve().parent
    _dims_cache: dict = {}
    _runtime_env = workspace_dir / "runtime_env.json"
    if _runtime_env.exists():
        try:
            _raw = json.loads(_runtime_env.read_text(encoding="utf-8"))
            _dims_cache = {k: tuple(v) for k, v in (_raw.get("video_dims_cache") or {}).items()}
        except Exception:
            pass

    # 探测所有源视频尺寸（去重），优先使用缓存，缓存缺失时才调 ffprobe
    unique_sources = {clip.source_video for clip in clips}
    source_dims: dict = {}
    for src in unique_sources:
        key = str(src.resolve())
        source_dims[src] = _dims_cache.get(key) or get_video_dimensions(ffprobe, src)

    # 按 clip_id 建立查找表，供后续 render_subtitle 使用
    clip_src_dims = {clip.clip_id: source_dims.get(clip.source_video) for clip in clips}

    target_resolution: Optional[Tuple[int, int]] = None
    if args.target_resolution:
        try:
            target_resolution = parse_resolution(args.target_resolution)
            print(f"Info: Target resolution = {target_resolution[0]}x{target_resolution[1]} (explicit)")
        except ValueError as e:
            print(f"Warning: {e}. Resolution normalization disabled.")
    elif DEFAULT_COMPOSE_TARGET_RESOLUTION and str(DEFAULT_COMPOSE_TARGET_RESOLUTION).strip():
        res_spec = str(DEFAULT_COMPOSE_TARGET_RESOLUTION).strip()
        try:
            target_resolution = parse_resolution(res_spec)
            print(
                f"Info: Target resolution = {target_resolution[0]}x{target_resolution[1]} "
                f"(skill_runtime.DEFAULT_COMPOSE_TARGET_RESOLUTION)"
            )
        except ValueError as e:
            print(
                f"Warning: DEFAULT_COMPOSE_TARGET_RESOLUTION ({res_spec!r}) invalid: {e}. "
                "Falling back to auto-detect from source clips."
            )
    if target_resolution is None and not args.target_resolution:
        manifest_res = read_workspace_compose_target_resolution(workspace_dir)
        if manifest_res:
            target_resolution = manifest_res
            print(
                f"Info: Target resolution = {target_resolution[0]}x{target_resolution[1]} "
                f"(runtime_env.json compose_target_resolution)"
            )
    if target_resolution is None and not args.target_resolution:
        # 兜底：与阶段 1 相同规则，按 storyboard 源视频多数决定（无 manifest 或旧工作区）
        dims_list = list(source_dims.values())
        target_resolution = infer_compose_target_resolution_from_dims(dims_list)
        portrait_count = sum(1 for d in dims_list if d and d[1] > d[0])
        landscape_count = sum(1 for d in dims_list if d and d[0] >= d[1])
        total_probed = portrait_count + landscape_count
        if total_probed > 0 and portrait_count > landscape_count:
            print(
                f"Info: Auto-detected portrait majority from storyboard sources "
                f"({portrait_count}/{total_probed} clips). "
                f"Target resolution: 1080x1920"
            )
        elif total_probed > 0:
            print(
                f"Info: Auto-detected landscape majority from storyboard sources "
                f"({landscape_count}/{total_probed} clips). "
                f"Target resolution: 1920x1080"
            )
        else:
            print("Info: Could not probe clip dimensions. Defaulting to 1920x1080.")

    font_file = None
    if args.font_file:
        candidate = Path(args.font_file)
        if candidate.exists():
            font_file = normalize_filter_path(candidate)
        else:
            print(f"Warning: Font file not found: {candidate}")
    if not font_file:
        font_file = find_default_font()

    subtitles_enabled = font_file is not None
    if not subtitles_enabled:
        print("Warning: No font file found. Subtitles will be skipped.")

    # -----------------------------
    # storyboard 防越界校验（关键）
    # -----------------------------
    # 原理：storyboard.json 里的 in_point/out_point 如果超出 source_video 的实际 duration，
    # 则会导致 extract/copy 得到 0s 或极短片段，进而在 xfade 链中静默截断。
    #
    # 策略：不直接 raise 终止；而是根据源视频时长，把片段的时间码钳位到可用范围。
    # - out_point > source_duration：把 out_point 钳到末尾
    # - in_point >= source_duration 或导致时长<=0：把 in_point 往前挪，使得 duration 尽量保持 clip.duration
    eps = 0.1  # 容忍误差（秒），避免浮点/容器元数据偏差造成误判
    for clip in clips:
        try:
            src_dur = get_media_duration(ffprobe, args.ffmpeg, clip.source_video)
        except Exception as e:
            print(f"Warning: failed to probe duration for {clip.source_video}: {e}")
            continue

        if src_dur is None or src_dur <= 0:
            continue

        desired_dur = float(clip.duration) if clip.duration and clip.duration > 0 else max(
            0.0, float(clip.out_point - clip.in_point)
        )
        if desired_dur <= 0:
            continue

        orig_in, orig_out = float(clip.in_point), float(clip.out_point)
        new_in, new_out = orig_in, orig_out

        # 1) 先处理负数/越界 out
        if new_in < 0:
            new_in = 0.0
        if new_out > src_dur - eps:
            new_out = src_dur

        # 2) 如果钳位后时长<=0：把 in_point 往前挪，让 duration 尽量保持 desired_dur
        new_dur = new_out - new_in
        if new_dur <= 0:
            new_in = max(0.0, src_dur - desired_dur)
            new_out = min(src_dur, new_in + desired_dur)
            new_dur = new_out - new_in

        # 3) 最终兜底：仍然<=0就抛错，避免后续生成 0s clip
        if new_dur <= 0:
            raise RuntimeError(
                f"Storyboard timecode cannot be clamped to a valid range: "
                f"clip_id={clip.clip_id}, sequence_order={clip.sequence_order}, "
                f"source_duration={src_dur:.3f}s, in_point={orig_in:.3f}s, out_point={orig_out:.3f}s"
            )

        # 4) 只有发生明显变化才打印，减少噪声
        if abs(new_in - orig_in) > eps or abs(new_out - orig_out) > eps:
            print(
                f"Warning: clamp storyboard timecode for clip_id={clip.clip_id}, "
                f"sequence_order={clip.sequence_order}. "
                f"in_point {orig_in:.3f}s -> {new_in:.3f}s, "
                f"out_point {orig_out:.3f}s -> {new_out:.3f}s, "
                f"duration -> {new_dur:.3f}s"
            )

        clip.in_point = float(new_in)
        clip.out_point = float(new_out)
        clip.duration = float(new_dur)

    processed_files: List[Path] = []

    for clip in clips:
        base = f"clip_{clip.sequence_order:02d}_id{clip.clip_id}"
        subtitle_path = temp_dir / f"{base}_sub.mp4"

        print(f"\n== Processing clip {clip.sequence_order} (clip_id={clip.clip_id}) ==")

        if clip.subtitle and subtitles_enabled:
            render_subtitle(
                ffmpeg=args.ffmpeg,
                source_video=clip.source_video,
                output_video=subtitle_path,
                in_point=clip.in_point,
                clip_duration=clip.duration,
                subtitle_text=clip.subtitle,
                font_file=font_file,
                font_size=args.font_size,
                max_line_len=args.max_line_len,
                dry_run=args.dry_run,
                target_resolution=target_resolution,
                src_dims=clip_src_dims.get(clip.clip_id),
            )
        else:
            transcode_clip(
                ffmpeg=args.ffmpeg,
                source_video=clip.source_video,
                output_video=subtitle_path,
                in_point=clip.in_point,
                clip_duration=clip.duration,
                dry_run=args.dry_run,
                target_resolution=target_resolution,
            )

        processed_files.append(subtitle_path)

    final_output = temp_dir / "merged_no_bgm.mp4"

    # 检查是否有转场效果
    has_transitions = any(clip.transition for clip in clips)

    if has_transitions and len(processed_files) >= 2:
        try:
            concat_videos_with_xfade(
                ffmpeg=args.ffmpeg,
                input_videos=processed_files,
                clips=clips,
                output_video=final_output,
                dry_run=args.dry_run,
            )
        except (RuntimeError, Exception) as e:
            print(f"\nWarning: xfade failed ({e}), falling back to hard-cut concat.")
            concat_videos(
                ffmpeg=args.ffmpeg,
                input_videos=processed_files,
                output_video=final_output,
                temp_dir=temp_dir,
                dry_run=args.dry_run,
            )
    else:
        print(f"\n== Concatenating {len(processed_files)} clips ==")
        concat_videos(
            ffmpeg=args.ffmpeg,
            input_videos=processed_files,
            output_video=final_output,
            temp_dir=temp_dir,
            dry_run=args.dry_run,
        )

    # 计算预期总时长（考虑转场重叠）
    total_clip_duration = sum(clip.duration for clip in clips)
    if has_transitions:
        overlap = sum(
            clip.transition_duration for clip in clips[:-1] if clip.transition
        )
        expected_dur = total_clip_duration - overlap
    else:
        expected_dur = total_clip_duration

    ffprobe = resolve_ffprobe(args.ffmpeg)

    # 实测合并视频的真实时长作为 BGM 混流基准，避免公式计算值与实际不符导致的截断
    if not args.dry_run and final_output.exists():
        measured_merged_dur = get_media_duration(ffprobe, args.ffmpeg, final_output)
        if measured_merged_dur and measured_merged_dur > 0:
            if abs(measured_merged_dur - expected_dur) > 1.0:
                print(
                    f"Warning: measured merged duration {measured_merged_dur:.3f}s "
                    f"differs from expected {expected_dur:.3f}s by more than 1s."
                )
            bgm_expected_dur: Optional[float] = measured_merged_dur
        else:
            bgm_expected_dur = expected_dur
    else:
        bgm_expected_dur = expected_dur

    bgm_output: Optional[Path] = None
    bgm_file = storyboard_bgm or find_bgm_file()
    if storyboard_bgm and not storyboard_bgm.exists():
        print(
            f"\nWarning: Storyboard BGM not found: {storyboard_bgm}. "
            "Falling back to random selection."
        )
        bgm_file = find_bgm_file()
    if bgm_file:
        bgm_output = output_dir / build_final_output_name(meta, clips)
        if storyboard_bgm and bgm_file == storyboard_bgm:
            print(f"\n== Adding storyboard BGM: {bgm_file} ==")
        else:
            print(f"\n== Adding BGM (fallback/random): {bgm_file} ==")
        add_bgm_to_video(
            ffmpeg=args.ffmpeg,
            ffprobe=ffprobe,
            input_video=final_output,
            output_video=bgm_output,
            bgm_file=bgm_file,
            dry_run=args.dry_run,
            expected_duration=bgm_expected_dur,
        )
    else:
        bgm_output = output_dir / build_final_output_name(meta, clips)
        print(
            "\nWarning: No BGM mp3 found. "
            "Copying non-BGM output to final name."
        )
        if not args.dry_run:
            shutil.copy2(final_output, bgm_output)

    print(f"\nDone. Intermediate (no BGM): {final_output}")
    if bgm_output:
        print(f"Done. Final output: {bgm_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
