#!/usr/bin/env python3
"""清理发改委重命名导致的同 URL 重复笔记。

背景（2026-08-11）：strip_site_suffix.py 重命名了 300 篇发改委笔记
（去掉站点后缀），update_news.py 重跑时按新文件名又导出一次 →
同一 URL 出现两个文件（如 "2023-02-27 【标题】.md" 和
"2023-02-27 标题.md"）。

策略：同 URL 组内保留更新时间较新的（内容含 author/summary），删旧的。
"""
import os
import re
from collections import defaultdict
from pathlib import Path

NOTES_ROOT = Path("Notes")
SKIP = {"政策库.md", "媒体库.md", "ai-index.md"}


def main() -> None:
    by_url: dict[str, list[Path]] = defaultdict(list)
    for dp, _, fs in os.walk(NOTES_ROOT):
        for f in fs:
            if not f.endswith(".md") or f in SKIP:
                continue
            fp = Path(dp) / f
            txt = fp.read_text(encoding="utf-8")
            m = re.search(r"^url:\s*(\S+)", txt, re.M)
            if m:
                by_url[m.group(1)].append(fp)

    removed = 0
    for url, files in by_url.items():
        if len(files) < 2:
            continue
        # 保留标题最完整的版本（详情页完整标题 > 列表页截断标题），
        # 同长度时保留 mtime 新的（含 author/完整正文）
        def title_len(fp: Path) -> int:
            txt = fp.read_text(encoding="utf-8")
            m = re.search(r"^# (.+)$", txt, re.M)
            return len(m.group(1)) if m else 0

        files.sort(key=lambda p: (title_len(p), p.stat().st_mtime), reverse=True)
        for fp in files[1:]:
            fp.unlink()
            removed += 1
            print(f"删除重复: {fp.relative_to(NOTES_ROOT)}")
    print(f"\n删除同URL重复: {removed} 个文件")


if __name__ == "__main__":
    main()
