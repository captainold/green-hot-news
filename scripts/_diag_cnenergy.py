#!/usr/bin/env python3
"""_diag_cnenergy.py — 服务器端诊断：中国能源报 Notes 现状 + 详情页直抓"""
import re
import sys
from pathlib import Path

sys.path.insert(0, "/opt/green-hot-news/scripts")
import article_content as ac

notes_dir = Path("/opt/green-hot-news/Notes/媒体库/中国能源报")
files = list(notes_dir.glob("*.md")) if notes_dir.exists() else []
with_summary = 0
with_body = 0
for f in files:
    try:
        c = f.read_text(encoding="utf-8", errors="ignore")
        if re.search(r'^summary:\s*"[^"]', c, re.M):
            with_summary += 1
        if "## 正文" in c:
            with_body += 1
    except Exception:
        pass
print(f"Notes 中国能源报: {len(files)} 笔记 | {with_summary} 有summary | {with_body} 有正文")

urls = [
    "https://www.cnenergynews.cn/article/4SrLqNFARAn",
    "https://www.cnenergynews.cn/article/4SrIBG7MWSx",
]
for u in urls:
    try:
        res = ac.fetch_article(u)
        if res:
            s = (res.get("summary") or "")[:60]
            print(f"fetch_article OK | {u} | summary: {s}")
        else:
            print(f"fetch_article FAIL | {u}")
    except Exception as e:
        print(f"fetch_article ERROR | {u} | {type(e).__name__}: {e}")
