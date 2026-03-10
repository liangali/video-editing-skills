"""
setup_resources.py - 下载并部署 video-editing-skills 所需的外部资源。

当前实现：
  - ffmpeg.exe / ffprobe.exe → <SKILL_DIR>/bin/

用法：
    python setup_resources.py          # 仅下载缺失资源
    python setup_resources.py --force  # 强制重新下载
    set HTTPS_PROXY=http://127.0.0.1:7890 & python setup_resources.py   # 走代理再下载

SKILL_DIR 自动解析为本脚本所在 scripts/ 目录的上一级，即 video-editing-skills/。
"""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
BIN_DIR = SKILL_DIR / "bin"

# ---------------------------------------------------------------------------
# ffmpeg 下载源（仅支持 .zip；按顺序尝试，第一个成功即停止）
# ---------------------------------------------------------------------------
FFMPEG_ZIP_URLS = [
    "https://github.com/GyanD/codexffmpeg/releases/download/8.0.1/ffmpeg-8.0.1-full_build.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
]
DOWNLOAD_TIMEOUT = 120  # 秒


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _find_in_zip(zf: zipfile.ZipFile, filename: str) -> str | None:
    """在 zip 里找到 filename（只取文件名，不含路径），返回 zip 内完整路径。"""
    for name in zf.namelist():
        if Path(name).name == filename:
            return name
    return None


def _verify_exe(exe_path: Path) -> bool:
    """运行 exe -version，返回是否成功（用于校验下载是否完整）。"""
    try:
        result = subprocess.run(
            [str(exe_path), "-version"],
            capture_output=True,
            timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


def _install_proxy_opener() -> None:
    """根据环境变量 HTTP_PROXY / HTTPS_PROXY 安装 urllib 的代理。"""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if proxy:
        proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        opener = urllib.request.build_opener(proxy_handler)
        urllib.request.install_opener(opener)


def _download_with_progress(url: str, dest: Path, timeout: int = DOWNLOAD_TIMEOUT) -> None:
    """下载 URL 到 dest，打印简单进度（MB）。"""
    print(f"  正在下载：{url}")
    print(f"  目标位置：{dest}（超时 {timeout}s）")

    def _reporthook(block_num: int, block_size: int, total_size: int) -> None:
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(100.0, downloaded / total_size * 100)
            mb = downloaded / 1024 / 1024
            total_mb = total_size / 1024 / 1024
            print(f"\r  {pct:.1f}%  {mb:.1f} / {total_mb:.1f} MB", end="", flush=True)
        else:
            mb = downloaded / 1024 / 1024
            print(f"\r  {mb:.1f} MB 已下载", end="", flush=True)

    try:
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
        try:
            urllib.request.urlretrieve(url, str(dest), reporthook=_reporthook)
        finally:
            socket.setdefaulttimeout(old_timeout)
    finally:
        print()  # 换行


# ---------------------------------------------------------------------------
# 核心功能：下载 ffmpeg / ffprobe
# ---------------------------------------------------------------------------

def setup_ffmpeg(force: bool = False) -> bool:
    """
    从内置 URL 下载 ffmpeg .zip，将 ffmpeg.exe 和 ffprobe.exe 部署到 <SKILL_DIR>/bin/。
    支持环境变量 HTTPS_PROXY / HTTP_PROXY。

    Returns:
        True 表示成功（含「已存在跳过」），False 表示失败。
    """
    ffmpeg_dest = BIN_DIR / "ffmpeg.exe"
    ffprobe_dest = BIN_DIR / "ffprobe.exe"

    # 检查是否已存在且可用
    if not force and ffmpeg_dest.exists() and ffprobe_dest.exists():
        if _verify_exe(ffmpeg_dest):
            print(f"[ffmpeg] 已存在且可用，跳过。（{ffmpeg_dest}）")
            return True
        else:
            print("[ffmpeg] 文件已存在但校验失败，将重新安装。")

    BIN_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)
        zip_path = tmp_dir / "ffmpeg.zip"

        # 1. 联网下载（支持代理）
        _install_proxy_opener()
        downloaded_ok = False
        for url in FFMPEG_ZIP_URLS:
            try:
                _download_with_progress(url, zip_path)
                if zip_path.stat().st_size == 0:
                    continue
                with zipfile.ZipFile(zip_path, "r") as zf:
                    if _find_in_zip(zf, "ffmpeg.exe") and _find_in_zip(zf, "ffprobe.exe"):
                        downloaded_ok = True
                        break
            except Exception as e:
                print(f"[ffmpeg] 当前源失败：{e}")
                continue
        if not downloaded_ok:
            print("[ffmpeg] 所有下载源均失败，请设置 HTTPS_PROXY / HTTP_PROXY 后重试。", file=sys.stderr)
            return False

        # 2. 解压并复制 ffmpeg.exe / ffprobe.exe
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                ffmpeg_zip_path = _find_in_zip(zf, "ffmpeg.exe")
                ffprobe_zip_path = _find_in_zip(zf, "ffprobe.exe")
                if not ffmpeg_zip_path or not ffprobe_zip_path:
                    print("[ffmpeg] zip 包内未找到 ffmpeg.exe 或 ffprobe.exe", file=sys.stderr)
                    return False

                print(f"  解压 {ffmpeg_zip_path} → {ffmpeg_dest}")
                with zf.open(ffmpeg_zip_path) as src, open(ffmpeg_dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

                print(f"  解压 {ffprobe_zip_path} → {ffprobe_dest}")
                with zf.open(ffprobe_zip_path) as src, open(ffprobe_dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        except zipfile.BadZipFile as e:
            print(f"[ffmpeg] zip 文件损坏：{e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"[ffmpeg] 解压失败：{e}", file=sys.stderr)
            return False

    # 3. 校验
    if _verify_exe(ffmpeg_dest):
        print(f"[ffmpeg] ✓ 安装成功：{ffmpeg_dest}")
        print(f"[ffmpeg] ✓ 安装成功：{ffprobe_dest}")
        return True
    else:
        print("[ffmpeg] 警告：下载后校验失败，可能需要手动检查。", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="下载并部署 video-editing-skills 所需外部资源"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新下载（即使目标文件已存在）",
    )
    parser.add_argument(
        "--ffmpeg-url",
        dest="ffmpeg_url",
        default=None,
        help="指定单个 ffmpeg .zip 下载 URL（未指定时使用内置多源顺序尝试）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    global FFMPEG_ZIP_URLS
    if args.ffmpeg_url:
        FFMPEG_ZIP_URLS = [args.ffmpeg_url]

    print("=" * 60)
    print("video-editing-skills 资源安装脚本")
    print(f"SKILL_DIR : {SKILL_DIR}")
    print(f"BIN_DIR   : {BIN_DIR}")
    print("=" * 60)

    ok = True

    print("\n[1/1] ffmpeg / ffprobe")
    if not setup_ffmpeg(force=args.force):
        ok = False

    print()
    if ok:
        print("✓ 所有资源安装完成。")
        return 0
    else:
        print("✗ 部分资源安装失败，请查看上方错误信息。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
