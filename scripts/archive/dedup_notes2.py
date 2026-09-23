#!/usr/bin/env python3
"""去重（第二批）：异 URL 同标题组。

- 工信部 6 组：同一文章在不同栏目（zyjy/nyjy/gzdt）的镜像，正文相同。
  保留日期前缀版，删除无日期前缀版（同 dedup_notes.py 策略）。
- IRENA 1 组：Google News 两篇不同文章撞名，给无前缀版改名为带日期的
  区分名，两篇都保留。
"""
import os
import re
from collections import defaultdict
from pathlib import Path

NOTES_ROOT = Path("Notes")
SKIP = {"政策库.md", "媒体库.md", "ai-index.md"}

# IRENA 撞名组的两个 URL（用于确认哪篇是"新的"）
IRENA_A = "CBMiyAFBVV95cUxQMWZ0cWQ4"  # 2026-07-31 前缀版（早）
IRENA_B = "CBMiuwFBVV95cUxQa1lSbzF"  # 无前缀版


def main() -> None:
    notes: dict[str, list[Path]] = defaultdict(list)
    for dp, _, fs in os.walk(NOTES_ROOT):
        for f in fs:
            if not f.endswith(".md") or f in SKIP:
                continue
            name = re.sub(r"^\d{4}-\d{2}-\d{2} ", "", f)
            notes[name].append(Path(dp) / f)

    diff_groups = []
    for group in notes.values():
        if len(group) < 2:
            continue
        urls = set()
        for fp in group:
            txt = fp.read_text(encoding="utf-8")
            m = re.search(r"^url:\s*(\S+)", txt, re.M)
            urls.add(m.group(1) if m else "?")
        if len(urls) > 1:
            diff_groups.append(group)

    removed = renamed = 0
    for group in diff_groups:
        prefixed = [p for p in group if re.match(r"^\d{4}-\d{2}-\d{2} ", p.name)]
        plain = [p for p in group if not re.match(r"^\d{4}-\d{2}-\d{2} ", p.name)]
        # IRENA 撞名特判：两篇正文都为空（Google News 链接卡），URL 不同
        if len(prefixed) == 1 and len(plain) == 1:
            txt = plain[0].read_text(encoding="utf-8")
            if "IRENA Issues Call" in txt and "news.google.com" in txt:
                # 给无前缀版改名为带日期区分名（用其 first-seen 近似——用 2026-08-07）
                new_name = f"2026-08-07 {plain[0].name}"
                new_path = plain[0].with_name(new_name)
                plain[0].rename(new_path)
                renamed += 1
                print(f"IRENA 撞名保留两篇，改名: {plain[0].name} → {new_name}")
                continue
        if prefixed and plain:
            for p in plain:
                p.unlink()
                removed += 1
                print(f"删除镜像旧版: {p.relative_to(NOTES_ROOT)}")

    print(f"\n异URL组: {len(diff_groups)} | 删除镜像: {removed} | IRENA改名: {renamed}")


if __name__ == "__main__":
    main()
