"""D: 竞品来源抓取器 —— 把用户贴的官网/新闻/社媒公开链接抓成可喂 LLM 的调研文本.

只取**公开可 GET 的页面**(HTTP/HTTPS),用 requests 拉 HTML + html2text 转正文。
不做全站爬虫、不绕反爬、不碰登录墙 —— 抓不到就如实标 ok=False(缺数据不伪造)。

产出每条来源 {url, ok, text, fetched_at, note},供 auto_research 合并后喂
capability_census.extract_capabilities_via_llm(抽能力条目 -> candidate 待复核)。
"""
from __future__ import annotations

import datetime
import os

import requests
import html2text

# 西方站点(官网/社媒)常需代理;取 GAP_ATTRIB_HTTPS_PROXY / HTTPS_PROXY,与归因同源。
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
_MAX_CHARS = 8000            # 单页正文喂 LLM 的字符上限,防超长
_TIMEOUT = int(os.environ.get("SOURCE_FETCH_TIMEOUT", "10"))


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _proxies() -> dict | None:
    p = (os.environ.get("GAP_ATTRIB_HTTPS_PROXY")
         or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"))
    return {"http": p, "https": p} if p else None


def _html_to_text(html: str) -> str:
    h = html2text.HTML2Text()
    h.ignore_links = True
    h.ignore_images = True
    h.body_width = 0
    return h.handle(html)[:_MAX_CHARS]


def fetch_one(url: str, *, timeout: int | None = None) -> dict:
    """抓一个公开页 -> {url, ok, text, fetched_at, note}. 失败如实标 ok=False。"""
    url = (url or "").strip()
    fetched_at = _now_iso()
    if not url.lower().startswith(("http://", "https://")):
        return {"url": url, "ok": False, "text": "", "fetched_at": fetched_at,
                "note": "非 HTTP(S) 链接,跳过(只抓公开网页)"}
    try:
        resp = requests.get(url, headers={"User-Agent": _UA},
                            timeout=timeout or _TIMEOUT, proxies=_proxies())
        if resp.status_code != 200:
            return {"url": url, "ok": False, "text": "", "fetched_at": fetched_at,
                    "note": f"HTTP {resp.status_code}(抓取失败,如实标)"}
        ctype = resp.headers.get("Content-Type", "")
        if "html" in ctype or "text" in ctype or not ctype:
            text = _html_to_text(resp.text)
        else:
            return {"url": url, "ok": False, "text": "", "fetched_at": fetched_at,
                    "note": f"非文本内容({ctype}),跳过"}
        text = text.strip()
        if not text:
            return {"url": url, "ok": False, "text": "", "fetched_at": fetched_at,
                    "note": "页面无可读正文(可能是纯 JS 渲染,如实标)"}
        return {"url": url, "ok": True, "text": text, "fetched_at": fetched_at,
                "note": ""}
    except Exception as ex:
        return {"url": url, "ok": False, "text": "", "fetched_at": fetched_at,
                "note": f"抓取异常(如实标): {str(ex)[:160]}"}


def fetch_sources(urls: list[str], *, timeout: int | None = None) -> list[dict]:
    """抓一批来源链接。空列表 -> 空(如实)。返回每条的抓取结果(含成功/失败)。"""
    out = []
    for u in (urls or []):
        if u and u.strip():
            out.append(fetch_one(u, timeout=timeout))
    return out


def merge_fetched_text(fetched: list[dict]) -> tuple[str, list[dict]]:
    """把成功抓到的来源正文合并成一段喂 LLM 的文本,并返回成功来源清单(带 url)。

    只合并 ok=True 的;每段带来源 URL 头,便于 LLM 标 source。全失败 -> ("", [])。
    """
    ok_sources = [f for f in fetched if f.get("ok") and f.get("text")]
    if not ok_sources:
        return "", []
    blocks = [f"### 来源: {f['url']}\n{f['text']}" for f in ok_sources]
    return "\n\n".join(blocks), ok_sources
