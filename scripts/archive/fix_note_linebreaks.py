#!/usr/bin/env python3
"""修复笔记正文换行：单换行 → 双换行（正确 Markdown 段落分隔）。

问题（2026-08-11 用户发现）：历史抓取的 211 篇笔记正文段落间只有单换行，
在 CommonMark 渲染中会被合并成一段（单换行=软换行）。本脚本把正文里的
"段落间单换行"升级为"空行分隔"。

规则（保守，避免破坏列表/代码块）：
- 只处理 "## 正文" 之后的部分
- 段落边界判定：前一行以中英文句号/问号/叹号/冒号结尾，或后一行以
  中文序号（一、1. 等）开头，或前后行都较长（>=15 字符）
- 跳过 frontmatter、标题、链接行、引用行、空行、列表项、代码块
"""
from pathlib import Path
import re

NOTES_ROOT = Path("Notes")
SKIP = {"政策库.md", "媒体库.md", "ai-index.md"}

# 段落结尾标点（中文/英文句号问号叹号冒号，及章节序号结束）
PARA_END = re.compile(r"[。．.？！?!：:）)]$")
# 段落开头特征：中文序号（一、1. （一）第X条 等）
PARA_START = re.compile(
    r"^(第?[一二三四五六七八九十百零\d]+[、\.．]|\(?[一二三四五六七八九十]+\)|"
    r"（[一二三四五六七八九十]+）|[（(]?\d+[)）、.]|•|\*|\u2014)"
)
# 列表项/引用/代码/标题行（不应在其后强插空行）
NON_PARAGRAPH = re.compile(r"^(\s*[-*+>#]|\s*\d+[\.、]|```|\s*$)")


def fix_body(text: str) -> tuple[str, bool]:
    """把 ## 正文 之后的单换行升级为双换行。返回 (新文本, 是否改动)。"""
    idx = text.find("## 正文")
    if idx < 0:
        return text, False
    head, body = text[:idx], text[idx:]
    lines = body.split("\n")
    out: list[str] = []
    changed = False
    for i, line in enumerate(lines):
        out.append(line)
        if i == len(lines) - 1:
            break
        nxt = lines[i + 1]
        # 当前行或下一行是空行 → 已正确分隔，跳过
        if not line.strip() or not nxt.strip():
            continue
        # 正文标题行/列表/引用/代码块内不处理
        if NON_PARAGRAPH.match(line) or NON_PARAGRAPH.match(nxt):
            continue
        # 段落边界判定：
        # 1) 当前行以句末标点结尾 且 下一行不是列表/引用
        # 2) 下一行是中文序号开头（新段落）
        # 3) 当前行以引号/括号闭合结尾且下一行较长
        if PARA_END.search(line) and not NON_PARAGRAPH.match(nxt):
            out.append("")
            changed = True
        elif PARA_START.match(nxt):
            out.append("")
            changed = True
        elif len(line.strip()) >= 15 and len(nxt.strip()) >= 15 and line.strip()[-1] not in "，,、；;":
            # 两行都很长且当前行不以逗号结尾——保守视为段落边界
            out.append("")
            changed = True
    return head + "\n".join(out), changed


def main() -> None:
    fixed = skipped = 0
    for dp, _, fs in os.walk(NOTES_ROOT):
        for f in fs:
            if not f.endswith(".md") or f in SKIP:
                continue
            fp = Path(dp) / f
            txt = fp.read_text(encoding="utf-8")
            if "## 正文" not in txt:
                continue
            new_txt, changed = fix_body(txt)
            if changed:
                fp.write_text(new_txt, encoding="utf-8")
                fixed += 1
            else:
                skipped += 1
    print(f"修复换行: {fixed} 篇 | 无需改动: {skipped} 篇")


if __name__ == "__main__":
    import os
    main()
