#!/usr/bin/env python3
"""_probe_restore_noaa.py — 恢复被误删的 NOAA 月度气候报告条目（从备份）"""
import json

bak = json.load(open("/tmp/history.json.bak", encoding="utf-8"))
bak_items = bak if isinstance(bak, list) else bak.get("items", [])

target = [i for i in bak_items if "Assessing the Global Temperature" in str(i.get("title", ""))]
print(f"备份中找到 {len(target)} 条")

cur = json.load(open("data/history.json", encoding="utf-8"))
cur_items = cur if isinstance(cur, list) else cur.get("items", [])
cur_urls = {i.get("url") for i in cur_items}

added = 0
for it in target:
    if it.get("url") in cur_urls:
        print(f"  已存在，跳过: {it.get('title','')[:50]}")
        continue
    # 剥离站名后缀
    it["title"] = "Assessing the Global Temperature and Precipitation in July 2026"
    cur_items.append(it)
    added += 1
    print(f"  恢复: {it.get('title','')[:60]}")

if added:
    if isinstance(cur, list):
        cur = cur_items
    else:
        cur["items"] = cur_items
    json.dump(cur, open("data/history.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"✓ 恢复 {added} 条")
else:
    print("无需恢复")
