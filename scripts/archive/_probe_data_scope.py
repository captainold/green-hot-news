#!/usr/bin/env python3
"""_probe_data_scope.py — 摸清 data 层站名/导航标题影响范围"""
import json, re

for f in ("data/history.json", "data/latest-24h.json"):
    d = json.load(open(f, encoding="utf-8"))
    items = d if isinstance(d, list) else d.get("items", [])
    print(f"=== {f} ({len(items)} 条)")
    for sid in ("us_doe", "us_noaa", "us_epa", "us_ferc", "uscarb", "us_eia", "mee", "cneeex", "irena", "chinanecc"):
        hits = [i for i in items if i.get("site_id") == sid]
        junk = [i for i in hits if re.search(r"\.gov\)|\(EIA\)|\(NOAA\)|\(EPA\)|\(DOE\)|Administration|公共服务网|即将离开", str(i.get("title", "")))]
        if hits:
            print(f"  {sid}: {len(hits)} 条, 含站名/导航特征 {len(junk)} 条")
            for i in junk[:6]:
                print(f"     {i.get('title','')[:78]}")
