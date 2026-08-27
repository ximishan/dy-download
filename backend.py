from __future__ import annotations

import sys
from pathlib import Path

import yaml


UPSTREAM_DIRNAME = "vendor/douyin-downloader"


class BackendManager:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.backend_dir = project_root / UPSTREAM_DIRNAME
        self.runtime_dir = project_root / ".runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.runtime_dir / "config.yml"

    def prepare_command(self) -> tuple[list[str], Path]:
        return [sys.executable, str(self.project_root / "bootstrap_backend.py")], self.project_root

    def ensure_backend(self):
        if not (self.backend_dir / "run.py").exists():
            raise RuntimeError("下载核心尚未安装，请先点击“安装/更新下载核心”。")

    def _python(self) -> str:
        return sys.executable

    def cookie_command(self) -> tuple[list[str], Path]:
        self.ensure_backend()
        if not self.config_path.exists():
            self.write_config(
                url="https://www.douyin.com/user/placeholder",
                output_dir=Path.home() / "Downloads" / "dy-download",
                count=0,
                threads=5,
                browser_fallback=True,
            )
        return [self._python(), "-m", "tools.cookie_fetcher", "--config", str(self.config_path)], self.backend_dir

    def download_command(self, config_path: Path) -> tuple[list[str], Path]:
        self.ensure_backend()
        return [self._python(), "run.py", "-c", str(config_path)], self.backend_dir

    def write_config(
        self,
        *,
        url: str,
        output_dir: Path,
        count: int,
        threads: int,
        browser_fallback: bool,
    ) -> Path:
        previous = self._read_existing_config()
        cookies = previous.get("cookies", {}) if isinstance(previous, dict) else {}

        config = {
            "link": [url],
            "path": str(output_dir.resolve()),
            "mode": ["post"],
            "number": {
                "post": int(count),
                "like": 0,
                "mix": 0,
                "music": 0,
                "collect": 0,
                "collectmix": 0,
            },
            "thread": int(threads),
            "retry_times": 3,
            "proxy": "",
            "database": True,
            "database_path": str((self.runtime_dir / "dy_downloader.db").resolve()),
            "progress": {"quiet_logs": False},
            "cookies": cookies or {
                "msToken": "",
                "ttwid": "",
                "odin_tt": "",
                "passport_csrf_token": "",
                "sid_guard": "",
            },
            "browser_fallback": {
                "enabled": bool(browser_fallback),
                "headless": False,
                "max_scrolls": 240,
                "idle_rounds": 8,
                "wait_timeout_seconds": 600,
            },
            "transcript": {"enabled": False},
        }

        with self.config_path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(config, fh, allow_unicode=True, sort_keys=False)
        return self.config_path

    def _read_existing_config(self) -> dict:
        if not self.config_path.exists():
            return {}
        try:
            with self.config_path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
