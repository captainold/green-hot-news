#!/usr/bin/env python3
r"""素材库索引生成（2026-09-23，P2-③；同日切库后成为主流程可调用步骤）。

产出：
1. `Notes/素材库/ai-index-政策.md` / `ai-index-媒体.md`：grep 友好的单行目录
   （`mat/<id> | 日期 | 来源 | 层·细类 | 标题 | url`），供人与 agent 直接检索
2. `cache/mat-index.json`：`mat/<id>` → {path,title,url,dimension,layer}，供脚本解析
   （4MB 派生缓存，`cache/` 已 gitignore，可随时重建；`export_qmd` 的增量去重也读它）

用法：
    python scripts/build_material_index.py [--apply]        # 默认 dry-run（只打印统计）
    python scripts/build_material_index.py --apply          # 写盘
    update_news.py --rebuild-index                          # 抓取后自动重建（可选）
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SC = ROOT / "Notes" / "素材库"
CACHE = ROOT / "cache"          # 派生缓存（cache/ 已 gitignore，4MB 索引不入库）
FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---", re.DOTALL)


def fm(fm_text: str, name: str) -> str:
    m = re.search(rf'^{name}:\s*"?(.*?)"?\s*$', fm_text, re.M)
    return m.group(1).strip() if m else ""


def build(apply: bool = False, quiet: bool = False) -> dict:
    """扫描素材库 → 生成 ai-index-*.md 与 cache/mat-index.json，返回统计。"""
    rows: dict[str, list[str]] = {"政策": [], "媒体": []}
    meta: dict[str, dict] = {}
    dims: dict[str, Counter[str]] = {}
    skipped = 0

    for f in sorted(SC.rglob("*.md")):
        if f.name.startswith("ai-index"):
            continue
        rel = f.relative_to(SC)
        top = rel.parts[0] if rel.parts else "政策"
        text = f.read_text(encoding="utf-8", errors="replace")
        m = FM_RE.match(text)
        fm_text = m.group(1) if m else ""
        nid = fm(fm_text, "id")
        date = (fm(fm_text, "date") or fm(fm_text, "published")
                or fm(fm_text, "published_at") or "")[:10]
        site = fm(fm_text, "site") or fm(fm_text, "source")
        dim = fm(fm_text, "dimension")
        sub = fm(fm_text, "sub_dimension")
        url = fm(fm_text, "url")
        title = (fm(fm_text, "title_zh") or fm(fm_text, "title") or f.stem)[:90]
        if not nid:
            skipped += 1
            continue
        dims.setdefault(top, Counter())[f"{dim}·{sub}"] += 1
        rows.setdefault(top, []).append(
            f"- `{nid}` | {date} | {site} | {dim}·{sub} | {title} | {url}")
        meta[nid] = {"path": str(rel).replace("\\", "/"), "title": title,
                     "url": url, "dimension": dim, "layer": fm(fm_text, "layer")}

    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    written: dict[str, int] = {}
    for top, lines in rows.items():
        if not lines:
            continue
        head = [
            "---",
            f'type: "ai-index"',
            f'updated: "{stamp}"',
            f"total: {len(lines)}",
            f'scope: "素材库/{top}"',
            "---",
            "",
            f"# 素材库索引 · {top}（{len(lines)} 条）",
            "",
            "> 单行一条，grep 友好：`mat/<id> | 日期 | 来源 | 层·细类 | 标题 | url`。",
            "> `mat/<id>` 是稳定 id（`sha1(url)[:12]`），改标题/改文件名不断链；"
            "机器可读映射见 `cache/mat-index.json`。",
            "> 由 `scripts/build_material_index.py` 生成（2026-09-23 切库后随抓取重建）。",
            "",
            "## 维度分布",
            "",
        ]
        head += [f"- {k}：{v}" for k, v in dims.get(top, Counter()).most_common(14)]
        head += ["", "## 目录", ""]
        out = SC / f"ai-index-{top}.md"
        written[top] = len(lines)
        if not quiet:
            print(f"{out.name}: {len(lines)} 条")
        if apply:
            out.write_text("\n".join(head + lines) + "\n", encoding="utf-8")

    if not quiet:
        print(f"id 总数 {len(meta)}｜缺 id 跳过 {skipped}")
    if apply:
        CACHE.mkdir(exist_ok=True)
        (CACHE / "mat-index.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        if not quiet:
            print("→ cache/mat-index.json（派生缓存，可随时重建）")
    return {"written": written, "ids": len(meta), "skipped_no_id": skipped}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写盘（默认 dry-run 只统计）")
    args = ap.parse_args()
    build(apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
