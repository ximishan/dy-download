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

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / "vendor" / "douyin-downloader"
if str(UPSTREAM) not in sys.path:
    sys.path.insert(0, str(UPSTREAM))

from core.api_client import DouyinAPIClient  # noqa: E402
from utils.validators import is_short_url, normalize_short_url  # noqa: E402


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
    """Extract sec_uid from all known Douyin user/share URL shapes.

    Supported examples:
      https://www.douyin.com/user/MS4w...
      https://www.iesdouyin.com/share/user/MS4w...
      ...?sec_uid=MS4w...
    """
    parsed = urlparse((url or "").strip())

    # Prefer explicit query parameter when present.
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


async def scan(url: str, config_path: Path, output: Path, limit: int) -> int:
    items: dict[str, dict] = {}
    no_growth_rounds = 0
    has_more = True

    cookie_dict = load_cookie_dict(config_path)
    resolved_url, target_sec_uid = await resolve_profile_url(url, cookie_dict)

    emit("status", "已识别用户主页，正在加载作品…")
    emit("log", f"用户 sec_uid：{target_sec_uid}")

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

        cookies = browser_cookies(cookie_dict)
        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()

        async def handle_response(response: Response) -> None:
            nonlocal has_more
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
                item = normalize_aweme(raw, target_sec_uid)
                if item:
                    items[item["aweme_id"]] = item

            if "has_more" in data:
                has_more = bool(data.get("has_more"))

            emit("progress", {"count": len(items), "message": f"已解析 {len(items)} 条作品"})

        page.on("response", handle_response)
        emit("status", "正在打开真实用户主页…")

        try:
            await page.goto(resolved_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            emit("log", f"主页加载提示：{exc}")

        await page.wait_for_timeout(3500)

        # Browser may append query params or perform another redirect; log it for diagnostics.
        final_url = page.url
        final_sec_uid = sec_uid_from_url(final_url)
        if final_sec_uid:
            if final_sec_uid != target_sec_uid:
                target_sec_uid = final_sec_uid
                emit("log", f"最终 sec_uid：{target_sec_uid}")
            emit("log", f"浏览器最终主页：{final_url}")

        body_text = ""
        try:
            body_text = await page.locator("body").inner_text(timeout=5000)
        except Exception:
            pass

        for marker in ("验证码", "安全验证", "验证后继续"):
            if marker in body_text:
                emit("status", "检测到抖音安全验证，请在打开的浏览器中完成验证。")
                break

        previous_count = -1
        for index in range(260):
            if limit > 0 and len(items) >= limit:
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
                {"count": current, "message": f"滚动第 {index + 1} 次，已解析 {current} 条"},
            )

            if no_growth_rounds >= 8 and not has_more:
                break
            if no_growth_rounds >= 14:
                break

        result = list(items.values())
        result.sort(key=lambda x: x.get("create_time", 0), reverse=True)
        if limit > 0:
            result = result[:limit]

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        emit("items", result)
        emit("status", f"解析完成，共 {len(result)} 条作品")

        await browser.close()
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
