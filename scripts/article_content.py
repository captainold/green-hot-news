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

import json
import re
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# Nodes that are never article content
GARBAGE_SELECTORS = (
    "script,style,noscript,iframe,nav,footer,header,aside,button,"
    "svg,canvas,figure,map,audio,video,select,option,input,"
    ".advertisement,.ads,.ad,.banner,.share,.sharebox,.related,.recommend,"
    ".comment,.comments,.breadcrumb,.breadcrumbs,[class*='breadcrumb'],.pagination,.page-nav,"
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
    # 剥标题标签前缀（arXiv 详情页 h1 是 "Title: xxx" 格式，2026-08-19）
    m = re.match(r"^(title|标题|题名|文章标题)\s*[:：]\s*", t, re.IGNORECASE)
    if m:
        t = t[m.end():].strip()
    # 去掉站点 SEO 后缀（"标题_站点名" 模式，如 碳排放交易网/国家发展和改革委员会，
    # 以及英文源名后缀 " - EPA" / " - CleanTechnica" 等）
    for sep in ("_", "｜", "|", "——", "-", "–", "—"):
        if sep not in t:
            continue
        head, tail = t.rsplit(sep, 1)
        tail_s = tail.strip()
        if not tail_s:
            continue
        # 中文/日文站点后缀（2026-08-19 补 交易所/资讯/信息网/服务网——上海环交所
        # 详情页 title "标题-上海环境能源交易所"、chinanecc "…公共服务网" 等）
        if len(tail_s) <= 25 and re.search(
                r"(网|官网|委员会|政府|部$|中心|门户|交易所|资讯|信息网|服务网|新闻中心"
                r"|生态环境部|发展和改革委员会|环境省|经产省"
                r"|環境局|環境省|経産省|資源エネルギー庁)", tail_s):
            t = head.strip()
            break
        # 英文源名后缀：纯大写缩写 / 含域名 / 已知英文媒体机构名
        if len(tail_s) <= 30 and (
            re.fullmatch(r"[A-Z][A-Z0-9]{1,8}", tail_s)
            or re.search(r"\.(gov|com|org|net|in|eu|go\.jp)\b", tail_s, re.IGNORECASE)
            or (tail_s[0].isupper() and re.search(
                r"(CleanTechnica|Reuters|Carbon Brief|Asian Business Review|Euractiv|"
                r"World Bank|Department of Energy|Environmental Protection|US EPA|U\.S\. EPA|"
                r"European Commission|Climate Change AI|VentureBeat|Bloomberg|Guardian|"
                r"Financial Times|Scientific American|The Economist|Agora|E3G)",
                tail_s, re.IGNORECASE))
        ):
            t = head.strip()
            break
    return t[:120] or None


# 通用站名/栏目页标题（非文章标题）——PIB、gov 站点常见。
# 2026-08-19 大幅增强（chinanecc/EIA/arXiv/生态环境部/CARB 污染教训）：
#   - 中文"站名 - 栏目名"（国家节能中心公共服务网 - 节能研究，该站详情页 <title> 写死）
#   - 跳转确认页（生态环境部"您访问的链接即将离开…是否继续？"）
#   - 英文站名 + SEO 后缀（EIA "U.S. Energy Information Administration - EIA - Independent Statistics and Analysis"）
#   - GitHub 仓库 SEO 前缀（"GitHub - owner/repo: desc"）、arXiv 分类面包屑（"Computer Science > AI"）
#   - 栏目/导航词（Today in Energy / Main navigation / 相关阅读推荐 等）
_GENERIC_SITE_TITLE_RE = re.compile(
    r"(press release page|press information bureau|home\s*[|—–-]?|news\s*[|—–-]?|"
    r"english releases|photo album|blogdescription|pib backgrounder|"
    r"independent statistics and analysis|california air resources board|"
    r"snow station information|national hurricane center|main navigation|navigation menu|"
    r"today in energy|page not found|\b404\b|contact us|"
    r"computer science\s*>|github\s*-\s*[\w.-]+/[\w.-]+|"
    r"即将离开|是否继续|正在跳转|"
    r"相关阅读推荐|您可能对以下文章感兴趣|相关推荐|热门推荐|热点新闻|"
    r"^[\u4e00-\u9fff]{2,24}(网|中心|部|局|署|厅|院|站|官网|门户|平台)[\s\u3000]*[-—–|｜_][\s\u3000]*"
    r"[\u4e00-\u9fff]{0,8}?"
    r"(研究|动态|要闻|新闻|资讯|公告|通知|政策|法规|标准|专题|党建|简介|概况|机构|"
    r"服务|指南|文献|期刊|学报|目录|下载|数据|资源|招聘|版权|联系我们|首页|信息公开|"
    r"政务公开|互动交流|办事服务|政策法规|专题报道|工作动态|行业动态)\s*$)",
    re.IGNORECASE,
)


def _is_generic_site_title(raw: str) -> bool:
    """True if the <title> looks like a generic site/landing title, not an article."""
    t = (raw or "").strip()
    if not t:
        return True
    return bool(_GENERIC_SITE_TITLE_RE.search(t))


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


def _first_article_heading(soup: BeautifulSoup, tags: tuple[str, ...]) -> Optional[str]:
    """遍历 h1/h2，返回第一个「非通用站名/栏目/导航」的标题。

    2026-08-19 教训（chinanecc/EIA/arXiv/mee 实测）：
      - chinanecc 详情页无 h1，正文标题是 h2，<title> 写死为"站名 - 栏目名"
      - EIA 详情页有 3 个 h1：站名 → 栏目名（Today in Energy）→ 文章标题（第 3 个才是）
      - arXiv abs 页第 1 个 h1 是分类面包屑 "Computer Science > AI"，第 2 个是 "Title: xxx"
      - 生态环境部 h1 是跳转确认提示（"您访问的链接即将离开…是否继续？"），h2 才是标题
    """
    for tag in tags:
        for el in soup.find_all(tag):
            t = _clean_title(el.get_text())
            if t and not _is_generic_site_title(t):
                return t
    return None


def extract_readable(html: str, soup: Optional[BeautifulSoup] = None) -> tuple[str, Optional[str]]:
    """Return (body_text, page_title). body_text is '' when nothing found."""
    if soup is None:
        soup = BeautifulSoup(html, "html.parser")
    # 标题提取：h1 们（跳过站名/栏目）→ h2 们 → <title>（清洗 + 跳过站名）→ None。
    # 旧逻辑只取第一个 h1 / 只在一个 h2，导致 EIA 站名、arXiv 分类面包屑、
    # chinanecc 站名-栏目、生态环境部跳转提示被当成标题（2026-08-19）。
    page_title = _first_article_heading(soup, ("h1", "h2"))
    if not page_title:
        title_el = soup.find("title")
        if title_el is not None:
            t = _clean_title(title_el.get_text())
            if t and not _is_generic_site_title(t):
                page_title = t

    for el in soup.select(GARBAGE_SELECTORS):
        el.decompose()

    # 1) STRONG-PRIORITY containers: gov TRS systems mark the true article
    #    body with TRS_Editor / Custom_UnionStyle — trust it even if another
    #    candidate (e.g. a sidebar div) has more text.
    #    [class*='wysiwyg'] 是日本政府站（环境省 env.go.jp / 经产省等）通用 CMS 正文容器
    #    （2026-08-18：kyushu.env.go.jp 正文在 .wysiwyg 内，正文是直接文本节点 + <br>，
    #    不包 <p>/<li>，旧逻辑落回 whole-container 会混入面包屑与导航）。
    for sel in ("[class*='TRS_Editor']", "[class*='Custom_UnionStyle']", "[class*='wysiwyg']"):
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
                rest = b[len(page_title):].strip()
                if rest:
                    # 标题只是该块的前缀（正文紧跟其后，例如单块 fallback 的
                    # whole-container 文本）——保留剩余正文，不能整块丢弃。
                    deduped[i] = rest
                    body = "\n\n".join(deduped[i:])
                else:
                    # 该块就是标题本身（多块布局的首个标题块）——丢弃它
                    body = "\n\n".join(deduped[i + 1:])
                break
    return body, page_title


# ── 富文本提取（2026-08-24 阶段6：qmd 富文本优势——全文 + 图片 + 表格）──────
# 把正文容器转成 Markdown：保留段落/标题/列表/链接/表格/图片，供 qmd 数据库使用。
_IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp")


def _resolve_img_src(img) -> Optional[str]:
    """图片地址：data-src → src → srcset 首项，相对路径由调用方拼接 base。"""
    for attr in ("data-src", "data-original", "src"):
        v = img.get(attr)
        if v:
            return v.strip()
    srcset = img.get("srcset")
    if srcset:
        first = srcset.split(",")[0].strip().split(" ")[0]
        if first:
            return first
    return None


def download_images(markdown: str, att_dir: Path, session: Optional[requests.Session] = None,
                    timeout: tuple[int, int] = (10, 20)) -> tuple[str, int]:
    """下载 Markdown 中的图片到 att_dir，重写为相对路径引用（qmd 数据库附件）。

    返回 (new_markdown, 下载成功数)。失败图片保留原 URL（浏览器可加载），
    不阻断正文。图片命名 = md5(url)[:12] + 扩展名（防重名 + 幂等）。
    """
    import hashlib as _hl
    att_dir = Path(att_dir)
    att_dir.mkdir(parents=True, exist_ok=True)
    own = session is None
    sess = session
    try:
        if sess is None:
            sess = requests.Session()
            sess.headers.update({"User-Agent": BROWSER_UA})
        downloaded = 0

        def _swap(m: "re.Match[str]") -> str:
            nonlocal downloaded
            # PITFALL(2026-08-24): 正则 !\[([^\]]*)\]\((\S+)\) 的 group(1)=alt 文本、
            # group(2)=URL——之前误用 group(1) 当 src，alt 为空 → 全部图片 0 下载！
            src = m.group(2).strip()
            if not src or src.startswith("data:"):
                return m.group(0)  # base64 图不动
            ext = Path(src.split("?")[0]).suffix.lower() or ".jpg"
            if ext not in _IMG_EXTS:
                ext = ".jpg"
            fname = _hl.md5(src.encode("utf-8")).hexdigest()[:12] + ext
            dest = att_dir / fname
            if not dest.exists():
                try:
                    r = sess.get(src, timeout=timeout, stream=True)
                    r.raise_for_status()
                    data = r.content
                    if data and len(data) > 100:
                        dest.write_bytes(data)
                    else:
                        return m.group(0)
                except Exception:
                    return m.group(0)  # 失败保留原 URL
            downloaded += 1
            return f"![{m.group(1)}](attachments/{fname})"

        new_md = re.sub(r"!\[([^\]]*)\]\((\S+)\)", _swap, markdown)
        return new_md, downloaded
    finally:
        if own and sess is not None:
            try:
                sess.close()
            except Exception:
                pass


def _table_to_markdown(table) -> str:
    """<table> → GitHub Markdown 表格（简单表格；colspan/rowspan 降级为文本）。"""
    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    # 统一列数
    ncols = max(len(r) for r in rows)
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    lines = ["| " + " | ".join(r) + " |" for r in rows]
    lines.insert(1, "| " + " | ".join(["---"] * ncols) + " |")
    return "\n".join(lines)


def _node_to_markdown(el, base_url: str, out: list[str]) -> None:
    """递归把正文节点转 Markdown 片段。"""
    name = getattr(el, "name", None)
    if name is None:  # NavigableString
        t = str(el).strip()
        if t:
            out.append(t)
        return
    if name in ("script", "style", "nav", "noscript", "iframe", "form"):
        return
    if name == "img":
        src = _resolve_img_src(el)
        if src:
            # 图标/Logo/占位图过滤（2026-08-24：ico-article.png 等列表页图标混入正文）
            if re.search(r"(ico-|icon|logo|avatar|placeholder|loading|spinner)", src.lower()):
                return
            if src.startswith("//"):
                src = "https:" + src
            elif src.startswith("/"):
                src = (base_url or "").rstrip("/") + src
            alt = (el.get("alt") or "").strip()
            out.append(f"![{alt}]({src})")
        return
    if name == "table":
        md = _table_to_markdown(el)
        if md:
            out.append("\n" + md + "\n")
        return
    if name == "br":
        out.append("\n")
        return
    if name == "hr":
        out.append("\n---\n")
        return
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        txt = el.get_text(" ", strip=True)
        if txt:
            out.append("\n" + "#" * int(name[1]) + " " + txt + "\n")
        return
    if name == "li":
        txt = el.get_text(" ", strip=True)
        if txt:
            out.append("- " + txt)
        return
    if name == "blockquote":
        txt = el.get_text(" ", strip=True)
        if txt:
            out.append("\n> " + txt + "\n")
        return
    if name == "p":
        # 段落：先递归子节点（保留图/表/链接），再补段落分隔
        sub: list[str] = []
        for child in el.children:
            _node_to_markdown(child, base_url, sub)
        txt = "".join(sub).strip()
        if txt:
            out.append(txt + "\n\n")
        return
    if name == "a":
        href = el.get("href") or ""
        txt = el.get_text(" ", strip=True).strip()
        if txt:
            if href.startswith(("http://", "https://")):
                out.append(f"[{txt}]({href})")
            else:
                out.append(txt)
        return
    # 其他标签：递归子节点
    for child in el.children:
        _node_to_markdown(child, base_url, out)


def extract_rich(html: str, soup: Optional[BeautifulSoup] = None,
                 base_url: str = "") -> tuple[str, Optional[str]]:
    """富文本正文提取（qmd 用）：返回 (markdown_body, page_title)。

    与 extract_readable 同容器选择逻辑，但保留表格/图片/标题/列表结构，
    输出 GitHub 风格 Markdown（图片为 ![](绝对地址)，由调用方下载转存）。
    """
    if soup is None:
        soup = BeautifulSoup(html, "html.parser")
    page_title = _first_article_heading(soup, ("h1", "h2"))
    if not page_title:
        title_el = soup.find("title")
        if title_el is not None:
            t = _clean_title(title_el.get_text())
            if t and not _is_generic_site_title(t):
                page_title = t

    for el in soup.select(GARBAGE_SELECTORS):
        el.decompose()

    # 容器选择（与 extract_readable 相同逻辑）
    for sel in ("[class*='TRS_Editor']", "[class*='Custom_UnionStyle']", "[class*='wysiwyg']"):
        cands = soup.select(sel)
        if cands:
            text = cands[0].get_text(" ", strip=True)
            if len(text) >= 100:
                container = cands[0]
                break
    else:
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

    out: list[str] = []
    for child in container.children:
        _node_to_markdown(child, base_url, out)

    body = "\n".join(out)
    # 压缩连续空行
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
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


def _decode_google_news_url(url: str, session: Optional[requests.Session] = None,
                            timeout: tuple[int, int] = (10, 20)) -> Optional[str]:
    """Decode a Google News redirect URL to its real source article URL.

    Google News wraps every article link in an encrypted redirect
    (news.google.com/rss/articles/<b64>?oc=5). 解码需两步：
    1. GET https://news.google.com/articles/<b64> → 页面 c-wiz div 上的
       data-n-a-sg（签名）与 data-n-a-ts（时间戳）。
    2. POST batchexecute 协议（garturlreq）→ 返回真实 URL。
    失败返回 None（调用方按原逻辑降级：无摘要）。
    纯 requests 实现，不引入 selectolax 依赖。
    """
    path = urlparse(url).path
    parts = path.split("/")
    if "articles" not in parts:
        return None
    b64 = parts[-1].split("?")[0]
    if not b64:
        return None

    own_session = session is None
    sess = session
    try:
        if sess is None:
            sess = requests.Session()
            sess.headers.update({"User-Agent": BROWSER_UA,
                                 "Accept-Language": "en-US,en;q=0.9"})
        # 1) 取签名 + 时间戳
        # 注意：必须走 /rss/articles/<b64>?oc=5（RSS 直链），而非 /articles/<b64>。
        # /articles/<b64> 是「已解析文章页」，对无 Cookie 的脚本请求极易返回 429 限流，
        # 而 /rss/articles/ 返回 200 且同样带 data-n-a-sg / data-n-a-ts（2026-08-18 实测）。
        r = sess.get(f"https://news.google.com/rss/articles/{b64}?oc=5", timeout=timeout)
        r.raise_for_status()
        sg = re.search(r'data-n-a-sg="([^"]+)"', r.text)
        ts = re.search(r'data-n-a-ts="([^"]+)"', r.text)
        if not sg or not ts:
            return None
        signature, timestamp = sg.group(1), ts.group(1)
        # 2) batchexecute 协议解码
        payload = [
            "Fbv4je",
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,'
            'null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
            f'"{b64}",{timestamp},"{signature}"]',
        ]
        body = "f.req=" + quote(json.dumps([[payload]]))
        r2 = sess.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                     "User-Agent": BROWSER_UA},
            data=body, timeout=timeout,
        )
        r2.raise_for_status()
        parsed = json.loads(r2.text.split("\n\n")[1])[:-2]
        decoded = json.loads(parsed[0][2])[1]
        return decoded or None
    except Exception:
        return None
    finally:
        if own_session and sess is not None:
            try:
                sess.close()
            except Exception:
                pass


def _solve_tst_cookie(html: str) -> Optional[str]:
    """解析 __tst_status JS 反爬挑战脚本 → 计算 cookie 串。

    挑战页结构（cnenergynews 详情页实测，2026-08-19）：
      var e={WTKkN:<n1>,bOYDu:<n2>,dtzqS:...,wyeCN:<n3>,...}
      case"3":t=a[_0x649a("0x7")](t,<n4>)   ← EO_Bot_Ssid 值
    JS 逻辑（解混淆后）：t = n1+n2+n3；cookie = "__tst_status=<t>#; EO_Bot_Ssid=<n4>;"
    数字每次请求随机生成 → 必须从当前挑战页提取。正则提取失败返回 None。
    """
    import re as _re
    m1 = _re.search(r"WTKkN:(\d+),bOYDu:(\d+).*?wyeCN:(\d+)", html)
    m2 = _re.search(r"\(t,(\d+)\)", html)
    if not m1 or not m2:
        return None
    n1, n2, n3 = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
    n4 = int(m2.group(1))
    return f"__tst_status={n1 + n2 + n3}#; EO_Bot_Ssid={n4};"


def _clean_summary_meta(s: str) -> str:
    """清洗摘要开头的作者行/来源水印（2026-08-19 审计）。

    1. 碳道详情页把作者行「碳道小编 · 2026-08-19 20:08 · 阅读量 · 16」+「摘要：」
       渲染在正文前 → summary 污染；
    2. 碳交易网详情页来源行「文章来源:未知 碳交易网 2026-08-18 14:05 正文…」；
    3. 央行公告页导航垃圾（面包屑+字号+打印关闭，正文未提取）→ 整条清空。
    """
    s = (s or "").strip()
    # 3) 导航垃圾页（我的位置/字号/打印本页 = 页面骨架被当正文，无有用内容）
    if "我的位置" in s and "字号" in s and "打印本页" in s:
        return ""
    # 2) 文章来源行：文章来源:<来源名 可含空格/中文/未知> <日期 时间>
    s = re.sub(r"^文章来源[:：].{0,60}?\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}\s*", "", s)
    # 2b) 碳交易网页脚导航变体：「合作电话:xxx 栏目词…文章来源:xxx 时间 正文…」
    # （页脚导航被当正文提取时「文章来源」不在开头 — 2026-08-19 实测）
    m = re.search(
        r"合作电话[:：]?\d[\d\- ]{6,20}.*?文章来源[:：].{0,60}?\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}\s*",
        s)
    if m:
        s = s[m.end():]
        if len(s.strip()) < 15:  # 截断后只剩碎片 → 整条无效清空
            return ""
    # 1) 作者行：<可选标题前缀><名>小编/编辑 · YYYY-MM-DD HH:MM · 阅读量 · N
    # （前缀允许 0-50 字符——碳道部分摘要开头是「《标题》发布 推进… 碳道小编 · 时间 ·
    # 阅读量 · 6 摘要：」结构，小编不在开头 — 2026-08-19 审计二轮）
    s = re.sub(
        r"^.{0,50}?(小编|編輯|编辑)\s*[·.]\s*\d{4}-\d{2}-\d{2}.*?阅读量\s*[·:：]?\s*\d+\s*",
        "", s)
    # 详情页显式「摘要：」前缀
    for m in ("摘要：", "摘要:"):
        if s.startswith(m):
            s = s[len(m):].strip()
            break
    return s.strip()


def _clean_rich_body(s: str, title: str = "") -> str:
    """富文本正文清洗（2026-08-24 qmd 数据库：content 不截断，需独立清洗）。

    _clean_summary_meta 面向摘要（^ 锚定开头），富文本 content 开头常有
    标题重复行，作者行/摘要行出现在中段 → 用全局正则。
    """
    s = (s or "").strip()
    # 作者行（任意位置）：<名>小编/编辑 · YYYY-MM-DD HH:MM · 阅读量 · N
    s = re.sub(
        r"[^\n]{0,60}?(小编|編輯|编辑)\s*[·.]\s*\d{4}-\d{2}-\d{2}.*?阅读量\s*[·:：]?\s*\d+\s*",
        "", s)
    # 「摘要：xxx」行（详情页把摘要渲染在正文前；可能在标题重复行之后 → MULTILINE）
    s = re.sub(r"^摘要[:：][^\n]*\n?", "", s, flags=re.M)
    # 标题重复行：正文首行 == 页面标题时删除（只有匹配标题才删，防误删真实短段落）
    if title:
        first_line = s.split("\n", 1)[0].strip()
        if first_line and (first_line == title.strip() or first_line.startswith(title.strip()[:20])):
            s = s.split("\n", 1)[1] if "\n" in s else ""
    # 压缩连续空行
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def fetch_article(url: str, session: Optional[requests.Session] = None,
                  timeout: tuple[int, int] = (10, 20),
                  retries: int = 2,
                  rich: bool = False) -> Optional[dict[str, Optional[str]]]:
    """Fetch article page, extract summary + body.

    Returns {"summary": str, "content": str, "title": str|None}
    or None on any failure / non-HTML.
    Google News redirect URLs are decoded to their real source URL first
    (否则国外政府源摘要永远为空 — 2026-08-17)。
    rich=True（2026-08-24 qmd 数据库）：正文用 extract_rich 保留图片/表格，
    content 为完整 Markdown（不截断）。
    """
    url = (url or "").strip()
    if not url:
        return None
    real_url = url
    if url.lower().startswith(("https://news.google.com", "http://news.google.com")):
        real_url = _decode_google_news_url(url, session=session) or ""
        if not real_url:
            return None
        url = real_url
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
                # JS 反爬挑战页（__tst_status cookie 混淆，2026-08-19 cnenergynews 实测）：
                # 被拦时响应极小（~986B）且含挑战脚本特征 → 解码 cookie 后带 Cookie 重试，
                # 成功拿到完整正文页（30KB）。同 AIHOT 教训的通用处理——但 cnenergynews
                # 无官方 RSS 可走，只能绕挑战。
                if len(resp.text) < 5000 and "__tst_status" in resp.text:
                    ck = _solve_tst_cookie(resp.text)
                    if ck:
                        resp = sess.get(url, timeout=timeout, allow_redirects=True,
                                        headers={"Cookie": ck})
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
        if rich:
            # 富文本模式（qmd 数据库用）：保留图片/表格/标题结构 → Markdown
            body, page_title = extract_rich(resp.text, soup, base_url=url)
        else:
            body, page_title = extract_readable(resp.text, soup)
        head = body[:120]
        # 404/错误页检测（2026-08-19 大小写不敏感——CARB 404 页 "Page not found"
        # 曾被当正常文章抓取，素材 H1 变成站名）
        if (not page_title and not body) or len(body) < MIN_PARAGRAPH_CHARS or \
                any(m.lower() in head.lower() for m in ERROR_PAGE_MARKERS):
            return None
        if rich:
            content = body  # 富文本不截断（qmd 全量保存；由调用方控制）
            content = _clean_rich_body(content, page_title or "")  # 作者行/摘要/标题重复清洗（2026-08-24）
            summary = _cut_at_sentence(extract_readable(resp.text, soup)[0], MAX_SUMMARY_CHARS)
        else:
            summary = _cut_at_sentence(body, MAX_SUMMARY_CHARS)
            content = _cut_at_sentence(body, MAX_BODY_CHARS)
        summary = _clean_summary_meta(summary)  # 作者行/摘要前缀清洗（2026-08-19 碳道）
        published = extract_published_at(soup)
        source_org = extract_source_org(soup)
        if published:
            # Safety net: a publish time in the future is extraction garbage.
            # Detail-page times are Beijing-naive; compare against UTC now.
            # 2026-08-20 修复：date-only（'YYYY-MM-DD'）之前被 strptime(%H:%M) 抛
            # ValueError 误杀置 None——chinanecc 详情页只有日期（4-23），结果丢失
            # 原文时间落回首抓日。现在两种格式分别校验：date-only 判未来按天容差。
            try:
                import datetime as dtm
                bj_tz = dtm.timezone(dtm.timedelta(hours=8))
                if len(published) > 10:
                    pub_dt = dtm.datetime.strptime(published, "%Y-%m-%d %H:%M").replace(tzinfo=bj_tz)
                    if pub_dt > dtm.datetime.now(dtm.timezone.utc) + dtm.timedelta(hours=1):
                        published = None
                else:
                    pub_dt = dtm.datetime.strptime(published, "%Y-%m-%d").replace(tzinfo=bj_tz)
                    if pub_dt > dtm.datetime.now(dtm.timezone.utc) + dtm.timedelta(days=1):
                        published = None
            except (TypeError, ValueError):
                published = None
        return {"summary": summary, "content": content, "title": page_title,
                "published": published, "source_org": source_org,
                "real_url": real_url}
    except Exception:
        return None
    finally:
        if own_session and sess is not None:
            try:
                sess.close()
            except Exception:
                pass
