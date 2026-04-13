from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional, Tuple

MIN_PYTHON = (3, 10)
DEFAULT_MODEL_NAME = "Qwen2.5-VL-7B-Instruct-int4"

# 合成输出画幅：命令行未传 --target-resolution 且本常量非空时，由 compose_video 优先采用；
# 否则读工作区 runtime_env.json 的 compose_target_resolution，再否则按分镜源视频横竖多数推断。
DEFAULT_COMPOSE_TARGET_RESOLUTION: str | None = None

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
VENV_DIR = SKILL_DIR / ".venv"
VENV_PYTHON = VENV_DIR / "Scripts" / "python.exe"
REQUIREMENTS_FILE = SKILL_DIR / "requirements.txt"
REQUIREMENTS_STAMP = VENV_DIR / ".requirements.sha256"
BIN_DIR = SKILL_DIR / "bin"
FFMPEG_PATH = BIN_DIR / "ffmpeg.exe"
FFPROBE_PATH = BIN_DIR / "ffprobe.exe"
MODELS_DIR = SKILL_DIR / "models"
DEFAULT_MODEL_DIR = MODELS_DIR / DEFAULT_MODEL_NAME


def parse_resolution(res_str: str) -> Tuple[int, int]:
    """解析 'WxH' 或 'W:H' 格式的分辨率字符串，返回 (width, height)。"""
    for sep in ("x", "X", ":"):
        if sep in res_str:
            parts = res_str.split(sep, 1)
            try:
                w, h = int(parts[0]), int(parts[1])
                if w > 0 and h > 0:
                    return w, h
            except (ValueError, IndexError):
                pass
    raise ValueError(
        f"Invalid resolution format '{res_str}'. Expected 'WxH', e.g. '1920x1080'."
    )


def try_parse_resolution(value: object) -> Optional[Tuple[int, int]]:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return parse_resolution(value.strip())
    except ValueError:
        return None


def get_video_dimensions(ffprobe: str, video_path: Path) -> Optional[Tuple[int, int]]:
    """使用 ffprobe 获取视频的 (width, height)，失败时返回 None。"""
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            line = result.stdout.strip().split("\n")[0]
            parts = line.split(",")
            if len(parts) >= 2:
                return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return None


def infer_compose_target_resolution_from_dims(
    dimensions: Iterable[Optional[Tuple[int, int]]],
) -> Tuple[int, int]:
    """与 compose 一致：竖屏条数多于横屏 → 1080x1920，否则 → 1920x1080。"""
    portrait_count = sum(1 for d in dimensions if d and d[1] > d[0])
    landscape_count = sum(1 for d in dimensions if d and d[0] >= d[1])
    total_probed = portrait_count + landscape_count
    if total_probed > 0 and portrait_count > landscape_count:
        return (1080, 1920)
    return (1920, 1080)


def probe_compose_target_resolution_from_video_paths(
    ffprobe: str,
    video_paths: list[Path],
) -> Tuple[int, int]:
    dims = [get_video_dimensions(ffprobe, p) for p in video_paths]
    return infer_compose_target_resolution_from_dims(dims)


def read_workspace_compose_target_resolution(workspace_dir: Path) -> Optional[Tuple[int, int]]:
    """读取工作区 runtime_env.json 中的 compose_target_resolution（阶段 1 写入）。"""
    manifest = workspace_dir / "runtime_env.json"
    if not manifest.exists():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return try_parse_resolution(data.get("compose_target_resolution"))


def min_python_display() -> str:
    return f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]}"


def python_version_supported(version_info: tuple[int, int] | None = None) -> bool:
    if version_info is None:
        version_info = (sys.version_info.major, sys.version_info.minor)
    return version_info >= MIN_PYTHON


def assert_host_python_supported() -> None:
    if python_version_supported():
        return
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    raise RuntimeError(
        f"当前 Python 版本 {version} 不受支持，需要 Python >= {min_python_display()}。"
    )


def ensure_skill_venv() -> Path:
    assert_host_python_supported()
    if VENV_PYTHON.exists():
        return VENV_PYTHON

    VENV_DIR.parent.mkdir(parents=True, exist_ok=True)
    print(f"[venv] 创建统一虚拟环境：{VENV_DIR}")
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    if not VENV_PYTHON.exists():
        raise RuntimeError(f"虚拟环境创建后未找到 Python：{VENV_PYTHON}")
    print(f"[venv] ✓ 虚拟环境已就绪：{VENV_PYTHON}")
    return VENV_PYTHON


def requirements_digest() -> str:
    if not REQUIREMENTS_FILE.exists():
        return ""
    return hashlib.sha256(REQUIREMENTS_FILE.read_bytes()).hexdigest()


def requirements_current() -> bool:
    if not VENV_PYTHON.exists() or not REQUIREMENTS_STAMP.exists():
        return False
    return REQUIREMENTS_STAMP.read_text(encoding="utf-8").strip() == requirements_digest()


def ensure_skill_requirements(force: bool = False) -> Path:
    venv_python = ensure_skill_venv()
    digest = requirements_digest()

    if not force and digest and requirements_current():
        print(f"[venv] 依赖已是最新：{REQUIREMENTS_FILE}")
        return venv_python

    if not REQUIREMENTS_FILE.exists():
        raise FileNotFoundError(f"requirements.txt 不存在：{REQUIREMENTS_FILE}")

    print(f"[venv] 安装依赖：{REQUIREMENTS_FILE}")
    subprocess.run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
        check=True,
    )
    REQUIREMENTS_STAMP.write_text(digest, encoding="utf-8")
    print("[venv] ✓ requirements.txt 依赖安装完成")
    return venv_python


def running_in_skill_venv() -> bool:
    if not VENV_PYTHON.exists():
        return False
    try:
        current = Path(sys.executable).resolve()
        target = VENV_PYTHON.resolve()
    except OSError:
        return False
    return current == target


def maybe_reexec_in_skill_venv(script_path: Path) -> None:
    if running_in_skill_venv():
        return
    if not VENV_PYTHON.exists():
        return
    cmd = [str(VENV_PYTHON), str(script_path), *sys.argv[1:]]
    raise SystemExit(subprocess.call(cmd))


def runtime_summary() -> dict[str, str]:
    return {
        "skill_dir": str(SKILL_DIR),
        "venv_dir": str(VENV_DIR),
        "venv_python": str(VENV_PYTHON),
        "requirements_file": str(REQUIREMENTS_FILE),
        "ffmpeg": str(FFMPEG_PATH),
        "ffprobe": str(FFPROBE_PATH),
        "model_dir": str(DEFAULT_MODEL_DIR),
        "min_python": min_python_display(),
    }


def write_runtime_manifest(
    workspace_dir: Path,
    merge: dict[str, object] | None = None,
) -> Path:
    manifest_path = workspace_dir / "runtime_env.json"
    payload: dict[str, object] = dict(
        runtime_summary() | {"workspace_dir": str(workspace_dir)}
    )
    if merge:
        payload |= merge
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest_path
