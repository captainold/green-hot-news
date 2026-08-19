#!/usr/bin/env python3
"""_diag_topics3.py — 检查 /tmp/gpn-full 生成结果的 topics"""
import json
import collections

d = json.load(open("/tmp/gpn-full/history.json", encoding="utf-8"))
its = d.get("items", [])
c = collections.Counter(len(i.get("topics") or []) for i in its)
print("topics 分布:", dict(sorted(c.items())))
n = 0
for i in its:
    if "AI诉讼" in i.get("title", "") or i.get("site_id") == "mongabay":
        print(f"  topics={i.get('topics')} | {i.get('site_id')} | {i['title'][:55]}")
        n += 1
        if n > 6:
            break
