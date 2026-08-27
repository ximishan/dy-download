from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml
from playwright.async_api import Response, async_playwright

# Windows 子进程在 stdout 被管道接管时可能仍使用系统代码页（如 GBK）。
# GUI 端统一按 UTF-8 读取，所以这里显式固定 UTF-8，避免标题/类型/日志乱码。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / "vendor" / "douyin-downloader"
if str(UPSTREAM) not in sys.path:
    sys.path.insert(0, str(UPSTREAM))

from control.rate_limiter import RateLimiter  # noqa: E402
from core.api_client import DouyinAPIClient  # noqa: E402
from utils.validators import is_short_url, normalize_short_url  # noqa: E402

PAGE_SIZE = 20
PAGE_TIMEOUT_SECONDS = 45
MAX_BROWSER_SCROLLS = 260


def emit(kind: str, payload: Any) -> None:
    print("DYSCAN:" + json.dumps({"kind": kind, "payload": payload}, ensure_ascii=False), flush=True)


def load_cookie_dict(config_path: Path) -> dict[str, str]:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raw = data.get("cookies") or {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): str(value)
        for name, value in raw.items()
        if value is not None and str(value) != ""
    }


def browser_cookies(cookie_dict: dict[str, str]) -> list[dict]:
    return [
        {
            "name": name,
            "value": value,
            "domain": ".douyin.com",
            "path": "/",
        }
        for name, value in cookie_dict.items()
    ]


def sec_uid_from_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    query = parse_qs(parsed.query)
    for key in ("sec_uid", "sec_user_id"):
        values = query.get(key) or []
        if values and str(values[0]).strip():
            return str(values[0]).strip()

    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts):
        if part == "user" and index + 1 < len(parts):
            return parts[index + 1]
    return ""


def canonical_profile_url(sec_uid: str) -> str:
    return f"https://www.douyin.com/user/{sec_uid}"


async def resolve_profile_url(url: str, cookies: dict[str, str]) -> tuple[str, str]:
    candidate = (url or "").strip()

    if is_short_url(candidate):
        emit("status", "正在解析抖音分享短链接…")
        async with DouyinAPIClient(cookies) as api_client:
            resolved = await api_client.resolve_short_url(normalize_short_url(candidate))
        if not resolved:
            raise RuntimeError("抖音分享短链接解析失败，请确认链接仍然有效。")
        emit("log", f"短链接已展开：{resolved}")
    else:
        resolved = candidate

    sec_uid = sec_uid_from_url(resolved)
    if not sec_uid:
        raise RuntimeError(
            "这个链接没有识别出用户 sec_uid。请在目标用户主页点“分享 → 复制链接”后再粘贴。"
        )

    canonical = canonical_profile_url(sec_uid)
    if canonical != resolved:
        emit("log", f"标准主页地址：{canonical}")
    return canonical, sec_uid


def normalize_aweme(raw: dict, target_sec_uid: str) -> dict | None:
    aweme_id = str(raw.get("aweme_id") or raw.get("id") or "").strip()
    if not aweme_id:
        return None

    author = raw.get("author") or {}
    author_sec_uid = str(author.get("sec_uid") or "").strip()
    if target_sec_uid and target_sec_uid != "self" and author_sec_uid and author_sec_uid != target_sec_uid:
        return None

    desc = str(raw.get("desc") or "").strip().replace("\n", " ")
    images = raw.get("images") or []
    aweme_type = raw.get("aweme_type")
    is_gallery = bool(images) or aweme_type in {2, 68, 150}
    stats = raw.get("statistics") or {}
    create_time = raw.get("create_time") or 0

    cover = ""
    if is_gallery and images:
        first = images[0] or {}
        url_list = first.get("url_list") or first.get("download_url_list") or []
        cover = str(url_list[0]) if url_list else ""
    else:
        video = raw.get("video") or {}
        cover_obj = video.get("cover") or video.get("origin_cover") or {}
        url_list = cover_obj.get("url_list") or []
        cover = str(url_list[0]) if url_list else ""

    return {
        "aweme_id": aweme_id,
        "type": "图文" if is_gallery else "视频",
        "title": desc or "（无标题）",
        "author": str(author.get("nickname") or ""),
        "author_sec_uid": author_sec_uid,
        "create_time": int(create_time or 0),
        "digg_count": int(stats.get("digg_count") or 0),
        "comment_count": int(stats.get("comment_count") or 0),
        "share_count": int(stats.get("share_count") or 0),
        "image_count": len(images) if isinstance(images, list) else 0,
        "cover": cover,
    }


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _expected_target_count(profile_count: int, limit: int) -> int:
    if limit > 0:
        return min(profile_count, limit) if profile_count > 0 else limit
    return profile_count


async def collect_via_api(
    sec_uid: str,
    cookies: dict[str, str],
    limit: int,
) -> tuple[dict[str, dict], int, bool]:
    """参考上游项目：cursor 分页优先，检测异常时返回 restricted=True。"""
    items: dict[str, dict] = {}
    cursor = 0
    page_number = 0
    profile_count = 0
    restricted = False
    rate_limiter = RateLimiter(max_per_second=2)

    emit("status", "正在通过抖音作品接口分页抓取…")

    async with DouyinAPIClient(cookies) as api_client:
        try:
            await rate_limiter.acquire()
            user_info = await asyncio.wait_for(
                api_client.get_user_info(sec_uid),
                timeout=PAGE_TIMEOUT_SECONDS,
            )
            if isinstance(user_info, dict):
                profile_count = _to_int(user_info.get("aweme_count"))
                nickname = str(user_info.get("nickname") or "").strip()
                if nickname:
                    emit("log", f"用户昵称：{nickname}")
                if profile_count > 0:
                    emit("log", f"主页公开作品数：{profile_count}")
        except Exception as exc:
            emit("log", f"读取用户资料失败，将继续尝试作品分页：{exc}")

        expected_target = _expected_target_count(profile_count, limit)

        while True:
            page_number += 1
            request_cursor = cursor
            emit(
                "status",
                f"正在请求第 {page_number} 页，已抓取 {len(items)} 条…",
            )

            try:
                await rate_limiter.acquire()
                page_data = await asyncio.wait_for(
                    api_client.get_user_post(sec_uid, request_cursor, PAGE_SIZE),
                    timeout=PAGE_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                emit("log", f"第 {page_number} 页请求超时，将启用浏览器回补。")
                restricted = True
                break
            except Exception as exc:
                emit("log", f"第 {page_number} 页请求异常：{exc}，将启用浏览器回补。")
                restricted = True
                break

            if not isinstance(page_data, dict):
                emit("log", f"第 {page_number} 页没有返回有效数据。")
                restricted = True
                break

            raw_list = page_data.get("items") or page_data.get("aweme_list") or []
            if not isinstance(raw_list, list):
                raw_list = []

            status_code = _to_int(page_data.get("status_code"))
            has_more = bool(page_data.get("has_more", False))
            next_cursor = _to_int(page_data.get("max_cursor") or page_data.get("cursor"))
            risk_flags = page_data.get("risk_flags") if isinstance(page_data.get("risk_flags"), dict) else {}

            emit(
                "log",
                f"第 {page_number} 页：返回 {len(raw_list)} 条，has_more={has_more}，"
                f"cursor={request_cursor}→{next_cursor}，status={status_code}，risk={risk_flags}",
            )

            if not raw_list:
                if has_more or status_code == 0 or (expected_target > 0 and len(items) < expected_target):
                    restricted = True
                break

            before = len(items)
            for raw in raw_list:
                if not isinstance(raw, dict):
                    continue
                item = normalize_aweme(raw, sec_uid)
                if item:
                    items[item["aweme_id"]] = item

            emit(
                "progress",
                {
                    "count": len(items),
                    "message": f"接口分页第 {page_number} 页，已解析 {len(items)} 条作品",
                },
            )

            if limit > 0 and len(items) >= limit:
                break

            if has_more and next_cursor == request_cursor:
                emit("log", "检测到 cursor 停滞，为避免死循环，切换浏览器回补。")
                restricted = True
                break

            if not has_more:
                if expected_target > 0 and len(items) < expected_target:
                    emit(
                        "log",
                        f"接口提前结束：主页显示约 {profile_count} 条，当前仅抓到 {len(items)} 条，"
                        "将启用浏览器回补。",
                    )
                    restricted = True
                break

            if len(items) == before and has_more:
                emit("log", "本页没有新增作品但仍显示 has_more，切换浏览器回补。")
                restricted = True
                break

            cursor = next_cursor

    return items, profile_count, restricted


async def recover_via_browser(
    profile_url: str,
    sec_uid: str,
    cookies: dict[str, str],
    items: dict[str, dict],
    profile_count: int,
    limit: int,
) -> None:
    """API 分页受限时，用真实 Chromium 页面滚动监听作品接口回补并去重。"""
    emit("status", "接口分页受限，正在启动浏览器回补…")
    no_growth_rounds = 0
    page_has_more = True
    target_count = _expected_target_count(profile_count, limit)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1365, "height": 900},
            locale="zh-CN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            ),
        )
        cookie_list = browser_cookies(cookies)
        if cookie_list:
            await context.add_cookies(cookie_list)

        page = await context.new_page()

        async def handle_response(response: Response) -> None:
            nonlocal page_has_more
            if "/aweme/v1/web/aweme/post/" not in response.url and "aweme/post" not in response.url:
                return
            try:
                if "application/json" not in (response.headers.get("content-type") or ""):
                    return
                data = await response.json()
            except Exception:
                return

            raw_list = data.get("aweme_list") or data.get("items") or []
            if not isinstance(raw_list, list):
                return

            for raw in raw_list:
                if not isinstance(raw, dict):
                    continue
                item = normalize_aweme(raw, sec_uid)
                if item:
                    items[item["aweme_id"]] = item

            if "has_more" in data:
                page_has_more = bool(data.get("has_more"))

            emit(
                "progress",
                {"count": len(items), "message": f"浏览器回补中，已解析 {len(items)} 条作品"},
            )

        page.on("response", handle_response)

        try:
            await page.goto(profile_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            emit("log", f"浏览器主页加载提示：{exc}")

        await page.wait_for_timeout(3500)
        emit("log", f"浏览器最终主页：{page.url}")

        try:
            body_text = await page.locator("body").inner_text(timeout=5000)
        except Exception:
            body_text = ""
        for marker in ("验证码", "安全验证", "验证后继续"):
            if marker in body_text:
                emit("status", "检测到抖音安全验证，请在浏览器中完成验证后等待程序继续。")
                break

        previous_count = len(items)
        for index in range(MAX_BROWSER_SCROLLS):
            if limit > 0 and len(items) >= limit:
                break
            if target_count > 0 and len(items) >= target_count:
                break

            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1100)

            current = len(items)
            if current == previous_count:
                no_growth_rounds += 1
            else:
                no_growth_rounds = 0
            previous_count = current

            emit(
                "progress",
                {
                    "count": current,
                    "message": f"浏览器滚动第 {index + 1} 次，已解析 {current} 条",
                },
            )

            if no_growth_rounds >= 8 and not page_has_more:
                break
            if no_growth_rounds >= 14:
                break

        await browser.close()


async def scan(url: str, config_path: Path, output: Path, limit: int) -> int:
    cookie_dict = load_cookie_dict(config_path)
    profile_url, sec_uid = await resolve_profile_url(url, cookie_dict)
    emit("log", f"用户 sec_uid：{sec_uid}")

    items, profile_count, restricted = await collect_via_api(sec_uid, cookie_dict, limit)

    expected_target = _expected_target_count(profile_count, limit)
    needs_browser = restricted or not items
    if expected_target > 0 and len(items) < expected_target:
        needs_browser = True

    if needs_browser:
        await recover_via_browser(
            profile_url,
            sec_uid,
            cookie_dict,
            items,
            profile_count,
            limit,
        )
    else:
        emit("log", "接口分页完整，无需浏览器回补。")

    result = list(items.values())
    result.sort(key=lambda x: x.get("create_time", 0), reverse=True)
    if limit > 0:
        result = result[:limit]

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    emit("items", result)

    if profile_count > 0:
        emit("status", f"解析完成，共 {len(result)} 条作品（主页显示约 {profile_count} 条）")
    else:
        emit("status", f"解析完成，共 {len(result)} 条作品")

    return 0 if result else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    try:
        return asyncio.run(scan(args.url, Path(args.config), Path(args.output), args.limit))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        emit("error", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
