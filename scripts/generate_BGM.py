"""
generate_BGM.py - 使用 facebook/musicgen-small 从分镜脚本自动生成背景音乐。

从 storyboard.json 读取视频风格描述，将提示词转换为英文，
使用 MusicGen 模型生成音乐，并保存到 resource/bgm/ 目录。
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional


# 中文风格标签 → 英文音乐描述映射
STYLE_TAG_EN: dict[str, str] = {
    "舒缓优美": "soothing, gentle, beautiful, peaceful, calm ambient music",
    "温馨浪漫": "warm, romantic, tender, heartfelt, cozy background music",
    "民族古风": "traditional Chinese folk music, ancient style, ethnic instruments, guqin, erhu",
    "轻松愉悦": "light, pleasant, cheerful, easy-going, positive background music",
    "低沉忧郁": "melancholic, somber, introspective, emotional, sad background music",
    "活泼欢快": "lively, upbeat, joyful, energetic, festive, happy music",
}

# 情绪关键词 → 英文片段映射
MOOD_KEYWORD_EN: dict[str, str] = {
    "轻松": "relaxing and light",
    "活泼": "lively and playful",
    "温暖": "warm and comforting",
    "治愈": "healing and soothing",
    "诗意": "poetic and lyrical",
    "动感": "dynamic and rhythmic",
    "节日": "festive and celebratory",
    "喜庆": "joyful and festive",
    "感伤": "melancholic and nostalgic",
    "浪漫": "romantic",
    "古风": "ancient Chinese style",
    "清新": "fresh and bright",
    "悠扬": "melodious and flowing",
    "深沉": "deep and contemplative",
    "忧郁": "melancholic and introspective",
    "欢快": "cheerful and upbeat",
}

# 风格类型 → 英文映射
VLOG_TYPE_EN: dict[str, str] = {
    "旅行": "travel, adventure, exploration",
    "日常": "everyday life, daily routine",
    "美食": "food, culinary, tasting",
    "运动": "sports, athletic, energetic",
    "节日": "holiday, celebration, festival",
    "自然": "nature, outdoor, landscape",
    "城市": "urban, city life, metropolitan",
    "亲子": "family, children, heartwarming",
}

# Structured summary components: keywords in raw prompt -> (tempo, rhythm, instruments, timbre, mood)
# Used to build a single-line English summary like: "slow 4/4 tempo, steady rhythm, piano and violin lead, ..."
PROMPT_SUMMARY_MAP: list[tuple[list[str], tuple[str, str, str, str, str]]] = [
    # (trigger keywords, (tempo, rhythm, instruments, timbre, mood))
    (
        ["lively", "upbeat", "joyful", "energetic", "festive", "happy", "cheerful", "celebratory"],
        ("medium-fast 4/4 tempo", "steady bouncy rhythm", "piano, strings and light percussion lead", "bright warm timbre", "joyful energetic festive celebratory upbeat"),
    ),
    (
        ["soothing", "gentle", "peaceful", "calm", "ambient", "beautiful"],
        ("slow 4/4 tempo", "steady gentle rhythm", "piano, violin and flute lead", "soft warm bright timbre", "contemplative nostalgic gentle melancholic, dreamy ethereal, healing romantic lyrical, peaceful and serene"),
    ),
    (
        ["warm", "romantic", "tender", "heartfelt", "cozy"],
        ("moderate 4/4 tempo", "smooth flowing rhythm", "piano and strings lead", "warm soft timbre", "romantic tender lyrical, dreamy and intimate"),
    ),
    (
        ["melancholic", "somber", "introspective", "sad", "emotional"],
        ("slow 4/4 tempo", "steady minimal rhythm", "piano and cello lead", "soft dark warm timbre", "contemplative nostalgic gentle melancholic, dreamy ethereal"),
    ),
    (
        ["light", "pleasant", "easy-going", "positive", "relaxing"],
        ("moderate 4/4 tempo", "steady light rhythm", "piano and acoustic guitar lead", "soft bright timbre", "light pleasant cheerful, peaceful and serene"),
    ),
    (
        ["traditional", "folk", "ancient", "ethnic", "guqin", "erhu"],
        ("moderate 4/4 tempo", "flowing rhythm", "traditional and ethnic instruments lead", "warm organic timbre", "nostalgic lyrical, cultural and serene"),
    ),
    (
        ["dynamic", "rhythmic", "athletic", "sports"],
        ("fast 4/4 tempo", "driving rhythm", "percussion and synths lead", "bright punchy timbre", "energetic dynamic upbeat"),
    ),
]
DEFAULT_SUMMARY = ("moderate 4/4 tempo", "steady rhythm", "piano and strings lead", "warm balanced timbre", "pleasant cinematic mood, peaceful and serene")


def _strip_chinese_from_prompt(prompt: str) -> str:
    """Remove Chinese and other non-ASCII tokens; return English-only phrase list."""
    # Split by comma and strip; drop tokens that are purely non-ASCII
    tokens = [t.strip() for t in prompt.split(",") if t.strip()]
    en_tokens = []
    for t in tokens:
        # Keep token only if it contains at least one ASCII letter (so we keep "tempo", "4/4" etc.)
        if any(ord(c) < 128 and c.isalpha() for c in t):
            en_tokens.append(t)
        elif not any(ord(c) > 127 for c in t):
            en_tokens.append(t)
    return ", ".join(en_tokens) if en_tokens else prompt


def summarize_music_prompt(raw_prompt: str) -> str:
    """
    Summarize the raw music prompt into a structured English-only description:
    tempo, rhythm, instruments, timbre, mood. No Chinese in output.
    """
    en_only = _strip_chinese_from_prompt(raw_prompt)
    prompt_lower = en_only.lower()

    best_match = DEFAULT_SUMMARY
    best_score = 0
    for keywords, (tempo, rhythm, instruments, timbre, mood) in PROMPT_SUMMARY_MAP:
        score = sum(1 for k in keywords if k in prompt_lower)
        if score > best_score:
            best_score = score
            best_match = (tempo, rhythm, instruments, timbre, mood)

    tempo, rhythm, instruments, timbre, mood = best_match
    return f"{tempo}, {rhythm}, {instruments}, {timbre}, {mood}"


def try_translate(text: str) -> Optional[str]:
    """尝试使用 deep_translator 翻译中文文本为英文。"""
    try:
        from deep_translator import GoogleTranslator  # type: ignore

        result = GoogleTranslator(source="auto", target="en").translate(text)
        if result and result.strip():
            return result.strip()
    except Exception:
        pass
    return None


def map_keywords(text: str, keyword_map: dict[str, str]) -> list[str]:
    """在文本中查找关键词并返回对应英文片段。"""
    found = []
    for zh, en in keyword_map.items():
        if zh in text:
            found.append(en)
    return found


def build_music_prompt(storyboard_data: dict, video_duration: float) -> str:
    """从分镜脚本数据构建英文音乐生成提示词。"""
    storyboard_metadata = storyboard_data.get("storyboard_metadata") or {}
    audio_design = storyboard_data.get("audio_design") or {}
    bgm_info = audio_design.get("background_music") or {}
    story_outline = storyboard_data.get("story_outline") or {}

    parts: list[str] = []

    # 1. 风格标签（最高优先级，直接映射）
    style_tag = str(bgm_info.get("style_tag") or "").strip()
    if style_tag in STYLE_TAG_EN:
        parts.append(STYLE_TAG_EN[style_tag])
    elif style_tag:
        mapped = map_keywords(style_tag, MOOD_KEYWORD_EN)
        if mapped:
            parts.extend(mapped)

    # 2. BGM 情绪描述
    bgm_mood = str(bgm_info.get("mood") or "").strip()
    if bgm_mood:
        mood_parts = map_keywords(bgm_mood, MOOD_KEYWORD_EN)
        if mood_parts:
            parts.extend(mood_parts)
        else:
            translated = try_translate(bgm_mood)
            if translated:
                parts.append(translated)

    # 3. 视频整体情绪
    meta_mood = str(storyboard_metadata.get("mood") or "").strip()
    if meta_mood and meta_mood != bgm_mood:
        meta_mood_parts = map_keywords(meta_mood, MOOD_KEYWORD_EN)
        if meta_mood_parts:
            parts.extend(meta_mood_parts)

    # 4. 速度/节拍
    tempo = str(bgm_info.get("tempo") or "").strip()
    if tempo:
        tempo_en = try_translate(tempo) or tempo
        if tempo_en:
            parts.append(f"{tempo_en} tempo")

    # 5. 建议曲风
    suggested_genres = bgm_info.get("suggested_genres") or []
    if isinstance(suggested_genres, list) and suggested_genres:
        genre_parts = []
        for genre in suggested_genres[:3]:
            g = str(genre).strip()
            if not g:
                continue
            # 尝试映射或翻译
            mapped = map_keywords(g, MOOD_KEYWORD_EN)
            if mapped:
                genre_parts.extend(mapped)
            elif any(ord(c) > 127 for c in g):
                translated = try_translate(g)
                if translated:
                    genre_parts.append(translated)
            else:
                genre_parts.append(g)
        if genre_parts:
            parts.append(", ".join(genre_parts))

    # 6. BGM 摘要描述
    summary = str(bgm_info.get("summary") or "").strip()
    if summary:
        if not any(ord(c) > 127 for c in summary):
            # 已是英文或纯 ASCII
            parts.append(summary)
        else:
            translated_summary = try_translate(summary)
            if translated_summary:
                parts.append(translated_summary)

    # 7. vlog 类型
    vlog_type = str(storyboard_metadata.get("vlog_type") or "").strip()
    if vlog_type:
        for zh, en in VLOG_TYPE_EN.items():
            if zh in vlog_type:
                parts.append(en)
                break

    # 8. 兜底：使用主题
    if not parts:
        theme = str(storyboard_metadata.get("theme") or "").strip()
        if theme:
            translated_theme = try_translate(theme)
            desc = translated_theme if translated_theme else "vlog"
            parts.append(f"background music for {desc}")
        else:
            parts.append("pleasant cinematic background music, film score")

    # 9. 长视频提示
    if video_duration > 60:
        parts.append("continuous, looping, long form")

    # 去重并合并
    seen: set[str] = set()
    unique_parts: list[str] = []
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            unique_parts.append(p)

    prompt = ", ".join(unique_parts)
    return prompt


def get_video_duration(storyboard_data: dict) -> float:
    """从分镜脚本中获取视频预计时长（秒）。"""
    metadata = storyboard_data.get("storyboard_metadata") or {}
    duration = metadata.get("target_duration_seconds") or metadata.get(
        "actual_duration_seconds"
    )
    if duration:
        try:
            return float(duration)
        except (TypeError, ValueError):
            pass
    # 累加片段时长
    clips = storyboard_data.get("clips") or []
    total = 0.0
    for clip in clips:
        tc = clip.get("timecode") or {}
        d = tc.get("duration") or 0
        try:
            total += float(d)
        except (TypeError, ValueError):
            pass
    return total if total > 0 else 30.0


def generate_bgm(
    storyboard_path: Path,
    output_dir: Path,
    use_hf_mirror: bool = True,
) -> Path:
    """
    生成背景音乐并保存到 output_dir。

    Returns:
        生成的 WAV 文件路径。
    """
    if not storyboard_path.exists():
        raise FileNotFoundError(f"Storyboard not found: {storyboard_path}")

    with storyboard_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    video_duration = get_video_duration(data)
    raw_prompt = build_music_prompt(data, video_duration)
    prompt = summarize_music_prompt(raw_prompt)

    print(f"[generate_BGM] 音乐生成提示词（英文）: {prompt}")
    print(f"[generate_BGM] 视频目标时长: {video_duration:.1f}s")

    # 设置 HF 镜像
    if use_hf_mirror:
        os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
        print(f"[generate_BGM] 使用 HF 镜像: {os.environ.get('HF_ENDPOINT')}")

    # 懒加载重量级依赖，避免未安装时导入错误
    try:
        import numpy as np
        import scipy.io.wavfile  # type: ignore
        import torch
        from transformers import AutoProcessor, MusicgenForConditionalGeneration  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            f"缺少依赖: {exc}\n"
            "请安装: pip install transformers torch scipy numpy"
        ) from exc

    model_name = "facebook/musicgen-small"
    print(f"[generate_BGM] 正在加载模型: {model_name}")

    processor = AutoProcessor.from_pretrained(model_name)
    model = MusicgenForConditionalGeneration.from_pretrained(model_name)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    print(f"[generate_BGM] 使用设备: {device}")

    # musicgen-small: 50 帧/秒，每帧对应 ~0.02s 音频
    # max_new_tokens = duration_seconds * 50，上限 1500（约 30s）
    max_new_tokens = int(video_duration * 50)
    max_new_tokens = max(256, min(max_new_tokens, 1500))
    print(
        f"[generate_BGM] 生成 {max_new_tokens} tokens (~{max_new_tokens / 50:.1f}s 音频)..."
    )

    inputs = processor(
        text=[prompt],
        padding=True,
        return_tensors="pt",
    ).to(device)

    with torch.no_grad():
        audio_values = model.generate(**inputs, max_new_tokens=max_new_tokens)

    # 保存为 WAV
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = int(time.time())
    output_path = output_dir / f"generated_bgm_{timestamp}.wav"

    sampling_rate = model.config.audio_encoder.sampling_rate
    audio_data = audio_values[0, 0].cpu().numpy()

    # 归一化到 int16
    audio_int16 = (audio_data * 32767).clip(-32767, 32767).astype(np.int16)
    scipy.io.wavfile.write(str(output_path), rate=sampling_rate, data=audio_int16)

    print(f"[generate_BGM] 已保存: {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="使用 MusicGen 从分镜脚本自动生成背景音乐。"
    )
    parser.add_argument(
        "--storyboard",
        required=True,
        help="storyboard.json 文件路径",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="生成音乐的输出目录（默认：<SKILL_DIR>/resource/bgm/）",
    )
    parser.add_argument(
        "--no-hf-mirror",
        action="store_true",
        default=False,
        help="禁用 hf-mirror，使用默认 HuggingFace 端点",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    use_mirror = not args.no_hf_mirror

    storyboard_path = Path(args.storyboard)

    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        script_dir = Path(__file__).resolve().parent
        output_dir = script_dir.parent / "resource" / "bgm"

    try:
        bgm_path = generate_bgm(
            storyboard_path=storyboard_path,
            output_dir=output_dir,
            use_hf_mirror=use_mirror,
        )
        # 输出路径供调用方解析
        print(f"BGM_PATH={bgm_path}")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
