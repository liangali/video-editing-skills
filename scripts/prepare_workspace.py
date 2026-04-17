"""
prepare_workspace.py - 阶段 1：验证视频目录、创建工作区并完成统一准备。

阶段 1 负责：
    1. 检查 / 创建 <SKILL_DIR>/.venv
    2. 按 requirements.txt 安装依赖到统一 .venv
    3. 检查 / 下载 <SKILL_DIR>/bin/ffmpeg.exe 与 ffprobe.exe
    4. 检查 / 下载 <SKILL_DIR>/models/Qwen2.5-VL-7B-Instruct-int4
    5. 创建工作区目录，ffprobe 扫描 --video-dir 内视频横竖多数，将 compose_target_resolution 写入 runtime_env.json

输入：
    --video-dir     视频文件所在目录（必需）
    --user-request  用户原始请求文本（可选，写入 user_input.txt）

输出：
    成功时最后一行打印工作区绝对路径，退出码 0。
    失败时打印错误信息到 stderr，退出码 1。

用法：
    python scripts/prepare_workspace.py --video-dir "D:\\videos" --user-request "30秒vlog"
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from bootstrap import bootstrap_environment
from skill_runtime import (
    infer_compose_target_resolution_from_dims,
    probe_all_video_dims,
    write_runtime_manifest,
)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".wmv"}


def find_videos(video_dir: Path) -> list[Path]:
    """在目录顶层查找视频文件（不递归子目录）。"""
    videos = []
    for f in sorted(video_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
            videos.append(f)
    return videos


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段 1：验证视频目录并创建工作区")
    parser.add_argument("--video-dir", required=True, help="视频文件所在目录")
    parser.add_argument("--user-request", default=None, help="用户原始请求文本")
    parser.add_argument(
        "--check-ffmpeg",
        action="store_true",
        help="兼容旧参数；阶段 1 现在总会处理 ffmpeg / ffprobe",
    )
    parser.add_argument(
        "--skip-model",
        action="store_true",
        help="跳过模型准备（仅调试用）",
    )
    parser.add_argument(
        "--force-requirements",
        action="store_true",
        help="强制重新安装 requirements.txt",
    )
    parser.add_argument(
        "--force-ffmpeg",
        action="store_true",
        help="强制重新下载 ffmpeg / ffprobe",
    )
    parser.add_argument(
        "--force-model",
        action="store_true",
        help="强制重新下载模型",
    )
    args = parser.parse_args()

    video_dir = Path(args.video_dir).resolve()

    # 1. 验证视频目录
    if not video_dir.is_dir():
        print(f"错误：视频目录不存在：{video_dir}", file=sys.stderr)
        return 1

    videos = find_videos(video_dir)
    if not videos:
        print(f"错误：目录中未找到视频文件：{video_dir}", file=sys.stderr)
        print(f"支持的格式：{', '.join(sorted(VIDEO_EXTENSIONS))}", file=sys.stderr)
        return 1

    print(f"[准备] 找到 {len(videos)} 个视频文件：")
    for v in videos:
        print(f"  {v.name}")

    # 2. 创建工作区
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    workspace = video_dir / f"editing_{timestamp}"
    workspace.mkdir(parents=True, exist_ok=True)
    print(f"[准备] 工作区已创建：{workspace}")

    # 3. 保存用户请求
    if args.user_request:
        user_input_file = workspace / "user_input.txt"
        try:
            user_input_file.write_text(args.user_request, encoding="utf-8")
            print(f"[准备] 用户请求已保存：{user_input_file}")
        except OSError as e:
            print(f"[准备] 警告：无法保存用户请求：{e}", file=sys.stderr)

    # 4. 统一准备运行时
    try:
        print("[准备] 开始统一准备 .venv / requirements / ffmpeg / model ...")
        runtime = bootstrap_environment(
            force_requirements=args.force_requirements,
            force_ffmpeg=args.force_ffmpeg,
            force_model=args.force_model,
            skip_model=args.skip_model,
        )
        print("[准备] ✓ 运行时准备完成")
        print(json.dumps(runtime, ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"[准备] ✗ 运行时准备失败：{e}", file=sys.stderr)
        return 1

    # 5. 探测视频目录画幅多数，供合成阶段读取 runtime_env.json
    # 每个视频只调用一次 ffprobe，结果同时写入缓存供 Stage 4 复用
    ffprobe = str(runtime["ffprobe"])
    video_dims_cache = probe_all_video_dims(ffprobe, videos)
    dims_list = [tuple(v) for v in video_dims_cache.values()]
    portrait_n = sum(1 for d in dims_list if d[1] > d[0])
    landscape_n = sum(1 for d in dims_list if d[0] >= d[1])
    total_ok = portrait_n + landscape_n
    tw, th = infer_compose_target_resolution_from_dims(dims_list)
    res_str = f"{tw}x{th}"
    if total_ok > 0 and portrait_n > landscape_n:
        print(
            f"[准备] 视频目录横竖统计：竖 {portrait_n} / 横 {landscape_n}（可探测 {total_ok} 个）→ "
            f"compose_target_resolution={res_str}"
        )
    elif total_ok > 0:
        print(
            f"[准备] 视频目录横竖统计：横 {landscape_n} / 竖 {portrait_n}（可探测 {total_ok} 个）→ "
            f"compose_target_resolution={res_str}"
        )
    else:
        print(
            f"[准备] 警告：未能探测任一视频分辨率，默认横屏画布 {res_str}（与 compose 兜底一致）"
        )

    # 6. 写入运行时清单（含 video_dims_cache 供 Stage 4 复用）
    try:
        manifest_path = write_runtime_manifest(
            workspace,
            merge={
                "compose_target_resolution": res_str,
                "video_dims_cache": video_dims_cache,
            },
        )
        print(f"[准备] runtime_env.json 已写入：{manifest_path}")
    except OSError as e:
        print(f"[准备] ✗ 无法写入 runtime_env.json：{e}", file=sys.stderr)
        return 1

    # 最后一行输出工作区路径
    print(str(workspace))
    return 0


if __name__ == "__main__":
    sys.exit(main())
