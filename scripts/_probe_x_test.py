#!/usr/bin/env python3
"""_probe_x_test.py — fetch_x 单测：解析、过滤命中率、样例"""
import sys
import time
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, "scripts")
import update_news as un

sess = un.create_session()
t0 = time.time()
items = un.fetch_x(sess, datetime.now(timezone.utc))
dt = time.time() - t0
print(f"fetch_x 返回 {len(items)} 条推文（{dt:.1f}s）")

hits = 0
by_acct = Counter()
for it in items:
    ok = un.is_policy_relevant(it.title, it.url, it.site_id, it.meta.get("summary", ""))
    if ok:
        hits += 1
        by_acct[it.source] += 1
print(f"is_policy_relevant 命中 {hits}/{len(items)} = {hits / max(len(items), 1) * 100:.0f}%")
print("按账号命中:", dict(by_acct))

print("\n--- 命中样例（最多 10 条）---")
n = 0
for it in items:
    if un.is_policy_relevant(it.title, it.url, it.site_id, it.meta.get("summary", "")):
        print(f"[{it.source}] {it.published_at}")
        print(f"  {it.title[:150]}")
        n += 1
        if n >= 10:
            break

print("\n--- 未命中样例（最多 5 条，检查是否误杀）---")
n = 0
for it in items:
    if not un.is_policy_relevant(it.title, it.url, it.site_id, it.meta.get("summary", "")):
        print(f"[{it.source}] {it.published_at}")
        print(f"  {it.title[:150]}")
        n += 1
        if n >= 5:
            break
