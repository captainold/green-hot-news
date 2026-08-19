#!/usr/bin/env python3
"""_probe_cnenergy.py — 诊断中国能源报详情页正文提取失败原因"""
import sys
import requests

sys.path.insert(0, "scripts")
import article_content as ac

URLS = [
    "https://www.cnenergynews.cn/article/4SrLqNFARAn",   # 三部门印发指导目录
    "https://www.cnenergynews.cn/article/4SrIBG7MWSx",   # 工信部机器人
    "https://www.cnenergynews.cn/article/4SrIeIVuTRk",   # 钠电池
]

for u in URLS:
    print(f"\n=== {u} ===")
    try:
        r = requests.get(u, timeout=20, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0 Safari/537.36"),
        })
        print(f"status={r.status_code} len={len(r.text)}")
        r.encoding = r.apparent_encoding or "utf-8"
        res = ac.fetch_article(u)
        if res:
            print(f"  title: {res.get('title','')[:60]}")
            print(f"  summary: {str(res.get('summary'))[:100]}")
            print(f"  content: {str(res.get('content'))[:150]}")
            print(f"  source_org: {res.get('source_org')}")
        else:
            print("  fetch_article → None (提取失败)")
    except Exception as e:
        print(f"  ERROR {type(e).__name__}: {e}")
