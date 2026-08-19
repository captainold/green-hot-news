#!/usr/bin/env python3
"""Probe candidate sources for 人形机器人 / 绿色智能家居 / 绿色生活 (2026-08-19).

按照 green-policy-radar 技能的批量探测流程：requests + feedparser，
用 python3.11 跑（项目解释器）。每个候选打印条数 + 最新标题样例，
看内容质量再决定接入。媒体源统一走 Google News RSS site: 搜索
（服务器安全，避免 Cloudflare WAF），顺带探测直连 RSS 做参考。
"""
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
    """Google News RSS search → [(title, published_str)]"""
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
    """Direct RSS/Atom feed → [(title, published_str)]"""
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


def show(name: str, items: list[tuple[str, str]]):
    print("=" * 72)
    print("[%s] %d 条" % (name, len(items)))
    for t, pub in items[:5]:
        print("   %s | %s" % (pub, t[:90]))


print("probe time: %s" % datetime.now(timezone.utc).isoformat())

# ── 人形机器人 ─────────────────────────────────────────────
show("高工机器人 gg-robot.com (GNews zh)",
     gnews("site:gg-robot.com 机器人 OR 人形", "zh"))
show("高工机器人 gg-robot.com (GNews zh2)",
     gnews("site:gg-robot.com 人形机器人 OR 具身智能", "zh"))
show("中国机器人网 robot-china.com (GNews zh)",
     gnews("site:robot-china.com 机器人", "zh"))
show("The Robot Report (GNews en)",
     gnews("site:therobotreport.com robot OR humanoid"))
show("The Robot Report (RSS 直连)",
     rss("https://www.therobotreport.com/feed/"))
show("IEEE Spectrum (GNews en robotics)",
     gnews("site:spectrum.ieee.org robotics OR robot OR humanoid"))
show("IEEE Spectrum Robotics (RSS 直连)",
     rss("https://spectrum.ieee.org/feeds/topic/robotics.rss"))

# ── 绿色智能家居 ────────────────────────────────────────────
show("千家网 qianjia.com (GNews zh)",
     gnews("site:qianjia.com 智能家居", "zh"))
show("千家网 qianjia.com (GNews zh2 绿色)",
     gnews("site:qianjia.com 智能家居 OR 绿色 OR 节能", "zh"))
show("数智网 smarthomecn.com (GNews zh)",
     gnews("site:smarthomecn.com 智能家居 OR 节能", "zh"))
show("Energy Star energystar.gov (GNews en)",
     gnews("site:energystar.gov energy efficiency OR appliance OR rebate"))
show("Energy Star (RSS 直连)",
     rss("https://www.energystar.gov/about/news/feed"))

# ── 绿色生活 ────────────────────────────────────────────────
show("TreeHugger (GNews en)",
     gnews("site:treehugger.com green OR sustainable OR energy"))
show("TreeHugger (RSS 直连)",
     rss("https://www.treehugger.com/rss.xml"))
show("环保在线 hbzhan.com (GNews zh)",
     gnews("site:hbzhan.com 环保 OR 绿色 OR 低碳", "zh"))
show("环保在线 hbzhan.com (GNews zh2)",
     gnews("site:hbzhan.com 绿色生活 OR 节能 OR 环境", "zh"))
show("Greenpeace 绿色和平 (GNews en)",
     gnews("site:greenpeace.org climate OR energy OR environment"))
