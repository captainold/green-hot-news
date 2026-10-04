#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测：dup 组里 Google News 聚合 url 解码后，是否等于同组那条站点直连 url。

决定"同文两条 url"能否在 export_qmd 层根治（url 索引加解码后次键）：
  · 解码后 == 直连 url   → 可以归并（根治）
  · 解码后 != 直连 url   → 只能做正文互补（治标）

用法：python -X utf8 scripts/_probe_dup_decode.py [N]
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import article_content as ac  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 12
data = json.loads((ROOT / "cache" / "dup-eval.json").read_text(encoding="utf-8"))
groups = data.get("partial", [])
print(f"待探测组: {len(groups)}（每组一条 direct + 一条 gnews）\n")

same = diff = fail = 0
for g in groups[:N]:
    gn = next((m for m in g["members"] if "news.google.com" in m["url"]), None)
    direct = next((m for m in g["members"] if "news.google.com" not in m["url"]), None)
    if not gn or not direct:
        continue
    t0 = time.time()
    try:
        decoded = ac._decode_google_news_url(gn["url"])
    except Exception as e:
        decoded = f"ERR:{type(e).__name__}"
    dt = time.time() - t0
    ok = decoded and decoded == direct["url"]
    if not decoded or decoded.startswith("ERR"):
        fail += 1
    elif ok:
        same += 1
    else:
        diff += 1
    print(f"[{g['base'][:32]:<34}] 解码{'==' if ok else '≠'}直连  ({dt:.1f}s)")
    print(f"    gnews  : {gn['url'][:88]}")
    print(f"    解码后 : {(decoded or '')[:88]}")
    print(f"    直连   : {direct['url'][:88]}\n")

print(f"合计 {min(N, len(groups))} 组：解码==直连 {same}｜解码≠直连 {diff}｜解码失败 {fail}")
