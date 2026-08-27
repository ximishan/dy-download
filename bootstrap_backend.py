from __future__ import annotations

import subprocess
import sys
from pathlib import Path

UPSTREAM = "https://github.com/jiji262/douyin-downloader.git"
ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "vendor" / "douyin-downloader"


def run(*args: str, cwd: Path | None = None):
    print(">", " ".join(args), flush=True)
    subprocess.run(args, cwd=cwd, check=True)


def main():
    BACKEND.parent.mkdir(parents=True, exist_ok=True)
    if (BACKEND / ".git").exists():
        run("git", "pull", "--ff-only", cwd=BACKEND)
    else:
        run("git", "clone", "--depth", "1", UPSTREAM, str(BACKEND), cwd=ROOT)

    requirements = BACKEND / "requirements.txt"
    if requirements.exists():
        run(sys.executable, "-m", "pip", "install", "-r", str(requirements), cwd=BACKEND)

    # Browser fallback and automatic cookie capture require Playwright.
    run(sys.executable, "-m", "pip", "install", "playwright", cwd=BACKEND)
    run(sys.executable, "-m", "playwright", "install", "chromium", cwd=BACKEND)

    print("下载核心安装/更新完成。", flush=True)


if __name__ == "__main__":
    main()
