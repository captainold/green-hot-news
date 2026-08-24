#!/usr/bin/env python3.11
"""只重算 trl + 重打分（2026-08-24 TRL 关键词扩展后）。

TRL_RULES 新增高精度技术词（机组/电站/电芯/中标/通过评价/首例/首创/成套技术等）
后，需要重算历史条目的 trl 字段并重打分（trl 是 v4.0 打分第 6 维度，空=3 分、
7-9/4-6=5 分、1-3=4 分）。此脚本只动 trl + score* 字段，不碰 tech_feature
（避免触发 LLM 提取）。幂等，可重复运行。

用法：python3.11 scripts/recompute_trl.py
"""
from __future__ import annotations

import json
import shutil
import sys
import importlib.util
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("un", str(ROOT / "scripts" / "update_news.py"))
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)

NOW = datetime.now().astimezone()


def process(path: Path) -> int:
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    is_dict = isinstance(data, dict) and "items" in data
    items = data["items"] if is_dict else data
    changed = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        old_trl = it.get("trl", "")
        new_trl = un.classify_trl(it.get("title", ""), it.get("summary", ""))
        if new_trl == old_trl:
            continue
        it["trl"] = new_trl
        # 重打分：trl 变化影响第 6 维度分值
        people = it.get("people") or []
        scoring = un.score_item(
            it.get("site_id", ""),
            it.get("title", ""),
            it.get("summary", ""),
            people,
            it.get("published_at", ""),
            NOW,
            it.get("sub_dimension", ""),
            new_trl,
        )
        it.update(scoring)
        changed += 1
    if changed:
        bak = path.with_suffix(path.suffix + ".bak-trl")
        shutil.copy2(path, bak)
        if is_dict:
            data["items"] = items
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        else:
            path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        print(f"  {path.name}: trl 变化 {changed} 条（备份 {bak.name}）")
    return changed


def main() -> int:
    print("重算 trl + 重打分（2026-08-24 TRL 关键词扩展）", flush=True)
    total = 0
    for fn in ("history.json", "latest-24h.json", "latest-24h-all.json"):
        total += process(ROOT / "data" / fn)
    print(f"完成，共 {total} 条 trl 变化", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
