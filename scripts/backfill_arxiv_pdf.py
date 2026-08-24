#!/usr/bin/env python3.11
"""存量 arxiv 高分论文 PDF 全文回填（2026-08-24）：把 score>=55 的 arxiv qmd
正文从 abs 页 Abstract 换成 PDF 全文。

复用 article_content.fetch_arxiv_pdf（abs→pdf → PyMuPDF 提取 + 分栏重组）。

用法：
    python3.11 scripts/backfill_arxiv_pdf.py             # dry-run 统计
    python3.11 scripts/backfill_arxiv_pdf.py --apply     # 实际抓取 + 写回
"""
from __future__ import annotations

import argparse
import re
import sys
import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / "Notes" / "数据库"

spec = importlib.util.spec_from_file_location("ac", str(ROOT / "scripts" / "article_content.py"))
ac = importlib.util.module_from_spec(spec)
sys.modules["ac"] = ac
spec.loader.exec_module(ac)

_RE_URL = re.compile(r'^url:\s*"?([^"\n]+)"?\s*$', re.M)
_RE_SCORE = re.compile(r'^score:\s*"?(\d+)"?\s*$', re.M)
_RE_BODY = re.compile(r'^##\s*正文\s*$', re.M)


def replace_body(text: str, new_content: str) -> str:
    """替换 ## 正文 节的内容为 new_content，保留前后（frontmatter + 后续节）。"""
    m = _RE_BODY.search(text)
    if not m:
        return text
    head = text[: m.end()]
    rest = text[m.end():]
    m_next = re.search(r'^##\s', rest, re.M)
    tail = rest[m_next.start():] if m_next else ""
    return head + "\n\n" + new_content.strip() + "\n\n" + tail


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    candidates: list[tuple[Path, str, int]] = []  # (file, url, score)
    for fp in sorted(NOTES_DIR.glob("*.qmd")):
        try:
            txt = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        m_url = _RE_URL.search(txt)
        if not m_url or "arxiv.org/abs" not in m_url.group(1):
            continue
        m_score = _RE_SCORE.search(txt)
        score = int(m_score.group(1)) if m_score else 0
        if score < 55:
            continue
        candidates.append((fp, m_url.group(1).strip(), score))

    print(f"B 级（score>=55）arxiv qmd: {len(candidates)} 条")
    if not candidates:
        return 0

    ok = 0
    fail = 0

    def _work(item):
        fp, url, score = item
        txt = fp.read_text(encoding="utf-8", errors="ignore")
        pdf = ac.fetch_arxiv_pdf(url)
        if not pdf:
            return fp.name, None, 0
        # 正文过短（<500字）说明提取异常，保留原正文
        if len(pdf) < 500:
            return fp.name, None, 0
        new_txt = replace_body(txt, pdf)
        if new_txt != txt:
            if args.apply:
                fp.write_text(new_txt, encoding="utf-8")
        return fp.name, len(pdf), 1

    with ThreadPoolExecutor(max_workers=1) as ex:  # MinerU 用 GPU，串行避免 OOM
        futs = [ex.submit(_work, c) for c in candidates]
        for fut in as_completed(futs):
            name, plen, status = fut.result()
            if status:
                ok += 1
                print(f"  ✅ {name[:50]} ({plen} 字)", flush=True)
            else:
                fail += 1
                print(f"  · 失败/跳过 {name[:50]}", flush=True)

    print(f"\n成功回填 {ok} 条 / 失败 {fail} 条")
    if not args.apply:
        print("Dry-run（未写回）。确认后加 --apply。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
