#!/usr/bin/env python3
"""_diag_topics2.py — 直接调用 merge_history 验证 topics 回填"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/opt/green-hot-news/scripts")
import update_news as un

hist = json.loads(Path("/opt/green-hot-news/data/history.json").read_text(encoding="utf-8"))
targets = [it for it in hist.get("items", []) if "AI诉讼" in it.get("title", "")]
print(f"目标条目: {len(targets)}")
for t in targets:
    print(f"  前: topics={t.get('topics')} | {t['title'][:40]}")

out = Path("/tmp/mh-test")
out.mkdir(exist_ok=True)
un.merge_history(out, targets, datetime.now(timezone.utc))

res = json.loads((out / "history.json").read_text(encoding="utf-8"))
for it in res.get("items", []):
    print(f"  后: topics={it.get('topics')} | {it.get('title','')[:40]}")
print("OK")
