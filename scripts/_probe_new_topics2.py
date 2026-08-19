#!/usr/bin/env python3
"""Probe round 2: 补充候选源（2026-08-19）."""
import sys
import time
from datetime import datetime, timezone

import feedparser
import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})

LOCALES = {
    "en": {"hl": "en-US", "gl": "US", "ceid": "US:en"},
    "zh": {"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"},
}


def gnews(query: str, locale: str = "en", limit: int = 12) -> list[tuple[str, str]]:
    try:
        params = {"q": query, **LOCALES[locale]}
        r = S.get("https://news.google.com/rss/search", params=params, timeout=30)
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        out = []
        for e in feed.entries[:limit]:
            t = (e.get("title") or "").strip()
            pub = ""
            if hasattr(e, "published_parsed") and e.published_parsed:
                pub = time.strftime("%Y-%m-%d", e.published_parsed)
            out.append((t, pub))
        return out
    except Exception as ex:
        return [("ERROR: %s" % ex, "")]


def rss(url: str, limit: int = 10) -> list[tuple[str, str]]:
    try:
        r = S.get(url, timeout=30)
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        out = []
        for e in feed.entries[:limit]:
            t = (e.get("title") or "").strip()
            pub = ""
            if hasattr(e, "published_parsed") and e.published_parsed:
                pub = time.strftime("%Y-%m-%d", e.published_parsed)
            out.append((t, pub))
        if not out and len(feed.entries) == 0:
            return [("(feed empty, %s bytes)" % len(r.content), "")]
        return out
    except Exception as ex:
        return [("ERROR: %s" % ex, "")]


def html_links(url: str, needle: str = "", limit: int = 10) -> list[tuple[str, str]]:
    """Fetch a page and extract text+links for list pages."""
    try:
        r = S.get(url, timeout=30)
        r.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for a in soup.find_all("a", href=True):
            txt = a.get_text(strip=True)
            href = a["href"]
            if not txt or len(txt) < 15:
                continue
            if needle and needle not in href:
                continue
            out.append((txt[:100], href[:80]))
            if len(out) >= limit:
                break
        return out or [("(no links matched, %d bytes)" % len(r.content), "")]
    except Exception as ex:
        return [("ERROR: %s" % ex, "")]


def show(name: str, items: list[tuple[str, str]]):
    print("=" * 72)
    print("[%s] %d 条" % (name, len(items)))
    for t, pub in items[:5]:
        print("   %s | %s" % (pub, t[:90]))


print("probe2 time: %s" % datetime.now(timezone.utc).isoformat())

# 高工机器人直连 RSS 探测
show("高工机器人 gg-robot.com (RSS /feed/)", rss("https://www.gg-robot.com/feed/"))
show("高工机器人 gg-robot.com (RSS /rss.xml)", rss("https://www.gg-robot.com/rss.xml"))
show("高工机器人 gg-robot.com (首页直抓)", html_links("https://www.gg-robot.com/"))

# Energy Star 官网新闻列表直抓
show("Energy Star (官网新闻页直抓)", html_links("https://www.energystar.gov/about/news"))

# 绿色生活补充
show("绿色和平中文 greenpeace.org.cn (GNews zh)", gnews("site:greenpeace.org.cn 气候 OR 环境 OR 能源", "zh"))
show("Mongabay (GNews en)", gnews("site:mongabay.com climate OR conservation OR green"))
show("Mongabay (RSS 直连)", rss("https://news.mongabay.com/feed/"))
show("EcoWatch (GNews en)", gnews("site:ecowatch.com green OR climate OR sustainable"))
show("EcoWatch (RSS 直连)", rss("https://www.ecowatch.com/feed"))
show("WWF wwf.panda.org (GNews en)", gnews("site:wwf.panda.org climate OR energy OR environment"))

# 绿色智能家居补充
show("中国家电网 cheaa.com (GNews zh)", gnews("site:cheaa.com 家电 OR 节能 OR 绿色", "zh"))
show("Green Builder Media (GNews en)", gnews("site:greenbuildermedia.com green home OR smart home OR energy"))
show("Green Builder Media (RSS 直连)", rss("https://www.greenbuildermedia.com/feed"))
