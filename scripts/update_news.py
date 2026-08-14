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
def fetch_rss_feed(session: requests.Session, feed_url: str, site_id: str, site_name: str, now: datetime) -> list[RawItem]:
    """Fetch RSS/Atom feed and return RawItems."""
    items: list[RawItem] = []
    seen: set[tuple[str, str]] = set()
    try:
        r = session.get(feed_url, timeout=30)
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
    return items


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


# ── Scoring system (2026-08-14) ───────────────────────────────────────────────
# 打分体系 v1.0：五维加权，0-100 分，代表"老温品味"——官方权威优先、政策文件优先、
# 核心议题优先、关键人物加分、新鲜度加分。
#   来源权威 30 + 政策类型 25 + 主题相关 25 + 人物 10 + 时效 10
# 等级: S(85+) / A(70+) / B(55+) / C(40+) / D(<40)

# 1) 来源权威分（site_id → 0-30）
SOURCE_SCORE: dict[str, int] = {
    # 部委官方
    "ndrc": 30, "mee": 30, "nea": 30, "miit": 30,
    # 官方解读（部委网站发布的专家解读）
    "mee_jiedu": 28,
    # 国际组织
    "iea": 28, "irena": 28, "unfccc": 28, "worldbank": 28,
    # 专业政策媒体
    "tanpaifang": 20, "ideacarbon": 20, "carbonbrief": 20,
    # 行业媒体
    "chinaenergy": 15, "bjx": 15, "reuters": 15,
    # 全网热榜
    "allnet": 10,
}
DEFAULT_SOURCE_SCORE = 12

# 2) 政策类型分（auto_tag 的 POLICY_TYPE_RULES 结果 → 0-25）
TYPE_SCORE: dict[str, int] = {
    "政策文件": 25, "政策解读": 20, "新闻发布会": 15, "数据报告": 15, "行业动态": 8,
}

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
               published_at: str, now: datetime) -> dict[str, Any]:
    """五维打分 → {'score': 0-100, 'score_level': S/A/B/C/D, 'type_score': int, ...}"""
    src = SOURCE_SCORE.get(site_id, DEFAULT_SOURCE_SCORE)
    tags = auto_tag(title, site_id)
    # 政策类型：取 auto_tag 输出的最后一个（POLICY_TYPE_RULES 追加在末尾）
    ptype = tags[-1] if tags else "行业动态"
    tscore = TYPE_SCORE.get(ptype, 8)
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
            "source": src, "type": tscore, "topic": top,
            "people": pscore, "freshness": fscore,
        },
    }


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
}


def is_policy_relevant(title: str, url: str = "", site_id: str = "") -> bool:
    """Check if a title/URL/site is related to green/low-carbon policy."""
    # Auto-pass for known green sites
    if site_id in GREEN_SITES:
        return True
    title_lower = title.lower()
    url_lower = url.lower()
    for kw in POLICY_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower in title_lower:
            return True
        if url_lower and kw_lower in url_lower:
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
}


def site_library(site_id: str) -> str:
    """policy (政策库/权威原文) or media (媒体库/二手转述)."""
    return SITE_LAYOUT.get(site_id, ("policy", "其他"))[0]


def site_policy_group(site_id: str) -> str:
    """政策库内部分组（中国 / 国际组织）。媒体源无分组。"""
    return SITE_LAYOUT.get(site_id, ("policy", "其他"))[1]


# ── Main pipeline ─────────────────────────────────────────────────────────────
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
        }
        all_items.append(record)

        if is_policy_relevant(raw.title, raw.url, raw.site_id):
            green_items.append(record)

    # 24h window filter for web output
    window_start = now - timedelta(hours=args.window_hours)
    all_items_24h = [r for r in all_items if not r.get("published_at") or parse_iso(r["published_at"]) is None or parse_iso(r["published_at"]) >= window_start]
    green_items_24h = [r for r in green_items if not r.get("published_at") or parse_iso(r["published_at"]) is None or parse_iso(r["published_at"]) >= window_start]

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
        # 打分体系（2026-08-14）：五维加权，写入 score / score_level / score_breakdown
        people = extract_people(rec.get("title", ""), rec.get("summary", ""), "")
        scoring = score_item(
            rec.get("site_id", ""),
            rec.get("title", ""),
            rec.get("summary", ""),
            people,
            rec.get("published_at", ""),
            now,
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
    "chinaenergy": "中国", "tanpaifang": "中国", "bjx": "中国", "ideacarbon": "中国",
    "iea": "国际", "irena": "国际", "unfccc": "国际", "worldbank": "国际",
    "carbonbrief": "国际",
    "reuters": "全球",
}

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
    region = SOURCE_REGION.get(site_id, "")
    # For "全球" sources, try to detect region from title
    if region == "全球":
        if any(kw in title_lower for kw in ["eu", "european", "europe", "european union", "brussels"]):
            region = "欧盟"
        elif any(kw in title_lower for kw in ["us ", "u.s.", "america", "biden", "trump", "washington"]):
            region = "美国"
        elif any(kw in title_lower for kw in ["中国", "china", "beijing", "shanghai"]):
            region = "中国"
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
                content = fpath.read_text(encoding="utf-8")
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
