#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""qmd 数据库现状统计·第二波：正文质量/去重/增长趋势"""
import os, re, glob, yaml
from collections import Counter

BASE = "/mnt/c/Users/wenyu/Documents/Obsidian_wen/green-hot-news/Notes/数据库"
files = sorted(glob.glob(os.path.join(BASE, "*.qmd")))

def parse_qmd(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    fm = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                fm = yaml.safe_load(parts[1]) or {}
            except Exception:
                fm = {}
            body = parts[2]
    return fm, body

rows = [(os.path.basename(p), *parse_qmd(p)) for p in files]
N = len(rows)

# 正文长度分布（有 ## 正文 的）
lens = []
for name, fm, body in rows:
    m = re.search(r"## 正文\n(.*?)(?=\n## |\Z)", body, re.S)
    if m:
        lens.append(len(m.group(1).strip()))
lens_sorted = sorted(lens)
print(f"有正文文件: {len(lens)}")
print(f"正文长度: 最短 {min(lens)}, 最长 {max(lens)}, 中位 {lens_sorted[len(lens)//2]}")
short = [l for l in lens if l < 100]
print(f"正文 <100 字符(疑似伪正文/仅摘要重复): {len(short)} ({len(short)/len(lens)*100:.1f}%)")

# 无正文文件里有 ## 摘要 的
no_body = [(n, fm, b) for n, fm, b in rows if "## 正文" not in b]
has_sum = sum(1 for n, fm, b in no_body if "## 摘要" in b)
print(f"无正文 {len(no_body)} 条中, 有摘要的: {has_sum} ({has_sum/len(no_body)*100:.0f}%)")

# 有正文文件里含 技术特征 section 的
has_tech = sum(1 for n, fm, b in rows if "## 技术特征" in b)
print(f"全部文件中含 '## 技术特征' section: {has_tech} ({has_tech/N*100:.1f}%)")

# 重复 URL
urls = Counter()
for name, fm, body in rows:
    u = (fm.get("url") or "").strip()
    if u:
        urls[u] += 1
dups = {u: c for u, c in urls.items() if c > 1}
print(f"重复 URL: {len(dups)} 组 / 涉及 {sum(dups.values())} 条")

# 重复标题
titles = Counter()
for name, fm, body in rows:
    t = (fm.get("title") or "").strip()
    if t:
        titles[t] += 1
dt = {t: c for t, c in titles.items() if c > 1}
print(f"重复标题: {len(dt)} 组 / 涉及 {sum(dt.values())} 条")

# 无正文条目里的图片引用
img_re = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
nb_imgs = sum(len(img_re.findall(b)) for n, fm, b in no_body)
print(f"无正文条目中的图片引用: {nb_imgs} 处")

# 按月新增
dates = []
for p in files:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(p))
    if m:
        dates.append(m.group(1))
dc = Counter(d[:7] for d in dates)
print("按月新增 qmd 数(最近8个月):", dict(sorted(dc.items())[-8:]))

# 附件目录大小
att = os.path.join(BASE, "attachments")
if os.path.isdir(att):
    n_att = len(os.listdir(att))
    size = sum(os.path.getsize(os.path.join(att, f)) for f in os.listdir(att) if os.path.isfile(os.path.join(att, f)))
    print(f"attachments: {n_att} 个文件, 总大小 {size/1024/1024:.1f} MB")
