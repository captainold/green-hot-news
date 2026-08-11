#!/usr/bin/env python3
"""去重：删除同 URL 重复笔记中的无日期前缀旧版。

背景（2026-08-11）：published 字段修复后重跑 update_news.py，
同一文章被导出两次——早期无 published（文件名无日期前缀）+ 修复后有
published（文件名带 YYYY-MM-DD 前缀）。155 组重复中 148 组是同 URL。

策略：同 URL 组内，保留日期前缀版（published 已修复、正文完整），
删除无日期前缀旧版。异 URL 组不处理（需人工判断）。
"""
import os
import re
from collections import defaultdict
from pathlib import Path

NOTES_ROOT = Path("Notes")
SKIP = {"政策库.md", "媒体库.md", "ai-index.md"}


def main() -> None:
    notes: dict[str, list[Path]] = defaultdict(list)
    for dp, _, fs in os.walk(NOTES_ROOT):
        for f in fs:
            if not f.endswith(".md") or f in SKIP:
                continue
            name = re.sub(r"^\d{4}-\d{2}-\d{2} ", "", f)
            notes[name].append(Path(dp) / f)

    same_groups = []
    for group in notes.values():
        if len(group) < 2:
            continue
        urls = set()
        for fp in group:
            txt = fp.read_text(encoding="utf-8")
            m = re.search(r"^url:\s*(\S+)", txt, re.M)
            urls.add(m.group(1) if m else "?")
        if len(urls) == 1:
            same_groups.append(group)

    removed = 0
    for group in same_groups:
        prefixed = [p for p in group if re.match(r"^\d{4}-\d{2}-\d{2} ", p.name)]
        plain = [p for p in group if not re.match(r"^\d{4}-\d{2}-\d{2} ", p.name)]
        if prefixed and plain:
            for p in plain:
                p.unlink()
                removed += 1
                print(f"删除旧版: {p.relative_to(NOTES_ROOT)}")

    print(f"\n同URL重复组: {len(same_groups)} | 删除旧版: {removed} 个文件")


if __name__ == "__main__":
    main()
