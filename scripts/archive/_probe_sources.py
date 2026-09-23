#!/usr/bin/env python3
"""探测 18 个候选信源（2026-08-19 书签导入批次 A~O）。

对每个源依次尝试：RSS 直抓 → 列表页 HTML → Google News RSS 兜底。
打印：成功路径 / 条数 / 最新 3 条标题 + 日期样例 + 备注（JS 渲染/WAF 等）。
用项目 python3.11 跑：python3.11 scripts/_probe_sources.py
"""
import sys
import time
from datetime import datetime, timezone, timedelta

import requests
import feedparser
from bs4 import BeautifulSoup
from urllib.parse import urljoin

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
session = requests.Session()
session.headers.update({"User-Agent": UA})

NOW = datetime.now(timezone.utc)


def probe_rss(url, limit=10):
    """尝试 RSS 直抓，返回 (ok, items, note)。"""
    try:
        r = session.get(url, timeout=25)
        if r.status_code != 200:
            return False, [], f"HTTP {r.status_code}"
        if "html" in (r.headers.get("content-type") or "").lower() and "<rss" not in r.text[:2000].lower():
            return False, [], "HTML 壳（非 RSS）"
        d = feedparser.parse(r.content)
        entries = [e for e in d.entries if getattr(e, "title", "")]
        if not entries:
            return False, [], "RSS 解析 0 条"
        return True, entries[:limit], f"OK {len(entries)}条"
    except Exception as e:
        return False, [], f"{type(e).__name__}: {str(e)[:80]}"


def probe_html(url, link_filter=None, min_len=12, limit=10):
    """列表页 HTML 解析：收集 a[href] 标题，可选链接过滤。"""
    try:
        r = session.get(url, timeout=25)
        if r.status_code != 200:
            return False, [], f"HTTP {r.status_code}"
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for a in soup.find_all("a", href=True):
            txt = a.get_text(strip=True)
            href = a.get("href", "")
            if not txt or len(txt) < min_len:
                continue
            if link_filter and not link_filter(href):
                continue
            if (txt, href) in items:
                continue
            items.append((txt, href))
        if not items:
            return False, [], "无匹配链接（可能 JS 渲染）"
        return True, items[:limit], f"OK {len(items)}条"
    except Exception as e:
        return False, [], f"{type(e).__name__}: {str(e)[:80]}"


def probe_google(site, query_kws, locale="en-US", limit=10):
    """Google News RSS 搜 site 兜底。"""
    q = f"site:{site} ({query_kws}) when:7d"
    params = {"q": q, "hl": locale.split("-")[0], "gl": locale.split("-")[1],
              "ceid": f"{locale.split('-')[1]}:{locale}"}
    try:
        r = session.get("https://news.google.com/rss/search", params=params, timeout=25)
        if r.status_code != 200:
            return False, [], f"HTTP {r.status_code}"
        d = feedparser.parse(r.content)
        entries = [e for e in d.entries if getattr(e, "title", "")]
        if not entries:
            return False, [], "0 条"
        return True, entries[:limit], f"OK {len(entries)}条"
    except Exception as e:
        return False, [], f"{type(e).__name__}: {str(e)[:80]}"


def show(title, entries, kind):
    print(f"  ✓ {kind} 路径成功，样例：")
    for e in entries[:3]:
        if isinstance(e, dict) and "href" in e:
            t, u, pub_s = e["title"], e["href"], ""
        elif isinstance(e, tuple) and len(e) == 2:
            t, u, pub_s = e[0], e[1], ""
        else:
            t = getattr(e, "title", "")
            u = getattr(e, "link", "")
            pub = getattr(e, "published_parsed", None)
            pub_s = time.strftime("%Y-%m-%d", pub) if pub else ""
        print(f"    · {t[:60]} | {pub_s} | {u[:70]}")


CANDIDATES = [
    # (site_id, 名称, RSS 候选, HTML 列表页, Google site, Google 关键词, 说明)
    ("brookings", "Brookings", ["https://www.brookings.edu/feed/"],
     None, "brookings.edu",
     "climate OR energy OR emissions OR carbon OR clean",
     "美国智库 P0"),
    ("bruegel", "Bruegel", ["https://www.bruegel.org/rss.xml"],
     None, "bruegel.org",
     "climate OR energy OR carbon OR trade OR green",
     "欧盟智库 P0"),
    ("piie", "PIIE", ["https://www.piie.com/rss.xml", "https://www.piie.com/feed"],
     None, "piie.com",
     "climate OR carbon OR trade OR energy OR tariff",
     "美国经济智库"),
    ("csis", "CSIS", ["https://www.csis.org/rss.xml"],
     None, "csis.org",
     "climate OR energy OR clean OR carbon OR grid",
     "美国智库"),
    ("chatham", "Chatham House", ["https://www.chathamhouse.org/rss.xml"],
     None, "chathamhouse.org",
     "climate OR energy OR carbon OR environment",
     "英国智库"),
    ("carnegie", "Carnegie", ["https://carnegieendowment.org/rss.xml"],
     None, "carnegieendowment.org",
     "climate OR energy OR clean OR carbon",
     "美国智库"),
    ("rand", "RAND", ["https://www.rand.org/rss/news.xml"],
     None, "rand.org",
     "climate OR energy OR carbon OR environment",
     "美国智库"),
    ("wilson", "Wilson Center", ["https://www.wilsoncenter.org/rss.xml"],
     None, "wilsoncenter.org",
     "climate OR energy OR carbon OR environment",
     "美国智库"),
    ("americanprogress", "CAP", ["https://www.americanprogress.org/feed/"],
     None, "americanprogress.org",
     "climate OR energy OR clean OR environment",
     "美国智库"),
    ("goldman", "高盛GreaterChina", [],
     "https://www.goldmansachs.com/worldwide/greater-china/insights/",
     "goldmansachs.com",
     "energy OR climate OR carbon OR clean OR green",
     "投行研报"),
    ("caixin_shuangtan", "财新双碳", [],
     "https://shuangtan.blog.caixin.com/",
     "shuangtan.blog.caixin.com",
     "碳 OR 双碳 OR 碳中和 OR 绿电",
     "财新双碳专栏"),
    ("greenenergy", "绿证平台", [],
     "https://www.greenenergy.org.cn/",
     "greenenergy.org.cn",
     "绿证 OR 绿色电力证书 OR 可再生能源",
     "官方绿证"),
    ("chinanecc", "国家节能中心", [],
     "http://www.chinanecc.cn/website/index.shtml",
     "chinanecc.cn",
     "节能 OR 双碳 OR 碳排放 OR 绿色",
     "官方节能"),
    ("thepaper", "澎湃新闻", [],
     "https://www.thepaper.cn/",
     "thepaper.cn",
     "绿色 OR 低碳 OR 双碳 OR 碳市场 OR 能源",
     "综合媒体"),
    ("waytoagi", "WaytoAGI", [],
     "https://www.waytoagi.com/zh",
     "waytoagi.com",
     "AI OR GPT OR 大模型 OR agent",
     "AI 知识聚合"),
    ("artificialanalysis", "ArtificialAnalysis", [],
     "https://artificialanalysis.ai/",
     "artificialanalysis.ai",
     "AI OR model OR GPT OR benchmark",
     "AI 评测"),
    ("36kr", "36氪", [],
     "https://36kr.com/",
     "36kr.com",
     "AI OR 大模型 OR 新能源 OR 储能 OR 碳中和",
     "科技商业媒体"),
    ("huxiu", "虎嗅", [],
     "https://www.huxiu.com/",
     "huxiu.com",
     "AI OR 大模型 OR 新能源 OR 储能 OR 碳中和",
     "科技商业媒体"),
]


def main():
    print(f"=== 探测 {len(CANDIDATES)} 个候选源 @ {NOW:%Y-%m-%d %H:%M} UTC ===\n")
    for site_id, name, rss_urls, html_url, gsite, gkw, note in CANDIDATES:
        print(f"── {site_id} ({name}) — {note}")
        done = False
        # 1) RSS
        for u in rss_urls:
            ok, entries, msg = probe_rss(u)
            if ok:
                show(name, entries, f"RSS {u}")
                done = True
                break
            else:
                print(f"  ✗ RSS {u}: {msg}")
        if done:
            continue
        # 2) HTML 列表页
        if html_url:
            ok, items, msg = probe_html(html_url)
            if ok:
                show(name, items, f"HTML {html_url}")
                done = True
            else:
                print(f"  ✗ HTML: {msg}")
        if done:
            continue
        # 3) Google News 兜底
        ok, entries, msg = probe_google(gsite, gkw)
        if ok:
            show(name, entries, f"Google News site:{gsite}")
        else:
            print(f"  ✗ Google News: {msg}")
        print()
    print("\n=== 探测完成 ===")


if __name__ == "__main__":
    main()
