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
    ".list,.listbox,.news_list,.news-list,.search,.searchbox,"
    ".tanlistbox_right,.list_r_b_x,.list_img_news,.about-read"  # 碳交易网推荐/相关阅读 (2026-08-11)
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

# Published-time patterns found on Chinese gov/news detail pages
# e.g. 发布时间：2026/07/31 15:30 | 时间: 2026-07-31 15:30:00 | 2026年7月31日 15:30
_PUB_RE = re.compile(
    r"(20\d{2})[年\-/.]\s*(\d{1,2})[月\-/.]\s*(\d{1,2})[日]?\s*"
    r"(?:[　\s]|$|,|，)"
    r"(\d{1,2})[:：](\d{2})"
)
_PUB_DATE_ONLY_RE = re.compile(
    r"(20\d{2})[年\-/.]\s*(\d{1,2})[月\-/.]\s*(\d{1,2})[日]?"
)
# "发布时间"/"发布时间："/"时间："/"日期：" label immediately before a date
_PUB_LABEL_RE = re.compile(
    r"(?:发布\s*时间|时间|日期|发布时间|成文日期)[:：]?\s*"
    r"(20\d{2})[年\-/.]\s*(\d{1,2})[月\-/.]\s*(\d{1,2})[日]?"
)


def _fmt_pub(year: str, month: str, day: str,
             hm: Optional[str] = None) -> Optional[str]:
    try:
        y, mo, d = int(year), int(month), int(day)
        if not (2000 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            return None
        date_part = f"{y:04d}-{mo:02d}-{d:02d}"
        return f"{date_part} {hm}" if hm else date_part
    except (TypeError, ValueError):
        return None


# ISO 8601, e.g. 2026-07-09T12:00:00+00:00 / 2026-07-09 12:00:00Z
_ISO_RE = re.compile(
    r"(20\d{2})-(\d{2})-(\d{2})[T ](\d{1,2}):(\d{2})(?::(\d{2}))?"
    r"(?:(Z)|([+-])(\d{2}):?(\d{2}))?"
)


def _iso_to_beijing(m: "re.Match[str]") -> Optional[str]:
    """Convert ISO match to 'YYYY-MM-DD HH:MM'.

    Only timezone-annotated values (Z or ±HH:MM) are converted to Beijing;
    naive datetimes (Chinese sites' visible meta rows) are returned as-is —
    they are already Beijing wall-clock time.
    """
    try:
        import datetime as dtm
        y, mo, d, h, mi = (int(m.group(i)) for i in range(1, 6))
        if m.group(7) == "Z":
            tz = dtm.timezone.utc
        elif m.group(8):
            sign = 1 if m.group(8) == "+" else -1
            tz = dtm.timezone(sign * dtm.timedelta(
                hours=int(m.group(9)), minutes=int(m.group(10) or 0)))
        else:
            # no offset → already wall-clock (Beijing for CN sites)
            return f"{y:04d}-{mo:02d}-{d:02d} {int(h):02d}:{int(mi):02d}"
        dt = dtm.datetime(y, mo, d, h, mi, tzinfo=tz)
        bj = dt.astimezone(dtm.timezone(dtm.timedelta(hours=8)))
        return f"{bj:%Y-%m-%d %H:%M}"
    except (TypeError, ValueError):
        return None


def _pub_from_text(txt: str) -> Optional[str]:
    """Return normalized publish time from a short text snippet."""
    if not txt:
        return None
    m = _ISO_RE.search(txt)
    if m:
        hit = _iso_to_beijing(m)
        if hit:
            return hit
    m = _PUB_LABEL_RE.search(txt)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        hm = _PUB_RE.search(txt)
        if hm and hm.start() >= m.start():
            return _fmt_pub(y, mo, d, f"{int(hm.group(4)):02d}:{hm.group(5)}")
        return _fmt_pub(y, mo, d, None)
    m = _PUB_RE.search(txt)
    if m:
        return _fmt_pub(m.group(1), m.group(2), m.group(3),
                        f"{int(m.group(4)):02d}:{m.group(5)}")
    m = _PUB_DATE_ONLY_RE.search(txt)
    if m:
        return _fmt_pub(m.group(1), m.group(2), m.group(3), None)
    return None


def extract_published_at(soup: BeautifulSoup) -> Optional[str]:
    """Extract publish time from a detail page.

    Returns "YYYY-MM-DD HH:MM" (hour precision) when found, else
    "YYYY-MM-DD" (date-only), else None.

    Layered: visible body text with HH:MM (Chinese sites' meta rows are
    Beijing time) → <time>/meta ISO (some sites, e.g. 碳道, emit misleading
    UTC metas, but gov sites like NDRC keep precise time only in meta) →
    visible body date-only.
    """
    def short_texts():
        for el in soup.find_all(["span", "div", "p", "li", "em", "td", "i"]):
            txt = el.get_text(" ", strip=True)
            if txt and len(txt) <= 60:
                yield txt

    def has_context(txt: str) -> bool:
        """True if the element carries more than a bare datetime (author row,
        label, ·-separated meta). Bare '2026-07-31 11:15' spans on gov sites
        are hidden duplicates of the UTC meta — skip them."""
        rest = re.sub(r"[\d\s\-/:：年月日.]", "", txt)
        return len(rest) >= 1

    # A) visible text with HH:MM + context (Chinese meta rows: Beijing-naive)
    for txt in short_texts():
        if not has_context(txt):
            continue
        m = _PUB_RE.search(txt) or _ISO_RE.search(txt)
        if m:
            hit = _pub_from_text(txt)
            if hit and len(hit) > 10:
                return hit
    # B) <time datetime> / meta ISO (precise time, maybe UTC → Beijing)
    for el in soup.find_all("time"):
        dt = str(el.get("datetime") or el.get_text(strip=True))
        hit = _pub_from_text(dt)
        if hit and len(hit) > 10:
            return hit
    for sel in (
        'meta[property="article:published_time"]',
        'meta[property="og:published_time"]',
        'meta[name="pubdate"]',
        'meta[name="publishdate"]',
        'meta[name="PubDate"]',
        'meta[itemprop="datePublished"]',
    ):
        el = soup.select_one(sel)
        if el and el.get("content"):
            val = str(el.get("content")).strip()
            hit = _pub_from_text(val)
            if hit and len(hit) > 10:
                return hit
    # C) visible text, date-only
    for txt in short_texts():
        hit = _pub_from_text(txt)
        if hit:
            return hit
    return None


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


def extract_readable(html: str, soup: Optional[BeautifulSoup] = None) -> tuple[str, Optional[str]]:
    """Return (body_text, page_title). body_text is '' when nothing found."""
    if soup is None:
        soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("title")
    page_title = _clean_title(title_el.get_text() if title_el else None)

    for el in soup.select(GARBAGE_SELECTORS):
        el.decompose()

    # 1) STRONG-PRIORITY containers: gov TRS systems mark the true article
    #    body with TRS_Editor / Custom_UnionStyle — trust it even if another
    #    candidate (e.g. a sidebar div) has more text.
    for sel in ("[class*='TRS_Editor']", "[class*='Custom_UnionStyle']"):
        cands = soup.select(sel)
        if cands:
            text = cands[0].get_text(" ", strip=True)
            if len(text) >= 100:
                container = cands[0]
                break
    else:
        # 1b) best container by text length
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

    # 2c) fallback: whole container text when block extraction is too thin
    #     (span/br layouts — TRS_Editor gov pages have paragraphs as bare
    #     spans separated by <br/>, which find_all('div') misses entirely)
    if len(blocks) < 2 or sum(len(b) for b in blocks) < 100:
        whole = container.get_text("\n\n", strip=True)
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


def extract_source_org(soup: BeautifulSoup) -> Optional[str]:
    """Extract 发文单位/文章来源 (作者属性) from detail page.

    Patterns seen across sources (2026-08-11):
      - 发改委:  <div class="ly laiyuantext">来源：产业司</div>
      - 工信部:  <span>来源：节能与综合利用司</span>
      - 生态环境部: <em>来源：生态环境部</em>
      - 中国能源报: <span class="source">来源：中国证券报</span>
      - 碳交易网: <span>文章来源:深圳晚报</span>
    Returns cleaned org name or None.
    """
    if soup is None:
        return None
    # 1) known selectors first
    for sel in (".ly.laiyuantext", ".laiyuan", ".source", ".article_source_web",
                "[class*=source]", "[class*=laiyuan]", "[class*=origin]"):
        for el in soup.select(sel):
            txt = el.get_text(" ", strip=True)
            m = re.search(r"来源[:：]\s*([^\s][^，。；;]{1,29})", txt)
            if m:
                return m.group(1).strip("：:，,。 ")
    # 2) fallback: any element whose text starts with 来源/文章来源
    for el in soup.find_all(string=lambda s: s and re.match(r"^(文章)?来源[:：]", s.strip())):
        m = re.search(r"来源[:：]\s*([^\s][^，。；;]{1,29})", el.strip())
        if m:
            return m.group(1).strip("：:，,。 ")
    return None


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
        soup = BeautifulSoup(resp.text, "html.parser")
        body, page_title = extract_readable(resp.text, soup)
        head = body[:120]
        if len(body) < MIN_PARAGRAPH_CHARS or any(m in head for m in ERROR_PAGE_MARKERS):
            return None
        summary = _cut_at_sentence(body, MAX_SUMMARY_CHARS)
        content = _cut_at_sentence(body, MAX_BODY_CHARS)
        published = extract_published_at(soup)
        source_org = extract_source_org(soup)
        if published:
            # Safety net: a publish time in the future is extraction garbage.
            # Detail-page times are Beijing-naive; compare against UTC now.
            try:
                import datetime as dtm
                bj_tz = dtm.timezone(dtm.timedelta(hours=8))
                pub_dt = dtm.datetime.strptime(published, "%Y-%m-%d %H:%M").replace(tzinfo=bj_tz)
                if pub_dt > dtm.datetime.now(dtm.timezone.utc) + dtm.timedelta(hours=1):
                    published = None
            except (TypeError, ValueError):
                published = None
        return {"summary": summary, "content": content, "title": page_title,
                "published": published, "source_org": source_org}
    except Exception:
        return None
    finally:
        if own_session and sess is not None:
            try:
                sess.close()
            except Exception:
                pass
