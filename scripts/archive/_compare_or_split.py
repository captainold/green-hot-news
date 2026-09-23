#!/usr/bin/env python3
"""对比 OR 拆分前后各源入库数量。"""
import json
from collections import Counter

def load(path):
    d = json.load(open(path))
    return d['items'] if isinstance(d, dict) else d

before = load('/tmp/ghn_test4/latest-24h.json')
after = load('/tmp/ghn_test5/latest-24h.json')
cb = Counter(i.get('site_id') for i in before)
ca = Counter(i.get('site_id') for i in after)

print(f"{'site_id':22s} {'前':>4s} {'后':>4s}  变化")
print('-' * 45)
all_ids = sorted(set(cb) | set(ca))
for sid in all_ids:
    b, a = cb.get(sid, 0), ca.get(sid, 0)
    mark = ''
    if a > b:
        mark = f'▲ +{a-b}'
    elif a < b:
        mark = f'▼ {a-b}'
    if mark:
        print(f"{sid:22s} {b:4d} {a:4d}  {mark}")

print()
print(f"总量: {len(before)} → {len(after)}")
print(f"四维前: {dict(Counter(i.get('dimension') for i in before))}")
print(f"四维后: {dict(Counter(i.get('dimension') for i in after))}")
