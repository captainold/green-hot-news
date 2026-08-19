#!/usr/bin/env python3.11
"""按规范化标题清理重复条目（2026-08-19）。

Google News 聚合 URL 是 base64 且每次抓取不同，按 url 去重会漏——
同一条新闻可能入库多份。本脚本按 _title_dedup_key 去重，保留最早版本。
用法：python3.11 scripts/dedup_items.py [data/*.json ...]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("un", str(ROOT / "scripts" / "update_news.py"))
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)


def dedup_file(path: Path) -> int:
    if not path.exists():
        print(f"  跳过（不存在）: {path.name}")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    seen: dict[str, dict] = {}
    removed = 0
    kept: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        k = un._title_dedup_key(it.get("title", ""))
        if not k:
            kept.append(it)
            continue
        if k in seen:
            removed += 1
            continue
        seen[k] = it
        kept.append(it)
    if isinstance(data, dict) and "items" in data:
        data["count"] = len(kept)
        data["items"] = kept
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    print(f"  {path.name}: {len(items)} → {len(kept)}（移除 {removed} 重复）")
    return removed


def main() -> int:
    files = sys.argv[1:] or [
        "data/history.json",
        "data/latest-24h.json",
        "data/latest-24h-all.json",
    ]
    total = 0
    for fn in files:
        total += dedup_file(ROOT / fn)
    print(f"完成，共移除 {total} 条重复")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
