"""
analyze_video.py - 阶段 2：纯 Python 视频分析，替代 FLAMA。

使用 OpenCV 提取帧，OpenVINO GenAI VLMPipeline 进行视频内容分析。
输出与 FLAMA 完全兼容的 output_vlm.json 格式。

输入：
    --video-dir   视频文件所在目录（必需）
    --output      输出 JSON 文件路径（必需）
    --prompt      VLM 分析提示词（可选，有默认值）
    --model-dir   OpenVINO 模型目录（可选，默认 SKILL_DIR/models/Qwen2.5-VL-7B-Instruct-int4）
    --device      推理设备 GPU 或 CPU（可选，默认 GPU）
    --seg-duration  段时长秒数（可选，默认 3.0）
    --frames-per-seg  每段提取帧数（可选，默认 4）
    --scale       帧缩放比例（可选，默认 0.25）
    --max-tokens  VLM 最大生成 token 数（可选，默认 100）

输出：
    output_vlm.json 格式:
    {
      "processed_videos": [{
        "input_video": "D:\\path\\video.mp4",
        "segments": [{
          "seg_id": 0,
          "seg_start": 0.0,
          "seg_end": 3.0,
          "seg_dur": 3.0,
          "seg_desc": "AI生成的内容描述"
        }]
      }]
    }

用法：
    python scripts/analyze_video.py --video-dir "D:\\videos" --output "D:\\workspace\\output_vlm.json"
    python scripts/analyze_video.py --video-dir "D:\\videos" --output out.json --device CPU --seg-duration 2.0
"""

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv"}

DEFAULT_PROMPT = (
    "准确的描述这个视频片段中的主要内容，包括：场景环境、人物动作、"
    "画面构图、光线氛围、运镜方式。输出不超过100字的简要描述。"
)

DEFAULT_MODEL_DIR = SKILL_DIR / "models" / "Qwen2.5-VL-7B-Instruct-int4"


# ---------------------------------------------------------------------------
# 视频发现
# ---------------------------------------------------------------------------

def discover_videos(video_dir: Path) -> list[Path]:
    """扫描目录顶层查找视频文件，按文件名排序。"""
    videos = []
    for f in sorted(video_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            videos.append(f)
    return videos


# ---------------------------------------------------------------------------
# 视频时长获取
# ---------------------------------------------------------------------------

def get_video_duration(video_path: Path, ffprobe_path: str | None = None) -> float:
    """
    获取视频时长（秒）。优先使用 OpenCV，ffprobe 作为回退。
    """
    # 方法 1: OpenCV
    cap = cv2.VideoCapture(str(video_path))
    if cap.isOpened():
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        if fps > 0 and frame_count > 0:
            return frame_count / fps

    # 方法 2: ffprobe
    if ffprobe_path and Path(ffprobe_path).exists():
        try:
            result = subprocess.run(
                [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass

    raise RuntimeError(f"无法获取视频时长：{video_path}")


# ---------------------------------------------------------------------------
# 帧提取
# ---------------------------------------------------------------------------

def extract_segment_frames(
    video_path: Path,
    seg_start: float,
    seg_end: float,
    num_frames: int = 4,
    scale: float = 0.25,
) -> list[Image.Image]:
    """
    从视频指定时间段中等间隔提取帧。

    Returns:
        PIL Image 列表（RGB 格式，已按 scale 缩放）
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            return []

        seg_duration = seg_end - seg_start
        if seg_duration <= 0:
            return []

        if num_frames <= 1:
            positions = [seg_start + seg_duration / 2]
        else:
            positions = [
                seg_start + i * seg_duration / (num_frames - 1)
                for i in range(num_frames)
            ]

        frames = []
        for pos in positions:
            frame_idx = int(pos * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if not ret:
                continue
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            pil_frame = Image.fromarray(frame_rgb)
            if scale != 1.0 and scale > 0:
                new_w = max(1, int(pil_frame.width * scale))
                new_h = max(1, int(pil_frame.height * scale))
                pil_frame = pil_frame.resize((new_w, new_h), Image.Resampling.LANCZOS)
            frames.append(pil_frame)

        return frames
    finally:
        cap.release()


# ---------------------------------------------------------------------------
# VLM 管线
# ---------------------------------------------------------------------------

def init_vlm_pipeline(model_dir: Path, device: str = "GPU"):
    """初始化 OpenVINO GenAI VLMPipeline。"""
    import openvino_genai as ov_genai
    print(f"[VLM] 正在初始化模型：{model_dir}")
    print(f"[VLM] 设备：{device}")
    pipeline = ov_genai.VLMPipeline(str(model_dir), device)
    print("[VLM] ✓ 模型初始化完成")
    return pipeline


def analyze_segment_vlm(
    pipeline,
    frames: list[Image.Image],
    prompt: str,
    max_new_tokens: int = 100,
) -> str:
    """使用 VLM 分析一组帧，返回文本描述。"""
    import openvino as ov

    image_tensors = []
    for img in frames:
        rgb = img.convert("RGB")
        arr = np.array(rgb, dtype=np.uint8)
        image_tensors.append(ov.Tensor(arr))

    generation_config = {"repetition_penalty": 1.2}

    response = pipeline.generate(
        prompt,
        images=image_tensors if image_tensors else None,
        max_new_tokens=max_new_tokens,
        **generation_config,
    )

    result = str(response).strip() if response else ""
    for term in ["<|im_end|>", "<|endoftext|>"]:
        result = result.replace(term, "")
    result = result.strip()
    return result if result else "（模型未生成有效描述）"


# ---------------------------------------------------------------------------
# 单视频处理
# ---------------------------------------------------------------------------

def process_video(
    video_path: Path,
    pipeline,
    prompt: str,
    seg_duration: float,
    frames_per_seg: int,
    scale: float,
    max_tokens: int,
    ffprobe_path: str | None,
) -> dict:
    """处理单个视频：分段 → 提取帧 → VLM 分析 → 返回 FLAMA 格式结果。"""
    duration = get_video_duration(video_path, ffprobe_path)
    num_segments = max(1, math.ceil(duration / seg_duration))

    print(f"  时长：{duration:.2f}s，分 {num_segments} 段")

    segments = []
    for seg_id in range(num_segments):
        seg_start = seg_id * seg_duration
        seg_end = min((seg_id + 1) * seg_duration, duration)
        seg_dur = seg_end - seg_start

        # 提取帧
        seg_start_time = time.time()
        frames = extract_segment_frames(
            video_path, seg_start, seg_end, frames_per_seg, scale
        )

        if not frames:
            desc = "无法提取帧"
        else:
            # VLM 推理
            try:
                desc = analyze_segment_vlm(pipeline, frames, prompt, max_tokens)
            except Exception as e:
                desc = f"分析失败：{e}"
                print(f"    段 {seg_id} VLM 推理失败：{e}", file=sys.stderr)

        elapsed = time.time() - seg_start_time
        print(f"    段 {seg_id}: {seg_start:.1f}s-{seg_end:.1f}s | {len(frames)} 帧 | {elapsed:.1f}s | {desc[:50]}...")

        segments.append({
            "seg_id": seg_id,
            "seg_start": round(seg_start, 3),
            "seg_end": round(seg_end, 3),
            "seg_dur": round(seg_dur, 3),
            "seg_desc": desc,
        })

    return {
        "input_video": str(video_path),
        "segments": segments,
    }


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="阶段 2：视频分析（替代 FLAMA），输出 output_vlm.json"
    )
    parser.add_argument("--video-dir", required=True, help="视频文件所在目录")
    parser.add_argument("--output", "--json-file", required=True, dest="output",
                        help="输出 JSON 文件路径")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="VLM 分析提示词")
    parser.add_argument("--model-dir", default=None,
                        help=f"OpenVINO 模型目录（默认：{DEFAULT_MODEL_DIR}）")
    parser.add_argument("--device", default="GPU", choices=["GPU", "CPU"],
                        help="推理设备（默认：GPU）")
    parser.add_argument("--seg-duration", type=float, default=3.0,
                        help="段时长秒数（默认：3.0）")
    parser.add_argument("--frames-per-seg", type=int, default=4,
                        help="每段提取帧数（默认：4）")
    parser.add_argument("--scale", type=float, default=0.25,
                        help="帧缩放比例（默认：0.25）")
    parser.add_argument("--max-tokens", type=int, default=100,
                        help="VLM 最大生成 token 数（默认：100）")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # 参数校验
    if args.seg_duration <= 0:
        print("错误：--seg-duration 必须为正数", file=sys.stderr)
        return 1
    if args.frames_per_seg < 1:
        print("错误：--frames-per-seg 必须 >= 1", file=sys.stderr)
        return 1
    if args.scale <= 0:
        print("错误：--scale 必须为正数", file=sys.stderr)
        return 1

    # 解析路径
    video_dir = Path(args.video_dir).resolve()
    output_path = Path(args.output).resolve()
    model_dir = Path(args.model_dir) if args.model_dir else DEFAULT_MODEL_DIR
    ffprobe_path = str(SKILL_DIR / "bin" / "ffprobe.exe")

    # 验证模型目录
    if not model_dir.is_dir():
        print(f"错误：模型目录不存在：{model_dir}", file=sys.stderr)
        print("请运行：python scripts/setup_ov_model.py", file=sys.stderr)
        return 1

    # 发现视频
    videos = discover_videos(video_dir)
    if not videos:
        print(f"错误：目录中未找到视频文件：{video_dir}", file=sys.stderr)
        return 1

    print(f"[分析] 找到 {len(videos)} 个视频文件")
    print(f"[分析] 模型：{model_dir}")
    print(f"[分析] 设备：{args.device}")
    print(f"[分析] 段时长：{args.seg_duration}s，每段 {args.frames_per_seg} 帧，缩放 {args.scale}")
    print()

    # 初始化 VLM
    total_start = time.time()
    pipeline = init_vlm_pipeline(model_dir, args.device)

    # 逐视频处理
    results = []
    for i, video_path in enumerate(videos):
        pct = int((i / len(videos)) * 100)
        print(f"\n[{i+1}/{len(videos)}] {pct}% {video_path.name}")
        result = process_video(
            video_path=video_path,
            pipeline=pipeline,
            prompt=args.prompt,
            seg_duration=args.seg_duration,
            frames_per_seg=args.frames_per_seg,
            scale=args.scale,
            max_tokens=args.max_tokens,
            ffprobe_path=ffprobe_path,
        )
        results.append(result)

    # 写入输出
    output_data = {"processed_videos": results}
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"错误：无法写入输出文件 {output_path}：{e}", file=sys.stderr)
        return 1

    total_time = time.time() - total_start
    total_segments = sum(len(r["segments"]) for r in results)
    print(f"\n[分析] ✓ 完成：{len(videos)} 个视频，{total_segments} 个段，总耗时 {total_time:.1f}s")
    print(f"[分析] 输出：{output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
