from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / "vendor" / "douyin-downloader"

RISK_PATTERNS = [
    (re.compile(r"\bHTTP\s+429\b|status[=: ]+429", re.I), "检测到 429 请求过于频繁"),
    (re.compile(r"\bHTTP\s+403\b|status[=: ]+403", re.I), "检测到 403 风控拒绝"),
    (re.compile(r"Empty 200 response|anti-bot", re.I), "检测到空 200 响应，疑似反爬"),
    (re.compile(r"verify_ticket|verify_page|验证码|安全验证", re.I), "检测到验证页/验证码"),
    (re.compile(r"LoginRequiredError|登录态失效|需要重新登录|not logged in", re.I), "检测到登录态失效"),
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = load_config(config_path)
    ok, message = cookie_health(config)
    print(f"[风控保护] {message}", flush=True)
    if not ok:
        print("[风控保护] 为避免使用异常登录态继续请求，已停止下载。请重新获取 Cookie。", flush=True)
        return 12

    if not (UPSTREAM / "run.py").exists():
        print("[风控保护] 下载核心不存在，请先安装/更新下载核心。", flush=True)
        return 2

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("TERM", "dumb")

    command = [sys.executable, "-X", "utf8", "run.py", "-c", str(config_path)]
    print("[风控保护] 已启用保守模式：并发<=3，API 速率约 1.2 次/秒。", flush=True)

    proc = subprocess.Popen(
        command,
        cwd=UPSTREAM,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
    )

    assert proc.stdout is not None
    risk_hits = 0
    severe_reason = ""

    for line in proc.stdout:
        text = line.rstrip("\r\n")
        print(text, flush=True)

        for pattern, reason in RISK_PATTERNS:
            if pattern.search(text):
                risk_hits += 1
                severe_reason = reason
                print(f"[风控保护] {reason}，当前风险计数：{risk_hits}", flush=True)
                break

        # One explicit login failure / verification event is enough to stop.
        if severe_reason in {"检测到验证页/验证码", "检测到登录态失效"}:
            print("[风控保护] 已停止继续请求。请完成验证或重新登录后再继续。", flush=True)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            return 13

        # Repeated 403/429/anti-bot signals mean backing off is safer than retrying.
        if risk_hits >= 2:
            print("[风控保护] 连续检测到风控信号，已主动停止，避免继续增加账号风险。", flush=True)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            return 14

    return proc.wait()


if __name__ == "__main__":
    raise SystemExit(main())
