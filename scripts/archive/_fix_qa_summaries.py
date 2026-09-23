#!/usr/bin/env python3
"""_fix_qa_summaries.py — 一次性修复存量摘要/标题（QA 2026-08-21 发现）

对 data/latest-24h.json + latest-24h-all.json + history.json 的 summary 应用
_clean_summary（html.unescape + 去 {{...}} 模板变量 + 空白压缩），title 同样 unescape。
幂等（重复跑无副作用），备份到 /tmp 后写回。

用法: python3.11 scripts/_fix_qa_summaries.py
"""
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TMP = Path("/tmp")


def clean_summary(raw: str) -> str:
    if not raw:
        return ""
    s = html.unescape(str(raw))
    s = re.sub(r"\{\{[^}]*\}\}?", "", s)
    s = re.sub(r"((?:时间|来源|作者|编辑|责编|责任编辑|监制|采写|记者|摄影)：(?:\s|$))+", "", s)
    s = re.sub(r"本作品.*?(?:联系电话|版权)", "", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_title(raw: str) -> str:
    if not raw:
        return ""
    return re.sub(r"\{\{[^}]*\}\}", "", html.unescape(str(raw))).strip()


def fix_file(name: str) -> tuple[int, int]:
    p = DATA / name
    if not p.exists():
        return 0, 0
    data = json.loads(p.read_text(encoding="utf-8"))
    items = data if isinstance(data, list) else data.get("items", data.get("news", []))
    n_sum, n_tit = 0, 0
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("summary"):
            new = clean_summary(it["summary"])
            if new != it["summary"]:
                it["summary"] = new
                n_sum += 1
        if it.get("title"):
            new = clean_title(it["title"])
            if new != it["title"]:
                it["title"] = new
                n_tit += 1
    shutil.copy2(p, TMP / f"{name}.bak")
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return n_sum, n_tit


def main() -> int:
    total_s = total_t = 0
    for f in ("latest-24h.json", "latest-24h-all.json", "history.json"):
        s, t = fix_file(f)
        total_s += s
        total_t += t
        print(f"{f}: summary {s} 条修复, title {t} 条修复")
    print(f"合计: summary {total_s}, title {total_t}（备份在 /tmp/*.bak）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
