#!/usr/bin/env python3
"""_diag_cnenergy6.py — fetch_article 稳定性测试（3 次重复）"""
import sys
sys.path.insert(0, "/opt/green-hot-news/scripts")
import article_content as ac

URL = "https://www.cnenergynews.cn/article/4SrIBG7MWSx"
for i in range(1, 4):
    try:
        res = ac.fetch_article(URL)
        ok = bool(res and res.get("summary"))
        print(f"第 {i} 次: {'OK' if ok else 'FAIL'} | summary: {str(res.get('summary'))[:50] if res else '-'}")
    except Exception as e:
        print(f"第 {i} 次: ERROR {type(e).__name__}: {e}")
