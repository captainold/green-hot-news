#!/usr/bin/env python3.11
# -*- coding: utf-8 -*-
"""qmd 数据库现状统计（全量扫描 Notes/数据库/*.qmd）"""
import os, re, glob, yaml, json
from collections import Counter, defaultdict

BASE = "/mnt/c/Users/wenyu/Documents/Obsidian_wen/green-hot-news/Notes/数据库"
files = sorted(glob.glob(os.path.join(BASE, "*.qmd")))
print(f"总文件数: {len(files)}")

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

rows = []
for p in files:
    fm, body = parse_qmd(p)
    rows.append({"path": os.path.basename(p), "fm": fm, "body": body})

N = len(rows)

def fval(fm, key):
    v = fm.get(key)
    if v is None:
        return ""
    if isinstance(v, list):
        return v
    return str(v).strip()

# ---------- 1. 正文缺失 ----------
no_body = [r for r in rows if "## 正文" not in r["body"]]
print(f"\n[1] 无正文条目: {len(no_body)}/{N} = {len(no_body)/N*100:.1f}%")
no_body_sites = Counter(fval(r["fm"], "site") or fval(r["fm"], "site_id") or "(无site字段)" for r in no_body)
print("无正文 Top 站点:")
for s, c in no_body_sites.most_common(15):
    total = sum(1 for r in rows if (fval(r["fm"], "site") or fval(r["fm"], "site_id")) == s)
    print(f"  {s}: {c} 条 (该站共 {total} 条, 无正文率 {c/total*100 if total else 0:.0f}%)")

# ---------- 2. 图片本地化 ----------
img_re = re.compile(r'!\[[^\]]*\]\(([^)]+)\)')
http_img = 0
local_img = 0
total_img_files = 0
http_by_site = Counter()
img_by_site = Counter()
for r in rows:
    site = fval(r["fm"], "site") or fval(r["fm"], "site_id") or "(无site字段)"
    imgs = img_re.findall(r["body"])
    for u in imgs:
        total_img_files += 1
        img_by_site[site] += 1
        if u.startswith("http://") or u.startswith("https://"):
            http_img += 1
            http_by_site[site] += 1
        elif "attachments/" in u or u.startswith("attachments"):
            local_img += 1
print(f"\n[2] 图片引用: 共 {total_img_files} 处; 本地附件 {local_img} ({local_img/total_img_files*100:.1f}%), 外链 http {http_img} ({http_img/total_img_files*100:.1f}%)")
print("外链图片 Top 站点 (含图片总数, 外链率):")
for s, c in http_by_site.most_common(12):
    tot = img_by_site[s]
    print(f"  {s}: 外链 {c} / 共 {tot} ({c/tot*100:.0f}%)")

# ---------- 3. 字段缺失 ----------
FIELD_KEYS = ["title_zh", "dimension", "layer", "sub_dimension", "trl", "eu_taxonomy",
              "isic", "gics", "ipc", "enabling_tech", "tech_feature", "topics", "region", "people"]
print(f"\n[3] 字段缺失率 (空值/空列表/缺失):")
for k in FIELD_KEYS:
    miss = 0
    for r in rows:
        v = fval(r["fm"], k)
        if v == "" or v == [] or v == "无":
            miss += 1
    print(f"  {k}: {miss}/{N} = {miss/N*100:.1f}%")

# 字段分布统计（用于报告）
print("\n--- 补充: 各多维字段取值分布 ---")
for k in ["layer", "dimension", "sub_dimension", "trl"]:
    c = Counter(fval(r["fm"], k) for r in rows)
    print(f"  {k}: {dict(c.most_common(12))}")

# 无正文条目样例（各站抽1个）
print("\n--- 无正文条目样例 ---")
seen = set()
for r in no_body:
    site = fval(r["fm"], "site") or fval(r["fm"], "site_id")
    if site not in seen:
        seen.add(site)
        if len(seen) <= 12:
            print(f"  {site}: {r['path']}")

# tech_feature 值分布
print("\n--- tech_feature 值分布 ---")
c = Counter()
for r in rows:
    v = fval(r["fm"], "tech_feature")
    if v == "":
        c["空字符串"] += 1
    elif v == "无":
        c["'无'占位"] += 1
    else:
        c["有真实内容"] += 1
print(dict(c))
