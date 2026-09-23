#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""补充检查：伪正文样例 / 图片引用形态 / 检索视图现状"""
import os, re, glob, yaml

BASE = "/mnt/c/Users/wenyu/Documents/Obsidian_wen/green-hot-news/Notes/数据库"
files = sorted(glob.glob(os.path.join(BASE, "*.qmd")))

def parse_qmd(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    fm, body = {}, text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except Exception:
                fm = {}
            body = parts[2]
    return fm, body

# 1) 伪正文样例（正文<100字符的）
print("== 正文<100字符 样例 ==")
cnt = 0
for p in files:
    fm, body = parse_qmd(p)
    m = re.search(r"## 正文\n(.*?)(?=\n## |\Z)", body, re.S)
    if m and len(m.group(1).strip()) < 100:
        print(f"  [{len(m.group(1).strip())}字] {os.path.basename(p)[:60]}")
        print(f"    正文内容: {m.group(1).strip()[:80]!r}")
        cnt += 1
        if cnt >= 5:
            break

# 2) 图片引用形态分类
img_re = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
kinds = {}
for p in files:
    _, body = parse_qmd(p)
    for u in img_re.findall(body):
        if u.startswith("http://") or u.startswith("https://"):
            k = "http外链"
        elif "attachments/" in u:
            k = "本地附件(attachments/)"
        elif u.startswith("attachment"):
            k = "本地(无斜杠)"
        else:
            k = f"其他({u[:40]})"
        kinds[k] = kinds.get(k, 0) + 1
print("\n== 图片引用形态 ==")
for k, c in sorted(kinds.items(), key=lambda x: -x[1]):
    print(f"  {k}: {c}")

# 3) 检索视图现状：根目录/analysis 下 dataview 查询
print("\n== 检索/索引文件现状 ==")
for root in ["/mnt/c/Users/wenyu/Documents/Obsidian_wen/green-hot-news/analysis",
             "/mnt/c/Users/wenyu/Documents/Obsidian_wen/green-hot-news/Notes"]:
    if os.path.isdir(root):
        for f in os.listdir(root)[:20]:
            print(f"  {root.split('/')[-1]}/{f}")
