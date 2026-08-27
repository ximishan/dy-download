from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml


UPSTREAM_DIRNAME = "vendor/douyin-downloader"


class BackendManager:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.resource_root = Path(getattr(sys, "_MEIPASS", project_root))
        self.backend_dir = project_root / UPSTREAM_DIRNAME
        self.runtime_dir = project_root / ".runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.runtime_dir / "config.yml"
        self.scan_path = self.runtime_dir / "scan.json"

    def _python(self) -> str:
        if getattr(sys, "frozen", False):
            found = shutil.which("python") or shutil.which("py")
            if not found:
                raise RuntimeError("EXE 版本当前仍需要系统安装 Python 3.10+。")
            return found
        return sys.executable

    def _python_cmd(self, *args: str) -> list[str]:
        return [self._python(), "-X", "utf8", *args]

    def prepare_command(self) -> tuple[list[str], Path]:
        script = self.resource_root / "bootstrap_backend.py"
        return self._python_cmd(str(script)), self.project_root

    def ensure_backend(self):
        if not (self.backend_dir / "run.py").exists():
            raise RuntimeError("下载核心尚未安装，请先点击“安装/更新下载核心”。")

    def cookie_command(self) -> tuple[list[str], Path]:
        self.ensure_backend()
        if not self.config_path.exists():
            self.write_profile_config(
                url="https://www.douyin.com/user/placeholder",
                output_dir=Path.home() / "Downloads" / "dy-download",
                count=0,
                threads=3,
                browser_fallback=True,
            )
        return self._python_cmd("-m", "tools.cookie_fetcher", "--config", str(self.config_path)), self.backend_dir

    @staticmethod
    def extract_douyin_url(text: str) -> str:
        raw = (text or "").strip()
        if not raw:
            return ""

        match = re.search(
            r"https?://(?:[A-Za-z0-9-]+\.)?(?:douyin\.com|iesdouyin\.com)(?:/[^\s]*)?",
            raw,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(0).rstrip("，。！？；;,.!?)）]】>\"'")

        match = re.search(
            r"(?:v\.douyin\.com|v\.iesdouyin\.com)/[^\s]+",
            raw,
            flags=re.IGNORECASE,
        )
        if match:
            return "https://" + match.group(0).rstrip("，。！？；;,.!?)）]】>\"'")

        return ""

    def scan_command(self, url: str, limit: int = 0) -> tuple[list[str], Path]:
        self.ensure_backend()
        if not self.config_path.exists():
            raise RuntimeError("请先点击“浏览器登录获取 Cookie”或手动填写 Cookie。")

        extracted_url = self.extract_douyin_url(url)
        if not extracted_url:
            raise RuntimeError("没有从输入内容中找到有效的抖音链接。")

        script = self.resource_root / "scan_profile.py"
        cmd = self._python_cmd(
            str(script),
            "--url",
            extracted_url,
            "--config",
            str(self.config_path),
            "--output",
            str(self.scan_path),
        )
        if limit > 0:
            cmd += ["--limit", str(limit)]
        return cmd, self.project_root

    def download_command(self, config_path: Path) -> tuple[list[str], Path]:
        self.ensure_backend()
        watchdog = self.resource_root / "safe_download.py"
        return self._python_cmd(str(watchdog), "--config", str(config_path)), self.project_root

    def write_profile_config(
        self,
        *,
        url: str,
        output_dir: Path,
        count: int,
        threads: int,
        browser_fallback: bool,
    ) -> Path:
        return self._write_config(
            links=[url],
            output_dir=output_dir,
            threads=threads,
            browser_fallback=browser_fallback,
            mode=["post"],
            post_count=count,
        )

    def write_selected_config(
        self,
        *,
        items: list[dict],
        output_dir: Path,
        threads: int,
        browser_fallback: bool,
    ) -> Path:
        links: list[str] = []
        for item in items:
            aweme_id = str(item.get("aweme_id") or "").strip()
            if not aweme_id:
                continue
            if item.get("type") == "图文":
                links.append(f"https://www.douyin.com/note/{aweme_id}")
            else:
                links.append(f"https://www.douyin.com/video/{aweme_id}")
        if not links:
            raise RuntimeError("没有可下载的作品。")
        return self._write_config(
            links=links,
            output_dir=output_dir,
            threads=threads,
            browser_fallback=browser_fallback,
            mode=["post"],
            post_count=0,
        )

    def save_manual_cookie(self, cookie_text: str) -> None:
        cookie_text = cookie_text.strip()
        if not cookie_text:
            raise ValueError("Cookie 不能为空。")
        parsed: dict[str, str] = {}
        for chunk in cookie_text.split(";"):
            if "=" not in chunk:
                continue
            key, value = chunk.split("=", 1)
            key = key.strip()
            if key:
                parsed[key] = value.strip()
        if not parsed:
            raise ValueError("Cookie 格式不正确。")
        data = self._read_existing_config()
        data["cookies"] = parsed
        self._dump_config(data)

    def cookie_summary(self) -> str:
        cookies = self._read_existing_config().get("cookies", {})
        if not isinstance(cookies, dict) or not cookies:
            return "未配置"

        required = ("ttwid", "odin_tt", "passport_csrf_token")
        login_keys = ("sessionid", "sessionid_ss", "sid_guard")
        missing = [key for key in required if not cookies.get(key)]
        has_login = any(cookies.get(key) for key in login_keys)

        if missing:
            return f"风险：缺少 {', '.join(missing)}"
        if not has_login:
            return "风险：未检测到有效登录会话"

        important = [
            k for k in ("sessionid", "sid_guard", "ttwid", "msToken", "passport_csrf_token")
            if cookies.get(k)
        ]
        return f"健康（{len(cookies)} 项，{', '.join(important)}）"

    @classmethod
    def validate_profile_url(cls, text: str) -> bool:
        try:
            url = cls.extract_douyin_url(text)
            if not url:
                return False
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                return False
            host = parsed.netloc.lower().split(":", 1)[0]
            if host in {"v.douyin.com", "v.iesdouyin.com"}:
                return True
            return (
                host.endswith("douyin.com") or host.endswith("iesdouyin.com")
            ) and ("/user/" in parsed.path or "/share/user/" in parsed.path)
        except Exception:
            return False

    def _write_config(
        self,
        *,
        links: list[str],
        output_dir: Path,
        threads: int,
        browser_fallback: bool,
        mode: list[str],
        post_count: int,
    ) -> Path:
        previous = self._read_existing_config()
        cookies = previous.get("cookies", {}) if isinstance(previous, dict) else {}
        safe_threads = max(1, min(int(threads), 3))
        config = {
            "link": links,
            "path": str(output_dir.resolve()),
            "mode": mode,
            "number": {
                "post": int(post_count),
                "like": 0,
                "mix": 0,
                "music": 0,
                "collect": 0,
                "collectmix": 0,
            },
            "thread": safe_threads,
            "rate_limit": 1.2,
            "retry_times": 3,
            "proxy": "",
            "database": True,
            "database_path": str((self.runtime_dir / "dy_downloader.db").resolve()),
            "progress": {"quiet_logs": False},
            "cookies": cookies or {},
            "browser_fallback": {
                "enabled": bool(browser_fallback),
                "headless": False,
                "max_scrolls": 240,
                "idle_rounds": 8,
                "wait_timeout_seconds": 600,
            },
            "transcript": {"enabled": False},
        }
        self._dump_config(config)
        return self.config_path

    def _dump_config(self, data: dict) -> None:
        with self.config_path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)

    def _read_existing_config(self) -> dict:
        if not self.config_path.exists():
            return {}
        try:
            with self.config_path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
