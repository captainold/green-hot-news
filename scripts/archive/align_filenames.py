#!/usr/bin/env python3
"""把截断文件名对齐为内容完整标题（保留日期前缀）。

背景（2026-08-11）：列表页标题截断导致文件名截断（如
"世界银行发布《2026年碳定价发展现状与未.md"），内容标题已用详情页
完整标题修正。本脚本用内容标题重命名文件。
"""
import os
import re
from pathlib import Path

NOTES_ROOT = Path("Notes")
SKIP = {"政策库.md", "媒体库.md", "ai-index.md"}


def main() -> None:
    renamed = 0
    for dp, _, fs in os.walk(NOTES_ROOT):
        for f in fs:
            if not f.endswith(".md") or f in SKIP:
                continue
            fp = Path(dp) / f
            txt = fp.read_text(encoding="utf-8")
            m = re.search(r"^# (.+)$", txt, re.M)
            if not m:
                continue
            content_title = m.group(1).strip()
            safe = re.sub(r'[<>:"/\\|?*]', "_", content_title)[:80].strip()
            date_pref = re.match(r"^(\d{4}-\d{2}-\d{2} )", f)
            new_name = (date_pref.group(1) if date_pref else "") + safe + ".md"
            if new_name == f:
                continue
            new_fp = fp.with_name(new_name)
            if new_fp.exists():
                continue  # 目标已存在（可能是另一个重复），跳过
            fp.rename(new_fp)
            renamed += 1
            print(f"{f[:40]} → {new_name[:55]}")
    print(f"\n重命名 {renamed} 篇")


if __name__ == "__main__":
    main()
