from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from playwright.async_api import Response, async_playwright


def emit(kind: str, payload: Any) -> None:
    print("DYSCAN:" + json.dumps({"kind": kind, "payload": payload}, ensure_ascii=False), flush=True)


def load_cookies(config_path: Path) -> list[dict]:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raw = data.get("cookies") or {}
    if not isinstance(raw, dict):
        return []
    cookies = []
    for name, value in raw.items():
        if value is None or value == "":
            continue
        cookies.append(
            {
                "name": str(name),
                "value": str(value),
                "domain": ".douyin.com",
                "path": "/",
            }
        )
    return cookies


def sec_uid_from_url(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "user":
        return parts[1]
    return ""


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
    target_sec_uid = sec_uid_from_url(url)

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
        cookies = load_cookies(config_path)
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
        emit("status", "正在打开抖音主页…")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            emit("log", f"主页加载提示：{exc}")
        await page.wait_for_timeout(3500)

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
            emit("progress", {"count": current, "message": f"滚动第 {index + 1} 次，已解析 {current} 条"})
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
