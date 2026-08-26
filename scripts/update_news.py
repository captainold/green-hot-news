#!/usr/bin/env python3
"""Green Policy News Radar — aggregate green/low-carbon policy updates from global sources."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dtparser

try:
    from . import article_content
except ImportError:  # running as a plain script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import article_content

try:
    from . import translator
except ImportError:  # running as a plain script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import translator

try:
    from . import tech_feature
except ImportError:  # running as a plain script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import tech_feature

try:
    import feedparser
except ModuleNotFoundError:
    feedparser = None

# ── constants ──────────────────────────────────────────────────────────────────
UTC = timezone.utc
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
SH_TZ = timezone(timedelta(hours=8))


@dataclass
class RawItem:
    site_id: str
    site_name: str
    source: str = ""
    title: str = ""
    url: str = ""
    published_at: datetime | None = None
    summary: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


# ── helpers ────────────────────────────────────────────────────────────────────
def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def iso(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_iso(dt_str: str | None) -> datetime | None:
    if not dt_str:
        return None
    try:
        dt = dtparser.parse(dt_str)
    except Exception:
        return None
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_date_only(date_str: str | None) -> datetime | None:
    """Parse 'YYYY-MM-DD' (or 'YYYY/MM/DD') into a UTC midnight datetime."""
    if not date_str:
        return None
    try:
        dt = dtparser.parse(date_str)
    except Exception:
        return None
    return dt.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=UTC)


def normalize_url(raw_url: str) -> str:
    try:
        parsed = urlparse(raw_url.strip())
        if not parsed.scheme:
            return raw_url.strip()
        return urljoin(raw_url.strip(), parsed.path).rstrip("/")
    except Exception:
        return raw_url.strip()


def _title_dedup_key(title: str) -> str:
    """规范化标题用于去重（2026-08-19）。

    Google News RSS 的聚合 URL 是 base64 且每次抓取都不同（同一篇新闻被多个
    搜索词命中时 URL 各异），按 url 去重会漏——实测日本环境省一条新闻 x8 重复。
    标题才是稳定标识：去空白/全角空格/常见标点后小写，取前 120 字符。
    """
    import re as _re
    t = _re.sub(r"[\s\u3000\-_—–()（）【】\[\]「」『』・,，.。:：;；/\\|]", "", (title or "").lower())
    return t[:120]


def _titles_similar(a: str, b: str) -> bool:
    """标题相似度判定（2026-08-24 去重治理 P0）——标题变体判重。

    merge_history 原只用 _title_dedup_key 精确匹配，但同一新闻被抓多次时标题
    常有变体：截断（"明确2030年前" vs "明确2"）、标点差异（，vs ,）、源名后缀
    （"…研讨会召开" vs "…研讨会召开-上海环境能源交易所"）、措辞微调（"部分" vs "多家"）
    ——精确 key 不同而漏去重。此函数补相似度 + 前缀截断判定。
    """
    import difflib
    a, b = (a or "").strip(), (b or "").strip()
    if len(a) < 8 or len(b) < 8:
        return False
    if difflib.SequenceMatcher(None, a, b).ratio() >= 0.80:
        return True
    # 前缀截断：短标题是长标题的前缀（列表页抓取截断）
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return longer.startswith(shorter) and len(longer) - len(shorter) >= 3


def _title_prefix_key(title: str) -> str:
    """标题去重前缀桶（前 30 字符），用于相似度去重的候选缩小（性能）。"""
    return _title_dedup_key(title)[:30]


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
    return session


def make_item_id(site_id: str, title: str, url: str) -> str:
    key = f"{site_id}||{title}||{normalize_url(url)}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


# ── RSS helpers ────────────────────────────────────────────────────────────────
def fetch_rss_feed(session: requests.Session, feed_url: str, site_id: str, site_name: str, now: datetime, limit: int = 60, headers: dict | None = None) -> list[RawItem]:
    """Fetch RSS/Atom feed and return RawItems.

    limit: 最多返回条数。OpenAI/arXiv 等 RSS 含全部历史文章（1100+ 条），
    必须限量否则 export 阶段逐条抓详情页会卡死（2026-08-14 实测 timeout）。
    headers: 可选请求头（如 aihot 需带 aihot-api UA）。
    """
    items: list[RawItem] = []
    seen: set[tuple[str, str]] = set()
    try:
        r = session.get(feed_url, timeout=30, headers=headers)
        r.raise_for_status()
    except Exception:
        return items

    if feedparser:
        feed = feedparser.parse(r.content)
        for entry in feed.entries:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            key = (title, link)
            if key in seen:
                continue
            seen.add(key)

            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime(*entry.published_parsed[:6], tzinfo=UTC)
                except Exception:
                    pass
            if not published and hasattr(entry, "updated_parsed") and entry.updated_parsed:
                try:
                    published = datetime(*entry.updated_parsed[:6], tzinfo=UTC)
                except Exception:
                    pass

            source = entry.get("author", "") or site_name
            # 摘要：RSS/Atom 的 summary/description 字段（Google News 源等，2026-08-23 补）
            summary = None
            for _k in ("summary", "description"):
                _v = entry.get(_k)
                if _v:
                    summary = _clean_summary(_v)
                    break
            items.append(RawItem(
                site_id=site_id, site_name=site_name,
                source=source, title=title, url=link,
                published_at=published,
                meta={"feed_url": feed_url, "summary": summary if summary else ""},
            ))
    else:
        # Fallback: basic XML parsing
        from xml.etree import ElementTree as ET
        try:
            root = ET.fromstring(r.content)
        except Exception:
            return items
        for tag in ("item", "entry"):
            for node in root.iter(tag):
                title = (node.findtext("title") or "").strip()
                link = (node.findtext("link") or "").strip()
                if not title or not link:
                    continue
                key = (title, link)
                if key in seen:
                    continue
                seen.add(key)
                items.append(RawItem(
                    site_id=site_id, site_name=site_name,
                    source=site_name, title=title, url=link,
                    meta={"feed_url": feed_url},
                ))
    return items[:limit]


def fetch_aihot(session: requests.Session, now: datetime) -> list[RawItem]:
    """AIHOT — AI 行业动态聚合（2026-08-14 接入）。

    aihot.virxact.com 聚合 X/公众号/RSS 几十个 AI 信源，每条带热度与 AI 评分。
    页面有 JS 反爬（__tst_status cookie 挑战），但 RSS 端点匿名可访问（文档明确
    curl 是正式支持路径），ttl=30 恰好匹配本雷达 30 分钟抓取节奏。
    actor 是匿名标识（非密钥，清浏览器数据会更换），按服务条款个人使用免费。
    精选摘要 feed：最新 50 条，link 指向站内阅读页（items/xxx），正文由
    article_content 抓站内页；站内页若被 JS 挑战挡，RSS description 摘要兜底。
    """
    actor = "7077622b-91da-4e53-9bbb-48f5dc5e079f"
    return fetch_rss_feed(
        session,
        f"https://aihot.virxact.com/feed.xml?aihot_actor={actor}",
        "aihot", "AIHOT", now, limit=50,
        headers={"User-Agent": f"aihot-api/1.0 aihot-actor/{actor}"},
    )


def fetch_radarai(session: requests.Session, now: datetime) -> list[RawItem]:
    """RadarAI·GitHub趋势 — 开源项目热度追踪（radarai.top/trends）。

    radarai.top 聚合 GitHub Trending 开源项目（中文摘要 + star 数），
    /api/trends 返回干净 JSON（count=1052，无分页参数生效 → 代码内取前 40 条，
    即 GitHub 日榜 stars 排序的头部项目，作为技术风向标）。
    热榜条目无发布时间 → published_at=None 走收录时间兜底（同 allnet）。
    summary 塞 meta 备用（前端摘要回填通道未接 meta.summary，仅存档）。
    """
    url = "https://radarai.top/api/trends"
    limit = 40
    try:
        r = session.get(url, timeout=(10, 20))
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []
    items: list[RawItem] = []
    for proj in (data.get("data") or [])[:limit]:
        title = (proj.get("title") or "").strip()
        link = (proj.get("link") or "").strip()
        if not title or not link:
            continue
        summary = (proj.get("summary") or proj.get("description_zh") or "").strip()
        items.append(RawItem(
            site_id="radarai",
            site_name="RadarAI·GitHub趋势",
            source="RadarAI·GitHub趋势",
            title=title,
            url=link,
            meta={
                "summary": summary,
                "stars_total": proj.get("stars_total"),
                "language": proj.get("language"),
                "period": proj.get("period"),
            },
        ))
    return items


def fetch_jiqizhixin(session: requests.Session, now: datetime) -> list[RawItem]:
    """机器之心 — 中文 AI 头部媒体（2026-08-14 扩充）。

    PITFALL: jiqizhixin.com/rss 返回的是 HTML 壳（"机器之心·数据服务"）不是 RSS
    → 用 Google News RSS 搜 site:jiqizhixin.com，取最新条目。
    """
    items: list[RawItem] = []
    # 2026-08-23 修复：单主题词 + when:30d（AGENTS.md 铁律：括号 OR 语法返回
    # 全站混合内容——原查询返回 2022-2024 旧文，62 天窗口滤空）
    queries = [
        '"jiqizhixin.com" 大模型 when:30d',
        '"jiqizhixin.com" 芯片 when:30d',
        '"jiqizhixin.com" 智能体 when:30d',
    ]
    for q in queries:
        try:
            url = "https://news.google.com/rss/search"
            params = {"q": q, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}
            r = session.get(url, params=params, timeout=30)
            r.raise_for_status()
            feed = feedparser.parse(r.content) if feedparser else None
            if not feed:
                continue
            for entry in feed.entries[:15]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link:
                    continue
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=UTC)
                    except Exception:
                        pass
                items.append(RawItem(
                    site_id="jiqizhixin", site_name="机器之心",
                    title=title, url=link, published_at=published,
                ))
        except Exception:
            continue
    seen: set[tuple[str, str]] = set()
    out: list[RawItem] = []
    for it in items:
        key = (it.title, it.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:20]


def fetch_qbitai(session: requests.Session, now: datetime) -> list[RawItem]:
    """量子位 — 中文 AI 产品/市场媒体（2026-08-14 扩充）。

    PITFALL: qbitai.com/feed 返回 403（WAF 拦）→ Google News RSS 搜 site:qbitai.com。
    """
    items: list[RawItem] = []
    queries = [
        '"qbitai.com" AI OR 模型 OR 大模型',
        '"qbitai.com" 机器人 OR 芯片 OR 融资',
        '"qbitai.com" 智能体 OR 自动驾驶 OR 商业化',
    ]
    for q in queries:
        try:
            url = "https://news.google.com/rss/search"
            params = {"q": q, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}
            r = session.get(url, params=params, timeout=30)
            r.raise_for_status()
            feed = feedparser.parse(r.content) if feedparser else None
            if not feed:
                continue
            for entry in feed.entries[:15]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link:
                    continue
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=UTC)
                    except Exception:
                        pass
                items.append(RawItem(
                    site_id="qbitai", site_name="量子位",
                    title=title, url=link, published_at=published,
                ))
        except Exception:
            continue
    seen: set[tuple[str, str]] = set()
    out: list[RawItem] = []
    for it in items:
        key = (it.title, it.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:20]


# ── Web scraping fetchers ─────────────────────────────────────────────────────
_LIST_DATE_RE = re.compile(r"(20\d{2})[/\-.](\d{1,2})[/\-.](\d{1,2})")


def _list_item_date(li) -> Optional[str]:
    """Extract a date (YYYY-MM-DD) from a list item on gov listing pages."""
    for sp in li.find_all(["span", "em", "i", "time"]):
        txt = sp.get_text(strip=True)
        m = _LIST_DATE_RE.search(txt)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2000 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}"
    # fallback: any date-looking text in the li
    txt = li.get_text(" ", strip=True)
    m = _LIST_DATE_RE.search(txt)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 2000 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return None


def _entry_published(entry) -> Optional[datetime]:
    """Extract publish time from a feedparser entry (UTC)."""
    published = None
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            published = datetime(*entry.published_parsed[:6], tzinfo=UTC)
        except Exception:
            pass
    if not published and hasattr(entry, "updated_parsed") and entry.updated_parsed:
        try:
            published = datetime(*entry.updated_parsed[:6], tzinfo=UTC)
        except Exception:
            pass
    return published


_EN_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_EN_DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]+),?\s+(20\d{2})")


def _parse_english_date(text: str) -> Optional[datetime]:
    """Parse '07 August 2026' / '3 Aug 2026' into a UTC midnight datetime."""
    if not text:
        return None
    m = _EN_DATE_RE.search(text)
    if not m:
        return None
    mon = _EN_MONTHS.get(m.group(2).lower()[:3])
    if not mon:
        return None
    try:
        return datetime(int(m.group(3)), mon, int(m.group(1)), tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def fetch_ndrc(session: requests.Session, now: datetime) -> list[RawItem]:
    """国家发改委 — 新闻发布 + 通知公告全量.

    两个栏目：
      - xwfb 新闻发布（首页 30 条）
      - tzgg 通知公告（全部分页，每页 ~20 条；2026-08 时约 20 页）
    通知公告含规划/通知/公告/公示等最权威文件，必须一个不落。
    """
    items: list[RawItem] = []

    def _scrape_list(base_url: str, limit: int) -> None:
        seen: set[tuple[str, str]] = set()
        # 第 1 页: base_url/  第 n 页: base_url/index_{n-1}.html
        for page in range(1, limit + 1):
            if page == 1:
                list_url = base_url
            else:
                list_url = f"{base_url}index_{page - 1}.html"
            try:
                r = session.get(list_url, timeout=30)
                r.raise_for_status()
                r.encoding = "utf-8"
            except Exception:
                break  # 页尾或网络问题，停止
            soup = BeautifulSoup(r.text, "html.parser")
            found = 0
            for a in soup.select("li a[href]"):
                href = (a.get("href") or "").strip()
                text = a.get_text(strip=True)
                if not text or not href or href in ("./", "#") or len(text) < 8:
                    continue
                if href.startswith("./"):
                    href = urljoin(base_url, href)
                elif not href.startswith("http"):
                    continue
                # 只要本栏目文章链接（日期路径格式 /2026xx/t2026xxxx.html）
                if f"/{base_url.split('/')[-2]}/" not in href:
                    continue
                if href.endswith(("index_", ".html")) is False or "t20" not in href:
                    continue
                li = a.find_parent("li")
                pub_date = _list_item_date(li) if li is not None else None
                dedup_key = (text, href)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                items.append(RawItem(
                    site_id="ndrc", site_name="国家发改委",
                    title=text, url=href,
                    published_at=parse_date_only(pub_date),
                ))
                found += 1
            if found == 0:
                break  # 空页：到末尾了
            if found < 5:
                break  # 页面异常，保守停止

    try:
        _scrape_list("https://www.ndrc.gov.cn/xwdt/xwfb/", 3)
        _scrape_list("https://www.ndrc.gov.cn/xwdt/tzgg/", 25)
    except Exception:
        pass
    # 通知公告优先，去重后返回（tzgg 20 页 ≈ 400 条 + xwfb 首页）
    return items[:500]


def fetch_mee(session: requests.Session, now: datetime) -> list[RawItem]:
    """生态环境部 — 新闻."""
    items: list[RawItem] = []
    try:
        r = session.get("https://www.mee.gov.cn/ywdt/xwfb/", timeout=30)
        r.raise_for_status()
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            text = a.get_text(strip=True)
            # Filter: only news articles, not navigation/footer links
            if not text or not href or len(text) < 8:
                continue
            if any(skip in href for skip in ["javascript", "mailto"]):
                continue
            # Only accept relative links (news) or absolute MEE links
            if href.startswith("./"):
                href = urljoin("https://www.mee.gov.cn/ywdt/xwfb/", href)
            elif "mee.gov.cn" in href:
                pass  # keep absolute MEE links
            else:
                continue  # skip external domains (nav/department links)
            # Further filter: keep only news articles (URL contains date path)
            if "/20" not in href and "/xwfb/" not in href:
                continue
            li = a.find_parent("li")
            pub_date = _list_item_date(li) if li is not None else None
            items.append(RawItem(
                site_id="mee", site_name="生态环境部",
                title=text, url=href,
                published_at=parse_date_only(pub_date),
            ))
    except Exception:
        pass
    return items[:60]


def fetch_mee_jiedu(session: requests.Session, now: datetime) -> list[RawItem]:
    """生态环境部 — 政策解读栏目 (zcwj/zcjd/)，官方专家解读。

    2026-08-14 新增：部委网站发布的专家解读纳入政策库。
    栏目含「一图读懂」「司负责人答记者问」「解读XXX规划」等官方解读文章。
    """
    items: list[RawItem] = []
    list_url = "https://www.mee.gov.cn/zcwj/zcjd/"
    try:
        r = session.get(list_url, timeout=30)
        r.raise_for_status()
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            text = (a.get_text(strip=True) or "")
            if not text or not href or len(text) < 8:
                continue
            if any(skip in href for skip in ["javascript", "mailto"]):
                continue
            if href.startswith("./"):
                href = urljoin(list_url, href)
            elif "mee.gov.cn" not in href:
                continue
            # 只要解读文章（日期路径 t20xxxx）
            if "t20" not in href:
                continue
            li = a.find_parent("li")
            pub_date = _list_item_date(li) if li is not None else None
            items.append(RawItem(
                site_id="mee_jiedu", site_name="生态环境部·解读",
                title=text, url=href,
                published_at=parse_date_only(pub_date),
            ))
    except Exception:
        pass
    return items[:40]


def fetch_ccai(session: requests.Session, now: datetime) -> list[RawItem]:
    """Climate Change AI — 博客列表页（AI×气候交叉领域，2026-08-14 新增）。

    主题定位升级为「绿色低碳动态」后，AI/科技 是差异化增量维度。
    CCAI 无 RSS，抓 blog 列表页 /blog/ 下文章链接。
    PITFALL: 列表页按时间倒序但无日期元素（<time> 为 0），文章更新频率低
    （月更）——只取前 12 条最新，避免 2021 年历史文章涌入。
    """
    items: list[RawItem] = []
    list_url = "https://www.climatechange.ai/blog"
    try:
        r = session.get(list_url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            text = (a.get_text(strip=True) or "")
            if not href.startswith("/blog/"):
                continue
            if not text or len(text) < 12:
                continue
            full = urljoin("https://www.climatechange.ai", href)
            items.append(RawItem(
                site_id="ccai", site_name="Climate Change AI",
                title=text, url=full,
                published_at=None,
            ))
    except Exception:
        pass
    # 去重（列表页常有重复链接）并只保留最新 12 条
    seen: set[str] = set()
    out: list[RawItem] = []
    for it in items:
        if it.url in seen:
            continue
        seen.add(it.url)
        out.append(it)
    return out[:12]


def fetch_qjem(session: requests.Session, now: datetime) -> list[RawItem]:
    """经济管理学刊（QJEM）— 当期目录（2026-08-24 接入，老温指定全部抓取+参与评分）。

    机械工业信息研究院 + 北京大学光华管理学院主办（主编刘俏），经管综合学术
    期刊（宏观/金融/产业/养老/IPO/数字资产等）。目录页 /CN/home 直接含标题+
    作者+摘要（无需进详情页）。文章 URL = /CN/Y{年}/V{卷}/I{期}/{页码}。
    PITFALL: 官网仅 http（https 连接失败），且首页 302 → /CN/home。
    """
    items: list[RawItem] = []
    list_url = "http://www.qjem.cn/CN/home"
    # 重试 3 次（2026-08-24 生产实测：新加坡→中国 http 站偶发网络失败，
    # 单次 try 静默吞掉会整源 item_count=0，导致 qjem 漏抓）
    for _attempt in range(3):
        try:
            # PITFALL(2026-08-24 生产实测)：qjem.cn 是中国站，走 mihomo 家宽代理
            # （夏威夷出口）访问失败返回空 → 单次请求显式禁用代理直连
            r = session.get(list_url, timeout=30, proxies={"http": None, "https": None})
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            for block in soup.select(".article-l.article-w"):
                a = block.select_one(".j-title-1 a")
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = (a.get("href") or "").strip()
                if not title or not href:
                    continue
                full = urljoin("http://www.qjem.cn", href)
                author = ""
                au = block.select_one(".j-author")
                if au:
                    author = au.get_text(strip=True)
                summary = ""
                ab = block.select_one(".j-abstract")
                if ab:
                    summary = ab.get_text(" ", strip=True)
                items.append(RawItem(
                    site_id="qjem", site_name="经济管理学刊",
                    title=title, url=full,
                    meta={"summary": summary},
                ))
            break  # 成功，跳出重试
        except Exception:
            if _attempt < 2:
                time.sleep(1.0)
            # 最后一次失败 → items 保持空，静默降级
    # 去重（同 URL 只保留一次）
    seen: set[str] = set()
    out: list[RawItem] = []
    for it in items:
        if it.url in seen:
            continue
        seen.add(it.url)
        out.append(it)
    return out


def fetch_stdaily_green(session: requests.Session, now: datetime) -> list[RawItem]:
    """中国科技网（科技日报）— 绿色低碳/AI 动态。

    2026-08-14 新增：科技日报是国家级科技媒体，AI+绿色技术报道密集。
    PITFALL: Google News 搜 site:stdaily.com 返回的多是 1-3 月前旧文，
    会被 96h 窗口过滤 → 改为抓首页实时列表 + is_policy_relevant 过滤。
    """
    items: list[RawItem] = []
    try:
        r = session.get("https://www.stdaily.com/", timeout=30)
        r.raise_for_status()
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            text = (a.get_text(strip=True) or "")
            if not text or not href or len(text) < 10:
                continue
            # 只要文章链接（/web/YYYY-MM/ 日期路径）
            if "/web/20" not in href:
                continue
            if not href.startswith("http"):
                href = urljoin("https://www.stdaily.com", href)
            if not is_policy_relevant(text):
                continue
            li = a.find_parent("li")
            pub_date = _list_item_date(li) if li is not None else None
            items.append(RawItem(
                site_id="stdaily", site_name="中国科技网",
                title=text, url=href,
                published_at=parse_date_only(pub_date),
            ))
    except Exception:
        pass
    seen: set[tuple[str, str]] = set()
    out: list[RawItem] = []
    for it in items:
        key = (it.title, it.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:25]


def fetch_cleantechnica(session: requests.Session, now: datetime) -> list[RawItem]:
    """CleanTechnica — 清洁技术第一站（2026-08-14 新增）。

    PITFALL: cleantechnica.com/feed/ 直连被 Cloudflare WAF 拦（403 Just a moment，
    本地通过可抓但服务器 IP 被拦）→ 用 Google News RSS 搜 site 内容。
    走 is_policy_relevant 关键词过滤去车企商业噪音（Tesla 产量/Chevrolet 退出）。
    """
    items: list[RawItem] = []
    queries = [
        '"CleanTechnica" carbon OR climate OR energy',
        '"CleanTechnica" solar OR wind OR battery OR hydrogen',
        '"CleanTechnica" grid OR EV OR emission',
    ]
    for q in queries:
        try:
            url = "https://news.google.com/rss/search"
            params = {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"}
            r = session.get(url, params=params, timeout=30)
            r.raise_for_status()
            feed = feedparser.parse(r.content) if feedparser else None
            if not feed:
                continue
            for entry in feed.entries[:12]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link:
                    continue
                if not is_policy_relevant(title):
                    continue
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=UTC)
                    except Exception:
                        pass
                items.append(RawItem(
                    site_id="cleantechnica", site_name="CleanTechnica",
                    title=title, url=link, published_at=published,
                ))
        except Exception:
            continue
    seen: set[tuple[str, str]] = set()
    out: list[RawItem] = []
    for it in items:
        key = (it.title, it.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:20]


def _strip_rss_source_suffix(title: str, entry) -> str:
    """去掉 Google News RSS 标题尾部 " - 来源名" 标记。

    Google News RSS 的 title 格式是 "真实标题 - 来源名"，如
    "Government Ensures ... ISTS Framework - PIB" 或
    "... - Department of Energy (.gov)"。用 entry 的 source 字段
    （<source>PIB</source>）精确匹配尾部，匹配不上再按 " - " 分隔
    末尾短片段兜底。
    """
    t = title.strip()
    # 1) 用 entry source 精确匹配
    src_name = ""
    src = entry.get("source") if hasattr(entry, "get") else None
    if src is not None:
        src_name = (getattr(src, "title", None) or src.get("title") or "").strip()
    if src_name:
        tail = t.rsplit(" - ", 1)
        if len(tail) == 2 and tail[1].strip().lower() == src_name.lower():
            return tail[0].strip()
    # 2) 兜底：末尾 " - 短来源名" 模式（含域名/机构特征）
    #    2026-08-19：len 30→70 放行 EIA/NOAA 长站名（"U.S. Energy Information
    #    Administration (EIA) (.gov)" 42 字符、"NOAA National Centers for
    #    Environmental Information (NCEI) (.gov)" 66 字符），机构特征补
    #    Commission/Agency/Administration 等
    tail = t.rsplit(" - ", 1)
    if len(tail) == 2:
        right = tail[1].strip()
        if (len(right) <= 70 and re.search(
                r"(\.gov|\.com|\.in|\.org|\.go\.jp|网|官网|委员会|政府|中心|门户|部$|"
                r"PIB|EPA|DOE|NOAA|EIA|FERC|Euractiv|IEA|IRENA|NHC|CPC|"
                r"Administration|Commission|Agency|Department|Bureau|Institute)", right)):
            return tail[0].strip()
    return t


# 已知英文媒体/机构名（Google News RSS 标题尾部的来源名，非缩写/非域名部分）
_EN_SOURCE_NAMES = re.compile(
    r"(CleanTechnica|Reuters|Carbon Brief|Asian Business Review|Euractiv|"
    r"World Bank|Department of Energy|Environmental Protection|US EPA|U\.S\. EPA|"
    r"European Commission|Climate Change AI|VentureBeat|Bloomberg|Guardian|"
    r"Financial Times|Scientific American|The Economist|Agora|E3G|Mongabay)",  # Mongabay 2026-08-19 审计补
    re.IGNORECASE,
)


def _is_en_source_name(s: str) -> bool:
    """判断尾部片段是否像英文源名/站点名（用于剥离标题后缀）。"""
    s = (s or "").strip()
    if not s or len(s) > 30:
        return False
    # 纯大写缩写（EPA/DOE/NOAA/EIA/FERC/IRENA/IEA/PIB 等）
    if re.fullmatch(r"[A-Z][A-Z0-9]{1,8}", s):
        return True
    # 含域名（epa.gov / cleantechnica.com / meti.go.jp 等）
    if re.search(r"\.(gov|com|org|net|in|eu|go\.jp)\b", s, re.IGNORECASE):
        return True
    # 已知英文媒体/机构名（首字母大写，避免误伤 "in six charts" 等正文短语）
    if s[0].isupper() and _EN_SOURCE_NAMES.search(s):
        return True
    return False


def _title_similar(a: str, b: str) -> float:
    """标题字符重叠比例（0-1），用于判断详情页标题与列表标题是否同一篇文章。

    2026-08-19：详情页 title 覆盖列表标题前必须通过相似度门槛——否则源站
    <title> 写死为站名/栏目名（chinanecc "国家节能中心公共服务网 - 节能研究"、
    EIA 站名、arXiv 分类面包屑）时会把正常列表标题覆盖成垃圾。
    """
    def norm(s: str) -> str:
        return re.sub(r"[\s\-—–|｜_【】\[\]（）()《》〈〉<>「」『』\"'“”‘’.,，。:：;；!！?？、…]", "", s or "").lower()
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    # 截断关系视为同一篇（X 平台推文 150 字符截断、央行通知文号截断等——
    # 列表标题是详情页标题的子串时相似度应满分，避免阈值边缘误挡）
    if na in nb or nb in na:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _strip_title_suffix(title: str) -> str:
    """统一清理标题尾部的源名/站点后缀（" - EPA"、" - CleanTechnica" 等）。

    在构建 record 时对所有源统一应用，覆盖 fetch 函数未单独清理的
    Google News RSS 源（如 CleanTechnica/IRENA），以及详情页 title 回填
    后仍残留的英文源名后缀（2026-08-18）。
    """
    t = (title or "").strip()
    if not t:
        return t
    # 解码 HTML 实体（AIHOT 等源 feed 标题是 CDATA 包裹 + 内部 HTML 转义，
    # feedparser 不解 CDATA 里的实体，残留 &quot;/&amp; 等 — 2026-08-19）
    t = html.unescape(t)
    # 清理混入正文的"摘要：..."污染（碳道列表页 a.get_text() 会把标题+摘要+
    # 作者+相对时间拼在一起；旧笔记/title-index 回填时也会带进来 — 2026-08-18）
    for marker in ("摘要：", "摘要:"):
        if marker in t:
            t = t.split(marker, 1)[0].strip()
            break
    # 可剥的通用尾段（非源名但属于站点/栏目后缀的一部分——Mongabay
    # RSS 标题 "xxx - news - Mongabay" 需先剥 Mongabay 再剥 news — 2026-08-19）
    _GENERIC_TAIL_WORDS = {
        "news", "press", "releases", "updates", "media", "staff",
        "report", "blog", "daily", "weekly", "monthly",
    }
    for sep in (" - ", " — ", " – ", " | ", " ｜ ", " _ "):
        if sep not in t:
            continue
        # 循环剥离尾部源名/通用段（原只 rsplit 一次，剥不掉 " - news - Mongabay"）
        while sep in t:
            head, tail = t.rsplit(sep, 1)
            tail_s = tail.strip()
            if not tail_s:
                break
            # 中文/日文站点后缀
            if len(tail_s) <= 25 and re.search(
                    r"(网|官网|委员会|政府|部$|中心|门户|交易所|资讯|信息网|服务网|新闻中心"
                    r"|生态环境部|发展和改革委员会|环境省|经产省"
                    r"|環境局|環境省|経産省|資源エネルギー庁)", tail_s):
                t = head.strip()
                continue
            # 英文源名后缀
            if _is_en_source_name(tail_s):
                t = head.strip()
                continue
            # 通用栏目后缀段（news/press/releases…）
            if tail_s.lower() in _GENERIC_TAIL_WORDS:
                t = head.strip()
                continue
            break
    return t


# Google News 把站点导航/栏目页也当文章收录时的典型标题
# 2026-08-19 增强：EIA/DOE/NOAA 等站名页、工具页、栏目页（列表标题层过滤，
# 与 article_content 的详情页标题提取防御互补）
_NAV_JUNK_TITLE_RE = re.compile(
    r"^(english releases|photo album|blogdescription|pib backgrounder|"
    r"reports archives|.* archives|archives|glossary|education|data in the classroom|"
    r"station home page|tide predictions|daily weather map|"
    r"pib|eia webinars|short-term energy outlook|"
    r"contact us|about us|opendata|databases|dashboard|webinars|maps and data|energy explained|faqs|"
    r"hourly electric grid monitor|real-time operating grid|new england dashboard|"
    r"weekly petroleum status report|gasoline and diesel fuel update|steo data browser|"
    r"learn more about|map a career|renewable energy maps|data access viewer|sea level analysis tool|"
    r"archived directives|women in energy|from our blogs|grid talk|innovation|"
    r"energy workforce|find careers|find financing|credit subsidy|technical project officer|"
    r"collegiate wind competition|state energy advisory board|shara mohtadi|veronica jackson|"
    r"deploy 2024|energy improvements in rural|getting to know lpo|loan program office|aes marahu|"
    r"u\.s\. energy & employment report|marine energy basics|regional clean hydrogen hubs|"
    r"quarterly solar industry update|critical minerals and materials|solar workforce|"
    r"solar photovoltaic|types of hydropower|how distributed wind|hydrogen production|"
    r"solar cybersecurity|end-of-life management for solar|3 reasons why nuclear|5 fast facts about nuclear|"
    r"does eia project|what can i expect to pay for heating|national weather service marine forecast\b.*|"
    r"tropical storm \w+ forecast discussion\b.*|station \d+\b.*|station [a-z0-9]{3,6} \b.*|snow station information\b.*|"
    r"multi-state regions|electric matters|statements and speeches|data tool|"
    r"air quality system|public water system service areas|clean school bus program|"
    r"transmission facility financing|what types of cmei funding exist|30d new clean vehicle credit|"
    r"u\.s\. energy information administration\b.*|southwestern power administration\b.*|"
    r"california air resources board\b.*|federal energy regulatory commission\b.*|"
    r"national hurricane center\b.*|climate prediction center\b.*)\s*$",
    re.IGNORECASE,
)


def _clean_summary(raw: str) -> str:
    """统一清洗摘要（2026-08-21 QA 系统发现）：
    0. Google News RSS description 判空 —— <a href="news.google.com/rss/articles/…">标题</a>
       <font>源名</font> 无真实摘要，标题/源名均冗余（标题存 title、源名存 site_name），直接判空
    1. html.unescape —— X 平台 SSR content 属性 / 部分 feed CDATA 的 &amp; &quot; 残留
    2. 剥离 HTML 标签 —— 其他源描述里混入的 <a>/<font>/<br> 等（QA B5 实测 138 条残留）
    3. 去除 {{...}} 模板变量 —— 中国环境报等 Google News 收录模板页（{{content.publishTime}}）
    4. 清空标签序列（模板变量清掉后残留的"时间： 来源： 作者： "）与版权页脚
    5. 压缩空白
    保守清洗：只处理明确噪音，不动正文内容。
    """
    if not raw:
        return ""
    s = html.unescape(str(raw))
    # 2026-08-26：Google News RSS description 判空——无真实摘要，标题+源名均冗余
    if "news.google.com/rss/articles" in s:
        return ""
    # 2026-08-26：剥离 HTML 标签——其他源 description 混入的 <a>/<font>/<br> 等，
    # QA B5 实测 138 条残留。只匹配 < 后紧跟字母或 / 的真标签，避免误伤 "A < B" 数学式。
    s = re.sub(r"</?[a-zA-Z][^>]*>", " ", s)
    s = re.sub(r"\{\{[^}]*\}?\}", "", s)  # 模板变量（含未闭合的 {{item.publishTime.）
    # 空标签序列：模板变量清掉后"时间： 来源： 作者： 编辑： "只剩标签+空白
    s = re.sub(r"((?:时间|来源|作者|编辑|责编|责任编辑|监制|采写|记者|摄影)：(?:\s|$))+", "", s)
    # 版权/页脚残留（中国环境报等：本作品…联系电话…，允许跨句号）
    s = re.sub(r"本作品.*?(?:联系电话|版权)", "", s)
    # 页脚/导航垃圾词（2026-08-23 补：国家节能中心/上海环交所等详情页页脚）
    for _w in ("打印本页", "关闭窗口", "返回顶端", "网站首页", "加入收藏", "设为首页",
               "网上调查", "成绩查询", "联系我们", "站点地图", "网站地图", "加入收藏夹"):
        s = s.replace(_w, "")
    # 导航标记（"● 打印本页 ●" 的 ● 残留）与管道分隔空壳（"首页 | 联系我们 | …"）
    s = re.sub(r"[●◆▲■|·]\s*", " ", s)
    s = s.replace("<<", " ").replace(">>", " ")  # "返回顶端"链接的箭头残留
    # 孤立"登录/注册"按钮文字（上海环交所详情页页脚混入，前后是空白或标记）
    s = re.sub(r"(?:^|\s)(?:登录|注册|无障碍|简体|繁体)(?=\s|$)", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _is_nav_junk_title(title_clean: str) -> bool:
    """True if the cleaned title is a site navigation/landing-page title, not an article."""
    return bool(_NAV_JUNK_TITLE_RE.match(title_clean.strip()))


def fetch_foreign_gov(session: requests.Session, now: datetime, site_id: str, site_name: str, queries: list[str], limit: int = 20, locale: str = "en-US") -> list[RawItem]:
    """国外主要国家政策源 — Google News RSS 按站点搜索（2026-08-14 新增）。

    背景：美国/欧盟/日本/印度政府网站大多不提供 RSS（EPA/DOE/EU 等探测过，
    404 或 HTML 壳），白宫气候页 Google 未索引。用 Google News RSS 搜 site 是最
    成熟方案（与北极星/CleanTechnica 同款），加 when:7d 限近期。
    产出归政策库·国际（官方原文），SOURCE_SCORE 按部委档 25。
    locale: "en-US"/"ja"/"zh-CN" 等；日本源用 ja（hl=ja/gl=JP），中文源用 zh-CN（hl=zh-CN/gl=CN），否则关键词搜不出。
    """
    gl = "JP" if locale == "ja" else ("CN" if locale == "zh-CN" else "US")
    ceid = "JP:ja" if locale == "ja" else ("CN:zh-Hans" if locale == "zh-CN" else "US:en")
    hl = locale
    items: list[RawItem] = []
    for q in queries:
        try:
            url = "https://news.google.com/rss/search"
            params = {"q": q, "hl": hl, "gl": gl, "ceid": ceid}
            r = session.get(url, params=params, timeout=30)
            r.raise_for_status()
            feed = feedparser.parse(r.content) if feedparser else None
            if not feed:
                continue
            for entry in feed.entries[:15]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link:
                    continue
                if len(title) < 8:
                    continue  # 跳过站内导航类碎片（"News - EPA" 等）
                if title.startswith("-") or title.count(" ") < 2:
                    continue  # 跳过 "- 机构名" 导航碎片、无描述性标题
                # 去掉尾部 " - EPA (.gov)" 类来源标记
                title_clean = _strip_rss_source_suffix(title, entry)
                if len(title_clean) < 8:
                    continue
                # 纯日期标题（Google News 收录日期页/日历页：\"08/19/2026\" — QA 2026-08-21）
                if re.fullmatch(r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{2,4}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4}", title_clean):
                    continue
                # 过滤纯导航/栏目页标题（Google News 把站点导航页也当文章收录）
                if _is_nav_junk_title(title_clean):
                    continue
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=UTC)
                    except Exception:
                        pass
                # 摘要：Google News RSS 的 description 字段（部分站点有，如虎嗅）
                summary = None
                if hasattr(entry, "description") and entry.description:
                    summary = _clean_summary(entry.description)
                items.append(RawItem(
                    site_id=site_id, site_name=site_name,
                    title=title_clean, url=link, published_at=published,
                    meta={"summary": summary} if summary else {},
                ))
        except Exception:
            continue
    # 跨 query 去重（2026-08-19）：Google News 对同一新闻的聚合 URL 是 base64 且
    # 每次抓取不同，按 url 去重会漏（实测一条新闻 x8 重复）→ 按规范化标题去重
    seen: set[str] = set()
    out: list[RawItem] = []
    for it in items:
        key = _title_dedup_key(it.title)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:limit]


def fetch_us_epa(session: requests.Session, now: datetime) -> list[RawItem]:
    """美国环保署 EPA — 温室气体法规、发电厂排放标准（2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "us_epa", "美国EPA", [
        "site:epa.gov climate when:7d",
        "site:epa.gov emissions when:7d",
        "site:epa.gov greenhouse when:7d",
        "site:epa.gov power plant when:7d",
        "site:epa.gov methane when:7d",
        "site:epa.gov carbon pollution when:7d",
    ])


def fetch_us_doe(session: requests.Session, now: datetime) -> list[RawItem]:
    """美国能源部 DOE — 清洁能源计划、关键矿产、贷款项目（2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "us_doe", "美国DOE", [
        "site:energy.gov clean energy when:7d",
        "site:energy.gov solar when:7d",
        "site:energy.gov grid when:7d",
        "site:energy.gov battery when:7d",
        "site:energy.gov hydrogen when:7d",
        "site:energy.gov loan program when:7d",
        "site:energy.gov critical minerals when:7d",
        "site:energy.gov nuclear when:7d",
        "site:energy.gov wind when:7d",
    ])


def fetch_eu_commission(session: requests.Session, now: datetime) -> list[RawItem]:
    """欧盟委员会 — 气候行动总司/能源总司：Fit for 55、CBAM、EU ETS（2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "eu_commission", "欧盟委员会", [
        "site:ec.europa.eu climate when:7d",
        "site:ec.europa.eu emissions when:7d",
        "site:ec.europa.eu CBAM when:7d",
        "site:ec.europa.eu carbon when:7d",
        "site:ec.europa.eu energy when:7d",
        "site:ec.europa.eu renewables when:7d",
        "site:ec.europa.eu hydrogen when:7d",
        "site:ec.europa.eu grid when:7d",
    ])


def fetch_euractiv(session: requests.Session, now: datetime) -> list[RawItem]:
    """Euractiv（布鲁塞尔）— 欧盟政策专业媒体（2026-08-14 新增）。

    归政策库·国际（欧盟政策一手报道），媒体属性但政策浓度高。
    """
    return fetch_foreign_gov(session, now, "euractiv", "Euractiv·欧盟", [
        "site:euractiv.com climate when:7d",
        "site:euractiv.com energy when:7d",
        "site:euractiv.com emissions when:7d",
        "site:euractiv.com carbon when:7d",
        "site:euractiv.com CBAM when:7d",
        "site:euractiv.com ETS when:7d",
        "site:euractiv.com renewables when:7d",
        "site:euractiv.com green deal when:7d",
    ])


def fetch_india_pib(session: requests.Session, now: datetime) -> list[RawItem]:
    """印度新闻信息局 PIB — 绿氢使命、气候政策、可再生能源（2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "india_pib", "印度PIB", [
        "site:pib.gov.in climate when:7d",
        "site:pib.gov.in renewable when:7d",
        "site:pib.gov.in solar when:7d",
        "site:pib.gov.in energy when:7d",
        "site:pib.gov.in green hydrogen when:7d",
        "site:pib.gov.in emissions when:7d",
        "site:pib.gov.in carbon when:7d",
        "site:pib.gov.in sustainability when:7d",
    ])


# ── 美国/日本扩展官方源（2026-08-14 第二轮：NOAA/EIA/FERC/CARB/MOE/METI/ANRE） ──
def fetch_us_noaa(session: requests.Session, now: datetime) -> list[RawItem]:
    """美国国家海洋大气局 NOAA — 气候科学、温室气体监测、海洋与大气（2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "us_noaa", "美国NOAA", [
        "site:noaa.gov climate change when:7d",
        "site:noaa.gov greenhouse when:7d",
        "site:noaa.gov carbon dioxide when:7d",
        "site:noaa.gov ocean warming when:7d",
        "site:noaa.gov sea level when:7d",
        "site:noaa.gov emissions when:7d",
    ])


def fetch_us_eia(session: requests.Session, now: datetime) -> list[RawItem]:
    """美国能源信息署 EIA — 能源统计与预测（天然气/电力/可再生，权威数据源，2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "us_eia", "美国EIA", [
        "site:eia.gov natural gas when:7d",
        "site:eia.gov electricity when:7d",
        "site:eia.gov renewables when:7d",
        "site:eia.gov emissions when:7d",
        "site:eia.gov energy outlook when:7d",
        "site:eia.gov battery when:7d",
        "site:eia.gov solar when:7d",
    ])


def fetch_us_ferc(session: requests.Session, now: datetime) -> list[RawItem]:
    """美国联邦能源监管委员会 FERC — 电网/输电/LNG/电力市场监管（2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "us_ferc", "美国FERC", [
        "site:ferc.gov grid when:14d",
        "site:ferc.gov transmission when:14d",
        "site:ferc.gov electricity when:14d",
        "site:ferc.gov LNG when:14d",
        "site:ferc.gov reliability when:14d",
        "site:ferc.gov interconnection when:14d",
        "site:ferc.gov wholesale market when:14d",
    ])


def fetch_us_carb(session: requests.Session, now: datetime) -> list[RawItem]:
    """加州空气资源委员会 CARB — 零排放汽车、碳市场、气候政策（美国州级最权威，2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "us_carb", "加州CARB", [
        "site:ww2.arb.ca.gov climate when:30d",
        "site:ww2.arb.ca.gov zero emission when:30d",
        "site:ww2.arb.ca.gov cap and trade when:30d",
        "site:ww2.arb.ca.gov trucks when:30d",
        "site:ww2.arb.ca.gov cars when:30d",
        "site:ww2.arb.ca.gov diesel when:30d",
        "site:ww2.arb.ca.gov regulations when:30d",
    ])


def fetch_jp_moe(session: requests.Session, now: datetime) -> list[RawItem]:
    """日本环境省 MOE — 气候政策、脱碳、碳市场（2026-08-14 新增，日语关键词）。"""
    return fetch_foreign_gov(session, now, "jp_moe", "日本环境省", [
        "site:env.go.jp 脱炭素 when:14d",
        "site:env.go.jp 気候変動対策 when:14d",
        "site:env.go.jp カーボンニュートラル when:14d",
        "site:env.go.jp 地球温暖化 when:14d",
        "site:env.go.jp 温室効果ガス when:14d",
        "site:env.go.jp 排出量取引 when:14d",
    ], limit=15, locale="ja")


def fetch_jp_meti(session: requests.Session, now: datetime) -> list[RawItem]:
    """日本经济产业省 METI — 能源政策、GX、氢能（2026-08-14 新增，日语关键词）。"""
    return fetch_foreign_gov(session, now, "jp_meti", "日本经产省", [
        "site:meti.go.jp エネルギー when:14d",
        "site:meti.go.jp 脱炭素 when:14d",
        "site:meti.go.jp 水素 when:14d",
        "site:meti.go.jp GX when:14d",
        "site:meti.go.jp 再生可能エネルギー when:14d",
        "site:meti.go.jp 電力 when:14d",
        "site:meti.go.jp カーボン when:14d",
    ], limit=15, locale="ja")


def fetch_jp_anre(session: requests.Session, now: datetime) -> list[RawItem]:
    """日本资源能源厅 ANRE（经产省下属）— 电力/油气/可再生能源政策（2026-08-14 新增，日语关键词）。"""
    return fetch_foreign_gov(session, now, "jp_anre", "日本资源能源厅", [
        "site:enecho.meti.go.jp 再生可能 when:14d",
        "site:enecho.meti.go.jp 水素 when:14d",
        "site:enecho.meti.go.jp 脱炭素 when:14d",
        "site:enecho.meti.go.jp 電力 when:14d",
        "site:enecho.meti.go.jp エネルギー when:14d",
        "site:enecho.meti.go.jp 石油 when:14d",
        "site:enecho.meti.go.jp ガス when:14d",
    ], limit=15, locale="ja")


# ── 国际智库（2026-08-17 第三轮：E3G/Agora/TERI） ──────────────────────────
def fetch_e3g(session: requests.Session, now: datetime) -> list[RawItem]:
    """E3G（伦敦气候与能源智库）— RSS 直抓优先，Google News 兜底（2026-08-17 接入）。

    欧洲最具影响力的气候政策智库之一，news 以欧盟/全球气候金融、能源转型评论为主，
    政策浓度高。RSS /feed/ 活跃（约 12 条滚动），有 published 时间。
    PITFALL: e3g.org/feed 在新加坡服务器 IP 被 Cloudflare 403（本地可抓）→
    RSS 返回空时自动 fallback Google News 搜 site:e3g.org（同 CleanTechnica 模式）。
    """
    items = fetch_rss_feed(
        session, "https://www.e3g.org/feed/", "e3g", "E3G", now, limit=20,
    )
    if items:
        return items
    return fetch_foreign_gov(session, now, "e3g", "E3G", [
        "site:e3g.org climate when:30d",
        "site:e3g.org energy when:30d",
        "site:e3g.org emissions when:30d",
        "site:e3g.org carbon when:30d",
        "site:e3g.org finance when:30d",
        "site:e3g.org policy when:30d",
        "site:e3g.org transition when:30d",
        "site:e3g.org grid when:30d",
    ], limit=20)


def fetch_agora(session: requests.Session, now: datetime) -> list[RawItem]:
    """Agora Energiewende（柏林能源转型智库）— news-events 列表页解析（2026-08-17 接入）。

    德国能源转型权威智库，出报告/政策建议/声明，无 RSS（/feed 404），
    列表页 /news-events 含文章卡片（标题+链接+发布日期 "1 August 2026"）。
    归媒体库·国际（专家解读档）。
    """
    items: list[RawItem] = []
    try:
        r = session.get("https://www.agora-energiewende.org/news-events", timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        seen: set[tuple[str, str]] = set()
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            title = a.get_text(strip=True)
            if not title or len(title) < 12:
                continue
            if not href.startswith("/news-events/"):
                continue
            if href.startswith("/news-events/filter"):
                continue  # 导航过滤链接
            if (title, href) in seen:
                continue
            seen.add((title, href))
            if not href.startswith("http"):
                href = urljoin("https://www.agora-energiewende.org", href)
            published = None
            cont = a.find_parent(["article", "li", "div"])
            if cont is not None:
                m = re.search(r"(\d{1,2}\s+\w+\s+\d{4})", cont.get_text())
                if m:
                    for fmt in ("%d %B %Y", "%d %b %Y"):
                        try:
                            published = datetime.strptime(m.group(1), fmt).replace(tzinfo=UTC)
                            break
                        except Exception:
                            continue
            items.append(RawItem(
                site_id="agora", site_name="Agora·能源转型",
                title=title, url=href, published_at=published,
            ))
    except Exception:
        pass
    return items[:20]


def fetch_teri(session: requests.Session, now: datetime) -> list[RawItem]:
    """TERI 印度能源与资源研究所 — press-release 列表页解析（2026-08-17 接入）。

    印度最权威能源/环境智库，官网 /press-release 列表干净
    （标题+链接+日期 "10 Aug 2026"）。补印度非官方视角（官方源已有 PIB）。
    """
    items: list[RawItem] = []
    try:
        r = session.get("https://www.teriin.org/press-release", timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        seen: set[tuple[str, str]] = set()
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            title = a.get_text(strip=True)
            if not title or len(title) < 12:
                continue
            if not href.startswith("/press-release/"):
                continue
            if (title, href) in seen:
                continue
            seen.add((title, href))
            if not href.startswith("http"):
                href = urljoin("https://www.teriin.org", href)
            published = None
            cont = a.find_parent(["article", "li", "div"])
            if cont is not None:
                m = re.search(r"(\d{1,2}\s+\w+\w*\s+\d{4})", cont.get_text())
                if m:
                    for fmt in ("%d %B %Y", "%d %b %Y"):
                        try:
                            published = datetime.strptime(m.group(1), fmt).replace(tzinfo=UTC)
                            break
                        except Exception:
                            continue
            items.append(RawItem(
                site_id="teri", site_name="TERI·印度能源与资源所",
                title=title, url=href, published_at=published,
            ))
    except Exception:
        pass
    return items[:20]


# ── 国际智库/投行（2026-08-19 第四轮：Brookings/Bruegel/PIIE/CSIS/Chatham/Carnegie/RAND/CAP/高盛）──
# PITFALL(2026-08-19 实测): Google News 的括号 OR 语法（site:x (a OR b) when:7d）
# 返回该站全站混合内容（军事/政治/经济都混进来，绿色命中率 <10%），
# 而单主题词 query（site:x climate）返回 70-90% 绿色相关内容。
# → 全部改用单主题词 query，不用括号 OR、不带 when（Google News 默认按相关+时间排序）。

def fetch_brookings(session: requests.Session, now: datetime) -> list[RawItem]:
    """Brookings 布鲁金斯学会 — 气候与能源经济政策（2026-08-19 接入）。

    RSS /feed/ 是 HTML 壳 → Google News 搜 site（单主题词 query）。
    美国顶级智库，能源/气候经济政策浓度高。归媒体库（专家解读档 18 分）。
    """
    return fetch_foreign_gov(session, now, "brookings", "Brookings", [
        "site:brookings.edu climate when:30d",
        "site:brookings.edu energy when:30d",
    ])


def fetch_bruegel(session: requests.Session, now: datetime) -> list[RawItem]:
    """Bruegel 布鲁盖尔研究所 — 欧盟经济政策×绿色新政（2026-08-19 接入）。

    RSS /rss.xml 是会议日程流（Session/Lunch/Coffee break，无文章）→ 不可用，
    直接用 Google News 搜 site。欧洲最权威经济智库之一，CBAM/碳关税/绿色新政分析强。
    """
    return fetch_foreign_gov(session, now, "bruegel", "Bruegel", [
        "site:bruegel.org climate when:30d",
        "site:bruegel.org carbon when:30d",
    ], limit=20)


def fetch_piie(session: requests.Session, now: datetime) -> list[RawItem]:
    """PIIE 彼得森国际经济研究所 — 贸易×碳边境调节/CBAM（2026-08-19 接入）。

    RSS 404 → Google News 搜 site。国际经济政策权威，碳关税/贸易×气候分析强。
    """
    return fetch_foreign_gov(session, now, "piie", "PIIE", [
        "site:piie.com climate when:30d",
        "site:piie.com energy when:30d",
    ])


def fetch_csis(session: requests.Session, now: datetime) -> list[RawItem]:
    """CSIS 战略与国际研究中心 — 能源安全/气候地缘（2026-08-19 接入）。

    RSS /rss.xml 只有 2016 年 events 流（不可用）→ Google News 搜 site。
    能源安全/气候地缘/清洁技术政策，美国核心智库。
    """
    return fetch_foreign_gov(session, now, "csis", "CSIS", [
        "site:csis.org climate when:30d",
        "site:csis.org energy when:30d",
    ])


def fetch_chatham(session: requests.Session, now: datetime) -> list[RawItem]:
    """Chatham House 查塔姆研究所 — 气候治理/国际关系（2026-08-19 接入）。

    RSS 403（WAF）→ Google News 搜 site。英国皇家国际事务研究所，
    气候/能源地缘政治权威。归媒体库（专家解读档）。
    """
    return fetch_foreign_gov(session, now, "chatham", "Chatham House", [
        "site:chathamhouse.org climate when:30d",
        "site:chathamhouse.org energy when:30d",
    ])


def fetch_carnegie(session: requests.Session, now: datetime) -> list[RawItem]:
    """Carnegie 卡内基国际和平基金会 — 气候能源项目（2026-08-19 接入）。

    RSS 404 → Google News 搜 site。能源转型/核能/电池地缘研究（实测
    Geothermal and Nuclear Strategy、Battery Manufacturing Monopoly 等能源内容质量高）。
    """
    return fetch_foreign_gov(session, now, "carnegie", "Carnegie", [
        "site:carnegieendowment.org climate when:30d",
        "site:carnegieendowment.org energy when:30d",
    ])


def fetch_rand(session: requests.Session, now: datetime) -> list[RawItem]:
    """RAND 兰德公司 — 气候安全/能源/AI 政策研究（2026-08-19 接入）。

    RSS 404 → Google News 搜 site。综合政策智库（气候/能源/国防交叉），
    AI 内容多命中 AI 关键词自然归 AI 维度。
    """
    return fetch_foreign_gov(session, now, "rand", "RAND", [
        "site:rand.org climate when:30d",
        "site:rand.org energy when:30d",
    ])


def fetch_americanprogress(session: requests.Session, now: datetime) -> list[RawItem]:
    """Center for American Progress — 美国进步中心（2026-08-19 接入）。

    RSS /feed/ 是 HTML 壳 → Google News 搜 site。美国自由派智库，
    气候政策/环境治理（实测 Deep-Sea Mining Scheme 等环境议题报道多）。
    """
    return fetch_foreign_gov(session, now, "americanprogress", "CAP", [
        "site:americanprogress.org climate when:30d",
        "site:americanprogress.org energy when:30d",
    ])


def fetch_goldman(session: requests.Session, now: datetime) -> list[RawItem]:
    """高盛 — 投行研报（2026-08-19 接入）。

    官网 Greater China Insights 页 JS 渲染（HTML 空壳）；且 goldmansachs.com
    官方站 Google News 索引极差（site: 查询 ≤10 条且多为公司公告）→
    改用「"Goldman Sachs" + 主题词」搜索媒体转述的高盛研报观点（实测
    GS SUSTAIN/Adaptation/碳市场报告等绿色浓度 70%+）。补金融维度权威
    （版图券商研究 P0）。归媒体库（研报档 18）。
    """
    return fetch_foreign_gov(session, now, "goldman", "高盛", [
        '"Goldman Sachs" climate when:30d',
        '"Goldman Sachs" energy when:30d',
    ])


# ── 中国 P0 扩容（2026-08-19 第四轮：财新双碳/国家节能中心/澎湃） ──

def fetch_caixin(session: requests.Session, now: datetime) -> list[RawItem]:
    """财新网 — 双碳/绿色金融/能源（2026-08-19 接入）。

    双碳专栏博客是 JS SPA（HTML 空壳、无 RSS）→ Google News 搜 site:caixin.com
    中文绿色词（实测 21 条/7d：油气十五五规划/碳市场扩围/再生铜，质量高）。
    ⚠️ 英文 query 会被成人站污染（site:caixin.com 的 en query 返回垃圾）→ 只用 zh-CN。
    """
    return fetch_foreign_gov(session, now, "caixin", "财新", [
        "site:caixin.com 碳 when:7d",
        "site:caixin.com 双碳 when:7d",
        "site:caixin.com 碳中和 when:7d",
        "site:caixin.com 碳市场 when:7d",
        "site:caixin.com 绿色金融 when:7d",
        "site:caixin.com 能源 when:7d",
        "site:caixin.com 环保 when:7d",
        "site:caixin.com 排放 when:7d",
    ], locale="zh-CN")


def fetch_chinanecc(session: requests.Session, now: datetime) -> list[RawItem]:
    """国家节能中心 — 节能降碳官方解读（2026-08-19 接入）。

    发改委下属事业单位（公共服务网），首页直抓 /website/News!view.shtml?id= 列表，
    内容为节能降碳官方文件/专家解读/一图读懂（实测 8 条全是高价值政策解读）。
    归政策库·中国（官方机构档 22），GREEN_SITES 直通。
    """
    items: list[RawItem] = []
    try:
        r = session.get("http://www.chinanecc.cn/website/index.shtml", timeout=30)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        seen: set[tuple[str, str]] = set()
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            title = a.get_text(strip=True)
            if not title or len(title) < 12:
                continue
            if "/website/News!view.shtml?id=" not in href:
                continue
            if (title, href) in seen:
                continue
            seen.add((title, href))
            if not href.startswith("http"):
                href = urljoin("http://www.chinanecc.cn", href)
            items.append(RawItem(
                site_id="chinanecc", site_name="国家节能中心",
                title=title, url=href, published_at=None,
            ))
    except Exception:
        pass
    return items[:20]


def fetch_thepaper(session: requests.Session, now: datetime) -> list[RawItem]:
    """澎湃新闻 — 绿政/能源/AI 报道（2026-08-19 接入）。

    首页 JS 加载 → Google News 搜 site 中文绿色词（实测：上海港绿色甲醇/
    非洲贸易绿色化/绿色算力，质量高）。版图综合媒体 P1（绿政公署栏目）。
    """
    return fetch_foreign_gov(session, now, "thepaper", "澎湃新闻", [
        "site:thepaper.cn 绿色 when:7d",
        "site:thepaper.cn 低碳 when:7d",
        "site:thepaper.cn 双碳 when:7d",
        "site:thepaper.cn 碳市场 when:7d",
        "site:thepaper.cn 能源 when:7d",
        "site:thepaper.cn 环保 when:7d",
        "site:thepaper.cn 碳中和 when:7d",
        "site:thepaper.cn 储能 when:7d",
        "site:thepaper.cn 新能源 when:7d",
        "site:thepaper.cn 排放 when:7d",
    ], locale="zh-CN")


# ── AI 维度扩容（2026-08-19 第四轮：Artificial Analysis/36氪/虎嗅） ──

def fetch_artificialanalysis(session: requests.Session, now: datetime) -> list[RawItem]:
    """Artificial Analysis — AI 模型评测/API 市场（2026-08-19 接入）。

    SPA JS 渲染（HTML 空壳、无 RSS）→ Google News 搜 site。
    AI 模型 Intelligence/Performance/Price 评测（实测 GLM-5.3/Search Index 发布），
    AI 维度权威数据源。归 AI_SITES 直通。
    """
    return fetch_foreign_gov(session, now, "artificialanalysis", "Artificial Analysis", [
        "site:artificialanalysis.ai model when:14d",
        "site:artificialanalysis.ai AI when:14d",
        "site:artificialanalysis.ai benchmark when:14d",
        "site:artificialanalysis.ai intelligence when:14d",
        "site:artificialanalysis.ai performance when:14d",
        "site:artificialanalysis.ai price when:14d",
        "site:artificialanalysis.ai LLM when:14d",
        "site:artificialanalysis.ai GPT when:14d",
    ])


def fetch_36kr(session: requests.Session, now: datetime) -> list[RawItem]:
    """36氪 — AI/新能源/储能（2026-08-19 接入）。

    首页 JS → Google News 搜 site 中文词（实测：新能源渗透率首破60%/储能/双碳）。
    综合科技商业媒体：走 AI_MEDIA_SITES 过滤（命中绿色词或 AI 词才入库）。
    """
    return fetch_foreign_gov(session, now, "36kr", "36氪", [
        "site:36kr.com AI when:7d",
        "site:36kr.com 大模型 when:7d",
        "site:36kr.com 新能源 when:7d",
        "site:36kr.com 储能 when:7d",
        "site:36kr.com 碳中和 when:7d",
        "site:36kr.com 智能体 when:7d",
        "site:36kr.com 算力 when:7d",
        "site:36kr.com 芯片 when:7d",
        "site:36kr.com 绿色 when:7d",
        "site:36kr.com 碳 when:7d",
    ], locale="zh-CN")


def fetch_huxiu(session: requests.Session, now: datetime) -> list[RawItem]:
    """虎嗅 — AI/新能源（2026-08-19 接入）。

    首页 JS + RSS HTML 壳 → Google News 搜 site 中文词（实测：百度AI业务/
    AI焚书/甲骨文算力）。综合科技商业媒体：走 AI_MEDIA_SITES 过滤。
    """
    return fetch_foreign_gov(session, now, "huxiu", "虎嗅", [
        "site:huxiu.com AI when:7d",
        "site:huxiu.com 大模型 when:7d",
        "site:huxiu.com 新能源 when:7d",
        "site:huxiu.com 碳中和 when:7d",
        "site:huxiu.com 智能体 when:7d",
        "site:huxiu.com 算力 when:7d",
        "site:huxiu.com 芯片 when:7d",
        "site:huxiu.com 储能 when:7d",
        "site:huxiu.com 绿色 when:7d",
    ], locale="zh-CN")


# ── 中国 P0 第二批（2026-08-14：人行/环交所/NCSC/CAEP/环境报/CNESA） ──

def fetch_pbc(session: requests.Session, now: datetime) -> list[RawItem]:
    """中国人民银行 — 新闻发布 + 政策文件栏目（2026-08-14 接入）。

    用户指定两个栏目：
    - 新闻动态 = 新闻发布 /goutongjiaoliu/113456/113469/（公告/货币政策执行报告/金融统计）
    - 政策文件 = 条法司 /tiaofasi/144941/3581332/（公告/办法/通知）
    PITFALL: pbc.gov.cn 是 GBK 编码（apparent_encoding），链接是 14 位时间戳
    /20\d{8,}/（不是 8 位）；标题过滤绿色关键词（人行内容以货币政策为主，
    绿色金融相关才保留）。
    """
    items: list[RawItem] = []
    urls = [
        ("http://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html", "新闻发布"),
        ("http://www.pbc.gov.cn/tiaofasi/144941/3581332/index.html", "政策文件"),
    ]
    for u, col in urls:
        try:
            r = session.get(u, timeout=30)
            r.encoding = r.apparent_encoding or "utf-8"
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                txt = a.get_text(strip=True)
                if not txt or len(txt) < 12:
                    continue
                if not re.search(r"/20\d{8,}/", href):
                    continue
                if not href.startswith("http"):
                    href = urljoin("http://www.pbc.gov.cn", href)
                items.append(RawItem(
                    site_id="pbc", site_name="中国人民银行",
                    title=txt, url=href, published_at=None,
                    meta={"column": col},
                ))
        except Exception:
            continue
    # 去重
    seen: set[tuple[str, str]] = set()
    out: list[RawItem] = []
    for it in items:
        key = (it.title, it.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:30]


def fetch_cneeex(session: requests.Session, now: datetime) -> list[RawItem]:
    """上海环交所 — 全国碳市场行情、配额公告（2026-08-14 接入）。

    官网首页直抓：/c/YYYY-MM-DD/数字.shtml 日期路径，含政策转载+市场动态。
    PITFALL(2026-08-14): 新加坡服务器直连 www.cneeex.com 失败（curl 异常，
    疑似 IP 限制/SSL）→ 抓到 0 条时 fallback Google News 搜 site:cneeex.com。
    """
    items: list[RawItem] = []
    try:
        r = session.get("https://www.cneeex.com/", timeout=30)
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            txt = a.get_text(strip=True)
            if not txt or len(txt) < 12:
                continue
            if not re.search(r"/c/20\d{2}-\d{2}-\d{2}/", href):
                continue
            if not href.startswith("http"):
                href = urljoin("https://www.cneeex.com", href)
            items.append(RawItem(
                site_id="cneeex", site_name="上海环交所",
                title=txt, url=href, published_at=None,
            ))
    except Exception:
        pass
    if not items:
        # fallback: Google News（服务器直连被拦时）
        items = fetch_foreign_gov(session, now, "cneeex", "上海环交所", [
            "site:cneeex.com 碳市场 when:30d",
        "site:cneeex.com 碳价 when:30d",
        "site:cneeex.com 配额 when:30d",
        "site:cneeex.com 碳交易 when:30d",
            "site:cneeex.com 碳排放 when:30d",
        "site:cneeex.com 环交所 when:30d",
        "site:cneeex.com 碳金融 when:30d",
        ], limit=15, locale="zh-CN")
    return items[:20]


def fetch_ncsc(session: requests.Session, now: datetime) -> list[RawItem]:
    """国家应对气候变化战略研究和国际合作中心 NCSC — 气候战略/碳市场研究（2026-08-14 接入）。"""
    return fetch_foreign_gov(session, now, "ncsc", "NCSC国家气候中心", [
        "site:ncsc.org.cn 气候 when:30d",
        "site:ncsc.org.cn 碳市场 when:30d",
        "site:ncsc.org.cn 碳中和 when:30d",
        "site:ncsc.org.cn 碳达峰 when:30d",
        "site:ncsc.org.cn 温室气体 when:30d",
        "site:ncsc.org.cn 减排 when:30d",
        "site:ncsc.org.cn 政策 when:30d",
    ], limit=10, locale="zh-CN")


def fetch_caep(session: requests.Session, now: datetime) -> list[RawItem]:
    """生态环境部环境规划院 CAEP — 环境规划/双碳路径（2026-08-14 接入）。"""
    return fetch_foreign_gov(session, now, "caep", "环境规划院CAEP", [
        "site:caep.org.cn 环境 when:30d",
        "site:caep.org.cn 双碳 when:30d",
        "site:caep.org.cn 规划 when:30d",
        "site:caep.org.cn 美丽中国 when:30d",
        "site:caep.org.cn 碳 when:30d",
        "site:caep.org.cn 气候 when:30d",
        "site:caep.org.cn 减污降碳 when:30d",
    ], limit=10, locale="zh-CN")


def fetch_cenews(session: requests.Session, now: datetime) -> list[RawItem]:
    """中国环境报 — 生态环境部机关报（2026-08-14 接入，媒体库）。"""
    return fetch_foreign_gov(session, now, "cenews", "中国环境报", [
        "site:cenews.com.cn 生态 when:14d",
        "site:cenews.com.cn 环境 when:14d",
        "site:cenews.com.cn 双碳 when:14d",
        "site:cenews.com.cn 碳市场 when:14d",
        "site:cenews.com.cn 绿色 when:14d",
        "site:cenews.com.cn 污染防治 when:14d",
    ], limit=15, locale="zh-CN")


def fetch_cnesa(session: requests.Session, now: datetime) -> list[RawItem]:
    """中关村储能产业技术联盟 CNESA — 储能装机数据/白皮书（2026-08-14 接入，媒体库·数据）。

    官网 /information/detail/?column_id=58（产业数据）直抓，储能数据极权威
    （15.77GWh 并网、2h 储能价格等）。
    """
    items: list[RawItem] = []
    try:
        r = session.get("http://www.cnesa.org/", timeout=30)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            txt = a.get_text(strip=True)
            if not txt or len(txt) < 12:
                continue
            if "/information/detail/" not in href:
                continue
            if not href.startswith("http"):
                href = urljoin("http://www.cnesa.org", href)
            items.append(RawItem(
                site_id="cnesa", site_name="CNESA储能联盟",
                title=txt, url=href, published_at=None,
            ))
    except Exception:
        pass
    seen: set[tuple[str, str]] = set()
    out: list[RawItem] = []
    for it in items:
        key = (it.title, it.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out[:15]


# ── 人形机器人 / 绿色智能家居 / 绿色生活（2026-08-19 新增） ────────────────
def fetch_therobotreport(session: requests.Session, now: datetime) -> list[RawItem]:
    """The Robot Report — 国际机器人产业头部媒体（2026-08-19 新增）。

    人形机器人（Figure/Tesla Optimus/宇树等）/工业机器人/具身智能行业动态。
    GNews site: 搜索（服务器安全；RSS 直连存在但避免新加坡 IP 被 Cloudflare 拦）。
    归 ROBOT_SITES 白名单直通（is_policy_relevant 放行），categorize 按关键词：
    humanoid/robot 命中 AI_DIM_KW → AI 榜（人形机器人=具身智能），纯产业动态落行业。
    """
    return fetch_foreign_gov(session, now, "therobotreport", "The Robot Report", [
        "site:therobotreport.com humanoid when:7d",
        "site:therobotreport.com robot when:7d",
        "site:therobotreport.com robotics when:7d",
        "site:therobotreport.com humanoid robots when:7d",
        "site:therobotreport.com embodied AI when:7d",
        "site:therobotreport.com robotics funding when:7d",
    ], limit=20)


def fetch_spectrum_robotics(session: requests.Session, now: datetime) -> list[RawItem]:
    """IEEE Spectrum — 权威工程科技媒体（2026-08-19 新增，robotics 栏目）。

    RSS 直连 `https://spectrum.ieee.org/feeds/topic/robotics.rss`（robotics 栏目，
    实测 2026-08-18 有 10 条新鲜条目，含人形机器人/无人机/机器人回收再利用）；
    直连失败/空则 GNews site: 兜底。归 ROBOT_SITES 直通。
    """
    items = fetch_rss_feed(
        session, "https://spectrum.ieee.org/feeds/topic/robotics.rss",
        "spectrum", "IEEE Spectrum", now, limit=30,
    )
    if items:
        return items
    return fetch_foreign_gov(session, now, "spectrum", "IEEE Spectrum", [
        "site:spectrum.ieee.org robot when:7d",
        "site:spectrum.ieee.org robotics when:7d",
        "site:spectrum.ieee.org humanoid when:7d",
        "site:spectrum.ieee.org drone when:7d",
        "site:spectrum.ieee.org autonomous when:7d",
        "site:spectrum.ieee.org AI when:7d",
    ], limit=20)


def fetch_qianjia(session: requests.Session, now: datetime) -> list[RawItem]:
    """千家网 — 国内头部智能家居门户（2026-08-19 新增）。

    绿色智能家居/节能家电/智能家居行业。GNews zh locale。
    全站非绿色主题（智能家居商业新闻多）→ 走 is_policy_relevant 关键词过滤。
    """
    return fetch_foreign_gov(session, now, "qianjia", "千家网", [
        "site:qianjia.com 智能家居 when:7d",
        "site:qianjia.com 绿色 when:7d",
        "site:qianjia.com 节能 when:7d",
        "site:qianjia.com 以旧换新 when:7d",
        "site:qianjia.com 家电 when:7d",
    ], limit=15, locale="zh-CN")


def fetch_greenbuilder(session: requests.Session, now: datetime) -> list[RawItem]:
    """Green Builder Media — 美国绿色建筑/绿色家居专业媒体（2026-08-19 新增）。

    Whole Home Automation / 绿色建筑 / 电气化 / 能效。GNews en。
    全站绿色主题 → GREEN_SITES 直通（不走过滤）。
    """
    return fetch_foreign_gov(session, now, "greenbuilder", "Green Builder Media", [
        "site:greenbuildermedia.com green home when:7d",
        "site:greenbuildermedia.com smart home when:7d",
        "site:greenbuildermedia.com energy efficiency when:7d",
        "site:greenbuildermedia.com green building when:14d",
        "site:greenbuildermedia.com electrification when:14d",
        "site:greenbuildermedia.com resilient when:14d",
    ], limit=15)


def fetch_cheaa(session: requests.Session, now: datetime) -> list[RawItem]:
    """中国家电网 — 家电行业权威媒体（2026-08-19 新增）。

    绿色家电/以旧换新/能效标准（2026 国补"以旧换新"是绿色消费政策热点）。
    GNews zh；全站非绿色主题 → is_policy_relevant 过滤（含新增词"以旧换新"）。
    """
    return fetch_foreign_gov(session, now, "cheaa", "中国家电网", [
        "site:cheaa.com 家电 when:7d",
        "site:cheaa.com 节能 when:7d",
        "site:cheaa.com 以旧换新 when:7d",
        "site:cheaa.com 绿色 when:7d",
        "site:cheaa.com 能效 when:7d",
        "site:cheaa.com 智能家居 when:7d",
    ], limit=15, locale="zh-CN")


def fetch_greenpeace(session: requests.Session, now: datetime) -> list[RawItem]:
    """绿色和平（中文站）— 国际环保 NGO（2026-08-19 新增）。

    气候/能源转型/绿色消费/ESG 报告与倡议（绿电上车、就近消纳、钢企气候转型等）。
    GNews zh locale（site:greenpeace.org.cn）；月级更新 → 加 LOW_FREQ_SITES 宽窗口。
    全站环保主题 → GREEN_SITES 直通。
    """
    return fetch_foreign_gov(session, now, "greenpeace", "绿色和平", [
        "site:greenpeace.org.cn 气候 when:30d",
        "site:greenpeace.org.cn 能源 when:30d",
        "site:greenpeace.org.cn 环境 when:30d",
        "site:greenpeace.org.cn 绿色 when:30d",
        "site:greenpeace.org.cn 低碳 when:30d",
        "site:greenpeace.org.cn 转型 when:30d",
        "site:greenpeace.org.cn 报告 when:30d",
    ], limit=15, locale="zh-CN")


def fetch_mongabay(session: requests.Session, now: datetime) -> list[RawItem]:
    """Mongabay — 国际环境新闻专业媒体（2026-08-19 新增）。

    森林/生物多样性/气候/碳市场（全球知名环境新闻站，日更）。
    RSS 直连 news.mongabay.com/feed/；失败/空则 GNews site: 兜底。
    全站环境主题 → GREEN_SITES 直通。
    """
    items = fetch_rss_feed(
        session, "https://news.mongabay.com/feed/",
        "mongabay", "Mongabay", now, limit=30,
    )
    if items:
        return items
    return fetch_foreign_gov(session, now, "mongabay", "Mongabay", [
        "site:mongabay.com climate when:7d",
        "site:mongabay.com conservation when:7d",
        "site:mongabay.com deforestation when:7d",
        "site:mongabay.com green energy when:7d",
        "site:mongabay.com biodiversity when:7d",
        "site:mongabay.com wildlife when:7d",
    ], limit=20)


def fetch_nea(session: requests.Session, now: datetime) -> list[RawItem]:
    """国家能源局 — CMS JSON API."""
    items: list[RawItem] = []
    try:
        r = session.get(
            "https://www.nea.gov.cn/xwzx/ds_8839d76f7cb542ca8cbaab7122cc9b83.json",
            timeout=30,
            headers={"Referer": "https://www.nea.gov.cn/xwzx/nyyw.htm"},
        )
        r.raise_for_status()
        data = r.json()
        records = data.get("datasource", [])
        for rec in records[:50]:
            title = (rec.get("title") or rec.get("showTitle") or "").strip()
            publish_url = (rec.get("publishUrl") or "").strip()
            pub_time = (rec.get("publishTime") or "").strip()
            if not title or not publish_url:
                continue
            if not publish_url.startswith("http"):
                publish_url = urljoin("https://www.nea.gov.cn/xwzx/nyyw/", publish_url)
            published = None
            try:
                published = datetime.strptime(pub_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=SH_TZ)
            except Exception:
                pass
            items.append(RawItem(
                site_id="nea", site_name="国家能源局",
                source=rec.get("sourceText", "国家能源局"),
                title=title, url=publish_url,
                published_at=published,
            ))
    except Exception:
        pass
    return items


def fetch_miit(session: requests.Session, now: datetime) -> list[RawItem]:
    """工信部 — 节能与综合利用司.

    首页把同一文件挂在多个栏目（gzdt 工作动态 / wjfb 文件发布 / nyjy 能源节约 /
    zyjy 资源节约），标题相同 URL 不同 → 按标题去重，优先保留 gzdt（工作动态）。
    """
    items: list[RawItem] = []
    # 栏目优先级：gzdt(工作动态) 最权威，其次 wjfb(文件发布)，再其后按出现顺序
    section_prio = {"gzdt": 0, "wjfb": 1}
    by_title: dict[str, tuple[int, str, str]] = {}  # title -> (priority, href, pub_date)
    try:
        r = session.get("https://www.miit.gov.cn/jgsj/jns/", timeout=30)
        r.raise_for_status()
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            text = a.get_text(strip=True)
            if not text or not href or len(text) < 10:
                continue
            if not href.startswith("http"):
                href = urljoin("https://www.miit.gov.cn", href)
            # 栏目去重：同标题只留一篇，优先级 gzdt > wjfb > 其他
            prio = next((p for sec, p in section_prio.items() if f"/jns/{sec}/" in href), 2)
            li = a.find_parent("li")
            pub_date = _list_item_date(li) if li is not None else None
            prev = by_title.get(text)
            if prev is None or prio < prev[0]:
                by_title[text] = (prio, href, pub_date)
        for text, (_, href, pub_date) in by_title.items():
            items.append(RawItem(
                site_id="miit", site_name="工信部",
                title=text, url=href,
                published_at=parse_date_only(pub_date),
            ))
    except Exception:
        pass
    return items[:30]


def fetch_iea(session: requests.Session, now: datetime) -> list[RawItem]:
    """IEA — news page HTML scraping."""
    items: list[RawItem] = []
    try:
        r = session.get(
            "https://www.iea.org/news",
            timeout=30,
            headers={"Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"},
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        # IEA news page has article links with heading elements
        for article in soup.select("article a[href]"):
            href = (article.get("href") or "").strip()
            # find the heading inside
            heading = article.select_one("h4, h5, h6, [class*=heading], [class*=title]")
            text = heading.get_text(strip=True) if heading else article.get_text(strip=True)
            if not text or not href or len(text) < 15:
                continue
            if not href.startswith("http"):
                href = urljoin("https://www.iea.org", href)
            # Get date if available
            date_text = ""
            date_el = article.select_one("time, [class*=date], [datetime]")
            if date_el:
                date_text = date_el.get_text(strip=True)
            published = _parse_english_date(date_text) or _parse_english_date(
                article.get_text(" ", strip=True))
            items.append(RawItem(
                site_id="iea", site_name="IEA",
                title=text, url=href,
                published_at=published,
                meta={"date_text": date_text},
            ))
    except Exception:
        pass
    return items[:25]


def fetch_irena(session: requests.Session, now: datetime) -> list[RawItem]:
    """IRENA — news via Google News."""
    import feedparser as fp
    items: list[RawItem] = []
    try:
        r = session.get(
            "https://news.google.com/rss/search",
            params={"q": "IRENA renewable energy", "hl": "en-US", "gl": "US", "ceid": "US:en"},
            timeout=30,
        )
        r.raise_for_status()
        feed = fp.parse(r.content)
        for entry in feed.entries[:20]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            # Clean Google News redirect URLs
            if "news.google.com" in link:
                from urllib.parse import parse_qs, urlparse
                qs = parse_qs(urlparse(link).query)
                real_url = qs.get("url", [link])[0]
                link = real_url
            items.append(RawItem(
                site_id="irena", site_name="IRENA",
                title=title, url=link,
                published_at=_entry_published(entry),
            ))
    except Exception:
        pass
    return items


def fetch_carbonbrief(session: requests.Session, now: datetime) -> list[RawItem]:
    """Carbon Brief — climate & energy RSS."""
    return fetch_rss_feed(session,
        "https://www.carbonbrief.org/feed/",
        "carbonbrief", "Carbon Brief", now)


def fetch_reuters_energy(session: requests.Session, now: datetime) -> list[RawItem]:
    """Reuters — energy & climate news via Google News."""
    import feedparser as fp
    items: list[RawItem] = []
    try:
        r = session.get(
            "https://news.google.com/rss/search",
            params={"q": "reuters climate energy carbon policy", "hl": "en-US", "gl": "US", "ceid": "US:en"},
            timeout=30,
        )
        r.raise_for_status()
        feed = fp.parse(r.content)
        for entry in feed.entries[:20]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            # Only include Reuters articles (check title suffix)
            if not title.lower().endswith(" - reuters"):
                continue
            items.append(RawItem(
                site_id="reuters", site_name="Reuters",
                title=title, url=link,
                published_at=_entry_published(entry),
            ))
    except Exception:
        pass
    return items


def fetch_unfccc(session: requests.Session, now: datetime) -> list[RawItem]:
    """UNFCCC — news via Google News (direct site blocked by Incapsula)."""
    import feedparser as fp
    items: list[RawItem] = []
    try:
        r = session.get(
            "https://news.google.com/rss/search",
            params={"q": "UNFCCC climate COP", "hl": "en-US", "gl": "US", "ceid": "US:en"},
            timeout=30,
        )
        r.raise_for_status()
        feed = fp.parse(r.content)
        for entry in feed.entries[:20]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            items.append(RawItem(
                site_id="unfccc", site_name="UNFCCC",
                title=title, url=link,
                published_at=_entry_published(entry),
            ))
    except Exception:
        pass
    return items


def fetch_worldbank_climate(session: requests.Session, now: datetime) -> list[RawItem]:
    """World Bank — climate news via Google News.

    The worldbank.org topic pages are JS-rendered: static HTML link texts are
    the raw URLs themselves, so direct scraping yields garbage entries
    (e.g. https://www.worldbank.org/ext/en/home). Google News gives real
    headlines + publish time.
    """
    import feedparser as fp
    items: list[RawItem] = []
    try:
        r = session.get(
            "https://news.google.com/rss/search",
            params={"q": '"World Bank" climate change', "hl": "en-US", "gl": "US", "ceid": "US:en"},
            timeout=30,
        )
        r.raise_for_status()
        feed = fp.parse(r.content)
        for entry in feed.entries[:20]:
            title = (entry.get("title") or "").strip()
            link = (entry.get("link") or "").strip()
            if not title or not link:
                continue
            items.append(RawItem(
                site_id="worldbank", site_name="World Bank Climate",
                title=title, url=link,
                published_at=_entry_published(entry),
            ))
    except Exception:
        pass
    return items[:20]


def fetch_bjx(session: requests.Session, now: datetime) -> list[RawItem]:
    """北极星电力网 — via Google News (direct site blocked by Alibaba WAF).

    2026-08-23 修复：北极星本站 Google News 收录极少（30 天内仅 0-10 条且多为
    转载），单查询"北极星电力网 新能源…"返回 2025 旧文 → 改为多单主题词查询
    （AGENTS.md 铁律：单主题词 + when:30d，括号 OR 语法勿用），
    泛"北极星 储能"查询返回 8 月行业新闻（招标/装机/采购，有信息价值）。
    """
    import feedparser as fp
    items: list[RawItem] = []
    queries = [
        "北极星电力网 when:30d",
        "北极星 储能 when:30d",
    ]
    seen: set[tuple[str, str]] = set()
    for q in queries:
        try:
            r = session.get(
                "https://news.google.com/rss/search",
                params={"q": q, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"},
                timeout=30,
            )
            r.raise_for_status()
            feed = fp.parse(r.content)
            for entry in feed.entries[:15]:
                title = (entry.get("title") or "").strip()
                link = (entry.get("link") or "").strip()
                if not title or not link:
                    continue
                key = (title, link)
                if key in seen:
                    continue
                seen.add(key)
                items.append(RawItem(
                    site_id="bjx", site_name="北极星电力网",
                    title=title, url=link,
                    published_at=_entry_published(entry),
                ))
        except Exception:
            continue
    return items


# ── link filtering helpers ────────────────────────────────────────────────────
_JUNK_TEXT = (
    "注册", "登录", "协议", "条款", "关于", "联系我们", "备案", "版权",
    "下载", "APP", "VIP", "会员", "沪ICP", "隐私", "帮助", "常见问题",
    "手机版", "客户端", "订阅", "投稿", "广告", "合作", "招聘", "收藏本站",
    "设为首页", "返回顶部", "邮箱快捷", "短信快捷", "使用协议", "用户协议",
    "English", "简体", "繁體", "微博", "微信", "QQ群",
)
_JUNK_URL = (
    "/user/", "/login", "/register", "/about", "/aboutus", "/terms",
    "/privacy", "/protocol", "/copyright", "/disclaimer", "/faq", "/help",
    "/jobs", "/advert", "/contact", "/member", "/vip", "/profile",
    "/abouts", "/header_tab", "javascript:", "mailto:", "tel:", "#",
    "/xiey", "/hezuo", "/guanggao",
)


def _is_junk_link(text: str, href: str) -> bool:
    """True if a candidate link is nav/footer/auth junk, not content."""
    if not text or not href:
        return True
    t = text.strip()
    if len(t) < 6:
        return True
    for w in _JUNK_TEXT:
        if w in t:
            return True
    hl = href.lower()
    for u in _JUNK_URL:
        if u in hl:
            return True
    return False


def _allowed_path(href: str, patterns: tuple[str, ...]) -> bool:
    """True if href matches one of the content URL patterns."""
    return any(p in href for p in patterns)


def fetch_tanpaifang(session: requests.Session, now: datetime) -> list[RawItem]:
    """中国碳交易网 — 碳顾问 (tanguwen) channel only."""
    items: list[RawItem] = []
    try:
        from ftfy import fix_text
    except ImportError:
        fix_text = lambda x: x  # fallback
    try:
        r = session.get("http://www.tanpaifang.com/tanguwen/", timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            text = fix_text(a.get_text(strip=True))
            if _is_junk_link(text, href):
                continue
            # 碳顾问 channel: keep only its individual articles (URL has a
            # /tanguwen/ + /20xx/ date path and ends .html).
            if not (href.split("?")[0].endswith(".html")
                    and re.search(r"/20\d{2}/", href)
                    and "/tanguwen/" in href):
                continue
            if not href.startswith("http"):
                href = urljoin("http://www.tanpaifang.com", href)
            items.append(RawItem(
                site_id="tanpaifang", site_name="中国碳交易网",
                title=text, url=href,
                published_at=None,
            ))
    except Exception:
        pass
    return items[:30]


def fetch_tandao(session: requests.Session, now: datetime) -> list[RawItem]:
    """碳道 — carbon news aggregator."""
    items: list[RawItem] = []
    try:
        r = session.get("https://www.ideacarbon.org/", timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            text = a.get_text(strip=True)
            if _is_junk_link(text, href):
                continue
            if not _allowed_path(href, ("news_free", "newspc")):
                continue  # 碳道 news items live under /news_free/ or /newspc/
            if not href.startswith("http"):
                href = urljoin("https://www.ideacarbon.org", href)
            # 标题优先取列表卡片 .news-title 元素；a.get_text() 会把标题+摘要+
            # 作者+相对时间全拼在一起（2026-08-17 修复：标题重复污染）
            title_el = a.select_one(".news-title")
            if title_el:
                text = title_el.get_text(strip=True)
            items.append(RawItem(
                site_id="ideacarbon", site_name="碳道",
                title=text, url=href,
                published_at=None,
            ))
    except Exception:
        pass
    return items[:30]


def fetch_china_energy_news(session: requests.Session, now: datetime) -> list[RawItem]:
    """中国能源报."""
    items: list[RawItem] = []
    try:
        r = session.get("https://www.cnenergynews.cn/", timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            text = a.get_text(strip=True)
            if _is_junk_link(text, href):
                continue
            if not _allowed_path(href, ("/article/", "/topic/", "/energy/")):
                continue  # 能源报 news items live under /article/
            if not href.startswith("http"):
                href = urljoin("https://www.cnenergynews.cn", href)
            items.append(RawItem(
                site_id="chinaenergy", site_name="中国能源报",
                title=text, url=href,
                published_at=None,
            ))
    except Exception:
        pass
    return items[:30]


# ── allnet.hot 全网热点 ───────────────────────────────────────────────────────
ALLNET_API_BASE = "https://api.allnet.hot/api/open/v1"
# (board_id, board_name) — 主流综合热榜；最终入库内容由 is_policy_relevant 过滤
ALLNET_BOARDS = [
    (9, "微博热搜"),
    (13, "知乎热榜"),
    (140, "今日头条热榜"),
    (108, "澎湃热榜"),
    (139, "IT之家最新"),
]


def fetch_allnet(session: requests.Session, now: datetime) -> list[RawItem]:
    """全网热点 (api.allnet.hot) — 抓取主流热榜条目。

    需要 API Key：优先读环境变量 ALLNET_API_KEY，其次读项目根目录
    .env 文件（key=ALLNET_API_KEY）。未配置时静默跳过，不影响其他源。
    榜单无发布时间，published_at=None（回填为抓取时间）。入库内容由
    is_policy_relevant 关键词过滤，只保留绿色/低碳/气候相关政策相关条目。
    """
    items: list[RawItem] = []
    api_key = os.environ.get("ALLNET_API_KEY", "").strip()
    if not api_key:
        # 尝试从项目根目录 .env 读取
        env_path = Path(__file__).resolve().parent.parent / ".env"
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("ALLNET_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        except Exception:
            api_key = ""
    if not api_key:
        return items
    for board_id, board_name in ALLNET_BOARDS:
        try:
            r = session.get(
                f"{ALLNET_API_BASE}/sources/data",
                params={"id": board_id, "page": 1},
                headers={"X-API-Key": api_key},
                timeout=20,
            )
            r.raise_for_status()
            payload = r.json()
            entries = (payload.get("data") or {}).get("list") or []
            for entry in entries:
                title = (entry.get("title") or "").strip()
                url = (entry.get("jump_url") or "").strip()
                if not title:
                    continue
                items.append(RawItem(
                    site_id="allnet", site_name="全网热点",
                    source=board_name,
                    title=title, url=url,
                    published_at=None,
                    meta={"board": board_name},
                ))
        except Exception:
            continue
    return items[:60]


# ── X 平台（x.com）官方账号快讯（2026-08-19 接入，零成本方案）─────────────
# 原理：x.com 账号页对匿名请求返回 SSR HTML，内含 schema.org Microdata
# （itemType="https://schema.org/SocialMediaPosting"），requests 直抓即可解析
# 最近 5 条推文（推文 ID/全文/发布时间/互动数）。本地与新加坡服务器均实测
# HTTP 200（220KB 左右）。无需 API key、无登录墙、无付费。
# 账号清单：精选绿色低碳/能源/AI 领域的官方机构 + 权威 KOL（四维覆盖）。
# 入库内容由 is_policy_relevant 的 X_SITES 分支过滤（命中绿色词或 AI 词）。
X_ACCOUNTS: list[tuple[str, str]] = [
    # (handle, 中文名)
    # ── 官方机构（政策/国际组织/金融）──
    ("IEA", "IEA国际能源署"),
    ("IRENA", "IRENA国际可再生能源署"),
    ("UNFCCC", "UNFCCC联合国气候"),
    ("EU_ENV", "欧盟环境总司"),
    ("EPA", "美国环保署"),
    ("NGFS_", "央行绿色金融网络"),
    ("ember_energy", "Ember气候能源数据"),
    # ── 智库/媒体 ──
    ("CarbonBrief", "Carbon Brief"),
    ("BloombergNEF", "彭博新能源财经"),
    # ── KOL（人物维度：机构掌门人/气候专员/科学家）──
    ("fbirol", "IEA署长比罗尔"),
    ("WBHoekstra", "欧盟气候专员霍克斯特拉"),
    ("KHayhoe", "海伊霍·气候科学家"),
    # ── AI 维度 ──
    ("OpenAI", "OpenAI"),
]
X_PAGE_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_x_tweets(html: str, fallback_handle: str) -> list[dict]:
    """从 x.com 账号页 SSR HTML 解析推文列表（schema.org Microdata）。"""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html, "html.parser")
    posts = soup.find_all(attrs={"itemtype": "https://schema.org/SocialMediaPosting"})
    out: list[dict] = []
    for p in posts:
        def meta(prop: str) -> str:
            m = p.find(attrs={"itemprop": prop})
            if m and m.get("content"):
                return m["content"]
            return ""
        author_block = p.find(attrs={"itemprop": "author"})
        a_handle = ""
        if author_block:
            hm = author_block.find(attrs={"itemprop": "alternateName"})
            a_handle = hm.get("content", "") if hm else ""
        tid = meta("identifier")
        text = meta("text") or ""
        if not tid or not text:
            continue
        handle = a_handle or fallback_handle
        out.append({
            "id": tid,
            "handle": handle,
            "url": f"https://x.com/{handle}/status/{tid}",
            "published_at": meta("datePublished") or meta("dateCreated"),
            "text": text,
        })
    return out


def fetch_x(session: requests.Session, now: datetime) -> list[RawItem]:
    """X 平台官方账号快讯 — 抓取 X_ACCOUNTS 每个账号的最近 5 条推文。

    零成本方案：账号页 SSR 自带 schema.org Microdata，无需 API key/cookie。
    单账号失败静默跳过（不影响其他账号与其他源）。推文时间戳为 UTC ISO，
    置顶推文会混入 SSR 输出 → 按发布时间重排，旧置顶由窗口过滤自然滤掉。
    推文全文同时作为 title 与 meta.summary（前端摘要展开 + 打分参与）。
    """
    items: list[RawItem] = []
    for handle, name in X_ACCOUNTS:
        try:
            r = session.get(f"https://x.com/{handle}", timeout=20, headers=X_PAGE_HEADERS)
            r.raise_for_status()
            for t in parse_x_tweets(r.text, handle):
                text = html.unescape(re.sub(r"\s+", " ", t["text"]).strip())  # SSR content 属性里 &amp; 等实体不解码 — 2026-08-21
                if not text or not t["url"]:
                    continue
                published = parse_iso(t["published_at"]) if t["published_at"] else None
                items.append(RawItem(
                    site_id="x", site_name="X平台",
                    source=f"@{handle}",
                    title=text, url=t["url"],
                    published_at=published,
                    meta={"summary": text[:500]},
                ))
        except Exception:
            continue
    # SSR 输出顺序是「置顶+热门」非纯时间序 → 按发布时间倒序重排
    items.sort(key=lambda it: it.published_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    return items
def fetch_opml_rss(session: requests.Session, opml_path: str, now: datetime) -> list[RawItem]:
    """Read an OPML file and fetch all RSS feeds listed in it."""
    items: list[RawItem] = []
    if not opml_path or not os.path.exists(opml_path):
        return items

    from xml.etree import ElementTree as ET
    try:
        tree = ET.parse(opml_path)
        root = tree.getroot()
    except Exception:
        return items

    outlines = root.findall(".//outline")
    feed_urls: list[tuple[str, str]] = []
    for ol in outlines:
        xml_url = ol.get("xmlUrl") or ol.get("xml_url") or ""
        title = ol.get("title") or ol.get("text") or os.path.basename(xml_url)
        if xml_url and xml_url.startswith("http"):
            feed_urls.append((title, xml_url))

    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(fetch_rss_feed, session, url, "opml", title, now): (title, url)
                   for title, url in feed_urls}
        for f in as_completed(futures):
            try:
                items.extend(f.result())
            except Exception:
                pass
    return items


# ── Scoring system v2.0 (2026-08-14 四维定位重设计) ──────────────────────────
# 打分体系 v2.0：四维自适应，0-100 分。
# 与 v1.0 的关键差异：
#   v1.0 的"政策类型"只认政策文件（技术/AI/金融内容全卡行业动态 8 分，被压分）
#   v2.0 改为"内容强度"，按 政策/技术/金融/AI科技 各自的关键词档位计分
#   来源权威上限 30→25（防止政策源碾压，四维公平竞争）
# 权重：内容强度 30 + 来源权威 25 + 主题相关 25 + 人物 10 + 时效 10
# 等级: S(85+) / A(70+) / B(55+) / C(40+) / D(<40)

# 1) 内容强度分（按细类自适应，0-30）——每细类按关键词从高到低取第一档
#    结构: {sub_dimension: [(score, [keywords]), ...]}，末尾 () 为默认档
#    六细类（2026-08-23 三层重构）：政策法规/国际动态/企业经营/金融资本/技术研发/基础研究
CONTENT_STRENGTH_RULES: dict[str, list[tuple[int, list[str]]]] = {
    "政策法规": [
        (30, ["印发", "通知", "意见", "条例", "办法", "规划", "方案", "公告",
              "答记者问", "政策文件", "发布", "国务院", "管理办法", "新规"]),
        (25, ["解读", "一图读懂", "新闻发布会", "吹风会"]),
        (20, ["报告", "数据", "统计", "年报", "季报"]),
    ],
    "国际动态": [
        (30, ["协议", "峰会", "联合声明", "承诺", "达成", "签署", "宣言",
              "缔约方", "气候大会", "公报", "框架公约", "cop"]),
        (20, ["报告", "展望", "评估", "合作", "倡议", "声明"]),
    ],
    "企业经营": [
        (30, ["投产", "并网", "交付", "建成", "签约", "中标", "突破", "首次",
              "世界首个", "全球首个", "里程碑", "量产"]),
        (20, ["进展", "上线", "落地", "试点", "示范", "应用", "试验", "扩产",
              "产量", "订单", "营收", "合作", "建厂", "出口", "报告", "发布",
              "数据", "recycle", "yield", "output", "test", "upgrade"]),
    ],
    "金融资本": [
        (30, ["扩围", "大涨", "突破", "新高", "首次", "创纪录", "启动", "成交",
              "破", "亿元", "覆盖", "并购", "收购"]),
        (20, ["价格", "指数", "报告", "数据", "融资", "投资", "交易", "配额",
              "基金", "债券"]),
    ],
    "技术研发": [
        (30, ["突破", "首发", "首次", "世界首个", "全球首个", "里程碑", "发布",
              "上线", "部署", "启用", "大模型", "智能体", "攻克",
              # AI 治理/安全信号（2026-08-19）：AI 与政治/民主/国家安全的顶层交叉
              # —— 保留在技术研发 30 分档（AI 源直通技术研发）
              "治理", "监管", "问责", "合规", "立法", "管控",
              "国家安全", "网络安全", "民主监督",
              "governance", "oversight", "regulation", "regulatory",
              "accountability", "national security", "cybersecurity",
              "democratic", "safety", "cyber"]),
        (20, ["研发", "进展", "测试", "验证", "升级", "优化", "效率", "专利",
              "样机", "中试", "工艺", "材料", "方法", "评估", "预测",
              "adaptation", "response", "pathway", "framework", "system",
              "tool", "dataset", "workshop", "grant"]),
    ],
    "基础研究": [
        (30, ["突破性进展", "新模型", "新方法", "发表", "首次", "世界首个",
              "里程碑", "发现"]),
        (20, ["研究", "论文", "算法", "理论", "模型", "方法学", "实验",
              "benchmark", "数据集", "机理", "机制", "paper", "research",
              "study"]),
    ],
    "社会创新": [  # v5.0 新增（2026-08-26）：制度/机制/模式/消费/行为等创新
        (30, ["机制创新", "制度创新", "模式创新"]),
        (20, ["绿色消费", "低碳消费", "绿色生活", "低碳生活", "公众参与",
              "行为改变", "垃圾分类", "无废城市", "循环消费", "新业态"]),
    ],
}
# 内容强度兜底默认分（2026-08-26 老温裁决：按文档原设计分细类）
# 政策法规/国际动态/企业经营=10（政策/产业基础分量，无关键词也不低于产业普通动态），
# 金融资本/技术研发/基础研究/社会创新=8
DEFAULT_STRENGTH_BY_SUB: dict[str, int] = {
    "政策法规": 10, "国际动态": 10, "企业经营": 10,
    "金融资本": 8, "技术研发": 8, "基础研究": 8, "社会创新": 8,
}
DEFAULT_STRENGTH = 8  # 未知细类兜底


def score_content_strength(sub_dimension: str, title: str, summary: str) -> int:
    """内容强度分：按细类（七细类）关键词档位，从高到低取第一命中档。"""
    text = f"{title or ''} {summary or ''}".lower()
    rules = CONTENT_STRENGTH_RULES.get(sub_dimension, CONTENT_STRENGTH_RULES["企业经营"])
    for score, kws in rules:
        if any(kw.lower() in text for kw in kws):
            return score
    return DEFAULT_STRENGTH_BY_SUB.get(sub_dimension, DEFAULT_STRENGTH)


# 2) 来源权威分（site_id → 0-20，v4.0 从 25 分制压缩：匀 5 分给 TRL 第 6 维度）
SOURCE_SCORE: dict[str, int] = {
    # 部委官方（20 分）
    "ndrc": 20, "mee": 20, "nea": 20, "miit": 20,
    # 国外主要国家政策源（2026-08-14 新增：官方部委档）
    "us_epa": 20, "us_doe": 20, "eu_commission": 20,
    "euractiv": 16, "india_pib": 20,
    # 美国/日本扩展官方源（2026-08-14 第二轮：部委/联邦机构档）
    "us_noaa": 20, "us_eia": 20, "us_ferc": 20, "us_carb": 20,
    "jp_moe": 20, "jp_meti": 20, "jp_anre": 20,
    # 国际智库（2026-08-17 第三轮：专业媒体档）
    "e3g": 14, "agora": 14, "teri": 14,
    # 国际智库/投行（2026-08-19 第四轮：智库/投行研报同级 14）
    "brookings": 14, "bruegel": 14, "piie": 14, "csis": 14, "chatham": 14,
    "carnegie": 14, "rand": 14, "americanprogress": 14, "goldman": 14,
    # 中国 P0 扩容（2026-08-19 第四轮）
    "caixin": 14,      # 财新（专业财经媒体档）
    "chinanecc": 17,   # 国家节能中心（官方机构档，略低于部委 20）
    "thepaper": 12,    # 澎湃新闻（绿色科技媒体档）
    # AI 维度扩容（2026-08-19 第四轮）
    "artificialanalysis": 12,  # AI 模型评测（绿色科技媒体档）
    "36kr": 10, "huxiu": 10,   # 综合科技商业媒体（行业媒体档）
    # 中国 P0 第二批（2026-08-14：官方机构档）
    "pbc": 20, "cneeex": 20, "ncsc": 20, "caep": 20,
    "cenews": 12, "cnesa": 12,
    # 官方解读（部委网站发布的专家解读）
    "mee_jiedu": 18,
    # 国际组织
    "iea": 17, "irena": 17, "unfccc": 17, "worldbank": 17,
    # 专业政策/碳媒体 + AI×气候专业
    "tanpaifang": 14, "ideacarbon": 14, "carbonbrief": 14, "ccai": 14,
    # 经济管理学刊（2026-08-24 接入：北大光华+机械工业信息研究院学术期刊，专业媒体档）
    "qjem": 14,
    # 绿色科技媒体
    "stdaily": 12, "cleantechnica": 12,
    # AI 领域全链条源（2026-08-14 扩充）
    "jiqizhixin": 14, "qbitai": 14, "openai": 16,
    "venturebeat": 12, "arxiv_ai": 14, "aihot": 14,
    # 技术聚合（GitHub 开源项目趋势：无编辑自动榜单，略低于行业媒体）
    "radarai": 9,
    # 行业媒体
    "chinaenergy": 10, "bjx": 10, "reuters": 10,
    # 人形机器人/智能家居/绿色生活（2026-08-19 新增）
    "therobotreport": 12, "spectrum": 12,   # 机器人/科技权威媒体（绿色科技媒体档）
    "qianjia": 10, "cheaa": 10,             # 智能家居/家电行业媒体（行业媒体档）
    "greenbuilder": 12,                     # 绿色建筑家居专业媒体
    "greenpeace": 14, "mongabay": 14,       # 环保 NGO / 环境新闻专业媒体
    # 全网热榜
    "allnet": 6,
    # X 平台快讯（2026-08-19：官方机构账号权威但推文是快讯短文本 → 绿色科技媒体档）
    "x": 12,
}
DEFAULT_SOURCE_SCORE = 8

# 3) 主题相关分：标题+摘要命中关键词，分级取最高档
CORE_TOPIC_KW = [  # 核心议题（25 分）
    "碳市场", "碳交易", "CCER", "CBAM", "碳关税", "碳价", "碳排放权",
    "双碳", "碳中和", "碳达峰", "碳足迹", "碳普惠", "碳配额",
    "carbon market", "carbon price", "carbon border", "emissions trading",
    "net zero", "net-zero", "ETS",
]
IMPORTANT_TOPIC_KW = [  # 重要议题（18 分）
    "新能源", "储能", "氢能", "光伏", "风电", "新型电力系统", "电力市场",
    "绿电", "零碳", "CCUS", "碳捕集", "绿色金融", "ESG", "循环经济",
    "电动车", "电动汽车", "renewable", "solar", "wind", "hydrogen",
    "battery", "energy storage", "electric vehicle",
    # AI/科技（2026-08-14 主题升级）
    "人工智能", "大模型", "智能电网", "数字孪生", "能碳", "AI",
    "碳监测", "artificial intelligence", "machine learning", "smart grid",
]
GENERAL_TOPIC_KW = [  # 一般议题（12 分）
    "节能", "环保", "气候", "绿色", "低碳", "减排", "污染防治",
    "生态环境", "能源转型", "电力", "煤炭", "天然气", "成品油",
    "climate", "green", "emission", "decarbon", "sustainable",
    "environment", "energy transition", "coal",
]


def score_topic(title: str, summary: str = "") -> int:
    """主题相关分：命中最高档关键词即得该档分。"""
    text = f"{title or ''} {summary or ''}".lower()
    for kw in CORE_TOPIC_KW:
        if kw.lower() in text:
            return 25
    for kw in IMPORTANT_TOPIC_KW:
        if kw.lower() in text:
            return 18
    for kw in GENERAL_TOPIC_KW:
        if kw.lower() in text:
            return 12
    return 6


# 4) 人物分（PERSON_RULES 职务级别 → 0-10，取最高分人物）
def score_people(people: list[str]) -> int:
    """人物分：部长/主任级 10，副主任级 7，专家 5，分析师 3。"""
    if not people:
        return 0
    best = 0
    for name in people:
        role = person_role(name)
        if any(k in role for k in ["部长", "主任", "党组书记", "局长"]):
            best = max(best, 10)
        elif any(k in role for k in ["副主任", "副部长", "副局长"]):
            best = max(best, 7)
        elif any(k in role for k in ["院长", "教授", "理事长", "所长"]):
            best = max(best, 5)
        elif any(k in role for k in ["分析师", "首席"]):
            best = max(best, 3)
    return best


def score_freshness(published_at: str, now: datetime) -> int:
    """时效分：24h 内 10，48h 8，72h 6，96h 4，更久 2。无时间 0。"""
    dt = parse_iso(published_at)
    if not dt:
        return 0
    hours = (now - dt).total_seconds() / 3600
    if hours < 0:
        return 10  # 未来时间按最新算
    if hours < 24:
        return 10
    if hours < 48:
        return 8
    if hours < 72:
        return 6
    if hours < 96:
        return 4
    return 2


def score_item(site_id: str, title: str, summary: str, people: list[str],
               published_at: str, now: datetime, sub_dimension: str = "企业经营",
               trl: str = "") -> dict[str, Any]:
    """六维打分（v4.0）→ {'score': 0-100, 'score_level': S/A/B/C/D, 'strength': int, ...}

    内容强度按细类（六细类）自适应 + TRL 技术成熟度（第 6 维度，v4.0 新增）。
    """
    src = SOURCE_SCORE.get(site_id, DEFAULT_SOURCE_SCORE)
    tscore = score_content_strength(sub_dimension, title, summary)
    top = score_topic(title, summary)
    pscore = score_people(people)
    fscore = score_freshness(published_at, now)
    trl_score = score_trl(trl)
    total = min(100, src + tscore + top + pscore + fscore + trl_score)
    if total >= 85:
        level = "S"
    elif total >= 70:
        level = "A"
    elif total >= 55:
        level = "B"
    elif total >= 40:
        level = "C"
    else:
        level = "D"
    return {
        "score": total,
        "score_level": level,
        "score_breakdown": {
            "source": src, "strength": tscore, "topic": top,
            "people": pscore, "freshness": fscore, "trl": trl_score,
        },
    }


# ── 四维分类（2026-08-19 主体化：政府/行业/金融/AI） ─────────────────────────
# 优先级：AI_SITES直通 > 政府强词 > 政策库 > 双碳核心词 > AI词 > 金融词 > 行业词 > 政策弱词 > 行业兜底
# 决策点 A1（2026-08-19 双碳优先）：命中双碳核心词（碳中和/碳达峰/双碳/碳排放/净零等）
# → 优先归「行业」，只有纯 AI 信号（大模型/智能体/OpenAI 等无双碳词）才归 AI。
# 例：腾讯《碳中和中期报告 AI时代如何稳住碳排放》→ 行业（主体是双碳报告，AI 是背景词）。
# 纯 AI 源（机器之心/量子位/OpenAI 等）仍直通 AI，不受双碳优先影响。
# PITFALL: AI 判定只用标题（摘要常含反爬水印 "t a np ai fan g.com" 的 "ai "，
# 2026-08-14 实测误判"走进零碳园区"为 AI科技）且用词边界正则。
AI_DIM_KW = [
    "人工智能", "大模型", "机器学习", "智能电网", "数字孪生", "碳监测",
    "能碳", "智算", "算法", "机器人", "具身智能", "无人机", "卫星", "自动驾驶",
    "artificial intelligence", "machine learning", "smart grid",
    "robot", "humanoid", "autonomous", "drone", "satellite",
    # AI 领域全链条（2026-08-14 扩充：理论/模型/市场/商业）
    "大语言模型", "多模态", "生成式", "深度学习", "神经网络", "transformer",
    "llm", "gpt", "claude", "gemini", "deepseek", "qwen", "llama",
    "agent", "智能体", "推理", "训练", "算力", "芯片", "gpu", "英伟达",
    "openai", "anthropic", "google deepmind", "meta ai", "hugging face",
    "ai芯片", "ai应用", "ai模型", "模型发布", "ai创业", "ai融资",
    "机器学习模型", "计算机视觉", "自然语言处理", "强化学习", "aigc",
    "大模型创业", "模型即服务", "ai agent", "mcp", "语义", "transformer架构",
    # 2026-08-19：数据中心（X 源接入后实测——IEA 的 AI 数据中心能源推文
    # 「AI boom driving infrastructure expansion」因无 AI 字样被滤掉；
    # 数据中心=AI 算力基础设施，含此词归 AI 维度）
    "data centre", "data center", "数据中心",
    # 2026-08-17：GitHub 趋势类 AI 项目（stable-diffusion-webui 等仓库名不含 AI 关键词，
    # 但摘要必含 diffusion；radarai 摘要参与 AI 判定，故补此词）
    "diffusion",
]
# 标题级英文 AI：负向环视版词边界——ASCII 字母外的任意字符（中文/连字符/空格等）都算边界。
# 比 \bai\b 更能命中中文上下文（Python \b 把汉字当 \w，"AI对气候…" 用 \bai\b 会漏判，
# 实测漏判掉进技术榜），同时仍排除 "tail"/"said"/"again"/"Aira"/"taiyangnews" 等单词内 ai。
AI_TITLE_RE = r"(?<![a-z])ai(?![a-z])"
# 双碳核心词（2026-08-19 决策点 A1）：命中即优先归「行业」——双碳/碳中和内容是行业主体
# 议题，即使标题含 AI 背景词（如"AI时代如何稳住碳排放"）也不改判 AI。
# 注意：碳市场/碳价/碳配额等留在 FINANCE_DIM_KW（金融信号），不在此表。
DUAL_CARBON_KW = [
    "碳中和", "碳达峰", "双碳", "碳排放", "碳减排", "净零", "降碳",
    "碳足迹", "碳普惠", "碳中和管理", "零碳", "气候中和",
    "net zero", "net-zero", "carbon neutral", "carbon neutrality",
    "decarboni", "emission reduction", "climate action", "climate policy",
    "energy transition", "netzero",
]
# 政府行为强词（2026-08-19）：官方文件/发布/解读动作 + 部委名，**仅用标题判定**
# （摘要常含"目标/方案/实施"等泛词，用 text 会误抢行业/金融内容）
# 从原 POLICY_DIM_KW 拆出（原表混有双碳主题词，会误抢行业内容）。
GOV_STRONG_KW = [
    "印发", "通知", "意见", "条例", "规划", "方案",
    "发布会", "答记者问", "解读", "一图读懂", "政策", "国务院",
    "十五五", "法规", "实施", "行动方案", "指导意见",
    "政策文件", "政策解读", "标准", "规范", "部委",
    # 部委名（2026-08-19 补：发改委/能源局等是明确政府主体信号）
    "发改委", "发展改革委", "能源局", "生态环境部", "工信部", "生态环境",
    "住建部", "财政部", "商务部", "交通运输部", "水利部",
    "农业农村部", "人民银行", "央行", "国资委", "科技部",
    # 中文监管/问责词（2026-08-23 三层重构：AI 监管政策归政策法规）
    "监管", "问责", "合规", "管理办法", "新规",
    # English（2026-08-17 补充：国际智库 E3G/Agora/TERI 标题识别）
    "policy", "policies", "regulation", "regulatory", "legislation", "reform",
    "roadmap", "framework", "agreement", "government", "minister", "parliament",
    "mandate", "consultation", "strategy", "commitment", "target", "goal",
    "official", "ministry", "department", "commission", "agency",
]
# 国际动态词（2026-08-23 新增）：国际组织/国家间动态 → 政策·国际动态
INTERNATIONAL_KW = [
    "cop", "unfccc", "iea", "irena", "欧盟", "wto", "g20",
    "巴黎协定", "paris agreement", "国家间", "双边", "多边", "协议",
    "峰会", "联合声明", "气候大会", "缔约方", "联合国",
    "世界银行", "world bank", "国际能源署", "国际可再生能源",
]
# 金融词（原 FINANCE_DIM_KW 改名 + 补充并购/投融资）→ 产业·金融资本
FINANCE_KW = [
    "碳市场", "碳交易", "碳价", "碳配额", "碳关税", "CBAM", "CCER",
    "ESG", "绿色金融", "碳金融", "债券", "融资", "投资", "基金", "期货",
    "收购", "并购", "IPO", "股价", "碳资产", "绿色债券", "成交",
    "投融资", "私募", "股权投资", "风险投资",
    # v5.0（2026-08-26 老温决策）：绿色金融产品 → 产业·金融资本——
    # "碳减排挂钩贷款/绿色贷款"等产品类词（防 A1 双碳词抢先归企业经营）
    "贷款", "绿色贷款",
    "carbon market", "carbon price", "carbon trading", "ETS",
    "green bond", "finance", "investment", "fund",
]
# 技术研发词（2026-08-23 新增，从原 INDUSTRY_DIM_KW 拆分技术突破/研发强动作词）。
# 只放"强技术动作词"（突破/研发/首次等），不放泛"技术"词——避免误抢企业经营。
TECH_DEV_KW = [
    "突破", "研发", "首次", "世界首个", "全球首个", "里程碑", "专利",
    "攻克", "样机", "中试", "创新", "材料", "工艺", "装备",
    "光热", "绿氢", "甲醇", "甲烷", "负排放", "DAC", "BECCS", "生物炭",
    "CCUS", "碳捕集",
    "carbon capture", "technology",
]
# 企业经营词（2026-08-23 新增，从原 INDUSTRY_DIM_KW 拆分企业/项目/产能动作词 + 领域词）。
# 领域词（储能/氢能/光伏/风电/电池等）本身是"绿色产业"主体，默认归企业经营。
ENTERPRISE_KW = [
    "储能", "氢能", "光伏", "风电", "电池", "核能", "生物质",
    "装机", "投产", "并网", "产能", "产量", "出口", "工厂", "公司",
    "集团", "项目", "电站", "电网", "充电桩", "电动车", "新能源汽车",
    "订单", "营收", "合作", "建厂", "扩产", "量产", "供应", "中标", "签约",
    # v5.0（2026-08-26 老温决策）：碳普惠/碳账户已落地应用 → 产业·企业经营
    # （政府发文的管理办法/方案仍由 GOV_STRONG_KW 优先归政策·政策法规）
    "碳普惠", "碳账户",
    "solar", "wind", "battery", "hydrogen", "storage",
    "renewable", "nuclear", "factory", "plant",
    "gigafactory", "ev", "electric vehicle",
]
# 基础研究词（2026-08-23 新增）→ 创新·基础研究
# v5.0（2026-08-26）：补中文「研究」——AI 研究报告（斯坦福 AI 指数等）归基础研究；
# 「报告」不加（AI 公司年度经营报告会误判基础研究，且产品化词「发布」可正确兜住）
BASIC_RESEARCH_KW = [
    "论文", "理论", "方法学", "机理", "机制", "原理", "benchmark",
    "arxiv", "学术", "发表", "科研", "实验室", "数据集", "dataset",
    "paper", "research", "study", "研究",
]
# 基础研究窄词（v5.0 新增，2026-08-26）：普通路径（非 AI 源）的学术载体判定。
# 比 BASIC_RESEARCH_KW 更窄——不含「研究/发表/机制」等泛词（研究院/发表声明/市场机制
# 会误判）；AI 内容走 AI 分流（宽词含「研究」覆盖 AI 研究报告），非 AI 学术内容走本表
BASIC_RESEARCH_KW_NARROW = [
    "论文", "学术", "arxiv", "科研", "实验室", "数据集", "benchmark",
    "paper", "机理", "方法学", "原理",
]
# AI 产品化词（v5.0 新增，2026-08-26）：AI 命中后按技术阶段分流——
# 先查 BASIC_RESEARCH_KW（发布论文/研究报告 → 基础研究）再查本表（→ 产业·企业经营）
AI_PRODUCT_KW = [
    "发布", "推出", "上线", "商用", "商业化", "产品", "API", "订阅",
    "定价", "部署", "开放平台", "应用商店", "正式版",
    "launch", "release", "product", "deploy", "commercial",
    "subscription", "pricing",
]
# 社会创新词（v5.0 新增，2026-08-26）→ 创新·社会创新：制度/机制/模式/消费/行为等
# 尚未产业化的创新。注意：不放「社区/共享/试点/机制」等泛词（误抢产业落地）；
# 碳普惠/碳账户按老温决策归产业（DUAL_CARBON 的碳普惠 + ENTERPRISE_KW 的碳账户/碳普惠）
SOCIAL_INNOVATION_KW = [
    "社会创新", "制度创新", "机制创新", "创新机制", "模式创新", "商业模式",
    "绿色消费", "低碳消费", "绿色生活", "低碳生活", "公众参与",
    "行为改变", "生活方式", "垃圾分类", "无废城市", "循环消费", "新业态",
]
# 政策弱词（2026-08-19）：兜底前的政府信号（GOV_STRONG_KW 之外的剩余原政策词）
POLICY_WEAK_KW = [
    "目标", "承诺", "路线图", "白皮书", "纲要", "立法", "修正案",
    "target", "pledge", "white paper", "outline", "amendment",
]


def _ai_stage_sub(text: str) -> tuple[str, str]:
    """AI 按技术阶段分流（v5.0，2026-08-26）：AI 源直通 / AI 词命中后共用。

    三段式：基础研究词（论文/研究/报告/arxiv…）→ 创新·基础研究；
    产品化词（发布/推出/上线/API/部署…）→ 产业·企业经营；
    其余（突破/研发/样机/智能体开发…）→ 创新·技术研发。
    顺序保证「发布论文/发布研究报告」先命中基础研究词，不被误判产品化。
    """
    if any(kw.lower() in text for kw in BASIC_RESEARCH_KW):
        return "创新", "基础研究"
    if any(kw.lower() in text for kw in AI_PRODUCT_KW):
        return "产业", "企业经营"
    return "创新", "技术研发"


def categorize_dimension(site_id: str, title: str, summary: str, library: str) -> tuple[str, str]:
    """三层分类 + 七细类（2026-08-26 v5.0）：政策/创新/产业（中性命名）。

    返回 (dimension, sub_dimension)：
      政策 = 政策法规（政府发文）/ 国际动态（国际组织/国家间）
      创新 = 技术研发（技术突破/应用开发）/ 基础研究（论文/理论/研究报告）/
             社会创新（制度/机制/模式/消费/行为，v5.0 新增）
      产业 = 企业经营（企业进展/AI 产品化/碳普惠碳账户落地/兜底）/
             金融资本（碳市场/绿色金融产品/并购）
    优先级：DIM_SITE_OVERRIDE > AI_SITES 分流 > TECH_SITES(创新·技术研发)
    > 政府强词(政策·政策法规) > 国际动态词(政策·国际动态) > 金融词(产业·金融资本)
    > 双碳核心词 A1(产业·企业经营) > 社会创新词(创新·社会创新)
    > AI 词分流 > 基础研究窄词(创新·基础研究) > 技术研发词(创新·技术研发)
    > 企业经营词(产业·企业经营) > 政策库默认(政策·政策法规)
    > 政策弱词(政策·政策法规) > 兜底(产业·企业经营)。
    """
    import re as _dim_re
    title_l = (title or "").lower()
    text = f"{title or ''} {summary or ''}".lower()
    # 站点级维度强制（机制保留，2026-08-17 起无强制项）
    if site_id in DIM_SITE_OVERRIDE:
        dim, sub = DIM_SITE_OVERRIDE[site_id]
        return dim, sub
    # AI 源（AIHOT/机器之心等标题未必含 AI 关键词）→ 按技术阶段分流（v5.0）
    if site_id in AI_SITES:
        return _ai_stage_sub(text)
    # GitHub 开源趋势（TECH_SITES/radarai）：仓库名常不含 AI 关键词，摘要可参与
    # AI 判定；开源项目属研发阶段 → 创新·技术研发（v5.0 保持）
    if site_id in TECH_SITES:
        return "创新", "技术研发"
    # 政府强词（仅标题：印发/通知/部委名/政策/监管…）→ 政策·政策法规
    if any(kw.lower() in title_l for kw in GOV_STRONG_KW):
        return "政策", "政策法规"
    # 国际动态词（国际组织/国家间：COP/IEA/欧盟/峰会…）→ 政策·国际动态
    if any(kw.lower() in text for kw in INTERNATIONAL_KW):
        return "政策", "国际动态"
    # 金融词（碳市场/碳交易/碳价/ESG/并购…）→ 产业·金融资本——先于双碳判定：
    # "碳排放权交易/碳市场"是金融信号而非企业经营（防"碳排放"误抢金融）
    for kw in FINANCE_KW:
        if kw.lower() in text:
            return "产业", "金融资本"
    # 决策点 A1 双碳优先：双碳核心词 → 产业·企业经营（即使标题含 AI 背景词）
    # v5.0：碳普惠在此命中（老温 2026-08-26 决策：已落地应用 → 产业层）
    if any(kw.lower() in text for kw in DUAL_CARBON_KW):
        return "产业", "企业经营"
    # 社会创新词（v5.0 新增：制度/机制/模式/绿色消费/公众参与…）→ 创新·社会创新
    for kw in SOCIAL_INNOVATION_KW:
        if kw.lower() in text:
            return "创新", "社会创新"
    # AI 词（标题级，词边界）→ 按技术阶段分流（v5.0）
    if any(kw.lower() in title_l for kw in AI_DIM_KW) or _dim_re.search(AI_TITLE_RE, title_l):
        return _ai_stage_sub(text)
    # 基础研究窄词（v5.0 新增：非 AI 源的学术载体——论文/学术/arxiv/机理…）
    # → 创新·基础研究（先于技术研发词：Nature 论文、学术成果按载体归基础研究）
    for kw in BASIC_RESEARCH_KW_NARROW:
        if kw.lower() in text:
            return "创新", "基础研究"
    # 技术研发词（突破/研发/首次/专利…）→ 创新·技术研发（先于企业经营判定）
    for kw in TECH_DEV_KW:
        if kw.lower() in text:
            return "创新", "技术研发"
    # 企业经营词（投产/公司/储能/光伏…，含 v5.0 碳普惠/碳账户落地）→ 产业·企业经营
    for kw in ENTERPRISE_KW:
        if kw.lower() in text:
            return "产业", "企业经营"
    # 政策库（官方原文）默认政策——官方文件即使含双碳词也不改判产业
    if library == "policy":
        return "政策", "政策法规"
    for kw in POLICY_WEAK_KW:
        if kw.lower() in text:
            return "政策", "政策法规"
    return "产业", "企业经营"  # 兜底：媒体库行业动态归产业·企业经营


# ── 维度二：国际标准分类法（Domain Taxonomy，2026-08-23 新增） ──────────────
# 不自造词典，映射四大国际权威分类法的高层级：
#   EU Taxonomy 六大环境目标（绿色低碳专用）/ ISIC 门类 / GICS 部门 / WIPO IPC 部
# 完整标签词典见 docs/标准文档/本体与标签词典.md

# ── 关键词匹配工具（2026-08-25：修复英文短词子串误匹配） ──────────────
# 背景：纯子串匹配下，GICS "ev" 命中 every/level/review（62 条）、EU "ev"
# 虚增减缓（64 条）、生物科技 "gene" 命中 energy/generation（29/30 条）、
# "media" 命中 immediate。修复：ASCII 完整词用「左边界 + 词干 + 常见后缀 +
# 右边界」正则，防止嵌入更长无关单词；中文/含空格短语/故意前缀词保持子串。
_ASCII_ONLY_RE = re.compile(r"^[a-z0-9.]+$")
# 故意前缀匹配的关键词（需命中更长单词：decarbonization / remanufacturing）
_PREFIX_KWS = {"decarboni", "remanufactur"}


def _kw_hit(text: str, kw: str) -> bool:
    """关键词命中：ASCII 完整词走词边界（防 ev→level 类误匹配），其余子串。"""
    if not _ASCII_ONLY_RE.match(kw) or kw in _PREFIX_KWS:
        return kw in text
    # 词干 + 常见后缀（s/es/ing/ed/d 覆盖复数与动词变形），左右不允许字母数字
    return re.search(
        r"(?<![a-z0-9])" + re.escape(kw) + r"(?:s|es|ing|ed|d)?(?![a-z0-9])", text
    ) is not None


# EU Taxonomy 六大环境目标（顺序即优先级：减缓最宽放最前）
EU_TAXONOMY_RULES: list[tuple[str, list[str]]] = [
    ("气候变化减缓", [
        "新能源", "光伏", "风电", "储能", "氢能", "核能", "生物质", "水电",
        "节能", "能效", "减排", "降碳", "碳市场", "碳交易", "碳价", "碳配额",
        "CCUS", "碳捕集", "电动车", "零碳", "绿色制造", "碳中和", "碳达峰", "双碳",
        "碳足迹", "碳普惠", "绿电", "绿色低碳", "碳关税", "碳排放", "温室气体", "低碳",
        "renewable", "solar", "wind", "hydrogen", "nuclear", "biomass",
        "energy efficiency", "decarboni", "carbon capture", "ccus",
        "ev", "electric vehicle", "zero carbon", "carbon neutral", "net zero",
        "carbon price", "carbon market", "emission trading", "cbam",
        "carbon emission", "greenhouse gas", "ets",
    ]),
    ("污染防治", [
        "污染", "空气质量", "水污染", "土壤污染", "pm2.5", "挥发性有机物",
        "氮氧化物", "固废", "大气治理", "蓝天保卫战", "环境治理",
        "pollution", "air quality", "nox", "emission control",
    ]),
    ("循环经济", [
        "循环经济", "资源循环", "废弃物", "回收", "再利用", "再生材料",
        "废电池回收", "再生塑料", "废钢", "资源化", "以旧换新",
        "circular economy", "recycling", "reuse", "remanufactur", "waste",
    ]),
    ("气候变化适应", [
        "气候适应", "韧性", "防洪", "抗旱", "极端天气", "海平面", "气候风险", "热浪",
        "climate adaptation", "resilience", "flood", "drought",
        "extreme weather", "heatwave", "sea level",
    ]),
    ("水资源", [
        "水资源", "水处理", "节水", "污水处理", "海水淡化", "水循环", "再生水",
        "water", "wastewater", "desalination", "water treatment", "water reuse",
    ]),
    ("生物多样性", [
        "生物多样性", "自然保护", "栖息地", "物种", "森林", "湿地", "海洋保护", "红树林",
        "生态保护", "biodiversity", "ecosystem", "conservation", "habitat",
        "species", "forest", "wetland",
    ]),
]

# ISIC 门类（产业分类，重点绿色低碳相关门类；顺序即优先级）
ISIC_RULES: list[tuple[str, list[str]]] = [
    ("K 金融保险", [
        "金融", "银行", "证券", "保险", "基金", "投资", "债券", "碳资产", "期货",
        "融资", "并购", "ipo", "esg", "绿色金融", "碳金融", "私募", "股权",
        "finance", "bank", "investment", "fund", "bond", "insurance", "green bond",
    ]),
    ("J 信息通信", [
        "信息", "通信", "软件", "互联网", "数据中心", "算力", "人工智能", "芯片",
        "大模型", "智能体", "算法", "数字化",
        "information", "software", "internet", "data center", "chip", "algorithm",
    ]),
    ("D 电力燃气", [
        "电力", "发电", "电网", "供电", "燃气", "热力", "热电", "电价", "新型电力系统",
        "electricity", "power grid", "power generation", "utilities",
    ]),
    ("C 制造", [
        "制造", "工厂", "设备", "光伏组件", "电池制造", "汽车", "装备", "冶炼",
        "产能", "生产线", "manufacturing", "factory", "plant", "gigafactory",
    ]),
    ("B 采矿", [
        "采矿", "矿产", "稀土", "锂矿", "煤炭开采", "矿山", "勘探",
        "mining", "mineral", "lithium", "rare earth", "coal mine",
    ]),
    ("E 供水废物", [
        "供水", "污水", "废物管理", "回收", "环卫", "垃圾处理", "水处理",
        "wastewater", "waste management", "recycling", "water treatment",
    ]),
    ("F 建筑", [
        "建筑", "施工", "绿色建筑", "建材", "基建", "房地产",
        "construction", "building", "green building",
    ]),
    ("H 运输仓储", [
        "运输", "物流", "航运", "铁路", "仓储", "港口", "航空", "充电桩",
        "transport", "logistics", "shipping", "railway", "port", "aviation",
    ]),
    ("A 农业林业", [
        "农业", "林业", "渔业", "种植", "畜牧", "农田", "森林",
        "agriculture", "forestry", "fishing", "farming",
    ]),
    ("M 专业科技活动", [
        "科研", "研发", "咨询", "技术服务", "实验室", "检测", "学术", "论文",
        "research", "laboratory", "consulting", "technical service",
    ]),
    ("O 公共行政", [
        "政府", "行政", "监管", "部委", "政策", "条例", "法规",
        "government", "policy", "regulation", "ministry",
    ]),
]

# GICS 部门（金融投资视角，11 部门；顺序即优先级）
GICS_RULES: list[tuple[str, list[str]]] = [
    ("公用事业", ["公用事业", "电力", "燃气", "水务", "发电", "电网", "utilities", "power grid"]),
    ("能源", ["石油", "天然气", "煤炭", "油气", "能源设备", "oil", "natural gas", "coal", "petroleum"]),
    ("原材料", ["材料", "化工", "钢铁", "有色", "稀土", "锂", "铜", "materials", "chemical", "steel", "lithium", "copper"]),
    ("工业", ["工业", "制造", "机械", "装备", "航天", "军工", "电气设备", "工厂", "industrial", "manufacturing", "machinery", "equipment"]),
    ("信息技术", ["信息技术", "软件", "硬件", "半导体", "互联网", "芯片", "software", "semiconductor", "internet", "chip"]),
    ("金融", ["银行", "保险", "证券", "资管", "基金", "碳资产", "金融", "bank", "insurance", "fund", "finance"]),
    ("通信服务", ["通信", "电信", "媒体", "telecom", "communication", "media"]),
    ("非必需消费品", ["汽车", "家电", "零售", "纺织", "电动车", "automotive", "consumer", "retail", "ev"]),
    ("医疗保健", ["医疗", "制药", "生物", "healthcare", "pharma", "biotech"]),
    ("房地产", ["房地产", "物业", "reits", "real estate", "property"]),
    ("必需消费品", ["食品", "饮料", "日化", "consumer staples", "food", "beverage"]),
]

# WIPO IPC 部（技术专利视角，8 部；顺序即优先级）
IPC_RULES: list[tuple[str, list[str]]] = [
    ("H 电学", ["电学", "电子", "通信", "电力", "半导体", "电路", "电池", "electric", "electronic", "semiconductor", "circuit", "battery", "batteries"]),
    ("C 化学冶金", ["化学", "材料", "冶金", "催化剂", "电解", "碳材料", "化工", "chemistry", "chemical", "metallurgy", "catalyst", "electrolysis"]),
    ("G 物理", ["物理", "光学", "测量", "计算", "控制", "physics", "optical", "measurement", "computing", "control"]),
    ("F 机械工程", ["机械", "发动机", "照明", "供热", "燃烧", "mechanical", "engine", "heating", "combustion"]),
    ("B 作业运输", ["运输", "物流", "机械加工", "分离", "transport", "conveying", "separation"]),
    ("E 固定建筑", ["建筑", "土木", "施工", "building", "construction", "civil engineering"]),
    ("A 人类生活需要", ["农业", "食品", "医疗", "体育", "agriculture", "food", "medical"]),
    ("D 纺织造纸", ["纺织", "造纸", "textile", "paper"]),
]

# ISIC 源映射（仅明确门类的源；媒体源内容混合，靠关键词判定）
SOURCE_ISIC: dict[str, str] = {
    "pbc": "K 金融保险", "cneeex": "K 金融保险", "goldman": "K 金融保险",
    "caixin": "K 金融保险", "worldbank": "K 金融保险",
    "jiqizhixin": "J 信息通信", "qbitai": "J 信息通信", "openai": "J 信息通信",
    "arxiv_ai": "J 信息通信", "aihot": "J 信息通信", "artificialanalysis": "J 信息通信",
    "36kr": "J 信息通信", "huxiu": "J 信息通信", "radarai": "J 信息通信",
    "ndrc": "O 公共行政", "mee": "O 公共行政", "nea": "O 公共行政", "miit": "O 公共行政",
    "us_epa": "O 公共行政", "us_doe": "O 公共行政", "eu_commission": "O 公共行政",
    "india_pib": "O 公共行政", "jp_moe": "O 公共行政", "jp_meti": "O 公共行政",
    "jp_anre": "O 公共行政", "ncsc": "O 公共行政", "caep": "O 公共行政",
    "chinanecc": "O 公共行政", "unfccc": "O 公共行政",
    "iea": "M 专业科技活动", "irena": "M 专业科技活动", "e3g": "M 专业科技活动",
    "agora": "M 专业科技活动", "teri": "M 专业科技活动", "carbonbrief": "M 专业科技活动",
    "ccai": "M 专业科技活动",
    "qjem": "M 专业科技活动",  # 经济管理学刊（2026-08-24 学术期刊）
}


def classify_eu_taxonomy(title: str, summary: str) -> str:
    """EU Taxonomy 六大环境目标分类（2026-08-23）。返回目标中文名，无匹配返回空串。"""
    text = f"{title or ''} {summary or ''}".lower()
    for tag, kws in EU_TAXONOMY_RULES:
        if any(_kw_hit(text, kw) for kw in kws):
            return tag
    return ""


def classify_isic(site_id: str, title: str, summary: str) -> str:
    """ISIC 门类分类（2026-08-23）。源映射优先，再按关键词。返回门类名，无匹配返回空串。"""
    if site_id in SOURCE_ISIC:
        return SOURCE_ISIC[site_id]
    text = f"{title or ''} {summary or ''}".lower()
    for tag, kws in ISIC_RULES:
        if any(_kw_hit(text, kw) for kw in kws):
            return tag
    return ""


def classify_gics(title: str, summary: str) -> str:
    """GICS 部门分类（2026-08-23）。返回部门名，无匹配返回空串。"""
    text = f"{title or ''} {summary or ''}".lower()
    for tag, kws in GICS_RULES:
        if any(_kw_hit(text, kw) for kw in kws):
            return tag
    return ""


def classify_ipc(title: str, summary: str) -> str:
    """WIPO IPC 部分类（2026-08-23）。返回部名，无匹配返回空串。"""
    text = f"{title or ''} {summary or ''}".lower()
    for tag, kws in IPC_RULES:
        if any(_kw_hit(text, kw) for kw in kws):
            return tag
    return ""


# ── 维度三 + layer + TRL（2026-08-23 新增） ─────────────────────────────────
# 完整标签词典见 docs/标准文档/本体与标签词典.md

# dimension（中文）→ layer（国际化 Layer 1/2/3；v5.0 中性命名，Layer 编号不变）
DIM_TO_LAYER: dict[str, str] = {
    "政策": "Layer 1",
    "产业": "Layer 2",
    "创新": "Layer 3",
}

# 交叉技术标签（Enabling Technologies，多对多：一条信息可同时命中多个）
ENABLING_TECH_RULES: list[tuple[str, list[str]]] = [
    ("AI", [
        "人工智能", "机器学习", "大模型", "算法", "深度学习", "神经网络",
        "智能体", "agent", "数据科学", "计算机视觉", "自然语言处理", "生成式",
        "强化学习", "大语言模型", "多模态", "算力",
        "artificial intelligence", "machine learning", "deep learning",
        "neural network", "llm", "agent", "computer vision", "nlp",
    ]),
    ("生物科技", [
        "合成生物学", "基因", "微生物", "酶", "发酵", "生物制造", "生物质转化",
        "细胞", "基因编辑", "菌种", "生物燃料",
        "synthetic biology", "gene", "genes", "genetic", "genome", "genomic",
        "microbe", "enzyme", "fermentation", "biomanufacturing",
    ]),
    ("能源", [
        "新能源", "储能", "氢能", "核能", "光伏", "风电", "电力", "电池",
        "燃料电池", "生物质", "水电", "光热", "绿氢", "锂电池",
        "renewable", "storage", "hydrogen", "nuclear", "solar", "wind",
        "battery", "batteries", "fuel cell",
    ]),
    ("环境", [
        "碳捕集", "ccus", "污染防治", "生态", "废弃物", "循环", "水处理",
        "大气", "碳足迹", "碳普惠", "环保",
        "carbon capture", "pollution", "ecosystem", "waste", "circular",
        "water treatment",
    ]),
]


def classify_enabling_tech(title: str, summary: str) -> list[str]:
    """交叉技术标签（多对多，2026-08-23）。返回命中的所有赋能标签（可能多个）。"""
    text = f"{title or ''} {summary or ''}".lower()
    found: list[str] = []
    for tag, kws in ENABLING_TECH_RULES:
        if any(_kw_hit(text, kw) for kw in kws):
            found.append(tag)
    return found


# TRL 技术成熟度档位（顺序即优先级：7-9 商业化最高放最前）
TRL_RULES: list[tuple[str, list[str]]] = [
    ("7-9", [
        "投产", "并网", "交付", "量产", "商业化", "部署", "融资", "落地", "建成",
        "运营", "商业运营", "装机", "上市", "出口",
        # 2026-08-24 扩展：工程化/商业化高精度技术词（避免误判政策/资本类）
        "机组", "电站", "电芯", "中标", "通过评价", "通过验收", "通过鉴定",
        "示范工程", "首台", "首套", "首例", "首创",
        "commercial", "deployment", "operation", "production", "launch",
    ]),
    ("4-6", [
        "样机", "原型", "中试", "专利", "benchmark", "方法学", "实验室验证",
        "试验", "试点", "示范", "研发",
        # 2026-08-24 扩展：技术开发/成套技术
        "成套技术", "技术路线", "验证",
        "prototype", "pilot", "patent", "benchmark", "demonstration",
    ]),
    ("1-3", [
        "原理", "机理", "理论", "概念", "发现", "论文", "实验", "机制", "方法",
        "principle", "mechanism", "theory", "paper", "discovery", "experiment",
    ]),
]


def classify_trl(title: str, summary: str) -> str:
    """TRL 技术成熟度档判定（2026-08-23）。返回 '7-9'/'4-6'/'1-3'/''（空=无技术信号）。"""
    text = f"{title or ''} {summary or ''}".lower()
    for tag, kws in TRL_RULES:
        if any(kw.lower() in text for kw in kws):
            return tag
    return ""


def score_trl(trl: str) -> int:
    """TRL 技术成熟度打分（第 6 维度，0-5 分，2026-08-23）。

    7-9 工程化/商业化 → 5；4-6 技术开发 → 5；1-3 基础原理 → 4；空（无技术信号）→ 3（中性）。
    """
    if trl == "7-9":
        return 5
    if trl == "4-6":
        return 5
    if trl == "1-3":
        return 4
    return 3  # 空（政策类或无技术信号）→ 中性 3 分


# ── Policy relevance filter ──────────────────────────────────────────────────
POLICY_KEYWORDS = [
    # Chinese
    "碳", "绿色", "低碳", "减排", "双碳", "新能源", "可再生能源",
    "节能", "环保", "气候", "碳中和", "碳达峰", "清洁能源",
    "光伏", "风电", "储能", "氢能", "核能", "生物质",
    "碳交易", "碳市场", "碳关税", "碳足迹", "碳普惠",
    "ESG", "可持续发展", "循环经济", "绿色制造", "绿色金融",
    "能源转型", "电力市场", "新型电力系统",
    "生态环境", "污染防治", "蓝天保卫战", "以旧换新",
    "CCUS", "碳捕集",
    "发改", "能源", "电力", "成品油", "天然气", "煤炭",
    # English
    "carbon", "climate", "green", "renewable", "clean energy",
    "emission", "solar", "wind", "hydrogen", "battery",
    "net zero", "net-zero", "decarboni", "sustainable",
    "COP", "Paris Agreement", "NDC", "CBAM",
    "energy transition", "EV", "electric vehicle",
]


# Sites where ALL content is inherently green policy
GREEN_SITES = {
    "tanpaifang", "ideacarbon", "ndrc", "nea", "mee",
    "carbonbrief", "iea", "irena", "unfccc", "worldbank",
    "chinaenergy", "bjx", "reuters", "miit",
    "ccai", "stdaily",
    # 国外主要国家政策源（2026-08-14 新增：官方部委直通；Euractiv 是综合媒体不走直通）
    "us_epa", "us_doe", "eu_commission", "india_pib",
    # 美国/日本扩展官方源（2026-08-14 第二轮：联邦/部委官方直通）
    "us_noaa", "us_eia", "us_ferc", "us_carb", "jp_moe", "jp_meti", "jp_anre",
    # 中国 P0 第二批（2026-08-14：官方机构直通；环境报/CNESA 走关键词过滤）
    "pbc", "cneeex", "ncsc", "caep",
    # 国际智库（2026-08-17 第三轮：全站绿色主题，直通）
    "e3g", "agora", "teri",
    # 人形机器人/智能家居/绿色生活（2026-08-19 新增：全站绿色主题直通；
    # greenbuilder 是绿色建筑+地产混合媒体 → 走关键词过滤不进直通）
    "greenpeace", "mongabay",
    # 国家节能中心（2026-08-19 接入：发改委下属事业单位，全站节能降碳官方解读）
    "chinanecc",
}

# 低频源宽窗口（2026-08-14）：国外官方源 + 中国智库型机构（NCSC/CAEP），
# 更新频率低（周级/月级），网站数据用 7 天宽窗口过滤，其余源保持 96h
FOREIGN_GOV_SITES = {
    "us_epa", "us_doe", "us_noaa", "us_eia", "us_ferc", "us_carb",
    "eu_commission", "euractiv", "india_pib",
    "jp_moe", "jp_meti", "jp_anre",
    "ncsc", "caep",
    # 国际能源机构（2026-08-23 补：IEA/IRENA 周更~双周更，24h 窗口会整源滤空，
    # 62 天 0 条即此因；与国外官方源同级 7 天宽窗口）
    "iea", "irena", "unfccc", "worldbank",
}

# 超低频源（2026-08-17）：国际智库更新周级~双周级（Agora 最新条目可超 14 天），
# 深度分析时效性弱于新闻 → 网站数据用 21 天宽窗口，避免整源被滤空
LOW_FREQ_SITES = {
    "e3g", "agora", "teri",
    "greenpeace",  # 绿色和平中文站（月级更新，2026-08-19 新增）
    # 国际智库/投行第四轮（2026-08-19 接入：Brookings/Bruegel/PIIE/CSIS/Chatham/
    # Carnegie/RAND/CAP/高盛——智库周级~双周级更新，同 E3G/Agora 21 天宽窗口）
    "brookings", "bruegel", "piie", "csis", "chatham",
    "carnegie", "rand", "americanprogress", "goldman",
    # 国家节能中心（官方解读周级更新，2026-08-19 接入）
    "chinanecc",
}

# AI 领域全链条源（2026-08-14 扩充）：理论/模型/市场/商业 全部通过，
# 不加入 GREEN_SITES（那里是绿色政策源），单独一组放行
AI_SITES = {
    "jiqizhixin",   # 机器之心（中文 AI 头部媒体：模型/技术/商业）
    "qbitai",       # 量子位（中文 AI 产品/市场）
    "openai",       # OpenAI News（模型发布一手）
    "venturebeat",  # VentureBeat AI（国际 AI 商业）
    "arxiv_ai",     # arXiv cs.AI（理论前沿）
    "aihot",        # AIHOT（AI 行业动态聚合：模型/产品/行业/论文，带 AI 评分）
    # 2026-08-17：Climate Change AI（ccai）= 机器学习应对气候变化机构，
    # 全部产出均为 AI×绿色低碳（AI 资助/工作坊/ML 基准）→ 归 AI科技榜，
    # 避免 NeurIPS 工作坊/ML 基准等项目因标题不含 AI 关键词而落进技术榜
    "ccai",         # Climate Change AI（AI×气候交叉）
    # 2026-08-19：Artificial Analysis（AI 模型评测/API 市场数据——纯 AI 内容直通）
    "artificialanalysis",
}

# AI 综合媒体（2026-08-19 第四轮接入：36氪/虎嗅是科技商业综合媒体，非纯 AI 源）。
# 与 TECH_SITES 同逻辑：命中绿色词或 AI 词才入库（过滤无关科技商业噪音），
# 但 categorize_dimension 走常规关键词判定（不强制归 AI/行业）。
AI_MEDIA_SITES = {
    "36kr",   # 36氪（AI/新能源/储能/碳中和报道）
    "huxiu",  # 虎嗅（AI/新能源报道）
}

# 经管学术期刊（2026-08-24 接入：经济管理学刊）——老温指定全部抓取+参与评分，
# 全量直通（不过滤绿色低碳关键词）。经济管理综合期刊，内容为宏观/金融/产业/
# 养老/IPO/数字资产等，与绿色低碳关联度低，但作为"市场信号/产业"维度参考。
ACADEMIC_JOURNAL_SITES = {
    "qjem",  # 经济管理学刊（Quarterly Journal of Economics and Management）
}

# 技术全链条源（2026-08-14）：GitHub 开源项目趋势，全量直通（同 AI_SITES 逻辑）。
# 维度（2026-08-17 调整）：非 AI 项目落回「技术」（媒体库兜底）；AI 项目在
# categorize_dimension 中按关键词（标题+摘要）归 AI科技榜——技术榜只放绿色低碳技术
TECH_SITES = {
    "radarai",      # RadarAI·GitHub趋势（开源项目热度追踪）
}

# 机器人/具身智能全链条源（2026-08-19）：人形机器人/工业机器人/无人机。
# 同 AI_SITES 逻辑直通（不进 GREEN_SITES——非绿色主题媒体），categorize 按关键词：
# humanoid/robot 命中 AI_DIM_KW → AI 榜（人形机器人=具身智能核心），纯产业动态落行业。
ROBOT_SITES = {
    "therobotreport",   # The Robot Report（国际机器人产业头部媒体）
    "spectrum",         # IEEE Spectrum（机器人/科技权威媒体）
}

# X 平台快讯（2026-08-19 接入，零成本方案）：精选绿色/能源/AI 账号。
# 同 AI_MEDIA_SITES 逻辑——命中绿色词或 AI 词才入库（过滤 KOL 的非主题推文），
# categorize_dimension 走常规关键词判定（政策/行业/金融/AI 自然分流）。
X_SITES = {
    "x",
}

# 站点级维度强制：categorize_dimension 最先检查，优先于 AI_SITES 直通。
# 2026-08-17 起为空——radarai（GitHub 开源趋势）不再整源归「技术」：
# 技术榜只放绿色低碳技术，AI 项目按关键词（含摘要）归 AI科技榜，非 AI 项目落回技术兜底。
DIM_SITE_OVERRIDE: dict[str, str] = {}


def is_policy_relevant(title: str, url: str = "", site_id: str = "", summary: str = "") -> bool:
    """Check if a title/URL/site is related to green/low-carbon policy."""
    # Auto-pass for known green sites
    if site_id in GREEN_SITES:
        return True
    # AI 领域全链条源（2026-08-14）：理论/模型/市场/商业全通过
    if site_id in AI_SITES:
        return True
    # 技术全链条源（2026-08-14）：GitHub 开源项目趋势——2026-08-19 起不再全通过，
    # 需命中绿色主题词或 AI 词（否则 vitejs/vite 等与绿色低碳无关的开源项目混入行业榜）
    if site_id in TECH_SITES:
        t = f"{title or ''} {summary or ''}".lower()
        if any(kw.lower() in t for kw in POLICY_KEYWORDS):
            return True
        if any(kw.lower() in t for kw in AI_DIM_KW):
            return True
        return False
    # 机器人/具身智能全链条源（2026-08-19）：人形机器人/工业机器人直通
    if site_id in ROBOT_SITES:
        return True
    # 经管学术期刊（2026-08-24）：经济管理学刊——老温指定全部抓取，全量直通
    if site_id in ACADEMIC_JOURNAL_SITES:
        return True
    # AI 综合媒体（2026-08-19）：36氪/虎嗅是科技商业媒体——命中绿色词或 AI 词
    # 才入库（与 TECH_SITES 同逻辑，过滤无关科技商业噪音）
    if site_id in AI_MEDIA_SITES:
        t = f"{title or ''} {summary or ''}".lower()
        if any(kw.lower() in t for kw in POLICY_KEYWORDS):
            return True
        if any(kw.lower() in t for kw in AI_DIM_KW):
            return True
        return False
    # X 平台快讯（2026-08-19）：命中绿色词或 AI 词才入库（同 AI_MEDIA_SITES 逻辑）
    if site_id in X_SITES:
        t = f"{title or ''} {summary or ''}".lower()
        if any(kw.lower() in t for kw in POLICY_KEYWORDS):
            return True
        if any(kw.lower() in t for kw in AI_DIM_KW):
            return True
        return False
    title_lower = title.lower()
    url_lower = url.lower()
    # PITFALL(2026-08-19): 纯 ASCII 短关键词（EV/COP/NDC/ESG 等 ≤4 字符）必须用
    # \b 词边界正则——子串匹配会把 "development" 里的 "EV"、"copper" 里的 "COP"
    # 误判为命中（实测 Brookings "Stablecoins ... development" 因 EV 误放行）。
    # 中文关键词不用 \b（汉字是 \w，\b 边界不适用）。
    for kw in POLICY_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower.isascii() and len(kw_lower) <= 4:
            if re.search(rf"\b{re.escape(kw_lower)}\b", title_lower):
                return True
        elif kw_lower in title_lower:
            return True
        # PITFALL(2026-08-14): Google News 的 base64 URL（news.google.com/rss/articles/...）
        # 常"碰巧包含"短英文关键词（coal/wind/gas 等），导致无关条目被误放行
        # （如 Euractiv 的德国法院逮捕令新闻因 base64 含关键词而进政策库）
        if url_lower and "news.google.com" not in url_lower and kw_lower in url_lower:
            return True
    return False


# ── Source registry ───────────────────────────────────────────────────────────
# All built-in fetchers: (func, site_id, site_name)
BUILTIN_SOURCES: list[tuple[Any, str, str]] = [
    # Chinese government
    (fetch_ndrc, "ndrc", "国家发改委"),
    (fetch_mee, "mee", "生态环境部"),
    (fetch_mee_jiedu, "mee_jiedu", "生态环境部·解读"),
    (fetch_nea, "nea", "国家能源局"),
    (fetch_miit, "miit", "工信部"),
    # ── 国外主要国家政策源（2026-08-14 新增：Google News 搜 site） ──
    (fetch_us_epa, "us_epa", "美国EPA"),
    (fetch_us_doe, "us_doe", "美国DOE"),
    (fetch_eu_commission, "eu_commission", "欧盟委员会"),
    (fetch_euractiv, "euractiv", "Euractiv·欧盟"),
    (fetch_india_pib, "india_pib", "印度PIB"),
    # 美国/日本扩展官方源（2026-08-14 第二轮）
    (fetch_us_noaa, "us_noaa", "美国NOAA"),
    (fetch_us_eia, "us_eia", "美国EIA"),
    (fetch_us_ferc, "us_ferc", "美国FERC"),
    (fetch_us_carb, "us_carb", "加州CARB"),
    (fetch_jp_moe, "jp_moe", "日本环境省"),
    (fetch_jp_meti, "jp_meti", "日本经产省"),
    (fetch_jp_anre, "jp_anre", "日本资源能源厅"),
    # 国际智库（2026-08-17 第三轮）
    (fetch_e3g, "e3g", "E3G"),
    (fetch_agora, "agora", "Agora·能源转型"),
    (fetch_teri, "teri", "TERI·印度能源与资源所"),
    # 国际智库/投行（2026-08-19 第四轮：Brookings/Bruegel/PIIE/CSIS/Chatham/
    # Carnegie/RAND/CAP/高盛——补版图 2.4/3.4 智库 P0 + 券商研报 P0）
    (fetch_brookings, "brookings", "Brookings"),
    (fetch_bruegel, "bruegel", "Bruegel"),
    (fetch_piie, "piie", "PIIE"),
    (fetch_csis, "csis", "CSIS"),
    (fetch_chatham, "chatham", "Chatham House"),
    (fetch_carnegie, "carnegie", "Carnegie"),
    (fetch_rand, "rand", "RAND"),
    (fetch_americanprogress, "americanprogress", "CAP"),
    (fetch_goldman, "goldman", "高盛Insights"),
    # 中国 P0 扩容（2026-08-19 第四轮：财新双碳/国家节能中心/澎湃）
    (fetch_caixin, "caixin", "财新"),
    (fetch_chinanecc, "chinanecc", "国家节能中心"),
    (fetch_thepaper, "thepaper", "澎湃新闻"),
    # AI 维度扩容（2026-08-19 第四轮：Artificial Analysis/36氪/虎嗅）
    (fetch_artificialanalysis, "artificialanalysis", "Artificial Analysis"),
    (fetch_36kr, "36kr", "36氪"),
    (fetch_huxiu, "huxiu", "虎嗅"),
    # 中国 P0 第二批（2026-08-14）
    (fetch_pbc, "pbc", "中国人民银行"),
    (fetch_cneeex, "cneeex", "上海环交所"),
    (fetch_ncsc, "ncsc", "NCSC国家气候中心"),
    (fetch_caep, "caep", "环境规划院CAEP"),
    (fetch_cenews, "cenews", "中国环境报"),
    (fetch_cnesa, "cnesa", "CNESA储能联盟"),
    # 绿色科技/AI（2026-08-14 主题定位升级新增）
    (fetch_ccai, "ccai", "Climate Change AI"),
    (fetch_stdaily_green, "stdaily", "中国科技网"),
    # 经济管理学刊（2026-08-24 接入：经管综合学术期刊，老温指定全部抓取+参与评分）
    (fetch_qjem, "qjem", "经济管理学刊"),
    # International orgs
    (fetch_iea, "iea", "IEA"),
    (fetch_irena, "irena", "IRENA"),
    (fetch_carbonbrief, "carbonbrief", "Carbon Brief"),
    (fetch_unfccc, "unfccc", "UNFCCC"),
    (fetch_worldbank_climate, "worldbank", "World Bank Climate"),
    (fetch_reuters_energy, "reuters", "Reuters Energy"),
    # Chinese industry
    (fetch_bjx, "bjx", "北极星电力网"),
    (fetch_tanpaifang, "tanpaifang", "中国碳交易网"),
    (fetch_tandao, "ideacarbon", "碳道"),
    (fetch_china_energy_news, "chinaenergy", "中国能源报"),
    # CleanTechnica RSS→Google News fallback（2026-08-14 新增；服务器直连被 WAF 拦）
    (fetch_cleantechnica, "cleantechnica", "CleanTechnica"),
    # ── AI 领域全链条源（2026-08-14 扩充：理论/模型/市场/商业） ──
    (fetch_jiqizhixin, "jiqizhixin", "机器之心"),
    (fetch_qbitai, "qbitai", "量子位"),
    (lambda s, n: fetch_rss_feed(s, "https://openai.com/news/rss.xml", "openai", "OpenAI", n, limit=30),
     "openai", "OpenAI"),
    (lambda s, n: fetch_rss_feed(s, "https://venturebeat.com/category/ai/feed/", "venturebeat", "VentureBeat AI", n, limit=30),
     "venturebeat", "VentureBeat AI"),
    (lambda s, n: fetch_rss_feed(s, "https://rss.arxiv.org/rss/cs.AI", "arxiv_ai", "arXiv·AI", n, limit=30),
     "arxiv_ai", "arXiv·AI"),
    # AIHOT — AI 行业动态聚合（2026-08-14 接入；页面有 JS 反爬，RSS 端点匿名可访问）
    (fetch_aihot, "aihot", "AIHOT"),
    # RadarAI — GitHub 开源项目趋势（2026-08-14 接入；/api/trends 干净 JSON）
    (fetch_radarai, "radarai", "RadarAI·GitHub趋势"),
    # 人形机器人/绿色智能家居/绿色生活（2026-08-19 新增）
    (fetch_therobotreport, "therobotreport", "The Robot Report"),
    (fetch_spectrum_robotics, "spectrum", "IEEE Spectrum"),
    (fetch_qianjia, "qianjia", "千家网"),
    (fetch_greenbuilder, "greenbuilder", "Green Builder Media"),
    (fetch_cheaa, "cheaa", "中国家电网"),
    (fetch_greenpeace, "greenpeace", "绿色和平"),
    (fetch_mongabay, "mongabay", "Mongabay"),
    # Aggregated hot boards (filtered by policy keywords)
    (fetch_allnet, "allnet", "全网热点"),
    # X 平台官方账号快讯（2026-08-19 接入，零成本方案：SSR Microdata 直抓）
    (fetch_x, "x", "X平台"),
]

# ── Library layout: site_id → (库类型, 政策库内分组) ─────────────────────────
# 库类型: "policy" = 政策库（第一手权威原始出处）
#        "media"  = 媒体库（第二手转述/解读）
# 政策库分组: "中国"（部委） / "国际组织"
SITE_LAYOUT: dict[str, tuple[str, str]] = {
    # 政策库 · 中国部委
    "ndrc":       ("policy", "中国"),
    "mee":        ("policy", "中国"),
    "mee_jiedu":  ("policy", "中国"),
    "nea":        ("policy", "中国"),
    "miit":       ("policy", "中国"),
    # 国外政府源（2026-08-17：按国家分组——政府与非政府区分，
    # 「国际组织」只放政府间机构；Euractiv 是媒体移入媒体库）
    "us_epa":       ("policy", "美国"),
    "us_doe":       ("policy", "美国"),
    "us_noaa":      ("policy", "美国"),
    "us_eia":       ("policy", "美国"),
    "us_ferc":      ("policy", "美国"),
    "us_carb":      ("policy", "美国"),
    "eu_commission":("policy", "欧盟"),
    "jp_moe":       ("policy", "日本"),
    "jp_meti":      ("policy", "日本"),
    "jp_anre":      ("policy", "日本"),
    "india_pib":    ("policy", "印度"),
    "euractiv":     ("media", ""),
    # 国际智库（2026-08-17 第三轮 → 媒体库：专家解读/政策评论）
    "e3g":   ("media", ""),
    "agora": ("media", ""),
    "teri":  ("media", ""),
    # 国际智库/投行（2026-08-19 第四轮 → 媒体库：专家解读/研报档）
    "brookings":        ("media", ""),
    "bruegel":          ("media", ""),
    "piie":             ("media", ""),
    "csis":             ("media", ""),
    "chatham":          ("media", ""),
    "carnegie":         ("media", ""),
    "rand":             ("media", ""),
    "americanprogress": ("media", ""),
    "goldman":          ("media", ""),
    # 中国 P0 扩容（2026-08-19 第四轮）
    "caixin":     ("media", ""),       # 财新（双碳专栏，专业财经媒体）
    "chinanecc":  ("policy", "中国"),  # 国家节能中心（官方机构→政策库·中国）
    "thepaper":   ("media", ""),       # 澎湃新闻（绿政公署栏目）
    # AI 维度扩容（2026-08-19 第四轮 → 媒体库）
    "artificialanalysis": ("media", ""),
    "36kr":               ("media", ""),
    "huxiu":              ("media", ""),
    # 中国 P0 第二批（2026-08-14）
    "pbc":    ("policy", "中国"),
    "cneeex": ("policy", "中国"),
    "ncsc":   ("policy", "中国"),
    "caep":   ("policy", "中国"),
    "cenews": ("media", "中国"),
    "cnesa":  ("media", "中国"),
    # 政策库 · 国际组织
    "iea":        ("policy", "国际组织"),
    "irena":      ("policy", "国际组织"),
    "unfccc":     ("policy", "国际组织"),
    "worldbank":  ("policy", "国际组织"),
    # 媒体库
    "carbonbrief": ("media", ""),
    "reuters":     ("media", ""),
    "bjx":         ("media", ""),
    "tanpaifang":  ("media", ""),
    "ideacarbon":  ("media", ""),
    "chinaenergy": ("media", ""),
    "allnet":      ("media", ""),
    # 绿色科技/AI（2026-08-14 新增）
    "ccai":          ("media", ""),
    "stdaily":       ("media", ""),
    "cleantechnica": ("media", ""),
    # AI 领域全链条源（2026-08-14 扩充：理论/模型/市场/商业）
    "jiqizhixin":  ("media", ""),
    "qbitai":      ("media", ""),
    "openai":      ("media", ""),
    "venturebeat": ("media", ""),
    "arxiv_ai":    ("media", ""),
    "aihot":       ("media", ""),
    "radarai":     ("media", ""),
    # 人形机器人/智能家居/绿色生活（2026-08-19 新增，全部媒体库）
    "therobotreport": ("media", ""),
    "spectrum":       ("media", ""),
    "qianjia":        ("media", ""),
    "greenbuilder":   ("media", ""),
    "cheaa":          ("media", ""),
    "greenpeace":     ("media", ""),
    "mongabay":       ("media", ""),
    "x":              ("media", ""),  # X 平台快讯（社交快讯→媒体库）
}


def site_library(site_id: str) -> str:
    """policy (政策库/权威原文) or media (媒体库/二手转述)."""
    return SITE_LAYOUT.get(site_id, ("policy", "其他"))[0]


def site_policy_group(site_id: str) -> str:
    """政策库内部分组（中国 / 国际组织）。媒体源无分组。"""
    return SITE_LAYOUT.get(site_id, ("policy", "其他"))[1]


# ── Main pipeline ─────────────────────────────────────────────────────────────
def merge_history(output_dir: Path, new_items: list[dict], now: datetime) -> None:
    """累积历史 data/history.json（2026-08-17）：前端排行榜日/周/月周期切换的数据源。

    - 按 url 去重：已存在条目保留首次收录版本（分数/维度不重算），新条目追加
    - 按 published_at（无则 first_seen_at）裁剪 62 天
    - 读取失败/损坏 → 从空重建，不阻断主流程（服务器 set -euo pipefail 兼容）
    """
    path = output_dir / "history.json"
    existing: list[dict] = []
    if path.exists():
        try:
            existing = (json.loads(path.read_text(encoding="utf-8")) or {}).get("items", []) or []
        except Exception:
            existing = []
    seen: dict[str, dict] = {}
    seen_prefix: dict[str, list[str]] = {}  # 2026-08-24: 前缀桶 → 已见标题（相似度去重候选）
    for it in existing:
        u = it.get("url") or ""
        # 2026-08-19：按规范化标题去重（Google News 聚合 URL 每次抓取不同，
        # 按 url 会累积同一条新闻的多份副本——实测日本环境省 x8 重复）
        k = _title_dedup_key(it.get("title", ""))
        if k and k not in seen:
            seen[k] = it
            _t = it.get("title", "") or ""
            _pfx = _title_prefix_key(_t)
            seen_prefix.setdefault(_pfx, []).append(_t)
        elif u and not k:
            seen[u] = it
    added = 0
    for it in new_items:
        u = it.get("url") or ""
        k = _title_dedup_key(it.get("title", ""))
        if k and k not in seen:
            # 标题相似度去重（2026-08-24 去重治理 P0）：截断/标点/源名后缀/微调判重
            _t = it.get("title", "") or ""
            _pfx = _title_prefix_key(_t)
            if any(_titles_similar(_t, _cand) for _cand in seen_prefix.get(_pfx, [])):
                continue
            seen[k] = it
            seen_prefix.setdefault(_pfx, []).append(_t)
            added += 1
        elif u and not k and u not in seen:
            seen[u] = it
            added += 1
    cutoff = now - timedelta(days=62)

    def _item_time(it: dict):
        ts = it.get("published_at") or it.get("first_seen_at") or ""
        return parse_iso(ts) if ts else None

    items = [it for it in seen.values() if (_item_time(it) or now) >= cutoff]
    # 统一清理历史条目的标题尾部源名后缀，并回填缺失的 title_zh（非中文才翻译，
    # 带缓存；历史条目的旧标题可能残留 " - EPA" 等后缀 — 2026-08-18）
    # 2026-08-23：回填翻译改为并发 3（原串行几百条 × TMT 限流会拖死 merge，
    # 实测 update_news.py 卡在 merge_history 数分钟——62 天 0 条断源根因之一）
    for it in items:
        _t = _strip_title_suffix(it.get("title", "") or "")
        if _t != it.get("title", ""):
            it["title"] = _t
        it.setdefault("title_zh", "")
        # 历史条目摘要统一清洗（2026-08-23：国家节能中心/上海环交所等旧条目
        # summary 残留页脚垃圾词——清洗逻辑后来增强过，旧数据未重洗）
        if it.get("summary"):
            _s = _clean_summary(it["summary"])
            if _s != it["summary"]:
                it["summary"] = _s
    _missing_zh = [it for it in items
                   if translator.needs_translation(it.get("title", "")) and not (it.get("title_zh") or "").strip()]
    if _missing_zh:
        from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _AC
        with _TPE(max_workers=3) as _ex:
            _futs = {_ex.submit(translator.translate_title, it["title"]): it for it in _missing_zh}
            for _fut in _AC(_futs):
                _zh = _fut.result()
                if _zh:
                    _futs[_fut]["title_zh"] = _zh
    for it in items:
        # 回填地域（2026-08-19 修复）：旧条目首次收录时 region 可能为空（早期逻辑
        # 未算）或按 site 误标（中国站转载国际新闻被标「中国」）——每次 merge
        # 用最新 detect_region 重算，前端国内/国际筛选依赖此字段
        it["region"] = detect_region(it.get("site_id", ""), it.get("title", "") or "")
        # 回填主题标签（2026-08-19）：旧条目无 topics 字段时按标题补算，
        # 前端关系图谱依赖（地域/政策类型管理标签不导出）
        if not it.get("topics"):
            it["topics"] = extract_topic_tags(it.get("title", "") or "")
    items.sort(key=lambda r: r.get("published_at") or "0000-00-00", reverse=True)
    path.write_text(json.dumps({
        "generated_at": iso(now),
        "window_days": 62,
        "count": len(items),
        "items": items,
    }, ensure_ascii=False), encoding="utf-8")
    if added:
        print(f"   History: +{added} new, {len(items)} total (62d window)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Green Policy News Radar")
    parser.add_argument("--output-dir", default="data", help="Output directory for JSON files")
    parser.add_argument("--window-hours", type=int, default=24, help="Time window in hours")
    parser.add_argument("--rss-opml", default=None, help="Optional OPML file for extra RSS feeds")
    parser.add_argument("--obsidian-dir", default=None, help="Export news as Obsidian markdown notes to this dir")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    now = utc_now()
    session = create_session()
    _t0 = time.monotonic()

    # ── Fetch all sources ───────────────────────────────────────────────────
    raw_items: list[RawItem] = []
    source_statuses: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures: dict[Any, tuple[str, str]] = {}
        for func, site_id, site_name in BUILTIN_SOURCES:
            futures[ex.submit(func, session, now)] = (site_id, site_name)

        opml_future = None
        if args.rss_opml:
            opml_future = ex.submit(fetch_opml_rss, session, args.rss_opml, now)

        for f in as_completed(futures):
            site_id, site_name = futures[f]
            try:
                items = f.result()
                raw_items.extend(items)
                source_statuses.append({
                    "site_id": site_id, "site_name": site_name,
                    "ok": True, "item_count": len(items),
                })
            except Exception as exc:
                source_statuses.append({
                    "site_id": site_id, "site_name": site_name,
                    "ok": False, "item_count": 0, "error": str(exc),
                })

        if opml_future:
            try:
                opml_items = opml_future.result()
                raw_items.extend(opml_items)
                source_statuses.append({
                    "site_id": "opml", "site_name": "OPML订阅",
                    "ok": True, "item_count": len(opml_items),
                })
            except Exception as exc:
                source_statuses.append({
                    "site_id": "opml", "site_name": "OPML订阅",
                    "ok": False, "item_count": 0, "error": str(exc),
                })

    # ── Dedup (no time window) for Obsidian export ──────────────────────────
    seen_ids: set[str] = set()
    seen_items: set[str] = set()  # 2026-08-19: 统一按规范化标题去重（见下）
    seen_title_prefix: dict[str, list[str]] = {}  # 2026-08-24: 前缀桶 → 已见标题（相似度去重候选）
    print(f"  抓取完成: {len(raw_items)} 条 raw（{sum(1 for s in source_statuses if s['ok'])}/{len(source_statuses)} 源 ok，耗时 {time.monotonic()-_t0:.0f}s）", flush=True)

    all_items: list[dict[str, Any]] = []
    green_items: list[dict[str, Any]] = []

    # ── 非中文标题批量翻译（腾讯云 TMT，失败静默降级）────────────────────
    # 先收集去重后的干净标题，再并发翻译，避免逐条串行网络调用拖慢 pipeline。
    # 结果写入 record 的 title_zh 字段（前端非中文标题显示中文翻译）。
    _titles_to_translate: set[str] = set()
    for raw in raw_items:
        _t = _strip_title_suffix(raw.title)
        if translator.needs_translation(_t):
            _titles_to_translate.add(_t)
    print(f"  翻译开始: {len(_titles_to_translate)} 条非中文标题（QPS=5 限流，可能耗时数分钟，t+{time.monotonic()-_t0:.0f}s）", flush=True)
    title_zh_map: dict[str, str] = {}
    if _titles_to_translate:
        # 并发 3：TMT 免费版默认 QPS=5，6 并发会触发 RequestLimitExceeded 限流
        # （translator 内部已带退避重试，此处再降并发双保险 — 2026-08-18）
        with ThreadPoolExecutor(max_workers=3) as _ex:
            _futs = {_ex.submit(translator.translate_title, _t): _t
                     for _t in _titles_to_translate}
            for _fut in as_completed(_futs):
                _t = _futs[_fut]
                try:
                    _zh = _fut.result()
                except Exception:
                    _zh = None
                if _zh:
                    title_zh_map[_t] = _zh
    print(f"  翻译完成: {len(title_zh_map)} 条已译（t+{time.monotonic()-_t0:.0f}s）", flush=True)

    for raw in raw_items:
        tid = make_item_id(raw.site_id, raw.title, raw.url)
        if tid in seen_ids:
            continue
        seen_ids.add(tid)

        # 去重（2026-08-19）：统一按规范化标题——Google News 聚合 URL 是 base64
        # 且每次抓取不同，按 url 去重会漏（实测日本环境省一条新闻 x8 重复）。
        # seen_ids（url 维度）仍保留作快速通道；真正防重复靠 title_key。
        # 2026-08-23：key 用 strip 后缀后的标题（raw.title 带 " - 36氪" 等源名
        # 后缀时 key 不同 → 跨源同新闻不去重，QA F1 实测 36kr/jiqizhixin 重复）
        title_key = _title_dedup_key(_strip_title_suffix(raw.title))
        if title_key in seen_items:
            continue
        # 标题相似度去重（2026-08-24 去重治理 P0）：截断/标点/源名后缀/微调判重
        _clean_t = _strip_title_suffix(raw.title)
        _pfx = _title_prefix_key(_clean_t)
        if any(_titles_similar(_clean_t, _cand) for _cand in seen_title_prefix.get(_pfx, [])):
            continue
        seen_items.add(title_key)
        seen_title_prefix.setdefault(_pfx, []).append(_clean_t)

        # 统一清理标题尾部源名后缀（" - EPA" / " - CleanTechnica" 等），
        # 覆盖各 fetch 函数未单独清理的 Google News RSS 源（2026-08-18）
        clean_title = _strip_title_suffix(raw.title)
        # 统一清洗摘要：unescape + 去模板变量（QA 2026-08-21：X 平台 &amp;、中国环境报 {{content.*}}）
        clean_summary = _clean_summary(raw.meta.get("summary", ""))
        record = {
            "id": tid,
            "site_id": raw.site_id,
            "site_name": raw.site_name,
            "source": raw.source or raw.site_name,
            "library": site_library(raw.site_id),  # policy | media
            "title": clean_title,
            "title_zh": title_zh_map.get(clean_title, ""),
            "url": raw.url,
            "published_at": iso(raw.published_at),
            "first_seen_at": iso(now),
            # 抓取器自带摘要（radarai 的 GitHub 项目中文描述等）→ 参与打分 + 前端摘要
            "summary": clean_summary,
        }
        all_items.append(record)

        if is_policy_relevant(clean_title, raw.url, raw.site_id, clean_summary):
            green_items.append(record)

    # 24h window filter for web output
    # 国外官方源更新频率低（周级）→ 用 7 天宽窗口，否则 96h 窗口常滤空
    # （2026-08-14：CARB 最新 08-07 / 环境省 08-07 / 资源能源厅 08-10 曾被 96h 滤掉）
    # 国际智库（E3G/Agora/TERI）周级~双周级 → 21 天宽窗口（2026-08-17）
    window_start = now - timedelta(hours=args.window_hours)
    foreign_win = now - timedelta(hours=7 * 24)
    low_freq_win = now - timedelta(hours=21 * 24)
    all_items_24h = [r for r in all_items if not r.get("published_at") or parse_iso(r["published_at"]) is None or parse_iso(r["published_at"]) >= window_start]
    green_items_24h = [r for r in green_items
                       if not r.get("published_at") or parse_iso(r["published_at"]) is None
                       or parse_iso(r["published_at"]) >= (low_freq_win if r.get("site_id") in LOW_FREQ_SITES
                                                          else foreign_win if r.get("site_id") in FOREIGN_GOV_SITES
                                                          else window_start)]

    # Sort
    def sort_key(r: dict) -> str:
        return r.get("published_at") or "0000-00-00"
    all_items_24h.sort(key=sort_key, reverse=True)
    green_items_24h.sort(key=sort_key, reverse=True)

    # ── Obsidian export ────────────────────────────────────────────────────
    obsidian_new = 0
    obsidian_with_body = 0
    if args.obsidian_dir:
        obsidian_new, obsidian_with_body = export_to_obsidian(green_items, args.obsidian_dir, now)

    # Backfill publish times in JSON from the local archive (detail-page times,
    # hour precision, Beijing). Newly exported notes are picked up immediately.
    # In CI (no Notes/ dir) the mapping comes from the committed published-index.json.
    archived_pub: dict[str, str] = {}
    archived_titles: dict[str, str] = {}
    archived_summaries: dict[str, str] = {}
    archived_tech_features: dict[str, str] = {}  # 技术特征缓存（2026-08-23 新增）
    if args.obsidian_dir:
        archived_pub = load_archived_published(args.obsidian_dir)
        archived_titles = load_archived_titles(args.obsidian_dir)
        archived_summaries = load_archived_summaries(args.obsidian_dir)
    else:
        pub_index_path = output_dir / "published-index.json"
        if pub_index_path.exists():
            try:
                archived_pub = json.loads(pub_index_path.read_text(encoding="utf-8"))
            except Exception:
                archived_pub = {}
        title_index_path = output_dir / "title-index.json"
        if title_index_path.exists():
            try:
                archived_titles = json.loads(title_index_path.read_text(encoding="utf-8"))
            except Exception:
                archived_titles = {}
        summary_index_path = output_dir / "summary-index.json"
        if summary_index_path.exists():
            try:
                archived_summaries = json.loads(summary_index_path.read_text(encoding="utf-8"))
            except Exception:
                archived_summaries = {}

    # 技术特征缓存（url → tech_feature，统一从 output_dir 加载，两个分支都适用）
    # 2026-08-23 修复：缓存 key 改用规范化标题（Google News 聚合 URL 每次抓取都变，
    # 按 URL 缓存永不命中 → 每次抓取对全部 Layer 2/3 条目重复调 LLM，实测卡 8+ 分钟）。
    # 旧 URL-key 缓存通过 history.json 的 url→title 映射自动转为标题 key。
    tech_feature_path = output_dir / "tech-feature-index.json"
    archived_tech_features: dict[str, str] = {}
    if tech_feature_path.exists():
        try:
            _tf_raw = json.loads(tech_feature_path.read_text(encoding="utf-8"))
        except Exception:
            _tf_raw = {}
        # URL key → 标题 key 迁移（幂等：标题 key 已存在则跳过）
        _hist: list = []
        _url_to_title: dict = {}
        try:
            _hist = (json.loads((output_dir / "history.json").read_text(encoding="utf-8")) or {}).get("items", []) or []
            _url_to_title = {it.get("url", ""): it.get("title", "") for it in _hist if it.get("url")}
        except Exception:
            pass
        for _k, _v in _tf_raw.items():
            if "://" in _k and _k in _url_to_title:  # 旧 URL key
                _tk = _title_dedup_key(_url_to_title[_k])
                if _tk:
                    archived_tech_features[_tk] = _v
            else:
                archived_tech_features[_k] = _v  # 已是标题 key 或新格式
        # 预填充：history.json 全部非政策条目（标题 key → tech_feature 或"无"），
        # 最大化命中率——raw 与 history 标题重叠度高（2026-08-23）
        try:
            for _it in (_hist or []):
                if not isinstance(_it, dict) or _it.get("dimension") == "政策":
                    continue
                _tk = _title_dedup_key(_it.get("title", ""))
                if _tk and _tk not in archived_tech_features:
                    archived_tech_features[_tk] = _it.get("tech_feature") or "无"
        except Exception:
            pass

    def _archived_to_iso(pub: str) -> str:
        if " " in pub:
            return pub.replace(" ", "T") + "+08:00"
        return pub + "T00:00:00+08:00"  # date-only → midnight Beijing

    # NOTE: green_items shares the same dict objects as all_items, so this
    # single pass covers both lists (do not loop green_items again — it would
    # overwrite time_source).
    # 2026-08-23 修复：只在窗口内条目（前端展示的）上做回填/打分/技术特征提取——
    # 原对全量 all_items（含窗口外 Google News 旧文）提取，667 条未命中 × 3-10s
    # LLM 调用 = 主流程卡死 8+ 分钟（62 天 0 条断源根因）。
    # ⚠️ 遍历集 = all_items_24h ∪ green_items_24h（green 用 7/21 天宽窗口，
    # 包含 96h 窗口外的条目——漏掉它们会缺 score/dimension/region 等字段）
    _to_process: dict[int, dict] = {id(r): r for r in all_items_24h}
    for _r in green_items_24h:
        _to_process.setdefault(id(_r), _r)
    _tf_missing: list[tuple[dict, str]] = []  # 技术特征未命中的 (rec, key)，循环后并发提取
    for rec in _to_process.values():
        # 完整标题回填：笔记里的标题已用详情页标题修正，列表页截断标题
        # （如碳交易网 "…现状与未"）会被覆盖为完整版（2026-08-11）。
        # 回填时同样清理尾部源名后缀（title-index.json 里可能存了旧带后缀标题）。
        # 2026-08-19 防污染：回填标题若本身是站名/导航（title-index 旧坏数据，
        # 如 chinanecc "国家节能中心公共服务网 - 节能研究"）或与列表标题不相似
        # （不是同一篇），禁止覆盖。
        full_title = _strip_title_suffix(archived_titles.get(rec.get("url", "")) or "")
        if (full_title and len(full_title) > len(rec.get("title", ""))
                and not _is_nav_junk_title(full_title)
                and _title_similar(full_title, rec.get("title", "")) >= 0.45):
            rec["title"] = full_title
            # 标题被回填修正后，重新翻译 title_zh（非中文才翻译，带缓存）
            if translator.needs_translation(full_title):
                _zh = translator.translate_title(full_title)
                if _zh:
                    rec["title_zh"] = _zh
        # 摘要回填（前端可展开摘要，News Minimalist 风格；2026-08-14）
        if not rec.get("summary"):
            summary = archived_summaries.get(rec.get("url", ""))
            if summary:
                # 2026-08-23：回填摘要也要过 _clean_summary（历史存的旧摘要
                # 可能残留"打印本页/关闭窗口"等页脚垃圾词——QA B2 实测）
                rec["summary"] = _clean_summary(summary)
        if not rec.get("published_at"):
            if rec.get("url") in archived_pub:
                rec["published_at"] = _archived_to_iso(archived_pub[rec["url"]])
                rec["time_source"] = "published"
            elif rec.get("first_seen_at"):
                # source site gives no publish time — record scrape time instead
                rec["published_at"] = rec["first_seen_at"]
                rec["time_source"] = "scraped"
        else:
            rec["time_source"] = "published"
        # 三层分类 + 七细类（2026-08-26 v5.0）：政策/创新/产业（中性命名）
        dimension, sub_dimension = categorize_dimension(
            rec.get("site_id", ""),
            rec.get("title", ""),
            rec.get("summary", ""),
            rec.get("library", "media"),
        )
        rec["dimension"] = dimension
        rec["sub_dimension"] = sub_dimension
        # layer 国际化字段（2026-08-23 新增）：Layer 1/2/3
        rec["layer"] = DIM_TO_LAYER.get(dimension, "Layer 2")
        # 国际标准分类法（2026-08-23 新增）：EU Taxonomy / ISIC / GICS / IPC
        rec["taxonomy"] = {
            "eu_taxonomy": classify_eu_taxonomy(rec.get("title", ""), rec.get("summary", "")),
            "isic": classify_isic(rec.get("site_id", ""), rec.get("title", ""), rec.get("summary", "")),
            "gics": classify_gics(rec.get("title", ""), rec.get("summary", "")),
            "ipc": classify_ipc(rec.get("title", ""), rec.get("summary", "")),
        }
        # 交叉技术标签 + TRL（2026-08-23 新增）
        rec["enabling_tech"] = classify_enabling_tech(rec.get("title", ""), rec.get("summary", ""))
        rec["trl"] = classify_trl(rec.get("title", ""), rec.get("summary", ""))
        # 技术特征提取（2026-08-23 新增，护城河字段）：仅 Layer 2/3 提取，Layer 1 政策类跳过
        rec["tech_feature"] = ""
        if dimension != "政策":
            _tf_key = _title_dedup_key(rec.get("title", "")) or rec.get("url", "")
            if _tf_key in archived_tech_features:
                rec["tech_feature"] = archived_tech_features[_tf_key]
            else:
                _tf_missing.append((rec, _tf_key))  # 循环后统一并发提取（2026-08-23）
        # 区域字段（2026-08-17）：前端排行榜/时间线「国内/国际」切换依赖
        rec["region"] = detect_region(rec.get("site_id", ""), rec.get("title", ""))
        # 主题标签（2026-08-19）：仅主题标签（TOPIC_RULES），供前端「关系图谱」
        # 展示主题标签共现；地域/政策类型等数据库管理标签不导出、前端不显示
        rec["topics"] = extract_topic_tags(rec.get("title", ""))
        # 打分体系 v4.0（2026-08-23）：内容强度按细类 + TRL 第 6 维度
        people = extract_people(rec.get("title", ""), rec.get("summary", ""), "")
        scoring = score_item(
            rec.get("site_id", ""),
            rec.get("title", ""),
            rec.get("summary", ""),
            people,
            rec.get("published_at", ""),
            now,
            sub_dimension,
            rec["trl"],
        )
        rec.update(scoring)
        if people:
            rec["people"] = people

    # 技术特征未命中项并发提取（2026-08-23：原串行，1200+ 条 × 3-10s = 卡死主流程；
    # SiliconFlow QPS=5，4 并发安全）。"无"也缓存（避免重复调 LLM）。
    if _tf_missing:
        print(f"  技术特征提取: {len(_tf_missing)} 条未命中缓存，并发 4 提取中（t+{time.monotonic()-_t0:.0f}s）", flush=True)
        from concurrent.futures import ThreadPoolExecutor as _TPE2, as_completed as _AC2
        with _TPE2(max_workers=4) as _ex:
            _futs = {_ex.submit(tech_feature.extract_tech_feature,
                                rec.get("title", ""), rec.get("summary", "")): (rec, k)
                     for rec, k in _tf_missing}
            for _fut in _AC2(_futs):
                rec, k = _futs[_fut]
                try:
                    _tf = _fut.result()
                except Exception:
                    _tf = ""
                if _tf:
                    if _tf != "无":
                        rec["tech_feature"] = _tf
                    archived_tech_features[k] = _tf  # "无"也缓存，避免重复调 LLM（2026-08-23）
        print(f"  技术特征提取完成（t+{time.monotonic()-_t0:.0f}s）", flush=True)
    if archived_pub:
        (output_dir / "published-index.json").write_text(
            json.dumps(archived_pub, ensure_ascii=False, indent=1), encoding="utf-8")

    # Persist the url→full-title map so CI runs can backfill truncated titles
    # (list pages truncate titles; full titles come from note headings)
    if archived_titles:
        (output_dir / "title-index.json").write_text(
            json.dumps(archived_titles, ensure_ascii=False, indent=1), encoding="utf-8")

    # Persist the url→summary map so CI runs can backfill summaries
    if archived_summaries:
        (output_dir / "summary-index.json").write_text(
            json.dumps(archived_summaries, ensure_ascii=False, indent=1), encoding="utf-8")

    # Persist the url→tech_feature map so CI runs can skip re-extraction (2026-08-23)
    if archived_tech_features:
        (output_dir / "tech-feature-index.json").write_text(
            json.dumps(archived_tech_features, ensure_ascii=False, indent=1), encoding="utf-8")

    # Backfilled times change sort order — re-sort newest first
    all_items_24h.sort(key=sort_key, reverse=True)
    green_items_24h.sort(key=sort_key, reverse=True)

    # ── Site stats ─────────────────────────────────────────────────────────
    site_stats: dict[str, dict[str, Any]] = {}
    for item in green_items_24h:
        sid = item["site_id"]
        if sid not in site_stats:
            site_stats[sid] = {"site_id": sid, "site_name": item["site_name"], "count": 0}
        site_stats[sid]["count"] += 1

    # ── Write outputs ──────────────────────────────────────────────────────
    green_payload = {
        "generated_at": iso(now),
        "window_hours": args.window_hours,
        "total_items": len(green_items_24h),
        "total_raw": len(all_items_24h),
        "site_count": len(site_stats),
        "site_stats": sorted(site_stats.values(), key=lambda x: x["count"], reverse=True),
        "items": green_items_24h,
    }

    all_payload = {
        "generated_at": iso(now),
        "window_hours": args.window_hours,
        "total_items": len(all_items_24h),
        "items": all_items_24h,
    }

    status_payload = {
        "generated_at": iso(now),
        "sites": source_statuses,
        "successful": sum(1 for s in source_statuses if s["ok"]),
        "failed": sum(1 for s in source_statuses if not s["ok"]),
        "total_raw_items": len(raw_items),
        "total_green_items": len(green_items_24h),
    }

    (output_dir / "latest-24h.json").write_text(
        json.dumps(green_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✅ 写文件: latest-24h {len(green_items_24h)} 条 → {output_dir}", flush=True)
    (output_dir / "latest-24h-all.json").write_text(
        json.dumps(all_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (output_dir / "source-status.json").write_text(
        json.dumps(status_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # 历史累积（2026-08-17）：日/周/月排行榜数据源，每次抓取合并新条目
    print(f"  merge_history 开始（{len(green_items_24h)} 条 24h 窗口）", flush=True)
    merge_history(output_dir, green_items_24h, now)
    print("  merge_history 完成", flush=True)

    # ── qmd 数据库增量导出（2026-08-24 一体式：抓取完成直接产出 qmd 富文本）──
    # 架构：JSON 是网站数据源（单一事实源），qmd 是 Obsidian 数据库层——
    # 同一步产出，无需独立脚本步骤。已存在正文的条目自动跳过（增量）。
    try:
        import export_qmd  # 同目录模块（sys.path[0]=scripts）
        qmd_out = Path(__file__).resolve().parent.parent / "Notes" / "数据库"
        qmd_n = export_qmd.export(Path(output_dir) / "latest-24h.json", qmd_out)
        if qmd_n:
            print(f"  ✅ qmd 增量导出: {qmd_n} 条 → {qmd_out}", flush=True)
    except Exception as _e:
        print(f"  ⚠️ qmd 导出失败（不阻断主流程）: {_e}", flush=True)

    print(f"✅ Green Policy Radar done.")
    print(f"   Green items: {len(green_items_24h)}")
    print(f"   All items:   {len(all_items_24h)}")
    print(f"   Sources:     {len(source_statuses)} ({status_payload['successful']} ok / {status_payload['failed']} failed)")
    if args.obsidian_dir:
        print(f"   Obsidian:    {obsidian_new} new notes → {args.obsidian_dir}/Notes/政策库/ ({obsidian_with_body} with 正文)")
    return 0


# ── 人物识别（人名标签，2026-08-14 新增） ─────────────────────────────────────
# 白名单：绿色政策领域关键人物（官员/专家/分析师）。
# name → (职务, [匹配关键词])。匹配范围 = 标题 + summary + 正文前 2000 字。
# 只收录独特姓名（三字名/极独特两字名），避免常见名误报。
PERSON_RULES: dict[str, tuple[str, list[str]]] = {
    # 部委官员
    "郑栅洁": ("国家发改委主任", ["郑栅洁"]),
    "周海兵": ("国家发改委副主任", ["周海兵"]),
    "沈竹林": ("国家发改委副主任", ["沈竹林"]),
    "李春临": ("国家发改委副主任", ["李春临"]),
    "黄润秋": ("生态环境部部长", ["黄润秋"]),
    "孙金龙": ("生态环境部党组书记", ["孙金龙"]),
    "赵英民": ("生态环境部副部长", ["赵英民"]),
    "万劲松": ("国家能源局副局长", ["万劲松"]),
    "李乐成": ("工信部部长", ["李乐成"]),
    # 学界专家
    "林伯强": ("厦门大学中国能源政策研究院院长", ["林伯强"]),
    "魏一鸣": ("北京理工大学能源与环境政策研究中心教授", ["魏一鸣"]),
    "杨昆": ("中电联党委书记、常务副理事长", ["杨昆"]),
    # 行业分析师
    "卢书剑": ("西南证券电新行业联席首席分析师", ["卢书剑"]),
    "张维鑫": ("中信建投期货分析师", ["张维鑫"]),
    "郑小霞": ("华安证券研究所联席所长、首席经济学家", ["郑小霞"]),
    "傅强": ("罗兰贝格副合伙人、能源行业首席专家", ["傅强"]),
    "张玉昕": ("弘则研究分析师", ["张玉昕"]),
}


def extract_people(title: str, summary: str = "", content: str = "") -> list[str]:
    """从标题/摘要/正文前 2000 字识别白名单人物，按出现顺序去重返回。"""
    text = " ".join([title or "", summary or "", (content or "")[:2000]])
    found: list[str] = []
    for name, (_role, keywords) in PERSON_RULES.items():
        if any(kw in text for kw in keywords):
            found.append(name)
    return found


def person_role(name: str) -> str:
    """返回人物职务（用于 wiki 展示），未知返回空串。"""
    return PERSON_RULES.get(name, ("", [""]))[0]


# ── Auto-tagging ────────────────────────────────────────────────────────────────
# Source → default region mapping
SOURCE_REGION: dict[str, str] = {
    "ndrc": "中国", "nea": "中国", "mee": "中国", "mee_jiedu": "中国", "miit": "中国",
    # 国外主要国家政策源（2026-08-14 新增）
    "us_epa": "美国", "us_doe": "美国", "eu_commission": "欧盟",
    "euractiv": "欧盟", "india_pib": "印度",
    # 美国/日本扩展官方源（2026-08-14 第二轮）
    "us_noaa": "美国", "us_eia": "美国", "us_ferc": "美国", "us_carb": "美国",
    "jp_moe": "日本", "jp_meti": "日本", "jp_anre": "日本",
    # 国际智库（2026-08-17 第三轮）
    "e3g": "欧盟", "agora": "欧盟", "teri": "印度",
    # 国际智库/投行（2026-08-19 第四轮）
    "brookings": "美国", "bruegel": "欧盟", "piie": "美国", "csis": "美国",
    "chatham": "欧盟", "carnegie": "美国", "rand": "美国",
    "americanprogress": "美国", "goldman": "美国",
    # 中国 P0 扩容（2026-08-19 第四轮）
    "caixin": "中国", "chinanecc": "中国", "thepaper": "中国",
    # AI 维度扩容（2026-08-19 第四轮）
    "artificialanalysis": "国际", "36kr": "中国", "huxiu": "中国",
    # 中国 P0 第二批（2026-08-14）
    "pbc": "中国", "cneeex": "中国", "ncsc": "中国", "caep": "中国",
    "cenews": "中国", "cnesa": "中国",
    "chinaenergy": "中国", "tanpaifang": "中国", "bjx": "中国", "ideacarbon": "中国",
    "iea": "国际", "irena": "国际", "unfccc": "国际", "worldbank": "国际",
    "carbonbrief": "国际",
    "cleantechnica": "国际", "ccai": "国际", "stdaily": "中国",
    "jiqizhixin": "中国", "qbitai": "中国", "openai": "国际",
    "venturebeat": "国际", "arxiv_ai": "国际", "aihot": "中国",
    "reuters": "全球",
    # 人形机器人/智能家居/绿色生活（2026-08-19 新增）
    "therobotreport": "全球", "spectrum": "全球", "mongabay": "全球",
    "greenbuilder": "美国", "greenpeace": "中国",
    "qianjia": "中国", "cheaa": "中国",
    "x": "全球",
    # 2026-08-19 审计补：radarai（GitHub 全球项目）/ allnet（微博知乎等国内热榜）
    "radarai": "国际", "allnet": "中国",
}


def detect_region(site_id: str, title: str) -> str:
    """来源默认地域 + 标题地域词修正（2026-08-19 修复）。

    之前只对「全球」源按标题细分——中国站（碳交易网/北极星/中国能源报）转载的
    国际新闻（欧委会/哥斯达黎加/马耳他/美国国会…）全被标成「中国」，前端
    「国内/国际」筛选错乱（老温实测国内出现欧委会/哥斯达黎加新闻）。
    改为：标题地域词判定**优先于 site 默认**（所有源），无命中回落 site 默认，
    再兜底「国际」。优先级：中国 > 欧盟 > 美国 > 日本 > 印度 > 泛国际。
    """
    t = title or ""
    t_lower = t.lower()
    # 1) 中国（具体机构名/国名，避免「国际/国家」泛词误判）
    if any(k in t for k in ("中国", "我国", "国内", "国家发改委", "发展改革委", "工信部", "国务院",
                            "生态环境部", "能源局", "人民银行", "央行", "全国碳市场", "国产")) \
       or any(k in t_lower for k in ("china", "beijing", "shanghai", "shenzhen")):
        return "中国"
    # 2) 欧盟（含「欧委会」——中国媒体对 European Commission 的简称；成员国家名）
    if any(k in t for k in ("欧委会", "欧盟", "欧洲", "马耳他", "德国", "法国", "英国", "意大利",
                            "西班牙", "荷兰", "比利时", "芬兰", "瑞典", "波兰", "葡萄牙", "爱尔兰",
                            "丹麦", "奥地利", "希腊", "匈牙利", "捷克", "罗马尼亚", "保加利亚",
                            "克罗地亚", "斯洛文尼亚", "斯洛伐克", "立陶宛", "拉脱维亚", "爱沙尼亚")) \
       or any(k in t_lower for k in ("eu ", "european", "brussels", "germany", "france", "italy",
                                     "spain", "poland", "netherlands", "sweden", "portugal")):
        return "欧盟"
    # 3) 美国
    if any(k in t for k in ("美国", "特朗普", "拜登", "加州")) \
       or any(k in t_lower for k in ("us ", "u.s.", "america", "washington", "trump", "biden",
                                     "california")):
        return "美国"
    # 4) 日本
    if any(k in t for k in ("日本", "东京")) or any(k in t_lower for k in ("japan", "tokyo")):
        return "日本"
    # 5) 印度
    if "印度" in t or "india" in t_lower:
        return "印度"
    # 6) 泛国际（其他地区/国际组织）
    if any(k in t for k in ("国际", "联合国", "全球", "伊朗", "中东", "沙特", "澳大利亚", "巴西",
                            "加拿大", "俄罗斯", "韩国", "乌克兰", "印尼", "越南", "非洲", "挪威",
                            "瑞士", "新加坡", "以色列", "土耳其", "墨西哥", "智利", "阿根廷",
                            "哥斯达黎加", "新西兰")) \
       or any(k in t_lower for k in ("international", "united nations", "global", "iran", "brazil",
                                     "canada", "russia", "korea", "ukraine", "australia", "saudi",
                                     "singapore", "turkey", "mexico", "chile")):
        return "国际"
    return SOURCE_REGION.get(site_id, "") or "国际"

# Topic tag rules: (tag, [keywords])
TOPIC_RULES: list[tuple[str, list[str]]] = [
    ("碳市场", ["碳交易", "碳市场", "碳价", "碳配额", "碳关税", "CBAM", "CCER", "碳排放权", "碳排",
                "carbon market", "carbon price", "carbon trading", "emissions trading", "ETS", "carbon border",
                "carbon", "emission", "emissions"]),  # 2026-08-19 审计补裸英文词（land-use emissions 等）
    ("新能源", ["新能源", "光伏", "风电", "光热", "氢能", "核能", "生物质", "水电",
                "solar", "wind power", "wind", "hydrogen", "nuclear", "renewable energy", "renewables"]),
    ("储能", ["储能", "电池", "抽水蓄能", "battery", "energy storage"]),
    ("电力", ["电力", "电网", "电价", "电力市场", "新型电力系统", "消纳", "用电", "发电",
              "electricity", "power grid", "power market"]),
    ("化石能源", ["煤炭", "石油", "天然气", "成品油", "LNG", "coal", "oil", "natural gas", "fossil fuel"]),
    ("节能降碳", ["节能", "能效", "绿色制造", "绿色低碳", "零碳工厂", "减排", "降碳",
                  "energy efficiency", "decarboni", "net zero", "net-zero", "zero carbon"]),
    ("气候变化", ["气候", "COP", "NDC", "巴黎协定", "碳中和", "碳达峰", "双碳", "温室气体",
                  "climate change", "climate policy", "climate", "paris agreement", "greenhouse"]),
    ("绿色金融", ["ESG", "绿色金融", "碳金融", "碳资产", "green finance", "green bond"]),
    ("环境保护", ["生态环境", "环境保护", "污染防治", "空气质量", "蓝天保卫战",
                  "environment", "pollution", "air quality", "conservation", "wildlife"]),
    ("循环经济", ["循环经济", "资源循环", "废弃物", "circular economy"]),
    ("电动车", ["电动车", "电动汽车", "EV", "充电桩", "electric vehicle"]),
    ("政策法规", ["条例", "办法", "规定", "标准", "规范", "法律法规", "司法解释",
                  "regulation", "legislation"]),
    ("AI科技", ["人工智能", "AI", "大模型", "机器学习", "智能电网", "数字孪生",
                "碳监测", "能碳", "智算", "算法", "数字化", "数智化",
                "artificial intelligence", "machine learning", "smart grid"]),
]

# Policy type tag rules
# 顺序即优先级：解读类放最前（"一图读懂/解读/专家" 优先于 "规划/通知" 等文件词，
# 否则官方解读文章会因标题含"规划"被标成 政策文件 — 2026-08-14 调整）
POLICY_TYPE_RULES: list[tuple[str, list[str]]] = [
    ("政策解读", ["解读", "专家", "一图读懂", "答记者问"]),
    ("政策文件", ["通知", "意见", "办法", "条例", "规划", "方案", "公告", "印发", "关于印发"]),
    ("新闻发布会", ["新闻发布会", "答问", "通报", "发布", "发布会"]),
    ("数据报告", ["报告", "数据", "统计", "年报", "季报"]),
]


def extract_topic_tags(title: str) -> list[str]:
    """仅提取主题标签（TOPIC_RULES），不含地域/政策类型等管理标签（2026-08-19）。

    前端「关系图谱」依赖此字段展示主题标签共现关系——地域(#中国/#欧盟…)与
    政策类型(#政策文件/#数据报告…)属于数据库管理标签，不在此导出、前端不显示。
    """
    import re as _tag_re
    title_lower = (title or "").lower()
    tags: list[str] = []
    for tag, keywords in TOPIC_RULES:
        for kw in keywords:
            kw_lower = kw.lower()
            # ASCII 短词用「负向环视」词边界（2026-08-19 审计修复）：
            # Python \b 把汉字当 \w，\bai\b 在 "AI诉讼" 中不匹配 → AI科技标签
            # 漏标大量中文标题（实测 Anthropic AI诉讼/DeepMind AI路线 全漏）。
            # (?<![a-z])ai(?![a-z]) 只认 ASCII 字母边界，中文上下文也能命中。
            if len(kw) <= 3 and kw.isascii() and kw.isalpha():
                pattern = r"(?<![a-z])" + _tag_re.escape(kw_lower) + r"(?![a-z])"
                if _tag_re.search(pattern, title_lower):
                    tags.append(tag)
                    break
            elif kw_lower in title_lower:
                tags.append(tag)
                break  # one match per topic
    return tags


def auto_tag(title: str, site_id: str) -> list[str]:
    """Generate tags for a news item based on title and source."""
    tags: list[str] = extract_topic_tags(title)
    title_lower = title.lower()

    # Region tag
    region = detect_region(site_id, title)
    if region:
        tags.insert(0, region)  # region first

    # Policy type tag
    ptype = "行业动态"  # default
    for tag, keywords in POLICY_TYPE_RULES:
        for kw in keywords:
            if kw.lower() in title_lower:
                ptype = tag
                break
        if ptype != "行业动态":
            break
    tags.append(ptype)

    # Fallback
    if not any(t not in (region, ptype) for t in tags):
        tags.append("行业动态")

    # Dedup while preserving order
    seen = set()
    result = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


# ── Obsidian export ────────────────────────────────────────────────────────────
def format_published(iso_str: str) -> str:
    """Convert RSS iso timestamp to Beijing-time 'YYYY-MM-DD HH:MM'."""
    dt = parse_iso(iso_str)
    if not dt:
        return ""
    return dt.astimezone(SH_TZ).strftime("%Y-%m-%d %H:%M")


def load_archived_published(base_dir_str: str) -> dict[str, str]:
    """Map url -> published (Beijing 'YYYY-MM-DD HH:MM') from existing notes
    (政策库 + 媒体库)."""
    mapping: dict[str, str] = {}
    notes_root = Path(base_dir_str) / "Notes"
    if not notes_root.exists():
        return mapping
    for p in notes_root.rglob("*.md"):
        if p.name in ("政策库.md", "媒体库.md", "ai-index.md"):
            continue
        try:
            content = p.read_text(encoding="utf-8")
            if not content.startswith("---"):
                continue
            fm: dict[str, str] = {}
            for line in content.split("\n")[1:]:
                if line.strip() == "---":
                    break
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"')
            url = fm.get("url", "")
            pub = fm.get("published", "")
            if url and pub:
                mapping[url] = pub
        except Exception:
            continue
    return mapping


def load_archived_titles(base_dir_str: str) -> dict[str, str]:
    """Map url -> full title from existing notes' # heading.

    列表页标题常被源站截断（碳交易网等），笔记标题已用详情页标题回填过
    （backfill_full_titles.py），这里把完整标题同步回 JSON。
    """
    mapping: dict[str, str] = {}
    notes_root = Path(base_dir_str) / "Notes"
    if not notes_root.exists():
        return mapping
    for p in notes_root.rglob("*.md"):
        if p.name in ("政策库.md", "媒体库.md", "ai-index.md"):
            continue
        try:
            content = p.read_text(encoding="utf-8")
            m = re.search(r"^# (.+)$", content, re.M)
            if not m:
                continue
            um = re.search(r"^url:\s*(\S+)", content, re.M)
            if not um:
                continue
            mapping[um.group(1)] = m.group(1).strip()
        except Exception:
            continue
    return mapping


def load_archived_summaries(base_dir_str: str) -> dict[str, str]:
    """Map url -> summary from existing notes' frontmatter (政策库 + 媒体库).

    2026-08-14 新增：首页学 News Minimalist 做「可展开摘要」，需要把笔记里的
    summary 同步进 JSON（前端无需再抓正文）。
    """
    mapping: dict[str, str] = {}
    notes_root = Path(base_dir_str) / "Notes"
    if not notes_root.exists():
        return mapping
    for p in notes_root.rglob("*.md"):
        if p.name in ("政策库.md", "媒体库.md", "ai-index.md"):
            continue
        try:
            content = p.read_text(encoding="utf-8")
            um = re.search(r"^url:\s*(\S+)", content, re.M)
            sm = re.search(r'^summary:\s*"?(.+?)"?\s*$', content, re.M)
            if not um or not sm:
                continue
            summary = sm.group(1).strip().rstrip('"')
            if summary and len(summary) > 8:
                mapping[um.group(1)] = summary
        except Exception:
            continue
    return mapping


def export_to_obsidian(items: list[dict], base_dir_str: str, now: datetime) -> tuple[int, int]:
    """Export news items as Obsidian markdown notes.

    Returns (new_note_count, notes_with_body_count). Body/summary fetched
    concurrently; fetch failures degrade gracefully to link-only cards.
    """
    import re as _re
    notes_root = Path(base_dir_str) / "Notes"
    notes_root.mkdir(parents=True, exist_ok=True)

    # ── 1) plan new notes (dedup by filename AND by url) ────────────────────
    planned: list[tuple[Path, dict]] = []  # (filepath, item)
    # url → already exists in target dir? (文件名会因标题修正而变化，URL 稳定)
    seen_urls: set[str] = set()
    # url → 缺摘要的旧笔记路径（需重新抓正文补摘要，之后替换/删除）
    stale_files: dict[str, Path] = {}
    for existing in notes_root.rglob("*.md"):
        if existing.name in ("政策库.md", "媒体库.md", "ai-index.md"):
            continue
        try:
            _c = existing.read_text(encoding="utf-8")
            _m = _re.search(r"^url:\s*(\S+)", _c, re.M)
            if not _m:
                continue
            _url = _m.group(1)
            # 有摘要的笔记才算「已完善」，跳过；缺摘要的笔记标为待刷新，
            # 重新抓正文补摘要（修复国外政府源 Google News 解码后摘要为空 —
            # 2026-08-18）。
            if _re.search(r'^summary:\s*"[^"]', _c, re.M):
                seen_urls.add(_url)
            else:
                stale_files[_url] = existing
        except Exception:
            continue
    for item in items:
        site_id = item.get("site_id", "unknown")
        site_name = item.get("site_name", site_id)
        title = item.get("title", "untitled")
        url = item.get("url", "")
        pub_date = item.get("published_at", "")

        if url in seen_urls:
            continue  # 该 URL 已有笔记且已含摘要
        safe_site = _re.sub(r'[<>:"/\\|?*]', '_', site_name).strip()
        # Library layout: 政策库/<分组>/<站点>/  or  媒体库/<站点>/
        if site_library(site_id) == "media":
            site_dir = notes_root / "媒体库" / safe_site
        else:
            group = site_policy_group(site_id) or "其他"
            site_dir = notes_root / "政策库" / group / safe_site
        site_dir.mkdir(parents=True, exist_ok=True)

        safe_title = _re.sub(r'[<>:"/\\|?*]', '_', title)[:80].strip()
        if pub_date:
            date_prefix = pub_date[:10]  # YYYY-MM-DD
            filename = f"{date_prefix} {safe_title}.md"
        else:
            filename = f"{safe_title}.md"
        filepath = site_dir / filename

        # 同名文件已存在：只有「缺摘要待刷新」的旧笔记才允许覆盖重写
        if filepath.exists() and url not in stale_files:
            continue
        planned.append((filepath, item))

    # ── 2) fetch body + summary concurrently ─────────────────────────────────
    bodies: dict[str, Optional[dict]] = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {
            ex.submit(article_content.fetch_article, it.get("url", "")):
                (fp, it) for fp, it in planned
        }
        for fut in as_completed(futures):
            fp, it = futures[fut]
            try:
                res = fut.result()
            except Exception:
                res = None
            bodies[str(fp)] = res

    # ── 3) write notes ───────────────────────────────────────────────────────
    new_count = 0
    body_count = 0
    for fp, item in planned:
        site_name = item.get("site_name", item.get("site_id", "unknown"))
        title = item.get("title", "untitled")
        url = item.get("url", "")
        pub_date = item.get("published_at", "")
        res = bodies.get(str(fp))
        # Google News 解码成功 → 用真实 URL 覆盖（2026-08-19）：
        # ① 笔记 frontmatter 存真实链接（而非 base64 假链接，Obsidian 里可直接打开）
        # ② 下次抓取同一新闻（解码后同一真实 URL）可匹配 stale_files 自动补正文
        real_url = (res or {}).get("real_url") or ""
        if real_url and real_url != url:
            url = real_url
            item["url"] = real_url  # record 共享引用 → JSON 同步
        # 详情页标题优先：列表页标题常被源站截断（如碳交易网列表页
        # "…现状与未"），详情页 <title>/<h1> 是完整的（2026-08-11）。
        # 2026-08-19 加相似度门槛：详情页 title 是站名/栏目/导航（chinanecc
        # "国家节能中心公共服务网 - 节能研究"、EIA 站名、arXiv 分类面包屑）时
        # 与列表标题重叠 < 0.5，禁止覆盖，保留列表标题。
        page_title = (res or {}).get("title") or ""
        if (page_title and len(page_title) > len(title)
                and _title_similar(page_title, title) >= 0.45):
            title = page_title.strip()
            item["title"] = title  # record 共享引用 → JSON 同步
        summary = (res or {}).get("summary") or ""
        content = (res or {}).get("content") or ""
        source_org = (res or {}).get("source_org") or ""
        # Publish time: detail-page time (hour precision) wins, RSS time as fallback
        published = (res or {}).get("published") or ""
        if not published:
            published = format_published(item.get("published_at", ""))
        # 2026-08-20 修复：详情页/RSS 都没有时间 → published 留空，**绝不拿抓取当天
        # 冒充发布时间**——兜底当天会被 published-index 永久固化（实测 chinanecc
        # 4-23 的《碳达峰碳中和综合评价考核办法》答记者问被标成 8-19 首抓日）。
        # 无时间条目由 JSON 侧 first_seen_at + time_source='scraped' 表达「收录时间」，
        # 前端显示「收录 X」（抓取时间仅作新鲜度判断，不冒充原文发布时间）。
        date_val = (item.get("published_at") or "")[:10]
        if published and not date_val:
            date_val = published[:10]
        tags = auto_tag(title, item.get("site_id", ""))
        tag_str = ", ".join(tags)
        kw_set = set(tags)
        for t in title.replace("：", " ").replace("，", " ").replace("、", " ").split():
            t = _re.sub(r"[,，.。、:：;；!！?？'\"‘’“”()（）\[\]【】]", "", t).strip()
            if len(t) >= 2 and len(t) <= 12 and not t.startswith(("http", "www")):
                kw_set.add(t)
        kw_str = ", ".join(sorted(kw_set)[:15])
        lines = [
            "---",
            f'source: "{site_name}"',
            f"url: {url}",
            f"date: {date_val}",
            f"tags: [{tag_str}]",
            f"keywords: [{kw_str}]",
        ]
        if published:
            lines.append(f'published: "{published}"')
        if source_org:
            safe_org = source_org.replace(chr(34), chr(39))
            lines.append(f'author: "{safe_org}"')
        if summary:
            safe_summary = summary.replace(chr(34), chr(39)).replace("\n", " ")
            lines.append(f'summary: "{safe_summary}"')
        # 人物标签（2026-08-14）：标题+摘要+正文识别白名单人物
        people = extract_people(title, summary, content)
        if people:
            lines.append(f"people: [{', '.join(people)}]")
        lines += [
            "---",
            "",
            f"# {title}",
            "",
            f"[原文链接]({url})",
            "",
            f"> 来源: {site_name}",
            f"> 首次抓取: {now.strftime('%Y-%m-%d %H:%M')} UTC",
        ]
        if published:
            lines.append(f"> 发布时间: {published}")
        if source_org:
            lines.append(f"> 作者: {source_org}")
        if people:
            people_links = "、".join(f"[[人物/{p}|{p}]]" for p in people)
            lines.append(f"> 人物: {people_links}")
        if content:
            lines += ["", "## 正文", "", content]
            body_count += 1

        fp.write_text("\n".join(lines), encoding="utf-8")
        new_count += 1

    # 删除被替换的旧笔记（缺摘要 → 已重新生成；标题修正后文件名可能变化，
    # 旧文件名会残留成重复笔记，需清理）
    for fp, item in planned:
        _url = item.get("url", "")
        _old = stale_files.get(_url)
        if _old and _old != fp and _old.exists():
            try:
                _old.unlink()
            except Exception:
                pass

    # Update index pages (政策库 + 媒体库)
    _update_obsidian_index(notes_root / "政策库", now)
    _update_media_index(notes_root / "媒体库", now)
    # Update AI-readable index (政策库 + 媒体库)
    _update_ai_index(notes_root / "政策库", now)
    _update_ai_index(notes_root / "媒体库", now)
    return new_count, body_count


def _update_obsidian_index(base: Path, now: datetime) -> None:
    """Create dataview-powered index page for 政策库 (grouped: 中国/国际组织)."""
    index_path = base / "政策库.md"
    note_count = sum(1 for _ in base.rglob("*.md") if _.name != "政策库.md")
    group_dirs = sorted(d.name for d in base.iterdir() if d.is_dir() and d.name != "ai-index.md")

    source_list = ""
    for g in group_dirs:
        source_list += f"### {g}\n"
        for s in sorted(d.name for d in (base / g).iterdir() if d.is_dir()):
            count = sum(1 for _ in (base / g / s).glob("*.md"))
            source_list += f"- [[{g}/{s}/|{s}]] ({count} 篇)\n"
        source_list += "\n"

    content = f"""---
tags: [MOC, 政策库]
updated: {now.strftime('%Y-%m-%d %H:%M')}
---

# 🌿 绿色政策库

> 第一手权威原始出处：部委原文 / 国际组织报告。总计 **{note_count}** 篇笔记

## 信息源

{source_list}

## 最近更新

```dataview
TABLE source as "来源", date as "日期"
FROM "Notes/政策库"
SORT date DESC
LIMIT 50
```

## 按标签浏览

### 碳市场
```dataview
TABLE date as "日期", source as "来源"
FROM "Notes/政策库"
WHERE contains(tags, "碳市场")
SORT date DESC
LIMIT 20
```

### 新能源
```dataview
TABLE date as "日期", source as "来源"
FROM "Notes/政策库"
WHERE contains(tags, "新能源")
SORT date DESC
LIMIT 20
```

### 电力
```dataview
TABLE date as "日期", source as "来源"
FROM "Notes/政策库"
WHERE contains(tags, "电力")
SORT date DESC
LIMIT 20
```

### 政策文件
```dataview
TABLE date as "日期", source as "来源"
FROM "Notes/政策库"
WHERE contains(tags, "政策文件")
SORT date DESC
LIMIT 20
```

### 气候变化
```dataview
TABLE date as "日期", source as "来源"
FROM "Notes/政策库"
WHERE contains(tags, "气候变化")
SORT date DESC
LIMIT 20
```
"""
    index_path.write_text(content, encoding="utf-8")


def _update_media_index(base: Path, now: datetime) -> None:
    """Create dataview-powered index page for 媒体库 (flat site dirs)."""
    index_path = base / "媒体库.md"
    note_count = sum(1 for _ in base.rglob("*.md") if _.name != "媒体库.md")
    source_dirs = sorted(d.name for d in base.iterdir() if d.is_dir() and d.name != "ai-index.md")

    source_list = ""
    for s in source_dirs:
        count = sum(1 for _ in (base / s).glob("*.md"))
        source_list += f"- [[{s}/|{s}]] ({count} 篇)\n"

    content = f"""---
tags: [MOC, 媒体库]
updated: {now.strftime('%Y-%m-%d %H:%M')}
---

# 📰 媒体库

> 第二手转述/解读：行业媒体与通讯社（碳交易网、能源报、北极星、碳道、Carbon Brief、Reuters）。总计 **{note_count}** 篇笔记

## 信息源

{source_list}

## 最近更新

```dataview
TABLE source as "来源", date as "日期"
FROM "Notes/媒体库"
SORT date DESC
LIMIT 50
```
"""
    index_path.write_text(content, encoding="utf-8")


def _update_ai_index(base: Path, now: datetime) -> None:
    """Generate AI-readable plain-text index of all policy documents."""
    index_path = base / "ai-index.md"
    entries: list[dict] = []
    lib_name = base.name  # 政策库 / 媒体库
    index_files = {"政策库.md", "媒体库.md", "ai-index.md"}

    for root, dirs, files in os.walk(str(base)):
        for f in files:
            if f.endswith(".md") and f not in index_files:
                fpath = Path(root) / f
                rel = str(fpath.relative_to(base))
                # 容错（2026-08-14）：NTFS/WSL 下文件名偶有隐藏差异
                # （Windows 自动去尾空格/点、8.3 短名等），os.walk 列出但 read 失败时跳过
                try:
                    content = fpath.read_text(encoding="utf-8")
                except Exception:
                    continue
                fm: dict[str, str] = {}
                in_fm = False
                for line in content.split("\n"):
                    if line.strip() == "---":
                        if not in_fm:
                            in_fm = True
                        else:
                            break
                    elif in_fm:
                        if ":" in line:
                            k, v = line.split(":", 1)
                            fm[k.strip()] = v.strip().strip('"')
                entries.append({
                    "file": rel,
                    "title": fm.get("title", f),
                    "source": fm.get("source", ""),
                    "date": fm.get("date", ""),
                    "published": fm.get("published", ""),
                    "author": fm.get("author", ""),
                    "tags": fm.get("tags", ""),
                    "people": fm.get("people", ""),
                    "keywords": fm.get("keywords", ""),
                    "summary": fm.get("summary", ""),
                    "url": fm.get("url", ""),
                })

    entries.sort(key=lambda e: e["date"], reverse=True)

    lines = [
        "---",
        f"updated: {now.strftime('%Y-%m-%d %H:%M')}",
        "type: ai-index",
        f"total: {len(entries)}",
        "---",
        "",
        "# AI Policy Index",
        "",
        f"> Machine-readable catalog. {len(entries)} docs. grep-friendly.",
        "",
        "## By Date",
        "",
    ]

    for e in entries:
        lines.append(f"### {e['date']} | {e['source']} | {e['file']}")
        lines.append(f"- Title: {e['title']}")
        lines.append(f"- Published: {e.get('published', '') or '(unknown)'}")
        if e.get("author"):
            lines.append(f"- Author: {e['author']}")
        if e.get("people"):
            lines.append(f"- People: {e['people']}")
        lines.append(f"- Tags: {e['tags']}")
        lines.append(f"- Keywords: {e['keywords']}")
        summary = e.get("summary", "")
        lines.append(f"- Summary: {summary[:150] if summary else '(none)'}")
        lines.append(f"- URL: {e['url']}")
        lines.append("")

    # Topic index
    topic_index: dict[str, list[str]] = {}
    for e in entries:
        for tag in e["tags"].replace("[", "").replace("]", "").split(","):
            tag = tag.strip()
            if tag and tag not in ("MOC", "政策库", "媒体库", "wiki"):
                topic_index.setdefault(tag, []).append(e["file"])

    lines.append("## By Topic")
    lines.append("")
    for topic in sorted(topic_index.keys()):
        lines.append(f"### {topic} ({len(topic_index[topic])} docs)")
        for doc in topic_index[topic][:30]:
            lines.append(f"- {doc}")
        lines.append("")

    index_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
