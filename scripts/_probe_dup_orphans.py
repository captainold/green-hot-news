#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""孤儿 dup 文件核查：全库里有没有和它正文指纹相同的另一条（判断原件是被"去重"删掉的还是丢了名）。

结论决定动作：
  · 全库找不到同指纹 → 原件只是改名/丢了后缀 → 把 【dupN】 去掉即可（安全）
  · 全库找到同指纹   → 原件当初被当重复删了，剩的这份是历史残留 → 建议删除（需老温点头，不擅删）

用法：python -X utf8 scripts/_probe_dup_orphans.py
"""
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAT = ROOT / "Notes" / "素材库"
data = json.loads((ROOT / "cache" / "dup-eval.json").read_text(encoding="utf-8"))
orphans = data.get("orphan", [])
print(f"孤儿组 {len(orphans)} 个\n")


def fp_of(p: Path) -> str:
    t = p.read_text(encoding="utf-8", errors="replace")

    def sec(name):
        m = re.search(rf"^##\s*{name}\s*$", t, re.M)
        if not m:
            return ""
        rest = t[m.end():]
        nxt = re.search(r"^##\s", rest, re.M)
        return (rest[:nxt.start()] if nxt else rest).strip()
    return hashlib.sha1((re.sub(r"\s+", "", sec("摘要")) + "|" +
                         re.sub(r"\s+", "", sec("正文"))).encode()).hexdigest()[:12]


# 全库指纹 → 路径
index = defaultdict(list)
for p in MAT.rglob("*.md"):
    index[fp_of(p)].append(p)

safe = stale = 0
for g in orphans:
    stems = g["stems"]
    d = g["dir"]
    for stem in stems:
        p = MAT / d / f"{stem}.md"
        if not p.exists():
            print(f"  ⚠️ 文件不存在（路径可能含子目录）: {d}/{stem}")
            continue
        fp = fp_of(p)
        twins = [q for q in index.get(fp, []) if q != p]
        kind = "残留（全库有同指纹）" if twins else "仅名字丢了后缀（安全改回）"
        if twins:
            stale += 1
        else:
            safe += 1
        print(f"  [{kind}] {stem[:64]}")
        for q in twins[:2]:
            print(f"        同指纹: {q.relative_to(MAT)}")
print(f"\n合计：可安全改名 {safe}｜疑似残留 {stale}")
