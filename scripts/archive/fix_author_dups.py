#!/usr/bin/env python3
"""修复 author 字段：去重 + 清理 404 死链误提取。

问题（2026-08-11）：backfill_author.py --force 重跑时未先移除旧 author
行，导致 174 篇笔记 author 出现两次。另有一些 404 死链页的临时内容被
误提取为 author（"未知"、"商擎"）。

处理：
1. frontmatter 内重复的 author 行 → 只保留第一个
2. author 为异常值（未知/商擎）且 URL 是 404 死链 → 移除 author
"""
import os
import re
import sys
from pathlib import Path

NOTES_ROOT = Path("Notes")
SKIP = {"政策库.md", "媒体库.md", "ai-index.md"}
SUSPECT = {"未知", "商擎"}


def is_404(url: str) -> bool:
    import requests
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        r.encoding = "utf-8"
        return "这个地址不存在" in r.text or "无法找到该页" in r.text
    except Exception:
        return False


def fix_one(fp: Path) -> tuple[Path, str]:
    txt = fp.read_text(encoding="utf-8")
    lines = txt.split("\n")

    # 1) 去重 frontmatter author（保留第一个），并收集值
    author_vals: list[str] = []
    out: list[str] = []
    in_fm = False
    fm_done = False
    body_author_seen = False
    for line in lines:
        if not fm_done:
            if line.strip() == "---" and not in_fm:
                in_fm = True
                out.append(line)
                continue
            if in_fm and line.strip() == "---":
                fm_done = True
                out.append(line)
                continue
            m = re.match(r'^author:\s*"([^"]*)"', line)
            if m:
                author_vals.append(m.group(1))
                if len(author_vals) == 1:
                    out.append(line)  # 保留第一个
                continue  # 丢弃后续重复
            out.append(line)
            continue
        # 正文区：> 作者: 行去重
        if line.startswith("> 作者:"):
            if body_author_seen:
                continue  # 丢弃重复
            body_author_seen = True
        out.append(line)

    if not author_vals:
        return fp, "no author"
    author = author_vals[0]
    changed = len(author_vals) > 1

    # 2) 若 author 是异常值且 URL 404 → 移除 author 行和 "> 作者:" 行
    if author in SUSPECT:
        um = re.search(r"^url:\s*(\S+)", txt, re.M)
        url = um.group(1) if um else ""
        if url and is_404(url):
            out = [l for l in out if not re.match(r'^author:\s*"', l)
                   and not l.startswith("> 作者:")]
            changed = True

    if changed:
        fp.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
        return fp, f"fixed(author={author})"
    return fp, "ok"


def main() -> int:
    fixed = 0
    for dp, _, fs in os.walk(NOTES_ROOT):
        for f in fs:
            if not f.endswith(".md") or f in SKIP:
                continue
            fp = Path(dp) / f
            p, msg = fix_one(fp)
            if msg.startswith("fixed"):
                fixed += 1
                print(f"{msg:25s} {p.name[:45]}")
    print(f"\n修复 {fixed} 篇")
    return 0


if __name__ == "__main__":
    sys.exit(main())
