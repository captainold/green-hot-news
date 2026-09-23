#!/usr/bin/env python3
"""_probe_cnenergy_gnews.py — Google News 索引质量 + 首页摘要结构探测"""
import feedparser
import requests
from bs4 import BeautifulSoup

print("=== Google News site:cnenergynews.cn ===")
queries = [
    "site:cnenergynews.cn climate",
    "site:cnenergynews.cn energy",
    "site:cnenergynews.cn carbon",
]
for q in queries:
    try:
        r = requests.get(
            "https://news.google.com/rss/search",
            params={"q": q, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"},
            timeout=30,
        )
        r.raise_for_status()
        d = feedparser.parse(r.content)
        print(f"\n--- {q}: {len(d.entries)} 条 ---")
        for e in d.entries[:4]:
            print(f"  [{e.get('published','')[:16]}] {e.title[:60]}")
            desc = (e.get("summary") or "")[:80]
            print(f"      摘要: {desc}")
    except Exception as ex:
        print(f"  ERROR {ex}")

print("\n=== 首页卡片是否含摘要文本 ===")
r = requests.get("https://www.cnenergynews.cn/", timeout=20, headers={
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0 Safari/537.36"})
r.encoding = r.apparent_encoding or "utf-8"
soup = BeautifulSoup(r.text, "html.parser")
# 找 article 卡片/摘要容器
for sel in ["article", ".news-list li", ".list li", ".con li", "[class*=summary]", "[class*=intro]", "[class*=desc]"]:
    els = soup.select(sel)
    if els:
        sample = els[0]
        txt = sample.get_text(" ", strip=True)[:120]
        print(f"{sel}: {len(els)} 个 | 样例: {txt}")
        if len(els) > 1:
            print(f"       第二个: {els[1].get_text(' ', strip=True)[:120]}")
