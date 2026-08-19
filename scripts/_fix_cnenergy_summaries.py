#!/usr/bin/env python3
"""_fix_cnenergy_summaries.py — 一次性：重抓 chinaenergy 空摘要条目补 history + summary-index

（2026-08-19）服务器抓 cnenergynews 详情页曾被 __tst_status 挑战拦截，article_content
已修复绕过；本脚本对 history.json 里 chinaenergy 空摘要条目直接 fetch_article 重抓，
成功后写回 history.json 与 summary-index.json（幂等：有摘要的跳过）。
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, "/opt/green-hot-news/scripts")
import article_content as ac

DATA = Path("/opt/green-hot-news/data")
hist_path = DATA / "history.json"
sum_path = DATA / "summary-index.json"

hist = json.loads(hist_path.read_text(encoding="utf-8"))
summ = json.loads(sum_path.read_text(encoding="utf-8")) if sum_path.exists() else {}

targets = [
    it for it in hist.get("items", [])
    if it.get("site_id") == "chinaenergy" and not (it.get("summary") or "").strip()
]
print(f"chinaenergy 空摘要待补: {len(targets)} 条")

filled = 0
failed = []
with ThreadPoolExecutor(max_workers=6) as ex:
    futs = {ex.submit(ac.fetch_article, it.get("url", "")): it for it in targets}
    for fut in as_completed(futs):
        it = futs[fut]
        try:
            res = fut.result()
        except Exception:
            res = None
        s = (res or {}).get("summary") or ""
        if s:
            it["summary"] = s
            summ[it.get("url", "")] = s
            filled += 1
        else:
            failed.append(it.get("url", ""))

hist_path.write_text(json.dumps(hist, ensure_ascii=False), encoding="utf-8")
sum_path.write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"补回 {filled} 条，仍失败 {len(failed)} 条")
for u in failed[:10]:
    print("  失败:", u)
