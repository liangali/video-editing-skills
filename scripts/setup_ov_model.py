"""
setup_ov_model.py - 从 HuggingFace 下载 OpenVINO/Qwen2.5-VL-7B-Instruct-int4-ov，
                    并部署到 flama 的 models 目录下。

输出路径：<FLAMA_BIN_DIR>/models/<OUTPUT_DIR_NAME>/
  - 默认 FLAMA_BIN_DIR = <SKILL_DIR>/bin/flama（可通过 --flama-dir 或 FLAMA_PATH 覆盖）
  - 默认输出子目录名 = Qwen2.5-VL-7B-Instruct-int4-ov

下载完成后，flama 的 config.json 中 "genai.model_path" 将自动设置为 "models/<OUTPUT_DIR_NAME>"。

用法：
    # 基础（默认使用 hf-mirror 镜像，国内推荐）
    python setup_ov_model.py

    # 使用自定义 HF 镜像地址
    python setup_ov_model.py --hf-mirror https://hf-mirror.com

    # 不使用镜像（直连 HuggingFace，需要科学上网）
    python setup_ov_model.py --no-mirror

    # 指定代理（国内网络）
    set HTTPS_PROXY=http://127.0.0.1:7890
    python setup_ov_model.py

    # 指定 flama 目录 / 输出子目录名
    python setup_ov_model.py --flama-dir E:\\data\\agentkit\\flama\\build\\bin\\Release
    python setup_ov_model.py --output-name Qwen2.5-VL-7B-Instruct-int4-ov

    # 强制重新下载（即使目录已存在）
    python setup_ov_model.py --force

    # 只校验已有模型是否存在，不执行下载
    python setup_ov_model.py --check-only

依赖（运行前需安装）：
    pip install huggingface_hub
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent

# flama 目录查找顺序：1) --flama-dir 参数；2) FLAMA_PATH 环境变量（取 exe 所在目录）；
# 3) <SKILL_DIR>/bin/flama；4) 项目默认路径
_DEFAULT_FLAMA_DIRS = [
    SKILL_DIR / "bin" / "flama",
    Path("E:/data/agentkit/flama/build/bin/Release"),
]

# HuggingFace 模型 ID（已转换好的 OpenVINO INT4 模型）
HF_MODEL_ID = "OpenVINO/Qwen2.5-VL-7B-Instruct-int4-ov"

# 默认输出子目录名（与 config.json 中 model_path 对应）
DEFAULT_OUTPUT_NAME = "Qwen2.5-VL-7B-Instruct-int4"

# HF 镜像站地址（国内网络推荐使用）
HF_MIRROR_URL = "https://hf-mirror.com"

# 虚拟环境所需依赖（最小集合）
VENV_PACKAGES = ["huggingface_hub"]


# ---------------------------------------------------------------------------
# 虚拟环境管理
# ---------------------------------------------------------------------------

def _get_venv_python() -> "Path | None":
    """返回 <SKILL_DIR>/.venv 中的 Python 可执行路径，不存在返回 None。"""
    venv_dir = SKILL_DIR / ".venv"
    for candidate in [
        venv_dir / "Scripts" / "python.exe",  # Windows
        venv_dir / "bin" / "python",           # Linux / macOS
        venv_dir / "bin" / "python3",
    ]:
        if candidate.exists():
            return candidate
    return None


def _ensure_venv(packages: list) -> Path:
    """
    确保 <SKILL_DIR>/.venv 存在并安装了指定包列表。
    不存在时自动用当前系统 Python 创建，然后 pip install 所需包。
    返回 venv 内的 Python 可执行路径。
    """
    venv_dir = SKILL_DIR / ".venv"
    venv_python = _get_venv_python()

    if venv_python is None:
        print(f"[venv] 虚拟环境不存在，正在创建：{venv_dir}")
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            check=True,
        )
        venv_python = _get_venv_python()
        if venv_python is None:
            raise RuntimeError(f"创建虚拟环境后仍找不到 Python 可执行文件：{venv_dir}")
        print(f"[venv] ✓ 虚拟环境已创建：{venv_dir}")
    else:
        print(f"[venv] 已找到虚拟环境：{venv_python}")

    if packages:
        print(f"[venv] 安装依赖：{', '.join(packages)}")
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--quiet", *packages],
            check=True,
        )
        print(f"[venv] ✓ 依赖安装完成")

    return venv_python


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _find_flama_dir() -> Path | None:
    """按优先级查找 flama 可执行文件所在目录。"""
    flama_env = os.environ.get("FLAMA_PATH")
    if flama_env:
        p = Path(flama_env)
        candidate = p.parent if p.suffix.lower() == ".exe" else p
        if candidate.is_dir():
            return candidate

    for d in _DEFAULT_FLAMA_DIRS:
        if d.is_dir():
            return d

    return None


def _verify_model_dir(model_dir: Path) -> bool:
    """
    简单验证 OpenVINO 模型目录是否有效：
    目录存在 + 含至少一个 .xml 文件。
    """
    if not model_dir.is_dir():
        return False
    xml_files = list(model_dir.glob("*.xml"))
    return len(xml_files) > 0


def _download_model(
    repo_id: str,
    output_dir: Path,
    hf_endpoint: str | None = None,
) -> bool:
    """
    使用 huggingface_hub 将整个仓库快照下载到 output_dir。

    Args:
        repo_id: HuggingFace 仓库 ID，如 "OpenVINO/Qwen2.5-VL-7B-Instruct-int4-ov"
        output_dir: 本地保存目录
        hf_endpoint: HF 镜像站地址，如 "https://hf-mirror.com"

    Returns:
        True 表示下载成功，False 表示失败。
    """
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print(
            "[model] 未找到 huggingface_hub，请先安装：\n"
            "  pip install huggingface_hub",
            file=sys.stderr,
        )
        return False

    env_backup: dict[str, str | None] = {}
    if hf_endpoint:
        env_backup["HF_ENDPOINT"] = os.environ.get("HF_ENDPOINT")
        os.environ["HF_ENDPOINT"] = hf_endpoint

    try:
        print(f"[model] 正在从 {hf_endpoint or 'https://huggingface.co'} 下载 {repo_id} ...")
        print(f"[model] 目标目录：{output_dir}")
        print("[model] 下载文件较大（约 4~6 GB），请耐心等待。")
        print()

        output_dir.mkdir(parents=True, exist_ok=True)

        snapshot_download(
            repo_id=repo_id,
            local_dir=str(output_dir),
            local_dir_use_symlinks=False,
        )
        return True
    except Exception as e:
        print(f"[model] 下载失败：{e}", file=sys.stderr)
        return False
    finally:
        for key, val in env_backup.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


def _update_config_json(flama_dir: Path, model_path_value: str) -> None:
    """
    若 flama_dir 下存在 config.json，更新其中 genai.model_path 字段。
    """
    import json

    config_path = flama_dir / "config.json"
    if not config_path.exists():
        print(f"[model] 未找到 config.json（{config_path}），跳过自动更新。")
        return

    try:
        with config_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)

        if "genai" not in cfg:
            cfg["genai"] = {}
        old_val = cfg["genai"].get("model_path", "")
        cfg["genai"]["model_path"] = model_path_value

        with config_path.open("w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)

        if old_val != model_path_value:
            print(f"[model] 已更新 config.json: genai.model_path = \"{model_path_value}\"（原值：\"{old_val}\"）")
        else:
            print(f"[model] config.json 无需更新：genai.model_path = \"{model_path_value}\"")
    except Exception as e:
        print(f"[model] 更新 config.json 失败（可手动修改）：{e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def setup_ov_model(
    flama_dir: Path,
    repo_id: str,
    output_name: str,
    force: bool,
    check_only: bool,
    hf_endpoint: str | None = None,
) -> bool:
    """
    从 HuggingFace 下载 OpenVINO 模型并部署到 flama 的 models 目录。

    Returns:
        True 表示成功（含「已存在跳过」），False 表示失败。
    """
    models_dir = flama_dir / "models"
    output_dir = models_dir / output_name
    config_model_path = f"models/{output_name}"

    print(f"  flama 目录   : {flama_dir}")
    print(f"  models 目录  : {models_dir}")
    print(f"  输出模型目录 : {output_dir}")
    print(f"  config.json 将写入 model_path: \"{config_model_path}\"")
    print()

    # 仅校验模式
    if check_only:
        if _verify_model_dir(output_dir):
            print(f"[model] ✓ 模型目录已存在且有效：{output_dir}")
            return True
        else:
            print(f"[model] ✗ 模型目录不存在或无效：{output_dir}")
            return False

    # 已存在且有效时跳过
    if not force and _verify_model_dir(output_dir):
        print(f"[model] 模型已存在且有效，跳过下载。（{output_dir}）")
        _update_config_json(flama_dir, config_model_path)
        return True

    if force and output_dir.exists():
        print(f"[model] --force 模式：删除已有目录 {output_dir}")
        shutil.rmtree(output_dir, ignore_errors=True)

    models_dir.mkdir(parents=True, exist_ok=True)

    ok = _download_model(
        repo_id=repo_id,
        output_dir=output_dir,
        hf_endpoint=hf_endpoint,
    )

    if not ok:
        return False

    if not _verify_model_dir(output_dir):
        print(
            f"[model] 下载完成，但输出目录中未找到 .xml 文件：{output_dir}\n"
            "  请检查上方日志是否有错误。",
            file=sys.stderr,
        )
        return False

    _update_config_json(flama_dir, config_model_path)

    print(f"\n[model] ✓ 模型下载完成：{output_dir}")
    return True


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从 HuggingFace 下载 OpenVINO/Qwen2.5-VL-7B-Instruct-int4-ov 并部署到 flama models 目录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--flama-dir",
        dest="flama_dir",
        default=None,
        metavar="PATH",
        help=(
            "flama 可执行文件所在目录（含 config.json 和 models/ 子目录）。"
            "未指定时自动查找：优先 FLAMA_PATH 环境变量，其次 <SKILL_DIR>/bin/flama，"
            "最后 E:/data/agentkit/flama/build/bin/Release。"
        ),
    )
    parser.add_argument(
        "--repo-id",
        dest="repo_id",
        default=HF_MODEL_ID,
        metavar="REPO_ID",
        help=f"HuggingFace 仓库 ID（默认：{HF_MODEL_ID}）",
    )
    parser.add_argument(
        "--output-name",
        dest="output_name",
        default=DEFAULT_OUTPUT_NAME,
        metavar="DIR_NAME",
        help=f"models/ 下的输出子目录名（默认：{DEFAULT_OUTPUT_NAME}）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新下载（即使目标目录已存在）",
    )
    parser.add_argument(
        "--check-only",
        dest="check_only",
        action="store_true",
        help="仅校验模型目录是否已存在，不执行下载",
    )

    mirror_group = parser.add_mutually_exclusive_group()
    mirror_group.add_argument(
        "--hf-mirror",
        dest="hf_mirror",
        nargs="?",
        const=HF_MIRROR_URL,
        default=HF_MIRROR_URL,
        metavar="URL",
        help=(
            f"使用 HuggingFace 镜像站加速下载（默认启用 {HF_MIRROR_URL}）。"
            f"可指定自定义镜像地址，如 --hf-mirror https://hf-mirror.com。"
        ),
    )
    mirror_group.add_argument(
        "--no-mirror",
        dest="no_mirror",
        action="store_true",
        help="禁用镜像站，直连 HuggingFace（需要科学上网）",
    )

    return parser.parse_args()


def main() -> int:
    # ------------------------------------------------------------------
    # 虚拟环境检查：确保 .venv 存在并安装所需依赖
    # 若当前 Python 不是 .venv 中的 Python，则用 .venv Python 重新启动本脚本
    # ------------------------------------------------------------------
    try:
        venv_python = _ensure_venv(VENV_PACKAGES)
    except Exception as exc:
        print(f"[venv] 警告：无法创建/配置虚拟环境，将使用系统 Python：{exc}", file=sys.stderr)
        venv_python = Path(sys.executable)

    if venv_python.resolve() != Path(sys.executable).resolve():
        print(f"[venv] 切换至虚拟环境 Python 重新运行：{venv_python}")
        result = subprocess.run([str(venv_python), str(Path(__file__).resolve())] + sys.argv[1:])
        return result.returncode

    args = parse_args()

    # 确定 HF_ENDPOINT：--no-mirror 时不使用镜像；否则命令行参数 > 环境变量 > 默认镜像
    if args.no_mirror:
        hf_endpoint: str | None = None
    else:
        hf_endpoint = args.hf_mirror or os.environ.get("HF_ENDPOINT") or HF_MIRROR_URL

    # 确定 flama 目录
    if args.flama_dir:
        flama_dir = Path(args.flama_dir)
        if not flama_dir.is_dir():
            print(f"错误：指定的 --flama-dir 不存在：{flama_dir}", file=sys.stderr)
            return 1
    else:
        flama_dir = _find_flama_dir()
        if flama_dir is None:
            print(
                "错误：未找到 flama 目录。请通过以下方式之一指定：\n"
                "  1. --flama-dir <路径>\n"
                "  2. 设置环境变量 FLAMA_PATH=<flama.exe 路径>",
                file=sys.stderr,
            )
            return 1

    print("=" * 60)
    print("OpenVINO 模型下载脚本")
    print(f"仓库 ID    : {args.repo_id}")
    print(f"下载镜像   : {hf_endpoint or '直连 HuggingFace'}")
    print("=" * 60)
    print()

    ok = setup_ov_model(
        flama_dir=flama_dir,
        repo_id=args.repo_id,
        output_name=args.output_name,
        force=args.force,
        check_only=args.check_only,
        hf_endpoint=hf_endpoint,
    )

    print()
    if ok:
        print("✓ 完成。")
        return 0
    else:
        print("✗ 失败，请查看上方错误信息。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
