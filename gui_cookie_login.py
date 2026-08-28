from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

LOGIN_URL = "https://www.douyin.com/"
LOGIN_KEYS = ("sessionid", "sessionid_ss", "sid_guard")
REQUIRED_KEYS = ("ttwid", "odin_tt", "passport_csrf_token")


def _emit(text: str) -> None:
    print(text, flush=True)


def _load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_config(path: Path, cookies: dict[str, str]) -> None:
    data = _load_config(path)
    data["cookies"] = cookies
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, allow_unicode=True, sort_keys=False)


def _cookie_dict(raw_cookies: list[dict]) -> dict[str, str]:
    result: dict[str, str] = {}
    for cookie in raw_cookies:
        domain = str(cookie.get("domain") or "")
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "")
        if not name or not domain.endswith("douyin.com"):
            continue
        result[name] = value
    return result


def _login_detected(cookies: dict[str, str]) -> bool:
    return any(cookies.get(key) for key in LOGIN_KEYS)


async def run_login(config_path: Path, timeout_seconds: int) -> int:
    _emit("[扫码登录] 正在打开抖音登录页面…")
    _emit("[扫码登录] 请在打开的浏览器中使用抖音 App 扫码并确认登录。")
    _emit("[扫码登录] 登录成功后无需返回程序按 Enter，程序会自动检测并保存 Cookie。")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 820},
            locale="zh-CN",
        )
        page = await context.new_page()

        try:
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            _emit(f"[扫码登录] 页面加载提示：{exc}")

        deadline = asyncio.get_running_loop().time() + timeout_seconds
        last_missing = ""

        while asyncio.get_running_loop().time() < deadline:
            if page.is_closed():
                _emit("[扫码登录] 浏览器窗口已关闭，登录取消。")
                await context.close()
                await browser.close()
                return 2

            raw = await context.cookies()
            cookies = _cookie_dict(raw)

            if _login_detected(cookies):
                # Give Douyin a short grace period to populate anti-CSRF / device cookies.
                await page.wait_for_timeout(2500)
                try:
                    await page.reload(wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass
                await page.wait_for_timeout(1500)

                cookies = _cookie_dict(await context.cookies())
                missing = [key for key in REQUIRED_KEYS if not cookies.get(key)]
                if missing:
                    missing_text = ", ".join(missing)
                    if missing_text != last_missing:
                        _emit(f"[扫码登录] 已检测到登录会话，正在等待关键 Cookie：{missing_text}")
                        last_missing = missing_text
                    await asyncio.sleep(1.5)
                    continue

                _save_config(config_path, cookies)
                _emit(f"[扫码登录] 登录成功，已保存 {len(cookies)} 项 Cookie。")
                await context.close()
                await browser.close()
                return 0

            await asyncio.sleep(1.0)

        _emit("[扫码登录] 等待登录超时，请重新点击“浏览器登录获取 Cookie”后再试。")
        await context.close()
        await browser.close()
        return 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()

    try:
        return asyncio.run(run_login(Path(args.config).resolve(), max(60, int(args.timeout))))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        _emit(f"[扫码登录] 登录流程异常：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
