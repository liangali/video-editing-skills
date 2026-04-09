"""
setup_ov_model.py - 在统一 .venv 中安装导出依赖，并本地导出 Qwen3-VL OpenVINO INT4 模型。

参考流程：OpenVINO Notebook qwen3-vl.ipynb
https://github.com/openvinotoolkit/openvino_notebooks/blob/latest/notebooks/qwen3-vl/qwen3-vl.ipynb

默认导出命令：
    optimum-cli export openvino --model Qwen/Qwen3-VL-8B-Instruct --task image-text-to-text --weight-format int4 <MODEL_DIR>

用法：
    python setup_ov_model.py
    python setup_ov_model.py --force
    python setup_ov_model.py --check-only
    python setup_ov_model.py --model-id Qwen/Qwen3-VL-8B-Instruct
    python setup_ov_model.py --model-dir D:\\path\\to\\models\\Qwen3-VL-8B-Instruct-int4-ov
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from skill_runtime import (
    DEFAULT_MODEL_DIR,
    DEFAULT_MODEL_NAME,
    VENV_PYTHON,
    ensure_skill_requirements,
    maybe_reexec_in_skill_venv,
)

DEFAULT_HF_MODEL_ID = "Qwen/Qwen3-VL-8B-Instruct"
HF_MIRROR_ENDPOINT = "https://hf-mirror.com"

MODEL_MIN_XML_FILES = 1
MODEL_MIN_BIN_FILES = 1
MODEL_MIN_TOTAL_ENTRIES = 12

EXPORT_DEPENDENCIES = [
    "torch==2.8",
    "torchvision==0.23.0",
    "qwen-vl-utils",
    "Pillow",
    "gradio>=4.36",
    "nncf",
    "openvino>=2025.4",
]


def _inspect_model_dir(model_dir: Path) -> dict:
    if not model_dir.is_dir():
        return {
            "exists": False,
            "xml_count": 0,
            "bin_count": 0,
            "total_entries": 0,
            "valid": False,
            "reason": f"目录不存在：{model_dir}",
        }

    all_entries = list(model_dir.rglob("*"))
    all_files = [e for e in all_entries if e.is_file()]
    xml_count = len([f for f in all_files if f.suffix.lower() == ".xml"])
    bin_count = len([f for f in all_files if f.suffix.lower() == ".bin"])
    total_entries = len(all_entries)

    reasons = []
    if xml_count < MODEL_MIN_XML_FILES:
        reasons.append(f".xml 文件数 {xml_count} < 最低要求 {MODEL_MIN_XML_FILES}")
    if bin_count < MODEL_MIN_BIN_FILES:
        reasons.append(f".bin 文件数 {bin_count} < 最低要求 {MODEL_MIN_BIN_FILES}")
    if total_entries < MODEL_MIN_TOTAL_ENTRIES:
        reasons.append(f"总条目数 {total_entries} < 最低要求 {MODEL_MIN_TOTAL_ENTRIES}")

    return {
        "exists": True,
        "xml_count": xml_count,
        "bin_count": bin_count,
        "total_entries": total_entries,
        "valid": not reasons,
        "reason": "；".join(reasons) if reasons else "",
    }


def _verify_model_dir(model_dir: Path) -> bool:
    return _inspect_model_dir(model_dir)["valid"]


def _run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    print("[exec]", " ".join(cmd))
    subprocess.run(cmd, check=True, env=env)


def _build_export_env(use_hf_mirror: bool) -> dict[str, str]:
    env = os.environ.copy()
    if use_hf_mirror:
        env["HF_ENDPOINT"] = HF_MIRROR_ENDPOINT
        env["HUGGINGFACE_HUB_BASE_URL"] = HF_MIRROR_ENDPOINT
    return env


def _install_export_dependencies(use_hf_mirror: bool) -> None:
    env = _build_export_env(use_hf_mirror)
    print("[model] 在 .venv 中安装导出依赖 ...")
    _run([str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"], env=env)
    _run(
        [
            str(VENV_PYTHON),
            "-m",
            "pip",
            "uninstall",
            "-y",
            "optimum",
            "transformers",
            "optimum-intel",
            "optimum-onnx",
        ],
        env=env,
    )
    _run(
        [
            str(VENV_PYTHON),
            "-m",
            "pip",
            "install",
            *EXPORT_DEPENDENCIES,
            "--extra-index-url",
            "https://download.pytorch.org/whl/cpu",
        ],
        env=env,
    )
    _run(
        [
            str(VENV_PYTHON),
            "-m",
            "pip",
            "install",
            "git+https://github.com/huggingface/optimum-intel.git",
        ],
        env=env,
    )


def _export_model(model_id: str, model_dir: Path, use_hf_mirror: bool) -> None:
    env = _build_export_env(use_hf_mirror)
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    optimum_cli = VENV_PYTHON.parent / "optimum-cli.exe"
    if optimum_cli.exists():
        cmd = [
            str(optimum_cli),
            "export",
            "openvino",
            "--model",
            model_id,
            "--task",
            "image-text-to-text",
            "--weight-format",
            "int4",
            str(model_dir),
        ]
    else:
        cmd = [
            str(VENV_PYTHON),
            "-m",
            "optimum.exporters.openvino",
            "--model",
            model_id,
            "--task",
            "image-text-to-text",
            "--weight-format",
            "int4",
            str(model_dir),
        ]
    _run(cmd, env=env)


def setup_ov_model(
    model_dir: Path,
    model_id: str,
    force: bool,
    check_only: bool,
    use_hf_mirror: bool,
) -> bool:
    print(f"  模型目录 : {model_dir}")
    print(f"  模型 ID   : {model_id}")
    print(f"  HF 镜像   : {'开启' if use_hf_mirror else '关闭'}")
    if use_hf_mirror:
        print(f"  HF_ENDPOINT={HF_MIRROR_ENDPOINT}")
    print()

    if check_only:
        report = _inspect_model_dir(model_dir)
        if report["valid"]:
            print(f"[model] ✓ 模型目录完整有效：{model_dir}")
            print(
                f"[model]   .xml={report['xml_count']}  .bin={report['bin_count']}  "
                f"总条目={report['total_entries']}"
            )
            return True
        print(f"[model] ✗ 模型目录不完整：{model_dir}")
        if report["reason"]:
            print(f"[model]   原因：{report['reason']}")
        return False

    if not force:
        report = _inspect_model_dir(model_dir)
        if report["valid"]:
            print(f"[model] 模型已存在且完整，跳过导出。（{model_dir}）")
            return True
        if report["exists"]:
            print(f"[model] ⚠ 目录存在但不完整，将清理后重导出：{model_dir}")
            shutil.rmtree(model_dir, ignore_errors=True)

    if force and model_dir.exists():
        print(f"[model] --force 模式：删除已有目录 {model_dir}")
        shutil.rmtree(model_dir, ignore_errors=True)

    try:
        _install_export_dependencies(use_hf_mirror)
        _export_model(model_id, model_dir, use_hf_mirror)
    except subprocess.CalledProcessError as exc:
        print(f"[model] 导出失败，命令退出码 {exc.returncode}", file=sys.stderr)
        return False

    if not _verify_model_dir(model_dir):
        print(f"[model] 导出完成，但目录校验失败：{model_dir}", file=sys.stderr)
        return False

    print(f"\n[model] ✓ 模型导出完成：{model_dir}")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="通过 optimum-cli 本地导出 Qwen3-VL OpenVINO INT4 模型",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--model-dir",
        dest="model_dir",
        default=None,
        metavar="PATH",
        help=(
            f"模型导出目录。未指定时默认为 <SKILL_DIR>/models/{DEFAULT_MODEL_NAME} "
            f"(当前: {DEFAULT_MODEL_DIR})"
        ),
    )
    parser.add_argument(
        "--model-id",
        dest="model_id",
        default=DEFAULT_HF_MODEL_ID,
        metavar="OWNER/NAME",
        help=f"HuggingFace 模型 ID（默认：{DEFAULT_HF_MODEL_ID}）",
    )
    parser.add_argument("--force", action="store_true", help="强制重新导出（删除已有目录）")
    parser.add_argument(
        "--check-only",
        dest="check_only",
        action="store_true",
        help="仅校验模型目录是否可用，不执行导出",
    )
    parser.add_argument(
        "--no-hf-mirror",
        action="store_true",
        help="不设置 HF 镜像（默认会设置 HF_ENDPOINT=https://hf-mirror.com）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        ensure_skill_requirements(force=False)
        maybe_reexec_in_skill_venv(Path(__file__).resolve())
    except Exception as exc:
        print(f"[venv] ✗ 统一虚拟环境准备失败：{exc}", file=sys.stderr)
        return 1

    model_dir = Path(args.model_dir).resolve() if args.model_dir else DEFAULT_MODEL_DIR

    print("=" * 60)
    print("OpenVINO 模型导出脚本（Optimum CLI）")
    print(f"模型 ID    : {args.model_id}")
    print(f"模型目录   : {model_dir}")
    print("=" * 60)
    print()

    ok = setup_ov_model(
        model_dir=model_dir,
        model_id=args.model_id,
        force=args.force,
        check_only=args.check_only,
        use_hf_mirror=not args.no_hf_mirror,
    )
    print()
    if ok:
        print("✓ 完成。")
        return 0
    print("✗ 失败，请查看上方错误信息。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
