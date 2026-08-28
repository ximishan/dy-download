from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
UPSTREAM = ROOT / "vendor" / "douyin-downloader"

RISK_PATTERNS = [
    (re.compile(r"\bHTTP\s+429\b|status[=: ]+429", re.I), "检测到 429 请求过于频繁", "medium", False),
    (re.compile(r"\bHTTP\s+403\b|status[=: ]+403", re.I), "检测到 403 风控拒绝", "high", False),
    (re.compile(r"Empty 200 response|anti-bot", re.I), "检测到空 200 响应，疑似反爬", "medium", False),
    (re.compile(r"verify_ticket|verify_page|验证码|安全验证", re.I), "检测到验证页/验证码", "high", False),
    (re.compile(r"LoginRequiredError|登录态失效|需要重新登录|not logged in", re.I), "检测到登录态失效", "high", True),
]


def load_config(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def cookie_health(config: dict) -> tuple[bool, str]:
    cookies = config.get("cookies") or {}
    if not isinstance(cookies, dict) or not cookies:
        return False, "未配置 Cookie"
    required = ("ttwid", "odin_tt", "passport_csrf_token")
    missing = [k for k in required if not cookies.get(k)]
    if missing:
        return False, "Cookie 缺少关键字段：" + ", ".join(missing)
    if not any(cookies.get(k) for k in ("sessionid", "sessionid_ss", "sid_guard")):
        return False, "Cookie 中未检测到登录会话"
    return True, "Cookie 基础健康检查通过"


def write_state(
    path: Path | None, *, level: str, status: str, reason: str,
    hits: int, needs_login: bool, resumable: bool,
) -> None:
    if not path:
        return
    payload = {
        "level": level,
        "status": status,
        "reason": reason,
        "risk_hits": hits,
        "needs_login": needs_login,
        "resumable": resumable,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--risk-state")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    risk_state_path = Path(args.risk_state).resolve() if args.risk_state else None
    config = load_config(config_path)
    ok, message = cookie_health(config)
    print(f"[风控保护] {message}", flush=True)

    if not ok:
        write_state(
            risk_state_path, level="high", status="已停止", reason=message,
            hits=1, needs_login=True, resumable=True,
        )
        print("[风控保护] 为避免使用异常登录态继续请求，已停止下载。请重新获取 Cookie。", flush=True)
        return 12

    if not (UPSTREAM / "run.py").exists():
        write_state(
            risk_state_path, level="medium", status="核心缺失", reason="下载核心不存在",
            hits=0, needs_login=False, resumable=True,
        )
        print("[风控保护] 下载核心不存在，请重新下载完整发行包。", flush=True)
        return 2

    write_state(
        risk_state_path, level="low", status="下载中", reason="暂未检测到风控信号",
        hits=0, needs_login=False, resumable=True,
    )

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("TERM", "dumb")

    if getattr(sys, "frozen", False):
        command = [
            sys.executable,
            "--internal-upstream-download",
            "-c",
            str(config_path),
        ]
        cwd = Path(sys.executable).resolve().parent
    else:
        command = [sys.executable, "-X", "utf8", "run.py", "-c", str(config_path)]
        cwd = UPSTREAM

    print("[风控保护] 已启用保守模式：并发<=3，API 速率约 1.2 次/秒。", flush=True)

    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )

    assert proc.stdout is not None
    risk_hits = 0
    severe_reason = ""
    needs_login = False
    highest_level = "low"

    for line in proc.stdout:
        text = line.rstrip("\r\n")
        print(text, flush=True)

        for pattern, reason, level, login_required in RISK_PATTERNS:
            if pattern.search(text):
                risk_hits += 1
                severe_reason = reason
                needs_login = needs_login or login_required
                if level == "high" or highest_level == "low":
                    highest_level = level
                write_state(
                    risk_state_path, level=highest_level, status="检测到风险", reason=reason,
                    hits=risk_hits, needs_login=needs_login, resumable=True,
                )
                print(f"[风控保护] {reason}，当前风险计数：{risk_hits}", flush=True)
                break

        if severe_reason in {"检测到验证页/验证码", "检测到登录态失效"}:
            print("[风控保护] 已停止继续请求。请完成验证或重新登录后再继续。", flush=True)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            write_state(
                risk_state_path, level="high", status="等待恢复", reason=severe_reason,
                hits=risk_hits, needs_login=needs_login, resumable=True,
            )
            return 13

        if risk_hits >= 2:
            print("[风控保护] 连续检测到风控信号，已主动停止，避免继续增加账号风险。", flush=True)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            write_state(
                risk_state_path, level="high", status="冷却中", reason=severe_reason or "连续风控信号",
                hits=risk_hits, needs_login=needs_login, resumable=True,
            )
            return 14

    code = proc.wait()
    if code == 0:
        write_state(
            risk_state_path, level="low", status="正常", reason="本次下载未检测到明显风控信号",
            hits=risk_hits, needs_login=False, resumable=False,
        )
    else:
        write_state(
            risk_state_path, level=highest_level if highest_level != "low" else "medium",
            status="下载异常", reason=severe_reason or f"下载进程退出码 {code}",
            hits=risk_hits, needs_login=needs_login, resumable=True,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
