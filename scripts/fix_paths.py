# -*- coding: utf-8 -*-
"""修复删除原三目录后的路径引用（P2 收尾）。
1. 实体页 Dataview FROM 指向素材库
2. wiki 双链 [[../../媒体库|政策库|数据库/...]] 指向素材库
"""
from pathlib import Path

NOTES = Path(r"C:\Users\wenyu\Documents\Obsidian_wen\green-hot-news\Notes")

# ── 1. 实体页 Dataview FROM 修复 ──
n_entity = 0
for p in (NOTES / "实体").rglob("*.md"):
    t = p.read_text(encoding="utf-8")
    orig = t
    t = t.replace('FROM "Notes/政策库" OR "Notes/媒体库" OR "Notes/数据库"', 'FROM "Notes/素材库"')
    t = t.replace('FROM "Notes/数据库"', 'FROM "Notes/素材库"')
    if t != orig:
        p.write_text(t, encoding="utf-8")
        n_entity += 1
print(f"[实体页] 修复 {n_entity} 个 Dataview FROM")

# ── 2. wiki 双链路径修复 ──
n_wiki = 0
for p in (NOTES / "政策wiki").rglob("*.md"):
    t = p.read_text(encoding="utf-8")
    orig = t
    t = t.replace("[[../../媒体库/", "[[../../素材库/媒体/")
    t = t.replace("[[../../政策库/", "[[../../素材库/政策/")
    t = t.replace("[[../../数据库/", "[[../../素材库/")
    # 无 ../../ 前缀的（同层引用）
    t = t.replace("[[媒体库/", "[[../../素材库/媒体/")
    t = t.replace("[[政策库/", "[[../../素材库/政策/")
    if t != orig:
        p.write_text(t, encoding="utf-8")
        n_wiki += 1
print(f"[wiki] 修复 {n_wiki} 个双链路径")

# ── 3. 检查残留引用 ──
print("\n[检查] 残留的原目录引用:")
for p in list((NOTES / "实体").rglob("*.md")) + list((NOTES / "政策wiki").rglob("*.md")):
    t = p.read_text(encoding="utf-8", errors="replace")
    for old in ["Notes/政策库", "Notes/媒体库", "Notes/数据库", "[[../../媒体库", "[[../../政策库", "[[../../数据库"]:
        if old in t:
            print(f"  {p.relative_to(NOTES)}: 含 {old}")
