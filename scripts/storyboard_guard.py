#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class RuleConfig:
    min_unique_videos: int = 6
    # 同一 source_video 在 clips 中最多出现次数；≤ 此值通过校验
    per_video_max_clips: int = 3
    min_clip_duration: float = 3.0
    # 名义最小时长 min_clip_duration 下浮容差（秒），用于通过 2.6～2.9s 等略短于 3s 的 VLM 片段
    min_clip_duration_slack: float = 0.5
    allow_last_clip_shorter: bool = True
    duration_tolerance_sec: float = 6.0
    default_transition_duration: float = 0.8


def normalize_media_path(raw: str) -> str:
    """统一路径字符串：存在则 resolve；否则尽量 resolve(strict=False)，减少盘符/大小写不一致。"""
    s = str(raw).strip()
    if not s:
        return s
    try:
        p = Path(s).expanduser()
        return str(p.resolve(strict=False))
    except (OSError, ValueError, RuntimeError):
        return s


def effective_min_clip_duration(cfg: RuleConfig) -> float:
    return max(0.0, float(cfg.min_clip_duration) - float(cfg.min_clip_duration_slack))


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def get_clips(storyboard: dict) -> List[dict]:
    clips = storyboard.get("clips")
    if not isinstance(clips, list):
        return []
    return clips


def clip_key(clip: dict) -> Tuple[str, int]:
    return (
        normalize_media_path(str(clip.get("source_video", ""))),
        int(clip.get("source_segment_id", -1)),
    )


def clip_duration(clip: dict) -> float:
    tc = clip.get("timecode") or {}
    return float(tc.get("duration", 0.0))


def tc_in_out(clip: dict) -> Tuple[float, float]:
    tc = clip.get("timecode") or {}
    return float(tc.get("in_point", 0.0)), float(tc.get("out_point", 0.0))


def effective_story_duration(clips: List[dict], default_transition: float) -> float:
    total = sum(clip_duration(c) for c in clips)
    overlap = 0.0
    for idx, c in enumerate(clips):
        if idx == len(clips) - 1:
            continue
        trans = c.get("transition") or {}
        overlap += float(trans.get("duration", default_transition))
    return total - overlap


def build_segment_pool(output_vlm: dict) -> Dict[str, List[dict]]:
    """
    output_vlm expected:
    {
      "processed_videos": [
        {
          "input_video": "...",
          "segments": [{"seg_id":0, "seg_start":0.0, "seg_end":3.0, ...}]
        }
      ]
    }
    """
    pool: Dict[str, List[dict]] = {}
    for item in output_vlm.get("processed_videos", []):
        raw = str(item.get("input_video", ""))
        key = normalize_media_path(raw)
        if not key:
            continue
        segs = item.get("segments", []) or []
        normalized: List[dict] = []
        for s in segs:
            try:
                seg_id = int(s["seg_id"])
                seg_start = float(s["seg_start"])
                seg_end = float(s["seg_end"])
                if seg_end > seg_start:
                    normalized.append(
                        {
                            "seg_id": seg_id,
                            "seg_start": seg_start,
                            "seg_end": seg_end,
                            "seg_dur": float(s.get("seg_dur", seg_end - seg_start)),
                            "seg_desc": str(s.get("seg_desc", "")),
                        }
                    )
            except Exception:
                continue
        normalized.sort(key=lambda x: x["seg_id"])
        if key not in pool:
            pool[key] = normalized
        else:
            by_id = {int(s["seg_id"]): s for s in pool[key]}
            for s in normalized:
                by_id[int(s["seg_id"])] = s
            pool[key] = sorted(by_id.values(), key=lambda x: x["seg_id"])
    return pool


def validate_storyboard(
    storyboard: dict,
    cfg: RuleConfig,
    output_vlm: Optional[dict] = None,
    check_source_exists: bool = False,
) -> List[str]:
    errors: List[str] = []
    clips = get_clips(storyboard)
    if not clips:
        return ["clips 为空或缺失"]

    target = float((storyboard.get("storyboard_metadata") or {}).get("target_duration_seconds", 0))
    used_pairs: Set[Tuple[str, int]] = set()
    per_video = Counter()

    # 规则：基础字段与时码一致性
    for i, c in enumerate(clips, start=1):
        src = str(c.get("source_video", ""))
        seg_id = int(c.get("source_segment_id", -1))
        if not src:
            errors.append(f"clip#{i}: source_video 为空")
        if seg_id < 0:
            errors.append(f"clip#{i}: source_segment_id 非法")

        in_point, out_point = tc_in_out(c)
        dur = clip_duration(c)
        calc = out_point - in_point
        if out_point <= in_point:
            errors.append(f"clip#{i}: out_point <= in_point")
        if abs(calc - dur) > 1e-3:
            errors.append(f"clip#{i}: duration({dur}) != out-in({calc})")

        # 片段时长下限：名义 min_clip_duration，实际允许 min_clip_duration - slack（见 RuleConfig）
        eff_min = effective_min_clip_duration(cfg)
        if i != len(clips) or not cfg.allow_last_clip_shorter:
            if dur < eff_min:
                errors.append(
                    f"clip#{i}: duration({dur}) < 最小阈值(有效下限 {eff_min}s，名义 {cfg.min_clip_duration}s)"
                )

        pair = clip_key(c)
        if pair in used_pairs:
            errors.append(f"clip#{i}: 重复片段 {pair}")
        used_pairs.add(pair)
        per_video[normalize_media_path(src)] += 1

        if check_source_exists and src and not Path(src).exists():
            errors.append(f"clip#{i}: source_video 不存在: {src}")

        vo = (c.get("voiceover") or {}).get("text", "")
        if not str(vo).strip():
            errors.append(f"clip#{i}: voiceover.text 为空")

    # 规则：相邻不可同源
    for i in range(len(clips) - 1):
        cur_src = normalize_media_path(str(clips[i].get("source_video", "")))
        nxt_src = normalize_media_path(str(clips[i + 1].get("source_video", "")))
        if cur_src and cur_src == nxt_src:
            errors.append(f"clip#{i+1} 与 clip#{i+2}: 相邻片段来自同一 source_video")

    # 规则：覆盖至少 min_unique_videos
    unique_videos = {
        normalize_media_path(str(c.get("source_video", "")))
        for c in clips
        if str(c.get("source_video", "")).strip()
    }
    if len(unique_videos) < cfg.min_unique_videos:
        errors.append(
            f"source_video 覆盖不足: 当前 {len(unique_videos)}，要求至少 {cfg.min_unique_videos}"
        )

    # 规则：同一 source_video 最多 per_video_max_clips 段
    for src, cnt in per_video.items():
        if cnt > cfg.per_video_max_clips:
            errors.append(
                f"{src}: 使用 {cnt} 段，超过每源上限 {cfg.per_video_max_clips}（每源最多 {cfg.per_video_max_clips} 段）"
            )

    # 规则：时长大致匹配
    if target > 0:
        actual = effective_story_duration(clips, cfg.default_transition_duration)
        if abs(actual - target) > cfg.duration_tolerance_sec:
            errors.append(
                f"时长偏差过大: target={target:.3f}s, estimated={actual:.3f}s, "
                f"tolerance={cfg.duration_tolerance_sec:.3f}s"
            )

    # 规则：seg_id 必须在 output_vlm 中有效（路径与池 key 均经 normalize_media_path）
    if output_vlm is not None:
        pool = build_segment_pool(output_vlm)
        for i, c in enumerate(clips, start=1):
            src = str(c.get("source_video", ""))
            seg_id = int(c.get("source_segment_id", -1))
            src_key = normalize_media_path(src)
            if src_key not in pool:
                errors.append(f"clip#{i}: source_video 不在 output_vlm.processed_videos 中: {src}")
                continue
            seg_map = {int(s["seg_id"]): s for s in pool[src_key]}
            if seg_id not in seg_map:
                errors.append(f"clip#{i}: seg_id={seg_id} 不在 output_vlm 对应 source_video 中")

    return errors


def _set_clip_from_segment(clip: dict, src: str, seg: dict) -> None:
    clip["source_video"] = normalize_media_path(src)
    clip["source_segment_id"] = int(seg["seg_id"])
    tc = clip.setdefault("timecode", {})
    tc["in_point"] = float(seg["seg_start"])
    tc["out_point"] = float(seg["seg_end"])
    tc["duration"] = float(seg["seg_end"] - seg["seg_start"])


def _pick_available_segment(
    src: str,
    pool: Dict[str, List[dict]],
    used_pairs: Set[Tuple[str, int]],
    min_clip_duration: float,
) -> Optional[dict]:
    for seg in pool.get(src, []):
        key = (src, int(seg["seg_id"]))
        if key in used_pairs:
            continue
        dur = float(seg["seg_end"] - seg["seg_start"])
        if dur < min_clip_duration:
            continue
        return seg
    return None


def autofix_storyboard(
    storyboard: dict,
    cfg: RuleConfig,
    output_vlm: dict,
) -> Tuple[dict, List[str]]:
    """
    轻量自动修复策略：
    1) 优先补齐 min_unique_videos（替换“超配额”来源的片段）
    2) 控制每源 clip 数 <= per_video_max_clips
    3) 尽量打散相邻同源（尝试交换后续 clip）
    4) 对被替换片段自动同步 in/out/duration
    """
    notes: List[str] = []
    fixed = json.loads(json.dumps(storyboard))
    clips = get_clips(fixed)
    pool = build_segment_pool(output_vlm)
    if not clips or not pool:
        return fixed, ["autofix 跳过：clips 或 output_vlm 为空"]

    used_pairs = {clip_key(c) for c in clips}
    per_video = Counter(
        normalize_media_path(str(c.get("source_video", ""))) for c in clips
    )
    unique_used = {s for s in per_video if s}
    all_sources = [s for s in pool.keys() if s]
    min_seg = effective_min_clip_duration(cfg)

    # Step 1: 补齐最少视频覆盖
    missing_sources = [s for s in all_sources if s not in unique_used]
    while len(unique_used) < cfg.min_unique_videos and missing_sources:
        # 找一个“最超配额”的 clip 进行替换
        replace_idx = -1
        for idx, c in enumerate(clips):
            src = normalize_media_path(str(c.get("source_video", "")))
            if per_video[src] > cfg.per_video_max_clips:
                replace_idx = idx
                break
        if replace_idx < 0:
            # 没有超配额，替换后部 clip 以尽量减少叙事影响
            replace_idx = len(clips) - 1

        new_src = missing_sources.pop(0)
        seg = _pick_available_segment(new_src, pool, used_pairs, min_seg)
        if seg is None:
            notes.append(f"补覆盖失败：{new_src} 没有可用 segment")
            continue

        old_src = normalize_media_path(str(clips[replace_idx].get("source_video", "")))
        old_pair = clip_key(clips[replace_idx])
        used_pairs.discard(old_pair)
        per_video[old_src] -= 1
        if per_video[old_src] <= 0:
            per_video.pop(old_src, None)
            unique_used.discard(old_src)

        _set_clip_from_segment(clips[replace_idx], new_src, seg)
        used_pairs.add(clip_key(clips[replace_idx]))
        per_video[normalize_media_path(str(clips[replace_idx].get("source_video", "")))] += 1
        unique_used.add(normalize_media_path(new_src))
        notes.append(f"clip#{replace_idx+1}: 替换为新来源 {Path(new_src).name} seg#{seg['seg_id']}")

    # Step 2: 压制过度重复（每源 <= per_video_max_clips）
    for idx, c in enumerate(clips):
        src = normalize_media_path(str(c.get("source_video", "")))
        if per_video[src] <= cfg.per_video_max_clips:
            continue

        replacement_done = False
        # 先找当前使用次数更低的来源
        candidates = sorted(
            [s for s in all_sources if s != src and per_video[s] < cfg.per_video_max_clips],
            key=lambda s: per_video[s],
        )
        for cand_src in candidates:
            seg = _pick_available_segment(cand_src, pool, used_pairs, min_seg)
            if seg is None:
                continue
            old_pair = clip_key(c)
            used_pairs.discard(old_pair)
            per_video[src] -= 1
            _set_clip_from_segment(c, cand_src, seg)
            used_pairs.add(clip_key(c))
            per_video[normalize_media_path(str(c.get("source_video", "")))] += 1
            notes.append(f"clip#{idx+1}: 降重复，{Path(src).name} -> {Path(cand_src).name}")
            replacement_done = True
            break

        if not replacement_done and per_video[src] > cfg.per_video_max_clips:
            notes.append(f"clip#{idx+1}: 仍超过每源上限，未找到替代来源")

    # Step 3: 尝试打散相邻同源（交换）
    for i in range(len(clips) - 1):
        a = normalize_media_path(str(clips[i].get("source_video", "")))
        b = normalize_media_path(str(clips[i + 1].get("source_video", "")))
        if a != b:
            continue
        swapped = False
        for j in range(i + 2, len(clips)):
            csrc = normalize_media_path(str(clips[j].get("source_video", "")))
            prev_ok = csrc != a
            next_ok = True
            if j + 1 < len(clips):
                next_ok = normalize_media_path(str(clips[j + 1].get("source_video", ""))) != b
            if prev_ok and next_ok:
                clips[i + 1], clips[j] = clips[j], clips[i + 1]
                notes.append(f"重排: 交换 clip#{i+2} 和 clip#{j+1} 以打散相邻同源")
                swapped = True
                break
        if not swapped:
            notes.append(f"重排失败: clip#{i+1}/#{i+2} 仍为相邻同源")

    # 同步 sequence_order（clip_id 不动）
    for idx, c in enumerate(clips, start=1):
        c["sequence_order"] = idx

    return fixed, notes


def build_report(
    storyboard: dict,
    cfg: RuleConfig,
) -> dict:
    clips = get_clips(storyboard)
    per_video = Counter(
        normalize_media_path(str(c.get("source_video", ""))) for c in clips
    )
    by_duration = defaultdict(float)
    for c in clips:
        by_duration[normalize_media_path(str(c.get("source_video", "")))] += clip_duration(c)
    target = float((storyboard.get("storyboard_metadata") or {}).get("target_duration_seconds", 0))
    estimated = effective_story_duration(clips, cfg.default_transition_duration)

    return {
        "clips_count": len(clips),
        "unique_source_videos": len([k for k in per_video.keys() if k]),
        "per_video_clip_count": dict(per_video),
        "per_video_duration_seconds": dict(by_duration),
        "target_duration_seconds": target,
        "estimated_output_duration_seconds": round(estimated, 3),
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Validate/fix storyboard.json against video-editing rules."
    )
    p.add_argument("--storyboard", required=True, help="Path to storyboard.json")
    p.add_argument(
        "--output-vlm",
        default=None,
        help="Path to output_vlm.json (needed for seg_id/source validation and autofix)",
    )
    p.add_argument(
        "--mode",
        choices=["validate", "autofix"],
        default="validate",
        help="validate: only check; autofix: try fix, then re-validate",
    )
    p.add_argument("--write-back", action="store_true", help="Write fixed storyboard back to file")
    p.add_argument("--report-json", default=None, help="Optional path to write report json")
    p.add_argument("--min-unique-videos", type=int, default=6)
    p.add_argument(
        "--per-video-max",
        type=int,
        default=3,
        help="Max clips per source_video (default: 3)",
    )
    p.add_argument(
        "--min-clip-duration",
        type=float,
        default=3.0,
        help="Minimum allowed clip duration in seconds (default: 3.0)",
    )
    p.add_argument(
        "--min-clip-duration-slack",
        type=float,
        default=0.5,
        help="Below min-clip-duration by up to this many seconds is still accepted (default: 0.5)",
    )
    p.add_argument("--allow-last-clip-shorter", action="store_true")
    p.add_argument("--duration-tolerance-sec", type=float, default=6.0)
    p.add_argument("--default-transition-duration", type=float, default=0.8)
    p.add_argument("--check-source-exists", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    storyboard_path = Path(args.storyboard).resolve()
    if not storyboard_path.exists():
        print(f"ERROR: storyboard not found: {storyboard_path}")
        return 2

    output_vlm = None
    if args.output_vlm:
        output_vlm_path = Path(args.output_vlm).resolve()
        if not output_vlm_path.exists():
            print(f"ERROR: output_vlm not found: {output_vlm_path}")
            return 2
        output_vlm = read_json(output_vlm_path)

    cfg = RuleConfig(
        min_unique_videos=args.min_unique_videos,
        per_video_max_clips=args.per_video_max,
        min_clip_duration=args.min_clip_duration,
        min_clip_duration_slack=args.min_clip_duration_slack,
        allow_last_clip_shorter=args.allow_last_clip_shorter,
        duration_tolerance_sec=args.duration_tolerance_sec,
        default_transition_duration=args.default_transition_duration,
    )

    storyboard = read_json(storyboard_path)
    work_storyboard = storyboard
    autofix_notes: List[str] = []

    if args.mode == "autofix":
        if output_vlm is None:
            print("ERROR: mode=autofix requires --output-vlm")
            return 2
        work_storyboard, autofix_notes = autofix_storyboard(storyboard, cfg, output_vlm)

    errors = validate_storyboard(
        work_storyboard,
        cfg,
        output_vlm=output_vlm,
        check_source_exists=args.check_source_exists,
    )

    report = build_report(work_storyboard, cfg)
    if autofix_notes:
        report["autofix_notes"] = autofix_notes
    report["validation_errors"] = errors

    if args.report_json:
        write_json(Path(args.report_json), report)

    if args.mode == "autofix" and args.write_back:
        write_json(storyboard_path, work_storyboard)
        print(f"INFO: fixed storyboard written: {storyboard_path}")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

