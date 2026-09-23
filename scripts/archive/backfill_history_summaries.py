#!/usr/bin/env python3
"""backfill_history_summaries.py — 从 summary-index.json 回填 history.json 空摘要

背景（2026-08-19）：中国能源报详情页被 __tst_status JS 挑战拦截，服务器抓不到正文
→ 96% 条目首次收录时摘要为空并固化在 history.json（merge_history 保留首次版本，
不更新旧条目）。article_content 修复挑战绕过后，重跑抓取会补 Notes/summary-index，
但 history 旧条目仍是空 → 本脚本一次性回填（幂等，有摘要的跳过）。

用法：python3.11 scripts/backfill_history_summaries.py [--data-dir data]
"""
import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    hist_path = data_dir / "history.json"
    sum_path = data_dir / "summary-index.json"
    if not hist_path.exists() or not sum_path.exists():
        print(f"缺文件: history={hist_path.exists()} summary-index={sum_path.exists()}")
        return 1

    hist = json.loads(hist_path.read_text(encoding="utf-8"))
    summ = json.loads(sum_path.read_text(encoding="utf-8")) or {}
    items = hist.get("items", [])
    filled = 0
    still_empty = 0
    for it in items:
        if it.get("summary"):
            continue
        s = (summ.get(it.get("url", "")) or "").strip()
        if s:
            it["summary"] = s
            filled += 1
        else:
            still_empty += 1
    hist["items"] = items
    hist_path.write_text(
        json.dumps(hist, ensure_ascii=False), encoding="utf-8")
    print(f"history.json: 回填 {filled} 条摘要，仍空 {still_empty} 条（共 {len(items)}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
