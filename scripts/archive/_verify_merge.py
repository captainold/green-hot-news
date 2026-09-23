# -*- coding: utf-8 -*-
"""P2 合并后完整性验证：素材层独有 url 是否全部落入素材库（无丢失）。"""
import re
from pathlib import Path

NOTES = Path(r"C:\Users\wenyu\Documents\Obsidian_wen\green-hot-news\Notes")

def read_url(path):
    t = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
    if not m:
        return ""
    u = re.search(r'^url:\s*"?([^"\n]*)"?', m.group(1), re.M)
    return (u.group(1).strip() if u else "")

# 数据库 url 集合
db_urls = set()
for p in (NOTES/"数据库").rglob("*.md"):
    if p.is_file() and "_files" not in str(p):
        u = read_url(p)
        if u:
            db_urls.add(u)
print(f"[1] 数据库 url 去重: {len(db_urls)}")

# 素材层独有 url（不在数据库）
md_only_urls = set()
md_dup = 0
md_no_url = 0
for base in ["政策库", "媒体库"]:
    for p in (NOTES/base).rglob("*.md"):
        if p.is_file() and "_files" not in str(p) and "attachments" not in str(p):
            if p.name in ("ai-index.md", "政策库.md", "媒体库.md"):
                continue
            u = read_url(p)
            if not u:
                md_no_url += 1
            elif u in db_urls:
                md_dup += 1
            else:
                md_only_urls.add(u)
print(f"[2] 素材层独有 url: {len(md_only_urls)} | 重复(在数据库): {md_dup} | 无url: {md_no_url}")

# 素材库 url 集合
out_urls = set()
for p in (NOTES/"素材库").rglob("*.md"):
    if p.is_file():
        u = read_url(p)
        if u:
            out_urls.add(u)
print(f"[3] 素材库 url 去重: {len(out_urls)}")

# 丢失检查：素材层独有 url 不在素材库的
lost = md_only_urls - out_urls
print(f"[4] 素材层独有 url 丢失数: {len(lost)}")
for u in list(lost)[:10]:
    print(f"    {u[:100]}")

# 数据库 url 不在素材库的（db_copy 丢失）
db_lost = db_urls - out_urls
print(f"[5] 数据库 url 丢失数: {len(db_lost)}")

print(f"\n[结论] 素材库 url 去重 {len(out_urls)} = 数据库 {len(db_urls)} + 素材层独有 {len(md_only_urls)} - 丢失 {len(lost)+len(db_lost)}")
