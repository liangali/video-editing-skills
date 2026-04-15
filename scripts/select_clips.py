#!/usr/bin/env python3
"""
select_clips.py — 主题感知片段预选器（video-editing-skills 工作流）

从 output_vlm.json 中智能筛选片段，生成供 SKILL step 3.6 使用的候选片段池。

处理流程：
  Step 1: 解析 output_vlm.json，按主题对每个视频/片段评分（优先解析 seg_desc 首行“主题判定”）
  Step 2: 选出全部 video_score > 0 的主题相关视频（越多越好）；
          若相关视频数不足 --min-videos（默认 6），从剩余视频中按片段数补充至 min_videos
  Step 3: 两轮选片（每个视频最多 --max-per-video 段，默认 2）
          第 1 轮：每个视频取得分最高的 1 段（广覆盖优先）
          第 2 轮：若还有余量，再取每个视频第 2 高分段
  Step 4: 打散排列（第 1 轮所有片段在前，第 2 轮紧随其后；同轮内相邻不同源）
  Step 5: 写出 candidate_clips.json，供 SKILL step 3.6 直接使用

使用方法：
    python select_clips.py \\
        --output-vlm  <workspace>/output_vlm.json \\
        --theme       "节日庆典" \\
        --output      <workspace>/candidate_clips.json \\
        [--min-videos 6] \\
        [--max-per-video 3] \\
        [--min-clip-duration 1.5] \\
        [--extra-keywords "灯笼,烟花,喜庆"]

输出 candidate_clips.json 格式：
  - selection_metadata：选片统计与参数摘要
  - candidate_clips：已评分、已打散的候选片段列表
    每个片段包含 source_video / source_segment_id / timecode / seg_desc / theme_score
    AI 在 step 3.6 中直接从此列表选片，补充 voiceover.text / 转场 / BGM 后即可生成 storyboard.json
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ──────────────────────────────────────────────
# 主题评分
# ──────────────────────────────────────────────

# 评分时用于检测否定上下文的词
_NEGATION_WORDS = [
    "没有", "无法", "不符合", "未体现", "不存在", "未见", "缺乏", "无关", "不含", "未出现",
    "不匹配", "未匹配", "不具备", "不包含", "并未", "没能", "难以", "不能",
]

# 句子边界标点（按句号/感叹号/问号/分号切，保留逗号在同一句内以捕获跨逗号的否定）
_SENTENCE_ENDS = frozenset("。！？；\n")


def extract_keywords(theme: str, extra: Optional[List[str]] = None) -> List[str]:
    """
    从主题字符串提取搜索关键词：
      - 整个主题字符串本身
      - 按非字母/中文字符分割后的各词条
      - 所有 2-字 bigrams（滑动窗口）
    额外关键词通过 --extra-keywords 注入。
    """
    clean = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", " ", theme)
    parts = [p.strip() for p in clean.split() if p.strip()]

    kws: List[str] = []
    theme_clean = "".join(parts)
    if len(theme_clean) >= 2:
        kws.append(theme_clean)

    for part in parts:
        if len(part) >= 2:
            kws.append(part)
        for i in range(len(part) - 1):
            kws.append(part[i : i + 2])

    if extra:
        for kw in extra:
            kw = kw.strip()
            if kw:
                kws.append(kw)

    # 去重，保留最长者优先排序（避免子串重复计分）
    seen: set = set()
    unique: List[str] = []
    for kw in sorted(kws, key=len, reverse=True):
        if kw not in seen:
            seen.add(kw)
            unique.append(kw)
    return unique


def _sentence_of(text: str, idx: int) -> str:
    """
    提取包含位置 idx 的句子（以 。！？；\\n 为边界，逗号保留在同一句内）。

    VLM 描述的典型结构是：
      "由于没有出现节日元素，因此无法完全匹配「节日庆典」的主题。"
    否定词（"无法"）和关键词（"节日庆典"）在同一句话里，
    但可能被逗号分隔到不同子句——按句号切可以完整捕获整句的否定信号。
    """
    start = 0
    for i in range(idx - 1, -1, -1):
        if text[i] in _SENTENCE_ENDS:
            start = i + 1
            break
    end = len(text)
    for i in range(idx, len(text)):
        if text[i] in _SENTENCE_ENDS:
            end = i + 1
            break
    return text[start:end]


def score_text(text: str, keywords: List[str]) -> float:
    """
    对一段描述文本进行主题相关性评分。
    正向命中：关键词所在句子内无否定词 → +weight
    负向命中：关键词所在句子内含否定词 → -weight
    长关键词（≥3字）权重 ×2；最终分数 floor 到 0。

    使用句子级别（以 。！？；\\n 划界，逗号不切断）而非固定前缀窗口：
    - 修复 "无法完全匹配「节日庆典」" 中 "无法" 落在 6 字窗口之外的漏判
    - 修复 "与节日庆典主题不相关，场景中无法体现…" 中否定词跨逗号子句的漏判
    """
    if not text or not keywords:
        return 0.0

    raw_score = 0.0
    scored_spans: List[Tuple[int, int]] = []

    for kw in keywords:
        weight = 2.0 if len(kw) >= 3 else 1.0
        start = 0
        while True:
            idx = text.find(kw, start)
            if idx == -1:
                break
            end = idx + len(kw)
            overlaps = any(s <= idx and end <= e for s, e in scored_spans)
            if not overlaps:
                sentence = _sentence_of(text, idx)
                is_negated = any(neg in sentence for neg in _NEGATION_WORDS)
                raw_score += -weight if is_negated else weight
                scored_spans.append((idx, end))
            start = idx + 1

    return max(0.0, raw_score)


# 与 analyze_video.py 中 build_theme_aware_prompt 约定的首行格式一致
# 新格式：主题判定: <总结>（符合/部分符合/不符合）
# 兼容旧格式：THEME_VERDICT: MATCH|PARTIAL|MISMATCH 与 legacy 中文判定头
_THEME_VERDICT_HEAD_RE_NEW_CN = re.compile(r"主题判定\s*[:：][^\n]{0,200}?(不符合|部分符合|符合)")
_THEME_VERDICT_HEAD_RE_OLD_EN = re.compile(r"THEME_VERDICT\s*[:：]\s*(MATCH|PARTIAL|MISMATCH)", re.IGNORECASE)
_THEME_VERDICT_HEAD_RE_OLD_CN_BRACKET = re.compile(r"\u3010主题判定\u3011[：:\s]*(不符合|部分符合|符合)")


def parse_leading_theme_verdict(text: str) -> Optional[str]:
    """
    解析 seg_desc 开头的主题判定行（由 VLM 主题感知提示生成）。

    Returns:
        "match" | "partial" | "mismatch" | None（无标记时保持纯关键词打分，兼容旧数据）
    """
    if not text:
        return None
    head = text.lstrip()[:240]
    first_line = head.splitlines()[0] if head else ""
    m_new_cn = _THEME_VERDICT_HEAD_RE_NEW_CN.search(first_line)
    if m_new_cn:
        label = m_new_cn.group(1)
        if label == "符合":
            return "match"
        if label == "不符合":
            return "mismatch"
        return "partial"

    m_old_en = _THEME_VERDICT_HEAD_RE_OLD_EN.search(head)
    if m_old_en:
        label = m_old_en.group(1).upper()
        if label == "MATCH":
            return "match"
        if label == "MISMATCH":
            return "mismatch"
        return "partial"

    m_old_cn = _THEME_VERDICT_HEAD_RE_OLD_CN_BRACKET.search(head)
    if m_old_cn:
        label = m_old_cn.group(1)
        if label == "符合":
            return "match"
        if label == "不符合":
            return "mismatch"
        return "partial"
    return None


def score_segment(desc: str, keywords: List[str]) -> float:
    """
    片段主题分：优先采纳 VLM 首行“主题判定”（兼容旧格式），否则退回 score_text 关键词打分。
    """
    base = score_text(desc, keywords)
    verdict = parse_leading_theme_verdict(desc)
    if verdict == "mismatch":
        return 0.0
    if verdict == "match":
        return max(base, 3.0)
    if verdict == "partial":
        return max(base, 1.5)
    return base


# ──────────────────────────────────────────────
# 路径归一化（与 storyboard_guard.py 保持一致）
# ──────────────────────────────────────────────


def normalize_path(raw: str) -> str:
    s = str(raw).strip()
    if not s:
        return s
    try:
        return str(Path(s).resolve(strict=False))
    except Exception:
        return s


# ──────────────────────────────────────────────
# 两轮打散算法
# ──────────────────────────────────────────────


def _scatter_one_round(clips: List[dict], sorted_sources: List[str]) -> List[dict]:
    """
    将 clips 按 sorted_sources 顺序轮转排列，同轮内相邻不来自同一视频。
    若所有剩余片段均同源则直接追加（兜底，避免死循环）。
    """
    groups: Dict[str, deque] = defaultdict(deque)
    for clip in clips:
        groups[clip["source_video"]].append(clip)

    result: List[dict] = []
    last_src: Optional[str] = None

    while any(groups.values()):
        placed = False
        for src in sorted_sources:
            if groups[src] and src != last_src:
                result.append(groups[src].popleft())
                last_src = src
                placed = True
                break
        if not placed:
            for src in sorted_sources:
                if groups[src]:
                    result.append(groups[src].popleft())
                    last_src = src
                    break

    return result


def interleave_clips(clips: List[dict], max_per_video: int = 2) -> List[dict]:
    """
    两轮选片打散：
      第 1 轮：每个视频取得分最高的 1 段，按视频得分高→低轮转排列（广覆盖优先）。
      第 2 轮：若 max_per_video ≥ 2，再取每个视频第 2 高分段，同样轮转排列。
    同轮内保证相邻片段不来自同一 source_video。
    """
    # 按 source_video 分组，组内按得分降序
    groups: Dict[str, List[dict]] = defaultdict(list)
    for clip in clips:
        groups[clip["source_video"]].append(clip)
    for src in groups:
        groups[src].sort(key=lambda c: c["theme_score"], reverse=True)

    # 视频按最高片段得分降序（得分高的视频优先出现在轮转序列里）
    sorted_sources = sorted(
        groups.keys(),
        key=lambda src: max(c["theme_score"] for c in groups[src]),
        reverse=True,
    )

    round1 = [groups[src][0] for src in sorted_sources if groups[src]]
    round2 = [groups[src][1] for src in sorted_sources if len(groups[src]) > 1 and max_per_video >= 2]

    result = _scatter_one_round(round1, sorted_sources)
    if round2:
        result += _scatter_one_round(round2, sorted_sources)

    return result


# ──────────────────────────────────────────────
# 主选片逻辑
# ──────────────────────────────────────────────


def select_and_scatter(
    output_vlm: dict,
    theme: str,
    min_videos: int = 6,
    max_per_video: int = 2,
    min_clip_duration: float = 1.5,
    extra_keywords: Optional[List[str]] = None,
) -> Tuple[List[dict], dict]:
    """
    核心选片逻辑，返回 (scattered_clips, metadata_summary)。

    1. 对每个视频的每个片段打分（若 seg_desc 含“主题判定”则优先采用，否则关键词打分）
    2. 视频总分 = 所有片段分数之和
    3. 选出全部 video_score > 0 的视频（主题相关，越多越好）；
       若相关视频数 < min_videos，从剩余视频中按片段数补充
    4. 两轮选片：第 1 轮每视频取最优 1 段（广覆盖），第 2 轮补第 2 段（max_per_video=2）
    5. 打散排列：第 1 轮全部在前，第 2 轮紧随其后；同轮内相邻不同源
    """
    keywords = extract_keywords(theme, extra=extra_keywords)

    # ── 阶段 1：解析并评分 ──
    all_videos: List[dict] = []
    for item in output_vlm.get("processed_videos", []):
        video_path = str(item.get("input_video", "")).strip()
        if not video_path:
            continue

        scored_segs: List[dict] = []
        for seg in item.get("segments", []) or []:
            try:
                seg_start = float(seg["seg_start"])
                seg_end = float(seg["seg_end"])
                dur = seg_end - seg_start
                if dur < min_clip_duration:
                    continue
                desc = str(seg.get("seg_desc", ""))
                scored_segs.append(
                    {
                        "seg_id": int(seg["seg_id"]),
                        "seg_start": seg_start,
                        "seg_end": seg_end,
                        "duration": dur,
                        "seg_desc": desc,
                        "theme_score": score_segment(desc, keywords),
                    }
                )
            except (KeyError, ValueError, TypeError):
                continue

        if not scored_segs:
            continue

        video_score = sum(s["theme_score"] for s in scored_segs)
        positive_ratio = sum(1 for s in scored_segs if s["theme_score"] > 0) / len(scored_segs)
        all_videos.append(
            {
                "video_path": video_path,
                "video_score": video_score,
                "positive_ratio": positive_ratio,
                "segments": scored_segs,
            }
        )

    if not all_videos:
        return [], {"error": "output_vlm.json 中没有有效的视频/片段数据"}

    # ── 阶段 2：选出全部主题相关视频，不足时补充 ──
    all_videos.sort(key=lambda v: (v["video_score"], v["positive_ratio"]), reverse=True)

    matched = [v for v in all_videos if v["video_score"] > 0]
    unmatched = [v for v in all_videos if v["video_score"] == 0]

    # 默认取全部相关视频
    selected_videos = list(matched)
    padded_count = 0

    # 若相关视频不足 min_videos，从无关视频（按片段数排序）中补充
    if len(selected_videos) < min_videos:
        needed = min_videos - len(selected_videos)
        fill = sorted(unmatched, key=lambda v: len(v["segments"]), reverse=True)[:needed]
        selected_videos.extend(fill)
        padded_count = len(fill)

    # ── 阶段 3：每个视频取最优 ≤ max_per_video 个片段 ──
    all_clips: List[dict] = []
    for rank, video in enumerate(selected_videos, start=1):
        best_segs = sorted(video["segments"], key=lambda s: s["theme_score"], reverse=True)[
            :max_per_video
        ]
        for seg in best_segs:
            all_clips.append(
                {
                    "source_video": video["video_path"],
                    "source_segment_id": seg["seg_id"],
                    "timecode": {
                        "in_point": seg["seg_start"],
                        "out_point": seg["seg_end"],
                        "duration": seg["duration"],
                    },
                    "seg_desc": seg["seg_desc"],
                    "theme_score": seg["theme_score"],
                    "video_rank": rank,
                    "video_score": video["video_score"],
                }
            )

    # ── 阶段 4：两轮打散（第 1 轮：每视频 1 段；第 2 轮：补第 2 段） ──
    scattered = interleave_clips(all_clips, max_per_video=max_per_video)

    # ── 元数据摘要 ──
    unique_videos = list(dict.fromkeys(c["source_video"] for c in scattered))
    pad_note = (
        f"相关视频不足 {min_videos} 个，额外补充了 {padded_count} 个非主题视频。"
        if padded_count
        else ""
    )
    summary = {
        "theme": theme,
        "theme_keywords": keywords,
        "min_clip_duration_threshold": min_clip_duration,
        "total_videos_in_vlm": len(all_videos),
        "theme_matched_videos": len(matched),
        "selected_videos_count": len(selected_videos),
        "padded_from_unmatched": padded_count,
        "total_candidate_clips": len(scattered),
        "clips_per_video_limit": max_per_video,
        "selected_video_paths": unique_videos,
        "note": (
            f"从 {len(all_videos)} 个原始视频中选出 {len(matched)} 个主题相关视频"
            f"（video_score > 0），共 {len(scattered)} 个候选片段。{pad_note}"
            " AI 在 step 3.6 中从此池选片，补充 voiceover.text / 转场 / BGM 后生成 storyboard.json。"
        ),
    }

    return scattered, summary


# ──────────────────────────────────────────────
# 入口
# ──────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Theme-aware clip pre-selector for video-editing-skills workflow.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--output-vlm", required=True, help="output_vlm.json 路径（必需）")
    p.add_argument("--theme", required=True, help="视频主题，用于相关性评分（必需）")
    p.add_argument("--output", required=True, help="输出 candidate_clips.json 路径（必需）")
    p.add_argument(
        "--min-videos",
        type=int,
        default=6,
        help="主题相关视频不足时，从非相关视频补充至此数量（默认 6）",
    )
    p.add_argument(
        "--max-per-video",
        type=int,
        default=2,
        help="每个视频最多保留多少个片段（默认 2）；第 1 轮每视频取 1 段，第 2 轮补第 2 段",
    )
    p.add_argument(
        "--min-clip-duration",
        type=float,
        default=1.5,
        help="片段最短时长阈值，秒（默认 1.5）",
    )
    p.add_argument(
        "--extra-keywords",
        default="",
        help="附加关键词，逗号分隔（如 '灯笼,烟花,喜庆'）",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    vlm_path = Path(args.output_vlm).resolve()
    if not vlm_path.exists():
        print(f"ERROR: output_vlm.json 不存在: {vlm_path}")
        return 2

    with vlm_path.open("r", encoding="utf-8") as f:
        output_vlm = json.load(f)

    extra_kws = (
        [k.strip() for k in args.extra_keywords.split(",") if k.strip()]
        if args.extra_keywords
        else None
    )

    clips, summary = select_and_scatter(
        output_vlm=output_vlm,
        theme=args.theme,
        min_videos=args.min_videos,
        max_per_video=args.max_per_video,
        min_clip_duration=args.min_clip_duration,
        extra_keywords=extra_kws,
    )

    if "error" in summary:
        print(f"ERROR: {summary['error']}")
        return 1

    out_path = Path(args.output).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({"selection_metadata": summary, "candidate_clips": clips}, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nINFO: candidate_clips.json 已写入: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
