#!/usr/bin/env python3
"""_probe_obsidian_links.py — 检查这些文件是否被 Obsidian 双链引用（决定可否改名/删除）"""
import os, re, glob

# 待处理文件（站名后缀 / 导航页）
target_dirs = ["政策库/美国/美国DOE", "政策库/美国/美国EIA", "政策库/美国/美国EPA",
               "政策库/美国/美国FERC", "政策库/美国/美国NOAA", "政策库/美国/加州CARB"]
names = set()
for d in target_dirs:
    p = f"Notes/{d}"
    if os.path.isdir(p):
        for fn in os.listdir(p):
            if fn.endswith(".md"):
                names.add(fn[:-3])

# 全 Notes 搜 [[引用]]
refs = {}
for sub in ("政策库", "媒体库"):
    for dirpath, _d, files in os.walk(f"Notes/{sub}"):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                c = open(fp, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            for m in re.finditer(r"\[\[([^\]]+)\]\]", c):
                link = m.group(1).split("|")[0].strip()
                if link in names:
                    refs.setdefault(link, []).append(fp)

print(f"待处理文件数: {len(names)}")
print(f"被引用数: {len(refs)}")
for link, files in list(refs.items())[:20]:
    print(f"  [{link[:60]}] <- {files[0]}")
if not refs:
    print("  ✓ 无任何 Obsidian 双链引用 → 可安全改名/删除")
