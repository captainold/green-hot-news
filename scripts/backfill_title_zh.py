#!/usr/bin/env python3
"""回填历史数据的 title_zh 字段（非中文标题 → 中文翻译）。

用途：腾讯云 TMT 开通后，一次性回填 data/*.json 里已累积的非中文标题。
之后主 pipeline 会自动翻译新抓取的标题（带缓存），无需再手动跑本脚本。

用法：
    python3.11 scripts/backfill_title_zh.py            # 回填 data/*.json
    python3.11 scripts/backfill_title_zh.py --notes     # 同时回填 Notes 笔记 frontmatter
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from translator import needs_translation, translate_title  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
JSON_FILES = ["data/history.json", "data/latest-24h.json", "data/latest-24h-all.json"]


def backfill_json(path: Path) -> int:
    if not path.exists():
        print(f"  {path.name}: 不存在，跳过")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else data
    changed = 0
    for it in items:
        t = (it.get("title") or "").strip()
        if not t or not needs_translation(t):
            continue
        if (it.get("title_zh") or "").strip():
            continue
        zh = translate_title(t)
        if zh:
            it["title_zh"] = zh
            changed += 1
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"  {path.name}: 回填 {changed} 条")
    return changed


def backfill_notes(notes_root: Path) -> int:
    changed = 0
    for md in notes_root.rglob("*.md"):
        if md.name in ("政策库.md", "媒体库.md", "ai-index.md"):
            continue
        try:
            txt = md.read_text(encoding="utf-8")
        except Exception:
            continue
        # 标题在 frontmatter 后的第一个 # heading
        m = re.search(r"^#\s+(.+)$", txt, re.M)
        if not m:
            continue
        title = m.group(1).strip()
        if not title or not needs_translation(title):
            continue
        if re.search(r"^title_zh:", txt, re.M):
            continue
        zh = translate_title(title)
        if zh:
            # 在 frontmatter 末尾插入 title_zh 字段
            fm_end = re.search(r"^---\s*$", txt, re.M)
            if fm_end:
                txt = txt[:fm_end.start()] + f'title_zh: "{zh}"\n' + txt[fm_end.start():]
                md.write_text(txt, encoding="utf-8")
                changed += 1
    print(f"  Notes: 回填 {changed} 条")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="回填非中文标题的中文翻译")
    ap.add_argument("--notes", action="store_true", help="同时回填 Notes 笔记 frontmatter")
    args = ap.parse_args()

    print("回填 data/*.json 的 title_zh 字段：")
    total = 0
    for rel in JSON_FILES:
        total += backfill_json(ROOT / rel)
    if args.notes:
        print("回填 Notes 笔记：")
        backfill_notes(ROOT / "Notes")
    print(f"\n完成，共回填 {total} 条 JSON 记录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
