#!/usr/bin/env python3
"""_fix_cnenergy_bodies.py — 服务器：中国能源报缺正文笔记补抓

（2026-08-19）挑战解码修复后，对 Notes/媒体库/中国能源报/ 下缺 ## 正文的笔记
fetch_article 重抓，补 frontmatter summary + 正文段。幂等。
"""
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, "/opt/green-hot-news/scripts")
import article_content as ac

NOTES_DIR = Path("/opt/green-hot-news/Notes/媒体库/中国能源报")
DATA = Path("/opt/green-hot-news/data")

# 1. 收集缺正文笔记
targets = []
for f in NOTES_DIR.glob("*.md"):
    try:
        c = f.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    if "## 正文" in c:
        continue
    m = re.search(r"^url:\s*(\S+)", c, re.M)
    if not m:
        continue
    targets.append((f, m.group(1), c))
print(f"缺正文待补: {len(targets)} 条")

# 2. 并发抓正文
filled = 0
failed = []
with ThreadPoolExecutor(max_workers=6) as ex:
    futs = {ex.submit(ac.fetch_article, url): (f, url, c) for f, url, c in targets}
    for fut in as_completed(futs):
        f, url, c = futs[fut]
        try:
            res = fut.result()
        except Exception:
            res = None
        s = (res or {}).get("summary") or ""
        content = (res or {}).get("content") or ""
        if not content:
            failed.append((f.name, url))
            continue
        # 更新 frontmatter summary
        if s and not re.search(r'^summary:\s*"[^"]', c, re.M):
            m = re.search(r"^(keywords:.*)$", c, re.M)
            if m:
                safe = s.replace(chr(34), chr(39)).replace("\n", " ")
                c = c[:m.start(1)] + f"summary: \"{safe}\"" + "\n" + c[m.start(1):]
        # 追加正文
        if "## 正文" not in c:
            c = c.rstrip() + "\n\n## 正文\n\n" + content + "\n"
        f.write_text(c, encoding="utf-8")
        filled += 1
print(f"补回 {filled} 条，失败 {len(failed)} 条")
for name, url in failed[:8]:
    print("  失败:", name, url)
