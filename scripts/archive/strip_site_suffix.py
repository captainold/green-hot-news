#!/usr/bin/env python3
"""批量移除笔记标题中的站点后缀（如 "…-国家发展和改革委员会"）。

背景（2026-08-11）：发改委详情页 h1 是 "【标题】-国家发展和改革委员会"
格式，重抓正文时标题被带回来 → 300 篇笔记标题带站点后缀。
本脚本从正文 # 标题和文件名中移除已知站点后缀。
"""
import os
import re
from pathlib import Path

NOTES_ROOT = Path("Notes")
SKIP = {"政策库.md", "媒体库.md", "ai-index.md"}
# 已知站点后缀（按长度降序，避免先匹配短的）
SUFFIXES = [
    "-国家发展和改革委员会",
    "-国家发展和改革委",
    "-国家发改委",
    "-碳排放交易网",
    "-生态环境部",
    "-国家能源局",
    "_碳排放交易网",
]


def strip_suffix(title: str) -> str:
    for suf in SUFFIXES:
        if title.endswith(suf):
            return title[: -len(suf)].strip()
    return title


def main() -> None:
    fixed = 0
    for dp, _, fs in os.walk(NOTES_ROOT):
        for f in fs:
            if not f.endswith(".md") or f in SKIP:
                continue
            fp = Path(dp) / f
            txt = fp.read_text(encoding="utf-8")
            m = re.search(r"^# (.+)$", txt, re.M)
            if not m:
                continue
            cur = m.group(1)
            new_title = strip_suffix(cur)
            if new_title == cur:
                continue
            # 更新正文标题 + frontmatter title 字段
            new_txt = txt.replace(f"# {cur}", f"# {new_title}", 1)
            new_txt = re.sub(
                r'^title: ".*"$', f'title: "{new_title}"', new_txt, flags=re.M)
            fp.write_text(new_txt, encoding="utf-8")
            # 重命名文件（保留日期前缀）
            safe = re.sub(r'[<>:"/\\|?*]', "_", new_title)[:80].strip()
            date_pref = re.match(r"^(\d{4}-\d{2}-\d{2} )", fp.name)
            new_name = (date_pref.group(1) if date_pref else "") + safe + ".md"
            if new_name != fp.name and not fp.with_name(new_name).exists():
                fp.rename(fp.with_name(new_name))
            fixed += 1
    print(f"移除站点后缀: {fixed} 篇")


if __name__ == "__main__":
    main()
