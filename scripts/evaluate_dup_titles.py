#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""标题级重复（【dupN】）评估 —— 只读分析，先出报告不合并。

背景（P4 遗留）：`sanitize_note_names.py` 把同名文件规范成 `… 【dup2】.md`（2026-10-04 实测 1039 个）。
它们**不一定是真重复**：
  · 同标题不同 url = **不同文章**（export_qmd「同名不同 url 不覆盖」规则的产物，必须保留）
  · 同 url / 同正文指纹 = 真重复（可合并）
  · 原件已被删除、只剩 `【dupN】` 后缀文件 = **孤儿**（要改名回原件名）

用法：
    python -X utf8 scripts/evaluate_dup_titles.py [--json cache/dup-eval.json] [--top 15]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAT = ROOT / "Notes" / "素材库"
DUP_RE = re.compile(r"\s*【dup\d+】")
SUF_RE = re.compile(r"\s*〔mat-[0-9a-f]{6}〕")


def parse(path: Path) -> dict | None:
    t = path.read_text(encoding="utf-8", errors="replace")
    if not t.startswith("---"):
        return None
    fm = {}
    for line in t.split("\n")[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')

    def sec(name: str) -> str:
        m = re.search(rf"^##\s*{name}\s*$", t, re.M)
        if not m:
            return ""
        rest = t[m.end():]
        nxt = re.search(r"^##\s", rest, re.M)
        return (rest[:nxt.start()] if nxt else rest).strip()

    body, summary = sec("正文"), sec("摘要")
    return {
        "path": str(path.relative_to(ROOT)),
        "stem": path.stem,
        "dir": str(path.parent.relative_to(MAT)),
        "base": SUF_RE.sub("", DUP_RE.sub("", path.stem)).strip(),
        "is_dupname": bool(DUP_RE.search(path.stem)),
        "site": fm.get("site", "?"),
        "id": fm.get("id", ""),
        "url": fm.get("url", ""),
        "title": fm.get("title", ""),
        "date": (fm.get("published_at", "") or "")[:10],
        "body_len": len(body),
        "sum_len": len(summary),
        "fp": hashlib.sha1((re.sub(r"\s+", "", summary) + "|" +
                            re.sub(r"\s+", "", body)).encode()).hexdigest()[:12],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None)
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    notes: list[dict] = []
    for p in MAT.rglob("*.md"):
        rec = parse(p)
        if rec:
            notes.append(rec)

    dup_files = [n for n in notes if n["is_dupname"]]
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for n in notes:
        groups[(n["dir"], n["base"])].append(n)
    id_count = Counter(n["id"] for n in notes if n["id"])

    stat = Counter()
    orphan, identical, distinct, partial = [], [], [], []
    buckets = defaultdict(list)
    url_kind = Counter()
    for (d, base), members in groups.items():
        dups = [m for m in members if m["is_dupname"]]
        if not dups:
            continue
        urls = {m["url"] for m in members}
        fps = {m["fp"] for m in members}
        ids = {m["id"] for m in members}
        withbody = [m for m in members if m["body_len"] >= 50]
        # 孤儿：组里全是带后缀的文件（原件不在库）
        if len(dups) == len(members):
            stat["孤儿（只有带后缀的文件）"] += 1
            orphan.append((d, base, members))
            continue
        if len(members) >= 2 and (len(ids) == 1 or (len(urls) == 1 and len(fps) == 1)):
            stat["真重复（同 id 或同 url+指纹）"] += 1
            identical.append((d, base, members))
            continue
        # 同一篇文章的两条 url？看 url 形态
        kinds = {("gnews" if "news.google.com" in m["url"] else "direct") for m in members}
        url_kind["+".join(sorted(kinds))] += 1
        if len(withbody) == 0:
            stat["双空正文（两条都无正文）"] += 1
            buckets["双空"].append((d, base, members))
        elif len(withbody) == len(members):
            if len(fps) == 1:
                stat["双有正文且指纹相同（真重复）"] += 1
                identical.append((d, base, members))
            else:
                stat["双有正文且指纹不同（不同文章）"] += 1
                distinct.append((d, base, members))
        else:
            stat["一条有正文一条无（疑似同文两条 url，可互补）"] += 1
            partial.append((d, base, members))
    print(f"\nurl 形态分布（同 base 组内）: " +
          "｜".join(f"{k}×{v}" for k, v in url_kind.most_common()))

    print(f"【标题级重复评估｜只读】素材库 {len(notes)} 条｜带 【dupN】 后缀 {len(dup_files)} 个")
    print(f"涉及的 base 组: {len({k for k, v in groups.items() if any(m['is_dupname'] for m in v)})}")
    print(f"\n判据结果:")
    for k, v in stat.most_common():
        print(f"  {k:<28} {v} 组")
    print(f"  同 id 重复（全库 id 撞车）      {sum(1 for i, c in id_count.items() if c > 1)} 个 id")

    print(f"\n① 真重复样本（同 id 或 url+指纹相同 → 可合并）:")
    for d, base, members in identical[:args.top]:
        print(f"   {len(members)} 份 [{members[0]['site'][:12]}] {base[:40]}  "
              f"id={members[0]['id']}")
    print(f"\n② 一条有正文一条无样本（疑似同文两条 url → 正文可互补）:")
    for d, base, members in partial[:args.top]:
        b = "｜".join(f"{'gnews' if 'news.google.com' in m['url'] else 'direct'}"
                      f":{m['body_len']}" for m in members)
        print(f"   {len(members)} 份 [{members[0]['site'][:12]}] {base[:34]}  {b}")
    print(f"\n③ 双有正文且指纹不同样本（同标题不同文章 → 保留）:")
    for d, base, members in distinct[:args.top]:
        print(f"   {len(members)} 份 [{members[0]['site'][:12]}] {base[:36]}  "
              f"url×{len({m['url'] for m in members})} 正文长度={[m['body_len'] for m in members]}")
    print(f"\n④ 孤儿样本（原件已不在库，只剩 【dupN】）:")
    for d, base, members in orphan[:args.top]:
        print(f"   {len(members)} 份 [{members[0]['site'][:12]}] {members[0]['stem'][:60]}")

    print(f"\n按站点分布（带后缀文件数）:")
    for site, n in Counter(d["site"] for d in dup_files).most_common(12):
        print(f"  {site[:20]:<22} {n}")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "notes": len(notes), "dup_files": len(dup_files),
            "stat": dict(stat),
            "identical": [{"dir": d, "base": b, "n": len(m),
                           "stems": [x["stem"] for x in m]} for d, b, m in identical],
            "distinct": [{"dir": d, "base": b, "n": len(m),
                          "urls": [x["url"] for x in m]} for d, b, m in distinct],
            "partial": [{"dir": d, "base": b, "n": len(m),
                         "members": [{"stem": x["stem"], "url": x["url"],
                                      "body": x["body_len"], "sum": x["sum_len"],
                                      "date": x["date"]} for x in m]}
                        for d, b, m in partial],
            "both_empty": [{"dir": d, "base": b,
                            "members": [{"stem": x["stem"], "url": x["url"]} for x in m]}
                           for d, b, m in buckets["双空"]],
            "orphan": [{"dir": d, "base": b, "stems": [x["stem"] for x in m]}
                       for d, b, m in orphan],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n明细: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
