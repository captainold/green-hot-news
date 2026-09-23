#!/usr/bin/env python3
"""一次性迁移：.qmd → .md（2026-09-15）。

背景：Obsidian 图谱/搜索/双链只索引 .md（getMarkdownFiles 硬编码 "md"），
.qmd 文件永远进不了图谱。项目无 Quarto 渲染依赖，故统一改扩展名。

做三件事（幂等，可重跑）：
1. 改名 Notes/素材库/**/*.qmd 与 docs/底层数据库构建方法 260823.qmd → .md
2. 内容替换：
   - 正文 wikilink [[xxx.qmd]] / [[xxx.qmd#锚]] / [[xxx.qmd|别名]] → 去 .qmd
   - frontmatter related 字段 "xxx.qmd" → "xxx.md"
3. 输出统计

用法：
    python scripts/_migrate_qmd_to_md.py --dry-run   # 只统计
    python scripts/_migrate_qmd_to_md.py             # 执行
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SC = ROOT / "Notes" / "素材库"
DOCS_QMD = ROOT / "docs" / "底层数据库构建方法 260823.qmd"

# wikilink：.qmd 后跟 ]] 或 |（别名）时去掉扩展名。
# 注意：文件名可能含 #（推文 hashtag），不能把 # 当锚点分隔符——所以用
# 「.qmd 后面是 ]] 或 |」来定位扩展名，而不是枚举目标名字符。
WIKILINK_RE = re.compile(r"\.qmd(\]\]|\|)")
# related 行：related: ["xxx.qmd", ...] 整行替换所有 ".qmd" → ".md"
RELATED_LINE_RE = re.compile(r'related:\s*\[[^\]]*\]')


def collect_qmd() -> list[Path]:
    files = sorted(SC.rglob("*.qmd"))
    if DOCS_QMD.exists():
        files.append(DOCS_QMD)
    return files


def fix_content(text: str) -> tuple[str, int, int]:
    """返回 (新文本, wikilink替换数, related条目替换数)。"""
    new, n_wiki = WIKILINK_RE.subn(r"\1", text)

    n_rel = 0

    def _fix_related_line(m: "re.Match[str]") -> str:
        nonlocal n_rel
        line = m.group(0)
        n_rel += line.count('.qmd"')
        return line.replace('.qmd"', '.md"')

    new = RELATED_LINE_RE.sub(_fix_related_line, new)
    return new, n_wiki, n_rel


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只统计不落盘")
    args = ap.parse_args()

    files = collect_qmd()
    total = len(files)
    n_rename = 0
    n_fix_files = 0
    n_wiki_total = 0
    n_rel_total = 0
    collisions = []  # 目标 .md 已存在的冲突

    for f in files:
        target = f.with_suffix(".md")
        if target.exists():
            collisions.append(str(f.relative_to(ROOT)))
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        new_text, n_wiki, n_rel = fix_content(text)
        changed = n_wiki > 0 or n_rel > 0

        n_rename += 1
        if changed:
            n_fix_files += 1
            n_wiki_total += n_wiki
            n_rel_total += n_rel

        if not args.dry_run:
            if changed:
                f.write_text(new_text, encoding="utf-8")
            f.rename(target)

    print(f"{'[dry-run] ' if args.dry_run else ''}待改名 .qmd 文件: {total}")
    print(f"  改名成功(无冲突): {n_rename}")
    print(f"  内容修复文件: {n_fix_files}")
    print(f"    wikilink [[...qmd]] 替换: {n_wiki_total} 处")
    print(f"    related 字段 .qmd→.md: {n_rel_total} 处")
    if collisions:
        print(f"  ⚠ 目标 .md 已存在冲突 {len(collisions)} 个: {collisions[:5]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
