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


@dataclass
class ClipSpec:
    clip_id: int
    sequence_order: int
    source_video: Path
    in_point: float
    out_point: float
    duration: float
    subtitle: str


@dataclass
class StoryboardMeta:
    theme: str
    target_duration: Optional[float]
    actual_duration: Optional[float]
    cloud_llm_name: str


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
        fallback_candidate = bgm_dir / candidate.name
        if fallback_candidate.exists():
            return fallback_candidate
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
    cloud_llm_name = (
        storyboard_metadata.get("cloud_llm_name")
        or storyboard_metadata.get("llm_name")
        or "cloud_llm"
    )
    meta = StoryboardMeta(
        theme=str(theme_value).strip() or "video",
        target_duration=coerce_float(
            storyboard_metadata.get("target_duration_seconds")
        ),
        actual_duration=coerce_float(
            storyboard_metadata.get("actual_duration_seconds")
        ),
        cloud_llm_name=str(cloud_llm_name).strip() or "cloud_llm",
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

        specs.append(
            ClipSpec(
                clip_id=int(clip.get("clip_id", idx)),
                sequence_order=int(clip.get("sequence_order", idx)),
                source_video=Path(clip["source_video"]),
                in_point=in_point,
                out_point=out_point,
                duration=duration,
                subtitle=subtitle,
            )
        )

    return sorted(specs, key=lambda c: c.sequence_order), bgm_path, meta


def wrap_text(text: str, max_len: int) -> str:
    if not text:
        return ""
    if "\n" in text:
        return text
    lines: List[str] = []
    current = ""
    for ch in text:
        current += ch
        if len(current) >= max_len:
            lines.append(current)
            current = ""
    if current:
        lines.append(current)
    return "\n".join(lines)


def escape_drawtext_text(value: str) -> str:
    # Escape text for drawtext. Keep \n for line breaks.
    value = value.replace("\\", r"\\")
    value = value.replace(":", r"\:")
    value = value.replace(",", r"\,")
    value = value.replace("'", r"\'")
    value = value.replace("\n", r"\n")
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
    script_dir = Path(__file__).resolve().parent
    resource_font = script_dir.parent / "resource" / "font.ttf"
    if resource_font.exists():
        return normalize_filter_path(resource_font)
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


def extract_clip(
    ffmpeg: str,
    source_video: Path,
    output_path: Path,
    in_point: float,
    duration: float,
    dry_run: bool,
) -> None:
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(source_video),
        "-ss",
        f"{in_point}",
        "-t",
        f"{duration}",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(output_path),
    ]
    run_cmd(cmd, dry_run=dry_run)


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
    candidates = list(bgm_dir.glob("*.mp3")) + list(bgm_dir.glob("*.MP3"))
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
    fade_in: float = 1.0,
    fade_out: float = 1.5,
) -> None:
    duration = get_media_duration(ffprobe, ffmpeg, input_video)
    if not duration:
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
        "-shortest",
        str(output_video),
    ]
    run_cmd(cmd, dry_run=dry_run)

def render_subtitle(
    ffmpeg: str,
    input_video: Path,
    output_video: Path,
    subtitle_text: str,
    font_file: Optional[Path],
    font_size: int,
    max_line_len: int,
    dry_run: bool,
) -> None:
    subtitle_text = wrap_text(subtitle_text, max_line_len)
    escaped_text = escape_drawtext_text(subtitle_text)

    filter_parts = []
    if font_file:
        font_value = escape_drawtext_path(str(font_file))
        filter_parts.append(f"fontfile={font_value}")

    subtitle_file = output_video.with_suffix(".txt")
    subtitle_file.write_text(subtitle_text, encoding="utf-8")
    subtitle_path = normalize_filter_path(subtitle_file)

    use_textfile = ":" not in subtitle_path.as_posix()
    if use_textfile:
        textfile_value = escape_drawtext_path(str(subtitle_path))
        filter_parts.append(f"textfile={textfile_value}")
    else:
        filter_parts.append(f"text='{escaped_text}'")

    filter_parts.extend(
        [
            "x=(w-text_w)/2",
            "y=h*0.85",
            f"fontsize={font_size}",
            "fontcolor=white",
            "box=1",
            "boxcolor=black@0.5",
        ]
    )
    drawtext = "drawtext=" + ":".join(filter_parts)

    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_video),
        "-vf",
        drawtext,
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
    run_cmd(cmd, dry_run=dry_run)


def transcode_clip(
    ffmpeg: str,
    input_video: Path,
    output_video: Path,
    dry_run: bool,
) -> None:
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(input_video),
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
    llm_name = sanitize_filename_component(meta.cloud_llm_name, "cloud_llm")
    return f"{theme}_{duration}_bgm_{llm_name}.mp4"


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
            "'{theme}_{duration}_bgm_{cloud_llm}.mp4' in the output folder."
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
        default=40,
        help="Subtitle font size",
    )
    parser.add_argument(
        "--max-line-len",
        type=int,
        default=16,
        help="Max characters per subtitle line",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print ffmpeg commands without executing",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
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
    if meta.cloud_llm_name == "cloud_llm":
        print(
            "Warning: storyboard_metadata.cloud_llm_name is missing. "
            "Using default value 'cloud_llm' for output naming."
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

    processed_files: List[Path] = []

    for clip in clips:
        base = f"clip_{clip.sequence_order:02d}_id{clip.clip_id}"
        raw_path = temp_dir / f"{base}_raw.mp4"
        subtitle_path = temp_dir / f"{base}_sub.mp4"

        print(f"\n== Processing clip {clip.sequence_order} (clip_id={clip.clip_id}) ==")
        extract_clip(
            ffmpeg=args.ffmpeg,
            source_video=clip.source_video,
            output_path=raw_path,
            in_point=clip.in_point,
            duration=clip.duration,
            dry_run=args.dry_run,
        )

        if clip.subtitle and subtitles_enabled:
            render_subtitle(
                ffmpeg=args.ffmpeg,
                input_video=raw_path,
                output_video=subtitle_path,
                subtitle_text=clip.subtitle,
                font_file=font_file,
                font_size=args.font_size,
                max_line_len=args.max_line_len,
                dry_run=args.dry_run,
            )
        else:
            transcode_clip(
                ffmpeg=args.ffmpeg,
                input_video=raw_path,
                output_video=subtitle_path,
                dry_run=args.dry_run,
            )

        processed_files.append(subtitle_path)

    final_output = temp_dir / "merged_no_bgm.mp4"
    print(f"\n== Concatenating {len(processed_files)} clips ==")
    concat_videos(
        ffmpeg=args.ffmpeg,
        input_videos=processed_files,
        output_video=final_output,
        temp_dir=temp_dir,
        dry_run=args.dry_run,
    )

    ffprobe = resolve_ffprobe(args.ffmpeg)
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
