#!/usr/bin/env python3
"""_fix_audit_summaries.py — 清洗碳道污染摘要（history + summary-index + Notes）

污染模式：摘要开头带「碳道小编 · 2026-08-19 20:08 · 阅读量 · 16 摘要：xxx」。
article_content._clean_summary_meta 已修 fetch 侧，历史数据三处回填清洗。
幂等：清洗后再次运行无变化。
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "/opt/green-hot-news/scripts")
from article_content import _clean_summary_meta

DATA = Path("/opt/green-hot-news/data")
NOTES = Path("/opt/green-hot-news/Notes")

POLLUTED = re.compile(r"小编\s*[·.]\s*\d{4}-\d{2}-\d{2}.*?阅读量|^摘要[:：]|文章来源|我的位置")


def clean_count(s: str) -> tuple[str, bool]:
    out = _clean_summary_meta(s)
    return out, out != s


# 1. history.json
hist_path = DATA / "history.json"
hist = json.loads(hist_path.read_text(encoding="utf-8"))
h_fixed = 0
for it in hist.get("items", []):
    s = it.get("summary") or ""
    if POLLUTED.search(s):
        it["summary"] = _clean_summary_meta(s)
        h_fixed += 1
hist_path.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
print(f"history.json: 清洗 {h_fixed} 条")

# 2. summary-index.json
sum_path = DATA / "summary-index.json"
summ = json.loads(sum_path.read_text(encoding="utf-8"))
s_fixed = 0
for k, v in summ.items():
    if isinstance(v, str) and POLLUTED.search(v):
        summ[k] = _clean_summary_meta(v)
        s_fixed += 1
sum_path.write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"summary-index.json: 清洗 {s_fixed} 条")

# 3. Notes frontmatter（媒体库/碳道 等）
n_fixed = 0
for f in NOTES.rglob("*.md"):
    if f.name in ("政策库.md", "媒体库.md", "ai-index.md"):
        continue
    try:
        c = f.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        continue
    m = re.search(r'^(summary:\s*")(.*)("\s*)$', c, re.M)
    if not m:
        continue
    val = m.group(2)
    if POLLUTED.search(val):
        new_val = _clean_summary_meta(val)
        c = c[: m.start(2)] + new_val + c[m.end(2):]
        f.write_text(c, encoding="utf-8")
        n_fixed += 1
print(f"Notes frontmatter: 清洗 {n_fixed} 条")
print("done")
