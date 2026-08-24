#!/usr/bin/env python3.11
"""存量 arxiv 面包屑/页脚清理（2026-08-24）：清理 qmd 正文里 trafilatura
混入的面包屑/导航/arXivLabs 页脚。

复用 article_content._clean_arxiv_junk（截断 ### Bookmark 之后的页脚 +
去面包屑/重复标题/View PDF）。

用法：
    python3.11 scripts/clean_arxiv.py             # dry-run 统计
    python3.11 scripts/clean_arxiv.py --apply     # 实际写回
"""
from __future__ import annotations

import argparse
import re
import sys
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / "Notes" / "数据库"

spec = importlib.util.spec_from_file_location("ac", str(ROOT / "scripts" / "article_content.py"))
ac = importlib.util.module_from_spec(spec)
sys.modules["ac"] = ac
spec.loader.exec_module(ac)

_RE_URL = re.compile(r'^url:\s*"?([^"\n]+)"?\s*$', re.M)
_RE_BODY = re.compile(r'^##\s*正文\s*$', re.M)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    changed = 0
    total_arxiv = 0
    removed_lines = 0
    for fp in sorted(NOTES_DIR.glob("*.qmd")):
        try:
            txt = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        m_url = _RE_URL.search(txt)
        if not m_url or "arxiv.org" not in m_url.group(1):
            continue
        total_arxiv += 1
        m_body = _RE_BODY.search(txt)
        if not m_body:
            continue
        head = txt[: m_body.end()]
        body = txt[m_body.end():]
        new_body = ac._clean_arxiv_junk(body)
        # 清理后压掉多余空行
        new_body = re.sub(r"\n{3,}", "\n\n", new_body)
        if new_body.strip() == body.strip():
            continue
        removed_lines += body.count("\n") - new_body.count("\n")
        changed += 1
        if args.apply:
            fp.write_text(head + new_body, encoding="utf-8")

    print(f"arxiv qmd: {total_arxiv} | 清理 {changed} 个 | 移除约 {removed_lines} 行页脚/面包屑")
    if args.apply:
        print("✅ 已写回")
    else:
        print("Dry-run（未写回）。确认后加 --apply。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
