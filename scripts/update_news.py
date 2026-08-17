#!/usr/bin/env python3
"""Green Policy News Radar — aggregate green/low-carbon policy updates from global sources."""

from __future__ import annotations

import argparse
import hashlib
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
            items.append(RawItem(
                site_id=site_id, site_name=site_name,
                source=source, title=title, url=link,
                published_at=published,
                meta={"feed_url": feed_url},
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
    queries = [
        '"jiqizhixin.com" 大模型 OR 模型 OR AI',
        '"jiqizhixin.com" 芯片 OR 算力 OR 机器人',
        '"jiqizhixin.com" 智能体 OR 自动驾驶 OR 融资',
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
                # 去掉尾部 " - EPA (.gov)" 类来源标记再判导航碎片
                title_clean = title.rsplit(" - ", 1)[0].strip()
                if len(title_clean) < 8:
                    continue
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=UTC)
                    except Exception:
                        pass
                items.append(RawItem(
                    site_id=site_id, site_name=site_name,
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
    return out[:limit]


def fetch_us_epa(session: requests.Session, now: datetime) -> list[RawItem]:
    """美国环保署 EPA — 温室气体法规、发电厂排放标准（2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "us_epa", "美国EPA", [
        "site:epa.gov (climate OR emissions OR greenhouse) when:7d",
        "site:epa.gov (power plant OR methane OR carbon pollution) when:7d",
    ])


def fetch_us_doe(session: requests.Session, now: datetime) -> list[RawItem]:
    """美国能源部 DOE — 清洁能源计划、关键矿产、贷款项目（2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "us_doe", "美国DOE", [
        "site:energy.gov (clean energy OR solar OR grid OR battery OR hydrogen) when:7d",
        "site:energy.gov (loan program OR critical minerals OR nuclear OR wind) when:7d",
    ])


def fetch_eu_commission(session: requests.Session, now: datetime) -> list[RawItem]:
    """欧盟委员会 — 气候行动总司/能源总司：Fit for 55、CBAM、EU ETS（2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "eu_commission", "欧盟委员会", [
        "site:ec.europa.eu (climate OR emissions OR CBAM OR carbon) when:7d",
        "site:ec.europa.eu (energy OR renewables OR hydrogen OR grid) when:7d",
    ])


def fetch_euractiv(session: requests.Session, now: datetime) -> list[RawItem]:
    """Euractiv（布鲁塞尔）— 欧盟政策专业媒体（2026-08-14 新增）。

    归政策库·国际（欧盟政策一手报道），媒体属性但政策浓度高。
    """
    return fetch_foreign_gov(session, now, "euractiv", "Euractiv·欧盟", [
        "site:euractiv.com (climate OR energy OR emissions OR carbon) when:7d",
        "site:euractiv.com (CBAM OR ETS OR renewables OR green deal) when:7d",
    ])


def fetch_india_pib(session: requests.Session, now: datetime) -> list[RawItem]:
    """印度新闻信息局 PIB — 绿氢使命、气候政策、可再生能源（2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "india_pib", "印度PIB", [
        "site:pib.gov.in (climate OR renewable OR solar OR energy) when:7d",
        "site:pib.gov.in (green hydrogen OR emissions OR carbon OR sustainability) when:7d",
    ])


# ── 美国/日本扩展官方源（2026-08-14 第二轮：NOAA/EIA/FERC/CARB/MOE/METI/ANRE） ──
def fetch_us_noaa(session: requests.Session, now: datetime) -> list[RawItem]:
    """美国国家海洋大气局 NOAA — 气候科学、温室气体监测、海洋与大气（2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "us_noaa", "美国NOAA", [
        "site:noaa.gov (climate change OR greenhouse OR carbon dioxide) when:7d",
        "site:noaa.gov (ocean warming OR sea level OR emissions) when:7d",
    ])


def fetch_us_eia(session: requests.Session, now: datetime) -> list[RawItem]:
    """美国能源信息署 EIA — 能源统计与预测（天然气/电力/可再生，权威数据源，2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "us_eia", "美国EIA", [
        "site:eia.gov (natural gas OR electricity OR renewables) when:7d",
        "site:eia.gov (emissions OR energy outlook OR battery OR solar) when:7d",
    ])


def fetch_us_ferc(session: requests.Session, now: datetime) -> list[RawItem]:
    """美国联邦能源监管委员会 FERC — 电网/输电/LNG/电力市场监管（2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "us_ferc", "美国FERC", [
        "site:ferc.gov (grid OR transmission OR electricity OR LNG) when:14d",
        "site:ferc.gov (reliability OR interconnection OR wholesale market) when:14d",
    ])


def fetch_us_carb(session: requests.Session, now: datetime) -> list[RawItem]:
    """加州空气资源委员会 CARB — 零排放汽车、碳市场、气候政策（美国州级最权威，2026-08-14 新增）。"""
    return fetch_foreign_gov(session, now, "us_carb", "加州CARB", [
        "site:ww2.arb.ca.gov (climate OR zero emission OR cap and trade) when:30d",
        "site:ww2.arb.ca.gov (trucks OR cars OR diesel OR regulations) when:30d",
    ])


def fetch_jp_moe(session: requests.Session, now: datetime) -> list[RawItem]:
    """日本环境省 MOE — 气候政策、脱碳、碳市场（2026-08-14 新增，日语关键词）。"""
    return fetch_foreign_gov(session, now, "jp_moe", "日本环境省", [
        "site:env.go.jp (脱炭素 OR 気候変動対策 OR カーボンニュートラル) when:14d",
        "site:env.go.jp (地球温暖化 OR 温室効果ガス OR 排出量取引) when:14d",
    ], limit=15, locale="ja")


def fetch_jp_meti(session: requests.Session, now: datetime) -> list[RawItem]:
    """日本经济产业省 METI — 能源政策、GX、氢能（2026-08-14 新增，日语关键词）。"""
    return fetch_foreign_gov(session, now, "jp_meti", "日本经产省", [
        "site:meti.go.jp (エネルギー OR 脱炭素 OR 水素 OR GX) when:14d",
        "site:meti.go.jp (再生可能エネルギー OR 電力 OR カーボン) when:14d",
    ], limit=15, locale="ja")


def fetch_jp_anre(session: requests.Session, now: datetime) -> list[RawItem]:
    """日本资源能源厅 ANRE（经产省下属）— 电力/油气/可再生能源政策（2026-08-14 新增，日语关键词）。"""
    return fetch_foreign_gov(session, now, "jp_anre", "日本资源能源厅", [
        "site:enecho.meti.go.jp (再生可能 OR 水素 OR 脱炭素) when:14d",
        "site:enecho.meti.go.jp (電力 OR エネルギー OR 石油 OR ガス) when:14d",
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
        "site:e3g.org (climate OR energy OR emissions OR carbon) when:30d",
        "site:e3g.org (finance OR policy OR transition OR grid) when:30d",
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
            "site:cneeex.com (碳市场 OR 碳价 OR 配额 OR 碳交易) when:30d",
            "site:cneeex.com (碳排放 OR 环交所 OR 碳金融) when:30d",
        ], limit=15, locale="zh-CN")
    return items[:20]


def fetch_ncsc(session: requests.Session, now: datetime) -> list[RawItem]:
    """国家应对气候变化战略研究和国际合作中心 NCSC — 气候战略/碳市场研究（2026-08-14 接入）。"""
    return fetch_foreign_gov(session, now, "ncsc", "NCSC国家气候中心", [
        "site:ncsc.org.cn (气候 OR 碳市场 OR 碳中和 OR 碳达峰) when:30d",
        "site:ncsc.org.cn (温室气体 OR 减排 OR 政策) when:30d",
    ], limit=10, locale="zh-CN")


def fetch_caep(session: requests.Session, now: datetime) -> list[RawItem]:
    """生态环境部环境规划院 CAEP — 环境规划/双碳路径（2026-08-14 接入）。"""
    return fetch_foreign_gov(session, now, "caep", "环境规划院CAEP", [
        "site:caep.org.cn (环境 OR 双碳 OR 规划 OR 美丽中国) when:30d",
        "site:caep.org.cn (碳 OR 气候 OR 减污降碳) when:30d",
    ], limit=10, locale="zh-CN")


def fetch_cenews(session: requests.Session, now: datetime) -> list[RawItem]:
    """中国环境报 — 生态环境部机关报（2026-08-14 接入，媒体库）。"""
    return fetch_foreign_gov(session, now, "cenews", "中国环境报", [
        "site:cenews.com.cn (生态 OR 环境 OR 双碳) when:14d",
        "site:cenews.com.cn (碳市场 OR 绿色 OR 污染防治) when:14d",
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
    """北极星电力网 — via Google News (direct site blocked by Alibaba WAF)."""
    import feedparser as fp
    items: list[RawItem] = []
    try:
        r = session.get(
            "https://news.google.com/rss/search",
            params={"q": "北极星电力网 新能源 电力 储能 光伏 风电", "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"},
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
                site_id="bjx", site_name="北极星电力网",
                title=title, url=link,
                published_at=_entry_published(entry),
            ))
    except Exception:
        pass
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


# ── OPML RSS ──────────────────────────────────────────────────────────────────
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

# 1) 内容强度分（按维度自适应，0-30）——每维度按关键词从高到低取第一档
#    结构: {dimension: [(score, [keywords]), ...]}，末尾 () 为默认档
CONTENT_STRENGTH_RULES: dict[str, list[tuple[int, list[str]]]] = {
    "政策": [
        (30, ["印发", "通知", "意见", "条例", "办法", "规划", "方案", "公告",
              "答记者问", "政策文件", "发布", "国务院"]),
        (25, ["解读", "一图读懂", "新闻发布会", "吹风会"]),
        (20, ["报告", "数据", "统计", "年报", "季报"]),
        (10, []),
    ],
    "技术": [
        (30, ["突破", "首次", "首发", "成功", "世界首个", "全球首个", "里程碑",
              "实现", "投产", "并网", "交付", "建成"]),
        (20, ["进展", "研发", "上线", "落地", "试点", "示范", "应用", "试验",
              "回收", "产量", "扩产", "测试", "验证", "升级", "改造", "效率",
              "recycle", "yield", "output", "test", "upgrade", "efficiency"]),
        (10, []),
    ],
    "金融": [
        (30, ["扩围", "大涨", "突破", "新高", "首次", "创纪录", "启动", "成交",
              "破", "亿元", "覆盖"]),
        (20, ["价格", "指数", "报告", "数据", "融资", "投资", "交易", "配额"]),
        (8, []),
    ],
    "AI科技": [
        (30, ["落地", "应用", "发布", "大模型", "智能体", "突破", "首发",
              "平台", "上线", "部署", "启用"]),
        (20, ["研究", "方法", "评估", "预测", "优化", "监测", "算法", "模型",
              "adaptation", "response", "pathway", "framework", "system",
              "tool", "dataset", "workshop", "grant"]),
        (8, []),
    ],
}
DEFAULT_STRENGTH = 8


def score_content_strength(dimension: str, title: str, summary: str) -> int:
    """内容强度分：按维度关键词档位，从高到低取第一命中档。"""
    text = f"{title or ''} {summary or ''}"
    rules = CONTENT_STRENGTH_RULES.get(dimension, CONTENT_STRENGTH_RULES["政策"])
    for score, kws in rules:
        if any(kw in text for kw in kws):
            return score
    return DEFAULT_STRENGTH


# 2) 来源权威分（site_id → 0-25，v2.0 上限从 30 压缩）
SOURCE_SCORE: dict[str, int] = {
    # 部委官方
    "ndrc": 25, "mee": 25, "nea": 25, "miit": 25,
    # 国外主要国家政策源（2026-08-14 新增：官方部委档）
    "us_epa": 25, "us_doe": 25, "eu_commission": 25,
    "euractiv": 20, "india_pib": 25,
    # 美国/日本扩展官方源（2026-08-14 第二轮：部委/联邦机构档）
    "us_noaa": 25, "us_eia": 25, "us_ferc": 25, "us_carb": 25,
    "jp_moe": 25, "jp_meti": 25, "jp_anre": 25,
    # 国际智库（2026-08-17 第三轮：专家解读/政策评论档，同碳道/CCAI）
    "e3g": 18, "agora": 18, "teri": 18,
    # 中国 P0 第二批（2026-08-14：官方机构档）
    "pbc": 25, "cneeex": 25, "ncsc": 25, "caep": 25,
    "cenews": 16, "cnesa": 16,
    # 官方解读（部委网站发布的专家解读）
    "mee_jiedu": 23,
    # 国际组织
    "iea": 22, "irena": 22, "unfccc": 22, "worldbank": 22,
    # 专业政策/碳媒体 + AI×气候专业
    "tanpaifang": 18, "ideacarbon": 18, "carbonbrief": 18, "ccai": 18,
    # 绿色科技媒体
    "stdaily": 16, "cleantechnica": 16,
    # AI 领域全链条源（2026-08-14 扩充）
    "jiqizhixin": 18, "qbitai": 18, "openai": 20,
    "venturebeat": 16, "arxiv_ai": 18, "aihot": 18,
    # 技术聚合（GitHub 开源项目趋势：无编辑自动榜单，略低于行业媒体）
    "radarai": 12,
    # 行业媒体
    "chinaenergy": 13, "bjx": 13, "reuters": 13,
    # 全网热榜
    "allnet": 8,
}
DEFAULT_SOURCE_SCORE = 10

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
               published_at: str, now: datetime, dimension: str = "政策") -> dict[str, Any]:
    """五维打分（v2.0）→ {'score': 0-100, 'score_level': S/A/B/C/D, 'strength': int, ...}

    内容强度按 dimension 自适应（政策/技术/金融/AI科技 各自关键词档位），
    替代 v1.0 只认政策文件的"政策类型"分。
    """
    src = SOURCE_SCORE.get(site_id, DEFAULT_SOURCE_SCORE)
    tscore = score_content_strength(dimension, title, summary)
    top = score_topic(title, summary)
    pscore = score_people(people)
    fscore = score_freshness(published_at, now)
    total = min(100, src + tscore + top + pscore + fscore)
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
            "people": pscore, "freshness": fscore,
        },
    }


# ── 四维分类（2026-08-14 主题定位：政策/技术/金融/AI科技） ─────────────────────
# 优先级：AI科技 > 金融 > 技术 > 政策。
# PITFALL: AI 判定只用标题（摘要常含反爬水印 "t a np ai fan g.com" 的 "ai "，
# 2026-08-14 实测误判"走进零碳园区"为 AI科技）且用词边界正则。
AI_DIM_KW = [
    "人工智能", "大模型", "机器学习", "智能电网", "数字孪生", "碳监测",
    "能碳", "智算", "算法", "机器人", "无人机", "卫星", "自动驾驶",
    "artificial intelligence", "machine learning", "smart grid",
    "robot", "autonomous", "drone", "satellite",
    # AI 领域全链条（2026-08-14 扩充：理论/模型/市场/商业）
    "大语言模型", "多模态", "生成式", "深度学习", "神经网络", "transformer",
    "llm", "gpt", "claude", "gemini", "deepseek", "qwen", "llama",
    "agent", "智能体", "推理", "训练", "算力", "芯片", "gpu", "英伟达",
    "openai", "anthropic", "google deepmind", "meta ai", "hugging face",
    "ai芯片", "ai应用", "ai模型", "模型发布", "ai创业", "ai融资",
    "机器学习模型", "计算机视觉", "自然语言处理", "强化学习", "aigc",
    "大模型创业", "模型即服务", "ai agent", "mcp", "语义", "transformer架构",
    # 2026-08-17：GitHub 趋势类 AI 项目（stable-diffusion-webui 等仓库名不含 AI 关键词，
    # 但摘要必含 diffusion；radarai 摘要参与 AI 判定，故补此词）
    "diffusion",
]
# 标题级英文 AI：负向环视版词边界——ASCII 字母外的任意字符（中文/连字符/空格等）都算边界。
# 比 \bai\b 更能命中中文上下文（Python \b 把汉字当 \w，"AI对气候…" 用 \bai\b 会漏判，
# 实测漏判掉进技术榜），同时仍排除 "tail"/"said"/"again"/"Aira"/"taiyangnews" 等单词内 ai。
AI_TITLE_RE = r"(?<![a-z])ai(?![a-z])"
FINANCE_DIM_KW = [
    "碳市场", "碳交易", "碳价", "碳配额", "碳关税", "CBAM", "CCER",
    "ESG", "绿色金融", "碳金融", "债券", "融资", "投资", "基金", "期货",
    "收购", "并购", "IPO", "股价", "碳资产", "绿色债券", "成交",
    "carbon market", "carbon price", "carbon trading", "ETS",
    "green bond", "finance", "investment", "fund",
]
TECH_DIM_KW = [
    "储能", "氢能", "光伏", "风电", "电池", "CCUS", "碳捕集", "技术",
    "研发", "突破", "材料", "工艺", "装备", "光热", "绿氢", "甲醇",
    "甲烷", "负排放", "DAC", "BECCS", "生物炭", "核能", "生物质",
    "solar", "wind", "battery", "hydrogen", "storage", "technology",
    "carbon capture", "renewable", "nuclear",
]
POLICY_DIM_KW = [
    "印发", "通知", "意见", "规划", "方案", "条例", "办法", "公告",
    "发布会", "答记者问", "解读", "一图读懂", "政策", "文件", "国务院",
    "十五五", "碳达峰", "碳中和", "双碳", "目标", "标准", "规范",
    "法规", "实施", "行动方案", "指导意见", "政策文件", "政策解读",
    # English（2026-08-17：国际智库 E3G/Agora/TERI 接入后补充——
    # 英文政策/气候分析标题不再掉进媒体库"技术"兜底；已验证对存量数据 0 漂移）
    "policy", "policies", "regulation", "regulatory", "legislation", "reform",
    "roadmap", "framework", "agreement", "government", "minister", "parliament",
    "mandate", "consultation", "strategy", "target", "commitment",
    "energy transition", "climate action", "climate policy", "net zero", "net-zero",
]


def categorize_dimension(site_id: str, title: str, summary: str, library: str) -> str:
    """四维分类：AI科技 > 金融 > 技术 > 政策。"""
    import re as _dim_re
    title_l = (title or "").lower()
    text = f"{title or ''} {summary or ''}".lower()
    # 站点级维度强制（机制保留，2026-08-17 起无强制项）：
    # radarai 不再整源归「技术」——技术榜只放绿色低碳技术，AI 项目按关键词进 AI科技榜
    if site_id in DIM_SITE_OVERRIDE:
        return DIM_SITE_OVERRIDE[site_id]
    # AI 判定：AI_SITES 源全链条直通（AIHOT/机器之心等标题未必含 AI 关键词）
    # + 标题关键词 + 标题级英文 AI 词边界
    if site_id in AI_SITES:
        return "AI科技"
    if any(kw.lower() in title_l for kw in AI_DIM_KW) or _dim_re.search(AI_TITLE_RE, title_l):
        return "AI科技"
    # GitHub 开源趋势（TECH_SITES/radarai）：仓库名常不含 AI 关键词
    # （stable-diffusion-webui / browser-use 等），而 radarai 摘要是雷达站真实中文描述
    # （无反爬水印风险）→ 允许摘要参与 AI 判定；AI 项目归 AI科技榜，其余一律归「技术」，
    # 不再走政策/金融关键词级联——避免 framework/目标/投资 等通用词把 GitHub 项目
    # 误分到政策榜/金融榜（2026-08-17：技术榜只放绿色低碳技术，AI 项目单独归 AI科技榜）
    if site_id in TECH_SITES:
        if any(kw.lower() in text for kw in AI_DIM_KW):
            return "AI科技"
        return "技术"
    for kw in FINANCE_DIM_KW:
        if kw.lower() in text:
            return "金融"
    for kw in TECH_DIM_KW:
        if kw.lower() in text:
            return "技术"
    # 政策库（官方原文）默认政策；媒体库看关键词
    if library == "policy":
        return "政策"
    for kw in POLICY_DIM_KW:
        if kw.lower() in text:
            return "政策"
    return "技术"  # 兜底：媒体库行业动态归技术


# ── Policy relevance filter ──────────────────────────────────────────────────
POLICY_KEYWORDS = [
    # Chinese
    "碳", "绿色", "低碳", "减排", "双碳", "新能源", "可再生能源",
    "节能", "环保", "气候", "碳中和", "碳达峰", "清洁能源",
    "光伏", "风电", "储能", "氢能", "核能", "生物质",
    "碳交易", "碳市场", "碳关税", "碳足迹", "碳普惠",
    "ESG", "可持续发展", "循环经济", "绿色制造", "绿色金融",
    "能源转型", "电力市场", "新型电力系统",
    "生态环境", "污染防治", "蓝天保卫战",
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
}

# 低频源宽窗口（2026-08-14）：国外官方源 + 中国智库型机构（NCSC/CAEP），
# 更新频率低（周级/月级），网站数据用 7 天宽窗口过滤，其余源保持 96h
FOREIGN_GOV_SITES = {
    "us_epa", "us_doe", "us_noaa", "us_eia", "us_ferc", "us_carb",
    "eu_commission", "euractiv", "india_pib",
    "jp_moe", "jp_meti", "jp_anre",
    "ncsc", "caep",
}

# 超低频源（2026-08-17）：国际智库更新周级~双周级（Agora 最新条目可超 14 天），
# 深度分析时效性弱于新闻 → 网站数据用 21 天宽窗口，避免整源被滤空
LOW_FREQ_SITES = {
    "e3g", "agora", "teri",
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
}

# 技术全链条源（2026-08-14）：GitHub 开源项目趋势，全量直通（同 AI_SITES 逻辑）。
# 维度（2026-08-17 调整）：非 AI 项目落回「技术」（媒体库兜底）；AI 项目在
# categorize_dimension 中按关键词（标题+摘要）归 AI科技榜——技术榜只放绿色低碳技术
TECH_SITES = {
    "radarai",      # RadarAI·GitHub趋势（开源项目热度追踪）
}

# 站点级维度强制：categorize_dimension 最先检查，优先于 AI_SITES 直通。
# 2026-08-17 起为空——radarai（GitHub 开源趋势）不再整源归「技术」：
# 技术榜只放绿色低碳技术，AI 项目按关键词（含摘要）归 AI科技榜，非 AI 项目落回技术兜底。
DIM_SITE_OVERRIDE: dict[str, str] = {}


def is_policy_relevant(title: str, url: str = "", site_id: str = "") -> bool:
    """Check if a title/URL/site is related to green/low-carbon policy."""
    # Auto-pass for known green sites
    if site_id in GREEN_SITES:
        return True
    # AI 领域全链条源（2026-08-14）：理论/模型/市场/商业全通过
    if site_id in AI_SITES:
        return True
    # 技术全链条源（2026-08-14）：GitHub 开源项目趋势全通过
    if site_id in TECH_SITES:
        return True
    title_lower = title.lower()
    url_lower = url.lower()
    for kw in POLICY_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower in title_lower:
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
    # Aggregated hot boards (filtered by policy keywords)
    (fetch_allnet, "allnet", "全网热点"),
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
    for it in existing:
        u = it.get("url") or ""
        if u and u not in seen:
            seen[u] = it
    added = 0
    for it in new_items:
        u = it.get("url") or ""
        if u and u not in seen:
            seen[u] = it
            added += 1
    cutoff = now - timedelta(days=62)

    def _item_time(it: dict):
        ts = it.get("published_at") or it.get("first_seen_at") or ""
        return parse_iso(ts) if ts else None

    items = [it for it in seen.values() if (_item_time(it) or now) >= cutoff]
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
    seen_items: set[tuple[str, str]] = set()

    all_items: list[dict[str, Any]] = []
    green_items: list[dict[str, Any]] = []

    for raw in raw_items:
        tid = make_item_id(raw.site_id, raw.title, raw.url)
        if tid in seen_ids:
            continue
        seen_ids.add(tid)

        title_key = (raw.title.strip().lower()[:80], normalize_url(raw.url))
        if title_key in seen_items:
            continue
        seen_items.add(title_key)

        record = {
            "id": tid,
            "site_id": raw.site_id,
            "site_name": raw.site_name,
            "source": raw.source or raw.site_name,
            "library": site_library(raw.site_id),  # policy | media
            "title": raw.title,
            "url": raw.url,
            "published_at": iso(raw.published_at),
            "first_seen_at": iso(now),
            # 抓取器自带摘要（radarai 的 GitHub 项目中文描述等）→ 参与打分 + 前端摘要
            "summary": raw.meta.get("summary", ""),
        }
        all_items.append(record)

        if is_policy_relevant(raw.title, raw.url, raw.site_id):
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

    def _archived_to_iso(pub: str) -> str:
        if " " in pub:
            return pub.replace(" ", "T") + "+08:00"
        return pub + "T00:00:00+08:00"  # date-only → midnight Beijing

    # NOTE: green_items shares the same dict objects as all_items, so this
    # single pass covers both lists (do not loop green_items again — it would
    # overwrite time_source).
    for rec in all_items:
        # 完整标题回填：笔记里的标题已用详情页标题修正，列表页截断标题
        # （如碳交易网 "…现状与未"）会被覆盖为完整版（2026-08-11）
        full_title = archived_titles.get(rec.get("url", ""))
        if full_title and len(full_title) > len(rec.get("title", "")):
            rec["title"] = full_title
        # 摘要回填（前端可展开摘要，News Minimalist 风格；2026-08-14）
        if not rec.get("summary"):
            summary = archived_summaries.get(rec.get("url", ""))
            if summary:
                rec["summary"] = summary
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
        # 四维分类（2026-08-14）：政策/技术/金融/AI科技
        dimension = categorize_dimension(
            rec.get("site_id", ""),
            rec.get("title", ""),
            rec.get("summary", ""),
            rec.get("library", "media"),
        )
        rec["dimension"] = dimension
        # 区域字段（2026-08-17）：前端排行榜/时间线「国内/国际」切换依赖
        rec["region"] = detect_region(rec.get("site_id", ""), rec.get("title", ""))
        # 打分体系 v2.0（2026-08-14）：内容强度按维度自适应
        people = extract_people(rec.get("title", ""), rec.get("summary", ""), "")
        scoring = score_item(
            rec.get("site_id", ""),
            rec.get("title", ""),
            rec.get("summary", ""),
            people,
            rec.get("published_at", ""),
            now,
            dimension,
        )
        rec.update(scoring)
        if people:
            rec["people"] = people

    # Persist the url→published map so CI runs can reuse it
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
    (output_dir / "latest-24h-all.json").write_text(
        json.dumps(all_payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (output_dir / "source-status.json").write_text(
        json.dumps(status_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    # 历史累积（2026-08-17）：日/周/月排行榜数据源，每次抓取合并新条目
    merge_history(output_dir, green_items_24h, now)

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
}


def detect_region(site_id: str, title: str) -> str:
    """来源默认地域；"全球"源（reuters）按标题关键词再判定（2026-08-17 提取，
    供数据导出 region 字段与 auto_tag 共用——前端区域切换（国内/国际）依赖此字段）。"""
    region = SOURCE_REGION.get(site_id, "")
    if region == "全球":
        title_lower = (title or "").lower()
        if any(kw in title_lower for kw in ["eu", "european", "europe", "european union", "brussels"]):
            region = "欧盟"
        elif any(kw in title_lower for kw in ["us ", "u.s.", "america", "biden", "trump", "washington"]):
            region = "美国"
        elif any(kw in title_lower for kw in ["中国", "china", "beijing", "shanghai"]):
            region = "中国"
    return region

# Topic tag rules: (tag, [keywords])
TOPIC_RULES: list[tuple[str, list[str]]] = [
    ("碳市场", ["碳交易", "碳市场", "碳价", "碳配额", "碳关税", "CBAM", "CCER", "碳排放权", "碳排",
                "carbon market", "carbon price", "carbon trading", "emissions trading", "ETS", "carbon border"]),
    ("新能源", ["新能源", "光伏", "风电", "光热", "氢能", "核能", "生物质", "水电",
                "solar", "wind power", "hydrogen", "nuclear", "renewable energy", "renewables"]),
    ("储能", ["储能", "电池", "抽水蓄能", "battery", "energy storage"]),
    ("电力", ["电力", "电网", "电价", "电力市场", "新型电力系统", "消纳", "用电", "发电",
              "electricity", "power grid", "power market"]),
    ("化石能源", ["煤炭", "石油", "天然气", "成品油", "LNG", "coal", "oil", "natural gas", "fossil fuel"]),
    ("节能降碳", ["节能", "能效", "绿色制造", "绿色低碳", "零碳工厂", "减排", "降碳",
                  "energy efficiency", "decarboni", "net zero", "net-zero", "zero carbon"]),
    ("气候变化", ["气候", "COP", "NDC", "巴黎协定", "碳中和", "碳达峰", "双碳", "温室气体",
                  "climate change", "climate policy", "paris agreement", "greenhouse"]),
    ("绿色金融", ["ESG", "绿色金融", "碳金融", "碳资产", "green finance", "green bond"]),
    ("环境保护", ["生态环境", "环境保护", "污染防治", "空气质量", "蓝天保卫战",
                  "environment", "pollution", "air quality"]),
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


def auto_tag(title: str, site_id: str) -> list[str]:
    """Generate tags for a news item based on title and source."""
    import re as _tag_re
    tags: list[str] = []
    title_lower = title.lower()

    # Topic tags
    for tag, keywords in TOPIC_RULES:
        for kw in keywords:
            kw_lower = kw.lower()
            # Word-boundary check for short abbreviations
            if len(kw) <= 3 and kw.isascii() and kw.isalpha():
                # Match only as whole word (e.g. "EV" not in "several")
                pattern = r'\b' + _tag_re.escape(kw_lower) + r'\b'
                if _tag_re.search(pattern, title_lower):
                    tags.append(tag)
                    break
            elif kw_lower in title_lower:
                tags.append(tag)
                break  # one match per topic

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
    for existing in notes_root.rglob("*.md"):
        if existing.name in ("政策库.md", "媒体库.md", "ai-index.md"):
            continue
        try:
            _c = existing.read_text(encoding="utf-8")
            _m = _re.search(r"^url:\s*(\S+)", _c, re.M)
            if _m:
                seen_urls.add(_m.group(1))
        except Exception:
            continue
    for item in items:
        site_id = item.get("site_id", "unknown")
        site_name = item.get("site_name", site_id)
        title = item.get("title", "untitled")
        url = item.get("url", "")
        pub_date = item.get("published_at", "")

        if url in seen_urls:
            continue  # 该 URL 已有笔记（任意文件名）
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

        if filepath.exists():
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
        # 详情页标题优先：列表页标题常被源站截断（如碳交易网列表页
        # "…现状与未"），详情页 <title>/<h1> 是完整的（2026-08-11）
        page_title = (res or {}).get("title") or ""
        if page_title and len(page_title) > len(title):
            title = page_title.strip()
            item["title"] = title  # record 共享引用 → JSON 同步
        summary = (res or {}).get("summary") or ""
        content = (res or {}).get("content") or ""
        source_org = (res or {}).get("source_org") or ""
        # Publish time: detail-page time (hour precision) wins, RSS time as fallback
        published = (res or {}).get("published") or ""
        if not published:
            published = format_published(item.get("published_at", ""))

        date_val = pub_date[:10] if pub_date else now.strftime("%Y-%m-%d")
        if not published:
            published = date_val  # last resort: the date field itself
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
            f'published: "{published}"',
            f"tags: [{tag_str}]",
            f"keywords: [{kw_str}]",
        ]
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
            f"> 发布时间: {published}",
            f"> 首次抓取: {now.strftime('%Y-%m-%d %H:%M')} UTC",
        ]
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
