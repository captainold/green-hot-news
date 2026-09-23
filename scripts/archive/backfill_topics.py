#!/usr/bin/env python3.11
"""给现有 data/*.json 回填 topics（主题标签）字段（2026-08-19）。

前端「关系图谱」依赖 items[].topics（仅主题标签，不含地域/政策类型管理标签）。
历史 JSON（history.json / latest-24h.json / latest-24h-all.json）里旧条目无此字段，
本脚本按标题补算一次。幂等：已有 topics 的条目跳过。

用法：python3.11 scripts/backfill_topics.py [--data-dir data]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_news  # noqa: E402  （导入安全：有 __main__ 守卫）


def backfill_file(path: Path) -> int:
    if not path.exists():
        print(f"  跳过（不存在）: {path}")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else data
    if not isinstance(items, list):
        print(f"  跳过（无 items）: {path}")
        return 0
    filled = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        if not it.get("topics"):
            it["topics"] = update_news.extract_topic_tags(it.get("title", "") or "")
            filled += 1
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {path.name}: 回填 {filled}/{len(items)} 条")
    return filled


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data")
    args = ap.parse_args()
    data_dir = Path(args.data_dir)
    total = 0
    for name in ("history.json", "latest-24h.json", "latest-24h-all.json"):
        total += backfill_file(data_dir / name)
    print(f"完成：共回填 {total} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
