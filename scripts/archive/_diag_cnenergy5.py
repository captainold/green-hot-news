#!/usr/bin/env python3
"""_diag_cnenergy5.py — 检查 Notes 笔记 + summary-index 覆盖状态"""
import json
import re
from pathlib import Path

URL = "https://www.cnenergynews.cn/article/4SrIBG7MWSx"

# 1. Notes 里有没有这条笔记 + summary
notes_dir = Path("/opt/green-hot-news/Notes/媒体库/中国能源报")
found = None
for f in notes_dir.glob("*.md"):
    try:
        c = f.read_text(encoding="utf-8", errors="ignore")
        if URL in c and re.search(r"^url:\s*\S+", c, re.M):
            m = re.search(rf"^url:\s*({re.escape(URL)})", c, re.M)
            if m:
                found = (f.name, bool(re.search(r'^summary:\s*"[^"]', c, re.M)))
                break
    except Exception:
        pass
print("Notes 匹配:", found)

# 2. summary-index 里有没有这个 URL
si = json.loads((Path("/opt/green-hot-news/data/summary-index.json")).read_text(encoding="utf-8"))
print("summary-index 总条数:", len(si))
print("含 4SrIBG7MWSx:", URL in si)
if URL in si:
    print("  summary:", si[URL][:80])

# 3. history.json 里这条
hist = json.loads((Path("/opt/green-hot-news/data/history.json")).read_text(encoding="utf-8"))
for it in hist.get("items", []):
    if it.get("url") == URL:
        print("history 里 summary:", repr((it.get("summary") or "")[:60]))
        break
