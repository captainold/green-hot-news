#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布完成登记（2026-09-23）。

把当日 digest.json 里的 URL 记入 data/publish/state.json 的 published_urls，
后续精选自动排除，防止重复推送。

用法：python scripts/publish/mark_published.py [--date 2026-09-23]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import out_dir, save_state, load_state, today_str, utf8_console


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description="登记已发布")
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    date = args.date or today_str()

    odir = out_dir(date)
    digest_path = odir / "digest.json"
    if not digest_path.exists():
        print(f"❌ 找不到 {digest_path}")
        return 1
    digest = json.loads(digest_path.read_text(encoding="utf-8"))
    urls = [i["url"] for i in digest["items"] if i.get("url")]

    state = load_state()
    before = len(state.get("published_urls", []))
    merged = list(dict.fromkeys(state.get("published_urls", []) + urls))
    state["published_urls"] = merged
    state["last_marked_date"] = date
    state["last_marked_at"] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    print(f"✅ 已登记 {len(urls)} 条（去重后新增 {len(merged) - before}，累计 {len(merged)}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
