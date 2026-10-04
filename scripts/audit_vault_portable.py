#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""vault 可移植性体检：Windows/macOS 落不了盘或会互相覆盖的文件名。

检查项（服务器 ext4 能建、Windows 不能建/会覆盖）：
  1. 文件名 > 255 字节（ext4 上限；Windows 是 255 UTF-16 字符）
  2. 同目录内大小写不敏感重名（Windows/macOS 会互相覆盖 → git 永远显示 modified）
  3. Windows 非法字符 < > : " / \ | ? * 与结尾的点/空格
  4. Unicode 归一化差异重名（NFC/NFD，macOS 会碰撞）
  5. 全路径 > 250 字符（Windows MAX_PATH 未开长路径时落不下）

用法（服务器/本地均可）：
    python -X utf8 cache/_audit_portable.py [Notes/素材库]
"""
from __future__ import annotations

import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "Notes" / "素材库"


def main() -> int:
    files = [p for p in TARGET.rglob("*") if p.is_file() and ".git" not in p.parts]
    print(f"扫描 {len(files)} 个文件：{TARGET}")

    longb, illegal, longpath = [], [], []
    lower_map: dict[tuple[str, str], list[str]] = defaultdict(list)
    norm_map: dict[tuple[str, str], list[str]] = defaultdict(list)
    for p in files:
        n = p.name
        if len(n.encode("utf-8")) > 255:
            longb.append((len(n.encode("utf-8")), str(p)))
        if any(c in n for c in '<>:"/\\|?*') or n != n.rstrip(". ") or not n.strip():
            illegal.append(str(p))
        if len(str(p)) > 250:
            longpath.append((len(str(p)), str(p)))
        key = (str(p.parent), n.casefold())
        lower_map[key].append(n)
        norm_map[(str(p.parent), unicodedata.normalize("NFC", n))].append(n)

    case_dups = {k: v for k, v in lower_map.items() if len(set(v)) > 1}
    norm_dups = {k: v for k, v in norm_map.items() if len(set(v)) > 1}

    print(f"\n1) 文件名 > 255 字节: {len(longb)}")
    for b, p in sorted(longb, reverse=True)[:10]:
        print(f"   {b} 字节  {p}")
    print(f"2) 大小写不敏感重名（同目录）: {len(case_dups)}")
    for (d, _), names in list(case_dups.items())[:10]:
        print(f"   {d}: {sorted(set(names))}")
        for nm in sorted(set(names)):
            f = Path(d) / nm
            head = f.read_text(encoding="utf-8", errors="replace")[:600]
            url = next((l for l in head.splitlines() if l.startswith("url:")), "url: ?")
            mid = next((l for l in head.splitlines() if l.startswith("id:")), "id: ?")
            print(f"      {nm}  | {mid} | {url} | {f.stat().st_size}B")
    print(f"3) Windows 非法字符/结尾点空格: {len(illegal)}")
    for p in illegal[:10]:
        print(f"   {p}")
    print(f"4) Unicode 归一化重名: {len(norm_dups)}")
    for (d, _), names in list(norm_dups.items())[:10]:
        print(f"   {d}: {[unicodedata.normalize('NFC', x) for x in sorted(set(names))]}")
    print(f"5) 全路径 > 250 字符: {len(longpath)}")
    for n, p in sorted(longpath, reverse=True)[:10]:
        print(f"   {n}  {p}")
    total = len(longb) + len(case_dups) + len(illegal) + len(norm_dups) + len(longpath)
    print(f"\n合计问题 {total} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
