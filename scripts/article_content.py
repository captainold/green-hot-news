"""Article body + summary fetcher for green policy news.

Fetches a news URL, extracts the main readable text (readability-lite),
and produces a short summary + truncated body for local MD archiving.

Design goals:
- Zero new dependencies (requests + bs4 only).
- Never blocks the pipeline: on ANY failure returns None.
- Handles GBK/GB2312 Chinese gov sites via apparent_encoding fallback.
- Skips Google News redirect URLs (source sites often WAF-blocked).
"""

from __future__ import annotations

import re
from typing import Any, Optional

import requests
from bs4 import BeautifulSoup

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Nodes that are never article content
GARBAGE_SELECTORS = (
    "script,style,noscript,iframe,nav,footer,header,aside,form,button,"
    "svg,canvas,figure,map,audio,video,select,option,"
    ".advertisement,.ads,.ad,.banner,.share,.sharebox,.related,.recommend,"
    ".comment,.comments,.breadcrumb,.breadcrumbs,.pagination,.page-nav,"
    ".toc,.toolbar,.qrcode,.footer,.header,.nav,.menu,"
    ".list,.listbox,.news_list,.news-list,.search,.searchbox"
)

# Container hints: Chinese gov sites (TRS system), news portals, blogs
CONTAINER_SELECTORS = (
    "article",
    "main",
    "[class*='TRS_Editor']",
    "[class*='Custom_UnionStyle']",
    "[class*='article']",
    "[class*='Article']",
    "[class*='content']",
    "[class*='Content']",
    "[class*='detail']",
    "[class*='Detail']",
    "[class*='zw']",          # 正文
    "[class*='view']",        # news view
    "[class*='news_con']",
    "[class*='main-text']",
    "[class*='rich_media_content']",
    "[id*='content']",
    "[id*='Content']",
    "[id*='article']",
    "[id*='detail']",
    "[id*='zoom']",
)

# Paragraph-level tags kept when rebuilding clean text
BLOCK_TAGS = ("p", "h1", "h2", "h3", "h4", "li", "blockquote", "pre")

# Error-page / anti-bot markers: if the extracted body starts with these, treat as failure
ERROR_PAGE_MARKERS = (
    "抱歉，您访问的地址有错",
    "页面不存在",
    "您访问的页面不存在",
    "您访问的页面已经删除",
    "访问出错了",
    "页面无法访问",
    "404 Not Found",
    "Page not found",
    "Error 404",
)

MIN_PARAGRAPH_CHARS = 15
MAX_BODY_CHARS = 3000
MAX_SUMMARY_CHARS = 260
MIN_SUMMARY_CHARS = 60

_SENTENCE_END = re.compile(r"(?<=[。！？!?．\.])")


def _strip_html(src: str) -> str:
    """Remove tags/entities, collapse whitespace, keep CJK punctuation."""
    text = re.sub(r"<[^>]+>", "", src)
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _clean_title(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    t = raw.strip()
    t = re.sub(r"\s+", " ", t)
    return t[:120] or None


def _cut_at_sentence(text: str, limit: int) -> str:
    """Truncate at a sentence boundary near `limit` chars."""
    if len(text) <= limit:
        return text
    head = text[:limit]
    matches = list(_SENTENCE_END.finditer(head))
    if matches:
        cut = matches[-1].end()
        if cut >= MIN_SUMMARY_CHARS:
            return head[:cut]
    # fall back to last whitespace boundary
    sp = head.rfind(" ")
    if sp > MIN_SUMMARY_CHARS:
        return head[:sp]
    return head


def extract_readable(html: str) -> tuple[str, Optional[str]]:
    """Return (body_text, page_title). body_text is '' when nothing found."""
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("title")
    page_title = _clean_title(title_el.get_text() if title_el else None)

    for el in soup.select(GARBAGE_SELECTORS):
        el.decompose()

    # 1) best container by text length
    best: Any = None
    best_len = 0
    for sel in CONTAINER_SELECTORS:
        for cand in soup.select(sel):
            text = cand.get_text(" ", strip=True)
            if len(text) > best_len:
                best, best_len = cand, len(text)
    if best is not None and best_len >= 200:
        container = best
    else:
        container = soup.body or soup

    # 2) rebuild clean text from block-level elements
    blocks: list[str] = []
    for el in container.find_all(BLOCK_TAGS):
        txt = el.get_text(" ", strip=True)
        if len(txt) >= MIN_PARAGRAPH_CHARS:
            blocks.append(txt)
        if sum(len(b) for b in blocks) >= MAX_BODY_CHARS + 400:
            break

    # 2b) div-paragraph layouts (TRS/Custom_UnionStyle gov sites):
    #     leaf <div>s act as paragraphs when no <p> content was found
    if len(blocks) < 2 or sum(len(b) for b in blocks) < 100:
        div_blocks: list[str] = []
        for el in container.find_all("div"):
            if el.find(["p", "div", "li", "h1", "h2", "h3"]):
                continue  # not a leaf block
            txt = el.get_text(" ", strip=True)
            if len(txt) >= MIN_PARAGRAPH_CHARS:
                div_blocks.append(txt)
        if len(div_blocks) > len(blocks):
            blocks = div_blocks

    if not blocks:
        # fallback: whole container text
        whole = container.get_text(" ", strip=True)
        if len(whole) >= MIN_PARAGRAPH_CHARS:
            blocks = [whole]

    # dedupe consecutive identical blocks
    deduped: list[str] = []
    for b in blocks:
        if not deduped or b != deduped[-1]:
            deduped.append(b)

    body = "\n\n".join(deduped)
    # drop leading fragment if the page title was repeated as heading
    if page_title and len(page_title) > 8:
        for i, b in enumerate(deduped):
            if b.startswith(page_title):
                body = "\n\n".join(deduped[i + 1:])
                break
    return body, page_title


def fetch_article(url: str, session: Optional[requests.Session] = None,
                  timeout: tuple[int, int] = (10, 20),
                  retries: int = 2) -> Optional[dict[str, Optional[str]]]:
    """Fetch article page, extract summary + body.

    Returns {"summary": str, "content": str, "title": str|None}
    or None on any failure / non-HTML / Google-News redirect URL.
    """
    url = (url or "").strip()
    if not url or url.startswith(("https://news.google.com", "http://news.google.com")):
        return None
    if not url.lower().startswith(("http://", "https://")):
        return None

    own_session = session is None
    sess = session
    try:
        if sess is None:
            sess = requests.Session()
            sess.headers.update({
                "User-Agent": BROWSER_UA,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
        for attempt in range(max(1, retries + 1)):
            try:
                resp = sess.get(url, timeout=timeout, allow_redirects=True)
                break
            except Exception:  # network flakiness: retry fresh
                if attempt >= retries:
                    return None
        else:
            return None
        resp.raise_for_status()
        if "text/html" not in resp.headers.get("Content-Type", "").lower():
            # PDF / JSON / redirect payload — not worth archiving
            return None
        if resp.encoding is None or resp.encoding.lower() in ("iso-8859-1", "ascii"):
            resp.encoding = resp.apparent_encoding or "utf-8"
        body, page_title = extract_readable(resp.text)
        head = body[:120]
        if len(body) < MIN_PARAGRAPH_CHARS or any(m in head for m in ERROR_PAGE_MARKERS):
            return None
        summary = _cut_at_sentence(body, MAX_SUMMARY_CHARS)
        content = _cut_at_sentence(body, MAX_BODY_CHARS)
        return {"summary": summary, "content": content, "title": page_title}
    except Exception:
        return None
    finally:
        if own_session and sess is not None:
            try:
                sess.close()
            except Exception:
                pass
