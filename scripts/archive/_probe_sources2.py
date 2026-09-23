#!/usr/bin/env python3
"""第二轮探测：补测 HTML 空壳源（JS 渲染）的 Google News 兜底 + 备选 RSS。"""
import sys
import time
import requests
import feedparser
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
session = requests.Session()
session.headers.update({"User-Agent": UA})


def probe_google(site, query_kws, locale="en-US", limit=8):
    q = f"site:{site} ({query_kws}) when:7d"
    hl, gl = locale.split("-")
    params = {"q": q, "hl": hl, "gl": gl, "ceid": f"{gl}:{locale}"}
    try:
        r = session.get("https://news.google.com/rss/search", params=params, timeout=25)
        d = feedparser.parse(r.content)
        entries = [e for e in d.entries if getattr(e, "title", "")]
        return entries[:limit]
    except Exception as e:
        print(f"    ✗ {type(e).__name__}: {str(e)[:80]}")
        return []


def probe_rss(url, limit=8):
    try:
        r = session.get(url, timeout=25)
        if r.status_code != 200:
            print(f"    ✗ RSS {url}: HTTP {r.status_code}")
            return []
        if "html" in (r.headers.get("content-type") or "").lower() and "<rss" not in r.text[:2000].lower():
            print(f"    ✗ RSS {url}: HTML 壳")
            return []
        d = feedparser.parse(r.content)
        entries = [e for e in d.entries if getattr(e, "title", "")]
        return entries[:limit]
    except Exception as e:
        print(f"    ✗ RSS {url}: {type(e).__name__}: {str(e)[:80]}")
        return []


def show(entries):
    for e in entries[:3]:
        t = getattr(e, "title", "")
        u = getattr(e, "link", "")
        pub = getattr(e, "published_parsed", None)
        pub_s = time.strftime("%Y-%m-%d", pub) if pub else ""
        print(f"    · {t[:65]} | {pub_s} | {u[:70]}")


def main():
    # 1) 财新双碳：博客平台常见 RSS 端点
    print("── caixin_shuangtan 备选 RSS")
    for u in ["https://shuangtan.blog.caixin.com/feed/",
              "https://shuangtan.blog.caixin.com/rss/",
              "https://shuangtan.blog.caixin.com/feed"]:
        es = probe_rss(u)
        if es:
            show(es)
            break
    print("── caixin_shuangtan Google News")
    es = probe_google("shuangtan.blog.caixin.com", "碳 OR 双碳 OR 碳中和 OR 绿电 OR 排放", locale="zh-CN")
    if es:
        show(es)

    # 2) 澎湃：Google News 兜底
    print("── thepaper Google News")
    es = probe_google("thepaper.cn", "绿色 OR 低碳 OR 双碳 OR 碳市场 OR 能源 OR 环保", locale="zh-CN")
    if es:
        show(es)

    # 3) 高盛：Google News 兜底
    print("── goldman Google News")
    es = probe_google("goldmansachs.com", "energy OR climate OR carbon OR clean OR green")
    if es:
        show(es)

    # 4) 国家节能中心：首页结构细看
    print("── chinanecc 首页 a[href] 结构")
    try:
        r = session.get("http://www.chinanecc.cn/website/index.shtml", timeout=25)
        r.encoding = r.apparent_encoding or "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        n = 0
        for a in soup.find_all("a", href=True):
            txt = a.get_text(strip=True)
            href = a.get("href", "")
            if txt and len(txt) >= 10:
                print(f"    · {txt[:50]} | {href[:70]}")
                n += 1
                if n >= 8:
                    break
        if n == 0:
            print("    ✗ 无 ≥10 字链接（JS 渲染或需其他路径）")
    except Exception as e:
        print(f"    ✗ {type(e).__name__}: {str(e)[:80]}")

    # 5) WaytoAGI：RSS 端点 + Google News
    print("── waytoagi RSS/Google")
    for u in ["https://www.waytoagi.com/rss.xml", "https://www.waytoagi.com/feed",
              "https://www.waytoagi.com/zh/rss.xml"]:
        es = probe_rss(u)
        if es:
            show(es)
            break
    es = probe_google("waytoagi.com", "AI OR 大模型 OR GPT OR agent OR 智能体", locale="zh-CN")
    if es:
        show(es)

    # 6) Artificial Analysis：RSS + Google News
    print("── artificialanalysis RSS/Google")
    for u in ["https://artificialanalysis.ai/rss.xml", "https://artificialanalysis.ai/feed",
              "https://artificialanalysis.ai/feed.xml"]:
        es = probe_rss(u)
        if es:
            show(es)
            break
    es = probe_google("artificialanalysis.ai", "AI OR model OR benchmark OR GPT OR LLM")
    if es:
        show(es)

    # 7) 虎嗅：RSS 端点 + Google News（不同关键词）
    print("── huxiu RSS/Google")
    for u in ["https://www.huxiu.com/rss/", "https://www.huxiu.com/rss.xml",
              "https://www.huxiu.com/feed"]:
        es = probe_rss(u)
        if es:
            show(es)
            break
    es = probe_google("huxiu.com", "AI OR 大模型 OR 新能源 OR 碳中和", locale="zh-CN")
    if es:
        show(es)

    # 8) 36氪 Google News 补测（绿色词更精准）
    print("── 36kr Google News 精准词")
    es = probe_google("36kr.com", "新能源 OR 储能 OR 碳中和 OR 绿色", locale="zh-CN")
    if es:
        show(es)

    # 9) CSIS：RSS 是 events 流 → 试 analysis 流 + Google News
    print("── csis analysis RSS")
    for u in ["https://www.csis.org/rss/analysis", "https://www.csis.org/analysis/rss.xml",
              "https://www.csis.org/rss.xml?cat=analysis"]:
        es = probe_rss(u)
        if es:
            show(es)
            break
    print("── csis Google News")
    es = probe_google("csis.org", "energy OR climate OR clean OR carbon OR grid")
    if es:
        show(es)

    # 10) 绿证平台 Google News 中文字段重试
    print("── greenenergy Google News 中文")
    es = probe_google("greenenergy.org.cn", "绿证 OR 绿色电力证书", locale="zh-CN")
    if es:
        show(es)

    print("\n=== 第二轮探测完成 ===")


if __name__ == "__main__":
    main()
