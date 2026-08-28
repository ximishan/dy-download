from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def _force_utf8_stdio() -> None:
    """Keep every frozen/internal worker on the same UTF-8 pipe encoding."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def prepare_embedded_runtime() -> Path:
    _force_utf8_stdio()

    root = resource_root()
    browser_dir = root / "ms-playwright"
    if browser_dir.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir)

    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"

    vendor = root / "vendor" / "douyin-downloader"
    if vendor.exists() and str(vendor) not in sys.path:
        sys.path.insert(0, str(vendor))
    return root


def _args_after(flag: str) -> list[str]:
    try:
        index = sys.argv.index(flag)
    except ValueError:
        return []
    return sys.argv[index + 1 :]


def internal_dispatch() -> int | None:
    root = prepare_embedded_runtime()

    if "--internal-selfcheck" in sys.argv:
        vendor = root / "vendor" / "douyin-downloader" / "run.py"
        browser_root = root / "ms-playwright"
        if not vendor.exists():
            print("[环境检查] 内置下载核心缺失。", flush=True)
            return 2
        if not browser_root.exists() or not any(browser_root.iterdir()):
            print("[环境检查] 内置 Playwright Chromium 缺失。", flush=True)
            return 3
        print("[环境检查] 独立运行环境完整：Python 运行时、下载核心、Chromium 均已内置。", flush=True)
        return 0

    if "--internal-scan" in sys.argv:
        sys.argv = ["scan_profile.py", *_args_after("--internal-scan")]
        from scan_profile import main as scan_main
        return int(scan_main())

    if "--internal-safe-download" in sys.argv:
        sys.argv = ["safe_download.py", *_args_after("--internal-safe-download")]
        from safe_download import main as safe_main
        return int(safe_main())

    if "--internal-cookie" in sys.argv:
        # The upstream cookie_fetcher is terminal-driven and waits for Enter.
        # A --windowed PyInstaller EXE has no reliable stdin, so use our
        # GUI-friendly auto-detecting QR login flow instead.
        sys.argv = ["gui_cookie_login.py", *_args_after("--internal-cookie")]
        from gui_cookie_login import main as cookie_main
        return int(cookie_main())

    if "--internal-upstream-download" in sys.argv:
        args = _args_after("--internal-upstream-download")
        sys.argv = ["run.py", *args]
        run_path = root / "vendor" / "douyin-downloader" / "run.py"
        try:
            runpy.run_path(str(run_path), run_name="__main__")
        except SystemExit as exc:
            return int(exc.code or 0)
        return 0

    return None


def main() -> int:
    _force_utf8_stdio()
    os.environ["PYTHONUTF8"] = "1"
    os.environ["PYTHONIOENCODING"] = "utf-8"

    internal_code = internal_dispatch()
    if internal_code is not None:
        return internal_code

    from app import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
