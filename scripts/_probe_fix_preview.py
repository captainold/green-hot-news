#!/usr/bin/env python3
"""_probe_fix_preview.py — 干跑预览 _fix_polluted_titles 的判定结果（不修改）"""
import sys, json, os, re
sys.path.insert(0, "scripts")
from _fix_polluted_titles import strip_site_suffix, is_nav_junk, is_static_content

print("===== data 层预览（history.json）=====")
d = json.load(open("data/history.json", encoding="utf-8"))
items = d if isinstance(d, list) else d.get("items", [])
for it in items:
    t = str(it.get("title", ""))
    if "您访问的链接即将离开" in t:
        print(f"  FIX(mee) {t[:50]}")
        continue
    s = strip_site_suffix(t)
    if s == t:
        continue
    if is_nav_junk(s):
        print(f"  DEL  [{it.get('site_id')}] {t[:60]}")
    elif is_static_content(s):
        print(f"  DEL(静态页) [{it.get('site_id')}] {t[:60]}")
    else:
        print(f"  FIX  [{it.get('site_id')}] {t[:50]} → {s[:50]}")

print()
print("===== Notes 层预览（美国部委目录）=====")
for sub in ("政策库", "媒体库"):
    for dirpath, _d, files in os.walk(f"Notes/{sub}"):
        if not any(k in dirpath for k in ("美国DOE", "美国EIA", "美国EPA", "美国FERC", "美国NOAA", "加州CARB")):
            continue
        for fn in files:
            if not fn.endswith(".md"):
                continue
            base = os.path.basename(fn)[:-3]
            name_no_date = re.sub(r"^\d{4}-\d{2}-\d{2} ", "", base)
            s = strip_site_suffix(name_no_date)
            if s != name_no_date:
                action = "DEL" if is_nav_junk(s) else "REN"
                print(f"  {action} {os.path.join(dirpath, fn)}")
                print(f"        → {s}")
            elif is_nav_junk(name_no_date) and name_no_date not in {x for x in []}:
                pass  # 无后缀的纯导航名（如 'STEO Data Browser'）也检查
