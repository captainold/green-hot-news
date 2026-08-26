#!/usr/bin/env python3
"""回填历史数据的摘要 HTML 残留 + Google News 伪摘要判空（2026-08-26 QA B5 修复）。

背景：
1. Google News RSS 源的 description 是 `<a href="news.google.com/rss/articles/…">标题</a>
   <font>源名</font>` HTML 包裹——无真实摘要，标题/源名均冗余（标题存 title、源名存
   site_name）。旧版 _clean_summary 未剥离标签，摘要带 `<a href>` 残留（QA 实测 138 条）。
2. update_news.py 的 _clean_summary 已修：① Google News description 直接判空；② 其他源
   描述里的 HTML 标签剥离（只匹配 < 后紧跟字母或 / 的真标签，不误伤 "A < B" 数学式）。

本脚本回填存量：
  data/history.json + latest-24h.json + latest-24h-all.json：
    - url 含 news.google.com/rss/articles 的条目 → summary 置空（伪摘要无信息量）
    - 其他条目 → summary 重跑 _clean_summary（剥残留 HTML 标签）
  Notes/数据库/*.qmd：
    - url 含 news.google.com/rss/articles 的 → 删除整个「## 摘要」段
    - 其他 → 「## 摘要」段内容重跑 _clean_summary

用法：
    python3.11 scripts/backfill_clean_summary.py              # 回填 data/*.json + qmd
    python3.11 scripts/backfill_clean_summary.py --json-only  # 只回填 JSON
    python3.11 scripts/backfill_clean_summary.py --qmd-only   # 只回填 qmd
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from update_news import _clean_summary  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
JSON_FILES = ["data/history.json", "data/latest-24h.json", "data/latest-24h-all.json"]
QMD_DIR = ROOT / "Notes" / "数据库"

_GOOGLE_NEWS_URL_RE = re.compile(r"news\.google\.com/rss/articles")


def _is_google_news(url: str) -> bool:
    return bool(_GOOGLE_NEWS_URL_RE.search(url or ""))


def backfill_json(path: Path) -> int:
    if not path.exists():
        print(f"  {path.name}: 不存在，跳过")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    changed = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        if _is_google_news(it.get("url", "")):
            if it.get("summary"):
                it["summary"] = ""
                changed += 1
        else:
            raw = it.get("summary") or ""
            cleaned = _clean_summary(raw)
            if cleaned != raw:
                it["summary"] = cleaned
                changed += 1
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=None), encoding="utf-8")
    print(f"  {path.name}: 回填 {changed} 条")
    return changed


# 「## 摘要」段落：标题行 + 空行 + 内容（到下一个 ## 标题或文件尾）
_SUMMARY_SEC_RE = re.compile(r"(## 摘要[ \t]*\n[ \t]*\n)(.*?)(?=\n## |\Z)", re.DOTALL)
# 删除整个「## 摘要」段（中间段 + 文件尾段两种）
_SUMMARY_DEL_MID_RE = re.compile(r"## 摘要[ \t]*\n[ \t]*\n.*?\n[ \t]*\n(?=## )", re.DOTALL)
_SUMMARY_DEL_EOF_RE = re.compile(r"## 摘要[ \t]*\n[ \t]*\n.*\Z", re.DOTALL)


def _remove_summary_section(text: str) -> str:
    text = _SUMMARY_DEL_MID_RE.sub("", text)
    text = _SUMMARY_DEL_EOF_RE.sub("", text)
    return text


def backfill_qmd(qmd_dir: Path) -> int:
    if not qmd_dir.exists():
        print(f"  {qmd_dir}: 不存在，跳过")
        return 0
    changed = 0

    def _repl(m: re.Match) -> str:
        body = m.group(2)
        cleaned = _clean_summary(body)
        if cleaned == body.strip():
            return m.group(0)
        return m.group(1) + cleaned + "\n"

    for f in sorted(qmd_dir.glob("*.qmd")):
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        m_url = re.search(r'^url:\s*"([^"]+)"', txt, re.MULTILINE)
        if not m_url:
            continue
        if _is_google_news(m_url.group(1)):
            new_txt = _remove_summary_section(txt)
        else:
            new_txt = _SUMMARY_SEC_RE.sub(_repl, txt)
        if new_txt != txt:
            f.write_text(new_txt, encoding="utf-8")
            changed += 1
    print(f"  {qmd_dir.name}/: 回填 {changed} 个 qmd")
    return changed


def main() -> int:
    ap = argparse.ArgumentParser(description="回填摘要 HTML 残留 + Google News 伪摘要判空（QA B5）")
    ap.add_argument("--json-only", action="store_true", help="只回填 data/*.json")
    ap.add_argument("--qmd-only", action="store_true", help="只回填 qmd 摘要段落")
    args = ap.parse_args()

    do_json = not args.qmd_only
    do_qmd = not args.json_only

    if do_json:
        for rel in JSON_FILES:
            backfill_json(ROOT / rel)
    if do_qmd:
        backfill_qmd(QMD_DIR)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
