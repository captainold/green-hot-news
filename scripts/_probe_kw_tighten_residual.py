#!/usr/bin/env python3.11
"""列出 v5.2 收紧后仍判 30 档的 gold 条目（检查包补充）。"""
import importlib.util
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
spec = importlib.util.spec_from_file_location("gs", Path("scripts/gold_set.py"))
gs = importlib.util.module_from_spec(spec)
sys.modules["gs"] = gs
spec.loader.exec_module(gs)

rows = [r for r in gs.load_gold() if r.get("label_strength") is not None]
print("仍判 30 档的条目：")
for r in rows:
    sub = gs.live_sub(r)
    sc = gs.kw_strength(r, sub)
    if sc == 30:
        title = (r.get("title_zh") or r.get("title") or "")[:52]
        print("  gold={} sub={} | {}".format(r["label_strength"], sub, title))
