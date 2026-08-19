#!/usr/bin/env python3
"""_probe_audit.py — 审计修复点本地验证"""
import sys

sys.path.insert(0, "scripts")
import update_news as un

print("=== 1. Mongabay 标题后缀清洗 ===")
for t in [
    "How plastic infiltrates Amazonian wildlife - news - Mongabay",
    " sacred ties to Philippines' endemic birds - news - Mongabay",
    "ooked conservation strategies (commentary) - news - Mongabay",
    "dient, seaweed is gaining ground in Brazil - news - Mongabay",
]:
    print(f"  in : {t!r}")
    print(f"  out: {un._strip_title_suffix(t)!r}")

print("\n=== 2. extract_topic_tags 现状 ===")
for t in [
    "Anthropic支付15亿美元和解盗版图书训练AI诉讼，法律问题仍待解决",
    "Education for Climate Day 2026",
    "Why land-use emissions have fallen by a third this century - in six charts",
    "中国人民银行行长潘功胜会见澳门银行公会代表团",
    "哈萨比斯卸任Google DeepMind CEO，回顾DeepMind与OpenAI的AI路线之争",
]:
    print(f"  {t[:40]} → {un.extract_topic_tags(t)}")

print("\n=== 3. 碳道详情页 summary 污染 ===")
import article_content as ac
res = ac.fetch_article("https://www.ideacarbon.org/news_free/2026/08/19/xxx")
print("  抓取测试:", "跳过（URL 不确定，见下）" if not res else res.get("summary", "")[:120])
