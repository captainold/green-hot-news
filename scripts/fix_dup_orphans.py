#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""孤儿 dup 文件修复：把只剩 `【dupN】` 一条的笔记改回原名（去掉后缀）。

场景：`sanitize_note_names.py` 给同名文件加 `【dupN】`，之后同组其它文件被删/改名，
后缀就成了"唯一一份"的名字 —— 既丑又会让人误以为是重复副本。

安全前提（脚本内含校验）：
  1. 同目录下不存在去掉后缀后的同名文件（大小写不敏感）
  2. 全库不存在与它 摘要+正文 指纹相同的另一条（否则它是历史残留，应删除而非改名 → 只报告不动手）

用法：
    python -X utf8 scripts/fix_dup_orphans.py            # 预览
    python -X utf8 scripts/fix_dup_orphans.py --apply    # 执行改名
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAT = ROOT / "Notes" / "素材库"
DUP_RE = re.compile(r"\s*【dup\d+】")


def fingerprint(p: Path) -> str:
    t = p.read_text(encoding="utf-8", errors="replace")

    def sec(name: str) -> str:
        m = re.search(rf"^##\s*{name}\s*$", t, re.M)
        if not m:
            return ""
        rest = t[m.end():]
        nxt = re.search(r"^##\s", rest, re.M)
        return (rest[:nxt.start()] if nxt else rest).strip()
    return hashlib.sha1((re.sub(r"\s+", "", sec("摘要")) + "|" +
                         re.sub(r"\s+", "", sec("正文"))).encode()).hexdigest()[:12]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    notes = [p for p in MAT.rglob("*.md")]
    # 组键：同目录 + 去掉 【dupN】 后的名字
    groups: dict[tuple[Path, str], list[Path]] = defaultdict(list)
    for p in notes:
        groups[(p.parent, DUP_RE.sub("", p.stem).strip())].append(p)

    fp_index: dict[str, list[Path]] = defaultdict(list)
    for p in notes:
        fp_index[fingerprint(p)].append(p)

    renamed = blocked = stale = 0
    for (d, base), members in sorted(groups.items()):
        if not all(DUP_RE.search(m.stem) for m in members):
            continue        # 组里有"原件"，不是孤儿
        for m in members:
            fp = fingerprint(m)
            twins = [q for q in fp_index.get(fp, []) if q != m]
            target = d / f"{base}.md"
            if twins:
                stale += 1
                print(f"  ⏸ 疑似残留（全库有同指纹副本，需人工决定是否删除）: {m.name[:60]}")
                continue
            if target.exists():
                blocked += 1
                print(f"  ⛔ 目标已存在，跳过: {target.name[:60]}")
                continue
            if any(q.name.lower() == target.name.lower() for q in d.iterdir()):
                blocked += 1
                print(f"  ⛔ 大小写重名，跳过: {target.name[:60]}")
                continue
            print(f"  ✏️ {m.name[:70]}\n     → {target.name[:70]}")
            if args.apply:
                m.rename(target)
                fp_index[fp] = [target if q == m else q for q in fp_index[fp]]
            renamed += 1

    print(f"\n{'已改名' if args.apply else '待改名'} {renamed}｜疑似残留待人工 {stale}｜跳过 {blocked}")
    if not args.apply:
        print("[dry-run] 未改任何文件，加 --apply 执行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
