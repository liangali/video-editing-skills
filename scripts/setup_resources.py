"""
setup_resources.py - 下载并部署 video-editing-skills 所需的外部资源。

当前实现：
  - ffmpeg.exe / ffprobe.exe → <SKILL_DIR>/bin/
  - flama（zip 内全部文件）→ <SKILL_DIR>/bin/flama/
  - resource.zip → <SKILL_DIR>/resource/（需通过 --resource-url 或环境变量 RESOURCE_ZIP_URL 指定下载链接）

用法：
    python setup_resources.py          # 仅下载缺失资源
    python setup_resources.py --force  # 强制重新下载
    python setup_resources.py --resource-url "https://example.com/resource.zip"   # 同时下载并解压 resource.zip 到 resource/
    set RESOURCE_ZIP_URL=https://... & python setup_resources.py   # 通过环境变量指定 resource.zip 下载链接
    set RESOURCE_ZIP_PATH=C:/path/to/resource.zip & python setup_resources.py   # 使用本地已下载的 resource.zip，跳过下载
    set HTTPS_PROXY=http://127.0.0.1:7890 & python setup_resources.py   # 走代理再下载
    set FLAMA_ZIP_PATH=C:/Users/creator/Downloads/flama.zip & python setup_resources.py   # 使用本地已下载的 zip，跳过 flama 下载

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
FLAMA_DIR = BIN_DIR / "flama"
FLAMA_EXE = FLAMA_DIR / "flama.exe"
RESOURCE_DIR = SKILL_DIR / "resource"

# ---------------------------------------------------------------------------
# ffmpeg 下载源（仅支持 .zip；按顺序尝试，第一个成功即停止）
# ---------------------------------------------------------------------------
FFMPEG_ZIP_URLS = [
    "https://github.com/GyanD/codexffmpeg/releases/download/8.0.1/ffmpeg-8.0.1-full_build.zip",
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip",
    "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
]

#若已本地下载好 zip，可设置环境变量 FLAMA_ZIP_PATH 指向该文件则不再联网下载
FLAMA_ZIP_URL = "C:\\Users\\creator\\Downloads\\flama.zip"

# resource.zip 下载源；需通过 --resource-url 或环境变量 RESOURCE_ZIP_URL 指定；本地文件可用 RESOURCE_ZIP_PATH
RESOURCE_ZIP_URL = "https://video-editing-skills.tos-cn-beijing.volces.com/resource.zip?X-Tos-Algorithm=TOS4-HMAC-SHA256&X-Tos-Content-Sha256=UNSIGNED-PAYLOAD&X-Tos-Credential=REMOVED_KEY%2F20260311%2Fcn-beijing%2Ftos%2Frequest&X-Tos-Date=20260311T081105Z&X-Tos-Expires=3600&X-Tos-SignedHeaders=host&X-Tos-Security-Token=nChBBUEJycGR4MUk2UDU3RlJX.CiQKEGZCemE1ZmZCc2hwSlB5UnkSEDwX0nILakbyrRQsqNyO1FUQ4LvEzQYY8NfEzQYgxq6a8AcoATDGrprwBzoEcm9vdEIKc3RvcmFnZV9mZUqpAXsiU3RhdGVtZW50IjpbeyJFZmZlY3QiOiJBbGxvdyIsIkFjdGlvbiI6WyJ0b3M6KiIsInRvc3ZlY3RvcnM6KiIsImttczoqIiwiY2xvdWRfZGV0ZWN0OioiLCJjZXJ0X3NlcnZpY2U6KiIsInNoYWRvdzoqIiwia2Fma2E6KiIsInJvY2tldG1xOioiLCJjZG46KiJdLCJSZXNvdXJjZSI6WyIqIl19XX1SFzA5NDLmiYvmnLrnlKjmiLcjc2xhUmlnWAFgAQ.r6w9pGj7lFWtCScc7s5RGVm2WYcGEjej93_jAvtyDWq_k4P613TJ2xvPKxZbud6ZrDOpZbLEEYGk6-88RJTOWA&X-Tos-Signature=df8e0454a8f99867fbfd3d817f71bb55e006997e49a1b27f6a04345f3515cec2"

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


def _verify_exe(exe_path: Path, flags: tuple[str, ...] = ("-version",)) -> bool:
    """运行 exe 并尝试给定参数，返回是否成功（用于校验下载是否完整）。"""
    for flag in flags:
        try:
            result = subprocess.run(
                [str(exe_path), flag],
                capture_output=True,
                timeout=15,
            )
            if result.returncode == 0:
                return True
        except Exception:
            continue
    return False


def _install_proxy_opener() -> None:
    """根据环境变量 HTTP_PROXY / HTTPS_PROXY 安装 urllib 的代理。"""
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if proxy:
        proxy_handler = urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        opener = urllib.request.build_opener(proxy_handler)
        urllib.request.install_opener(opener)


def _download_with_progress(url: str, dest: Path, timeout: int = DOWNLOAD_TIMEOUT) -> None:
    """下载 URL 到 dest。"""
    print(f"  正在下载：{url}")
    print(f"  目标位置：{dest}（超时 {timeout}s）")

    try:
        old_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(timeout)
        try:
            urllib.request.urlretrieve(url, str(dest))
        finally:
            socket.setdefaulttimeout(old_timeout)
    except Exception:
        raise


def _extract_flat_exe_and_dlls(zf: zipfile.ZipFile, out_dir: Path) -> None:
    """
    从 zip 中提取所有 .exe 和 .dll 到 out_dir（扁平化）。
    若 zip 内只有一个顶层目录，则从该目录下取文件；否则从根取。
    """
    names = zf.namelist()
    top_dirs = set()
    for n in names:
        parts = n.replace("\\", "/").strip("/").split("/")
        if len(parts) >= 1 and parts[0]:
            top_dirs.add(parts[0])
    prefix = ""
    if len(top_dirs) == 1:
        single = list(top_dirs)[0]
        if any(n.startswith(single + "/") or n.startswith(single + "\\") for n in names if n != single):
            prefix = single + "/"
        elif not single.endswith(".exe") and not single.endswith(".dll"):
            prefix = single + "/"

    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        if name.endswith("/"):
            continue
        base = name.replace("\\", "/")
        if not base.startswith(prefix):
            continue
        rel = base[len(prefix) :].lstrip("/")
        if not rel or "/" in rel or "\\" in rel:
            continue
        if not (rel.lower().endswith(".exe") or rel.lower().endswith(".dll")):
            continue
        dest = out_dir / Path(rel).name
        with zf.open(name) as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)


def _extract_all_to_dir(zf: zipfile.ZipFile, out_dir: Path) -> None:
    """
    从 zip 中提取所有文件到 out_dir，保留目录结构。
    若 zip 内只有一个顶层目录，则将该目录下的内容展开到 out_dir；否则按 zip 内路径解压。
    """
    names = zf.namelist()
    top_dirs = set()
    for n in names:
        parts = n.replace("\\", "/").strip("/").split("/")
        if len(parts) >= 1 and parts[0]:
            top_dirs.add(parts[0])
    prefix = ""
    if len(top_dirs) == 1:
        single = list(top_dirs)[0]
        if any(n.startswith(single + "/") or n.startswith(single + "\\") for n in names if n != single):
            prefix = single + "/"
        elif "/" not in single and "\\" not in single and not single.endswith(".exe") and not single.endswith(".dll"):
            prefix = single + "/"

    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        base = name.replace("\\", "/")
        if not base.startswith(prefix):
            continue
        rel = base[len(prefix) :].lstrip("/")
        if not rel:
            continue
        dest = out_dir / rel
        if name.endswith("/"):
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(name) as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)


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
        if _verify_exe(ffmpeg_dest, ("-version",)):
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

                with zf.open(ffmpeg_zip_path) as src, open(ffmpeg_dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

                with zf.open(ffprobe_zip_path) as src, open(ffprobe_dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

        except zipfile.BadZipFile as e:
            print(f"[ffmpeg] zip 文件损坏：{e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"[ffmpeg] 解压失败：{e}", file=sys.stderr)
            return False

    # 3. 校验
    if _verify_exe(ffmpeg_dest, ("-version",)):
        print(f"[ffmpeg] ✓ 安装成功：{ffmpeg_dest}")
        print(f"[ffmpeg] ✓ 安装成功：{ffprobe_dest}")
        return True
    else:
        print("[ffmpeg] 警告：下载后校验失败，可能需要手动检查。", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# 核心功能：下载并部署 flama
# ---------------------------------------------------------------------------

def setup_flama(force: bool = False) -> bool:
    """
    从 FLAMA_ZIP_URL 下载 flama.zip，解压到 <SKILL_DIR>/bin/flama/，
    复制 zip 内全部文件（保留目录结构）。支持 HTTPS_PROXY / HTTP_PROXY。

    Returns:
        True 表示成功（含「已存在跳过」），False 表示失败。
    """
    if not force and FLAMA_EXE.exists():
        if _verify_exe(FLAMA_EXE, ("--version", "-version", "-h")):
            print(f"[flama] 已存在且可用，跳过。（{FLAMA_EXE}）")
            return True
        print("[flama] 文件已存在但校验失败，将重新安装。")

    BIN_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)
        zip_path = tmp_dir / "flama.zip"

        local_zip = os.environ.get("FLAMA_ZIP_PATH")
        if local_zip and Path(local_zip).is_file():
            print(f"  使用本地 zip：{local_zip}")
            shutil.copy2(local_zip, zip_path)
        else:
            _install_proxy_opener()
            try:
                _download_with_progress(FLAMA_ZIP_URL, zip_path)
            except Exception as e:
                print(f"[flama] 下载失败：{e}", file=sys.stderr)
                print("[flama] 若下载失败，可设置 FLAMA_ZIP_PATH 指向已下载的 flama.zip。", file=sys.stderr)
                return False

        if zip_path.stat().st_size == 0:
            print("[flama] 下载文件为空，请检查 URL 或网络。", file=sys.stderr)
            return False

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                has_flama = any(Path(n).name == "flama.exe" for n in zf.namelist())
                if not has_flama:
                    print("[flama] zip 内未找到 flama.exe。", file=sys.stderr)
                    return False
                if FLAMA_DIR.exists():
                    shutil.rmtree(FLAMA_DIR)
                _extract_all_to_dir(zf, FLAMA_DIR)
        except zipfile.BadZipFile as e:
            print(f"[flama] zip 文件损坏：{e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"[flama] 解压失败：{e}", file=sys.stderr)
            return False

    if not FLAMA_EXE.exists():
        print("[flama] 解压后未找到 flama.exe。", file=sys.stderr)
        return False
    if _verify_exe(FLAMA_EXE, ("--version", "-version", "-h")):
        print(f"[flama] ✓ 安装成功：{FLAMA_DIR}")
        return True
    print("[flama] 警告：下载后校验失败，请手动检查。", file=sys.stderr)
    return False


# ---------------------------------------------------------------------------
# 核心功能：下载并解压 resource.zip → resource/
# ---------------------------------------------------------------------------

def setup_resource(force: bool = False, resource_url: str | None = None) -> bool:
    """
    从指定 URL 或环境变量下载 resource.zip，解压到 <SKILL_DIR>/resource/。
    支持环境变量 RESOURCE_ZIP_URL、RESOURCE_ZIP_PATH（本地文件），以及参数 resource_url。

    Returns:
        True 表示成功（含「已存在跳过」或「未指定链接跳过」），False 表示失败。
    """
    url = resource_url or os.environ.get("RESOURCE_ZIP_URL") or RESOURCE_ZIP_URL
    local_zip = os.environ.get("RESOURCE_ZIP_PATH")

    if not url and not local_zip:
        print("[resource] 未指定 RESOURCE_ZIP_URL 或 RESOURCE_ZIP_PATH，跳过。")
        return True

    if not force and RESOURCE_DIR.exists() and any(RESOURCE_DIR.iterdir()):
        print(f"[resource] 目录已存在且非空，跳过。（{RESOURCE_DIR}）")
        return True

    with tempfile.TemporaryDirectory() as tmp_str:
        tmp_dir = Path(tmp_str)
        zip_path = tmp_dir / "resource.zip"

        if local_zip and Path(local_zip).is_file():
            print(f"  使用本地 zip：{local_zip}")
            shutil.copy2(local_zip, zip_path)
        else:
            _install_proxy_opener()
            try:
                _download_with_progress(url, zip_path)
            except Exception as e:
                print(f"[resource] 下载失败：{e}", file=sys.stderr)
                print("[resource] 可设置 RESOURCE_ZIP_PATH 指向已下载的 resource.zip。", file=sys.stderr)
                return False

        if zip_path.stat().st_size == 0:
            print("[resource] 下载文件为空，请检查 URL 或网络。", file=sys.stderr)
            return False

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                if RESOURCE_DIR.exists():
                    shutil.rmtree(RESOURCE_DIR)
                _extract_all_to_dir(zf, RESOURCE_DIR)
        except zipfile.BadZipFile as e:
            print(f"[resource] zip 文件损坏：{e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"[resource] 解压失败：{e}", file=sys.stderr)
            return False

    print(f"[resource] ✓ 安装成功：{RESOURCE_DIR}")
    return True


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
    parser.add_argument(
        "--flama-only",
        action="store_true",
        help="仅安装 flama（不安装 ffmpeg）",
    )
    parser.add_argument(
        "--ffmpeg-only",
        action="store_true",
        help="仅安装 ffmpeg（不安装 flama）",
    )
    parser.add_argument(
        "--resource-url",
        dest="resource_url",
        default=None,
        help="resource.zip 的下载链接，解压到 SKILL_DIR/resource/",
    )
    parser.add_argument(
        "--resource-only",
        action="store_true",
        help="仅安装 resource（下载并解压 resource.zip 到 resource/）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    global FFMPEG_ZIP_URLS
    if args.ffmpeg_url:
        FFMPEG_ZIP_URLS = [args.ffmpeg_url]

    print("=" * 60)
    print("video-editing-skills 资源安装脚本")
    print(f"SKILL_DIR   : {SKILL_DIR}")
    print(f"BIN_DIR     : {BIN_DIR}")
    print(f"RESOURCE_DIR: {RESOURCE_DIR}")
    print("=" * 60)

    ok = True
    do_ffmpeg = not args.flama_only and not args.resource_only
    do_flama = not args.ffmpeg_only and not args.resource_only
    do_resource = args.resource_only or (not args.ffmpeg_only and not args.flama_only)

    steps = sum([do_ffmpeg, do_flama, do_resource])
    step = 0

    if do_ffmpeg:
        step += 1
        print(f"\n[{step}/{steps}] ffmpeg / ffprobe")
        if not setup_ffmpeg(force=args.force):
            ok = False
    if do_flama:
        step += 1
        print(f"\n[{step}/{steps}] flama")
        if not setup_flama(force=args.force):
            ok = False
    if do_resource:
        step += 1
        print(f"\n[{step}/{steps}] resource")
        if not setup_resource(force=args.force, resource_url=args.resource_url):
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
