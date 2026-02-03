import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class ClipSpec:
    clip_id: int
    sequence_order: int
    source_video: Path
    in_point: float
    out_point: float
    duration: float
    subtitle: str


def load_storyboard(path: Path) -> List[ClipSpec]:
    if not path.exists():
        raise FileNotFoundError(f"Storyboard not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

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

    return sorted(specs, key=lambda c: c.sequence_order)


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
    # Escape path for drawtext fontfile. Prefer forward slashes.
    value = value.replace("\\", "/")
    value = value.replace(":", r"\:")
    return value


def quote_concat_path(path: Path) -> str:
    # Concat demuxer accepts file "path" lines.
    safe = str(path).replace("\\", "/").replace('"', r"\"")
    return f'file "{safe}"'


def find_default_font() -> Optional[Path]:
    script_dir = Path(__file__).resolve().parent
    resource_font = script_dir.parent / "resource" / "font.ttf"
    if resource_font.exists():
        return normalize_font_path(resource_font)
    return None


def normalize_font_path(font_path: Path) -> Path:
    if not font_path.is_absolute():
        return font_path
    try:
        return font_path.relative_to(Path.cwd())
    except ValueError:
        try:
            rel = Path(os.path.relpath(font_path, Path.cwd()))
            if ":" not in rel.as_posix():
                return rel
        except Exception:
            pass
    return font_path


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
        "-ss",
        f"{in_point}",
        "-i",
        str(source_video),
        "-t",
        f"{duration}",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(output_path),
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
    dry_run: bool,
) -> None:
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


def resolve_output_dir(clips: List[ClipSpec], override: Optional[str]) -> Path:
    if override:
        return Path(override)
    return clips[0].source_video.parent / "output"


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
        default="ffmpeg",
        help="Path to ffmpeg.exe (default: ffmpeg in PATH)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for temp and final files (default: source folder/output)",
    )
    parser.add_argument(
        "--output-name",
        default="storyboard_merged.mp4",
        help="Final output filename",
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
    storyboard_path = Path(args.storyboard)
    clips = load_storyboard(storyboard_path)

    output_dir = resolve_output_dir(clips, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    font_file = None
    if args.font_file:
        candidate = Path(args.font_file)
        if candidate.exists():
            font_file = normalize_font_path(candidate)
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
        raw_path = output_dir / f"{base}_raw.mp4"
        subtitle_path = output_dir / f"{base}_sub.mp4"

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

    final_output = output_dir / args.output_name
    print(f"\n== Concatenating {len(processed_files)} clips ==")
    concat_videos(
        ffmpeg=args.ffmpeg,
        input_videos=processed_files,
        output_video=final_output,
        dry_run=args.dry_run,
    )

    print(f"\nDone. Output: {final_output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
