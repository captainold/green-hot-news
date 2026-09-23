#!/usr/bin/env python3
"""补全/标记链接卡笔记：缺 published 的补上；链接卡加状态标记。

终审清理（2026-08-13）：
1. 缺 published 的笔记（World Bank 12 + Google News 14 + 其他）补 published：
   - 有 date → published = date（date 是发布日期或抓取日期兜底）
   - 无 date → published = 首次抓取日期
2. 无 ## 正文 的链接卡 → 加 "> 状态: 链接卡" 标记，明确数据形态
3. wiki 页面（无 source）跳过
"""
import os
import re
from pathlib import Path

NOTES_ROOT = Path("Notes")
SKIP = {"政策库.md", "媒体库.md", "ai-index.md"}


def main() -> None:
    fixed_pub = 0
    marked_card = 0
    for dp, _, fs in os.walk(NOTES_ROOT):
        for f in fs:
            if not f.endswith(".md") or f in SKIP:
                continue
            fp = Path(dp) / f
            txt = fp.read_text(encoding="utf-8")
            if not txt.startswith("---"):
                continue
            # wiki 页面跳过（无 source 字段）
            if not re.search(r'^source:\s*', txt, re.M):
                continue
            lines = txt.split("\n")
            changed = False
            # 1) 补 published
            if not re.search(r"^published:\s*", txt, re.M):
                d = re.search(r"^date:\s*(\S+)", txt, re.M)
                first = re.search(r"首次抓取: (\S+)", txt)
                pub = d.group(1) if d else (first.group(1)[:10] if first else "")
                if pub:
                    out: list[str] = []
                    inserted = False
                    for line in lines:
                        out.append(line)
                        if not inserted and line.startswith("date:"):
                            out.append(f'published: "{pub}"')
                            inserted = True
                    if inserted:
                        lines = out
                        changed = True
                        fixed_pub += 1
            # 2) 链接卡标记
            txt_now = "\n".join(lines)
            if "## 正文" not in txt_now and "> 状态:" not in txt_now:
                # 在 "> 首次抓取:" 行后加状态标记
                out2: list[str] = []
                added = False
                for line in lines:
                    out2.append(line)
                    if not added and line.startswith("> 首次抓取:"):
                        out2.append("> 状态: 链接卡（源站正文不可抓取，标题/链接有效）")
                        added = True
                if added:
                    lines = out2
                    changed = True
                    marked_card += 1
            if changed:
                fp.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"补 published: {fixed_pub} | 标记链接卡: {marked_card}")


if __name__ == "__main__":
    main()
