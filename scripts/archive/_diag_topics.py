#!/usr/bin/env python3
"""_diag_topics.py — 服务器端验证 topics 重算"""
import json
import sys

sys.path.insert(0, "/opt/green-hot-news/scripts")
import update_news as un

# 1. extract_topic_tags 实测
for t in [
    "Anthropic支付15亿美元和解盗版图书训练AI诉讼，法律问题仍待解决",
    "Education for Climate Day 2026",
    "Why land-use emissions have fallen by a third this century - in six charts",
]:
    print(f"extract_topic_tags({t[:30]}...) = {un.extract_topic_tags(t)}")

# 2. history 里这些条目的 topics 现状
hist = json.loads(open("/opt/green-hot-news/data/history.json", encoding="utf-8").read())
print(f"\nhistory 总数: {len(hist.get('items', []))} generated: {hist.get('generated_at')}")
for it in hist.get("items", []):
    if "AI诉讼" in it.get("title", "") or "Education for Climate" in it.get("title", ""):
        print(f"  topics={it.get('topics')} | {it['title'][:50]}")
