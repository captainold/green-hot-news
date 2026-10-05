#!/usr/bin/env python3.11
"""①b 假里程碑逐条归因：每条 kw=30 的 gold 样本，命中了 30 档词表里的哪个词。

同时检查细类错分 top 组（gold 国际动态→kw 政策法规 10 条）的标题特征，
为 categorize_dimension 的定向修复取证。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

spec = importlib.util.spec_from_file_location("un", str(ROOT / "scripts" / "update_news.py"))
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass


def level_of(score):
    return {30: 3, 25: 2, 20: 1}.get(score, 0)


def hit_words(sub, title, summary, tier_score):
    """返回该细类某档词表中命中的词。"""
    text = f"{title or ''} {summary or ''}".lower()
    rules = un.CONTENT_STRENGTH_RULES.get(sub, [])
    hits = []
    for score, kws in rules:
        if score != tier_score:
            continue
        for kw in kws:
            if un._kw_hit(text, kw.lower()):
                hits.append(kw)
    return hits


def main() -> None:
    rows = [json.loads(l) for l in (ROOT / "data" / "gold-set.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    labeled = [r for r in rows if r.get("label_strength") is not None]

    print("=== A 假里程碑：kw=30 而 gold≤2，命中词归因（30 档 + 全档）===")
    for r in labeled:
        kw_sc = un.score_content_strength(r["sub_kw"], r.get("title", ""), r.get("summary", ""))
        if level_of(kw_sc) != 3 or r["label_strength"] > 2:
            continue
        h30 = hit_words(r["sub_kw"], r.get("title", ""), r.get("summary", ""), 30)
        print(f"  [{r['sub_kw']}] gold=L{r['label_strength']} 30档命中={h30}")
        print(f"      {(r.get('title_zh') or r.get('title',''))[:60]}")

    print("\n=== A2 全库 30 档命中词频次（3613 条，看哪些词贡献了 505 个 L3）===")
    from collections import Counter
    d = json.load(open(ROOT / "data" / "history.json", encoding="utf-8"))
    items = [i for i in d.get("items", []) if isinstance(i, dict) and i.get("sub_dimension")]
    freq = Counter()
    n30 = 0
    for it in items:
        sub = it["sub_dimension"]
        text = f"{it.get('title','')} {it.get('summary','')}".lower()
        rules = un.CONTENT_STRENGTH_RULES.get(sub, [])
        hit30 = False
        for score, kws in rules:
            if score != 30:
                continue
            for kw in kws:
                if un._kw_hit(text, kw.lower()):
                    freq[(sub, kw)] += 1
                    hit30 = True
        if hit30:
            n30 += 1
    print(f"  30 档条目 {n30}/{len(items)}；命中词 top30：")
    for (sub, kw), n in freq.most_common(30):
        print(f"    {sub:<5} {kw:<14} {n}")

    print("\n=== C 细类错分取证：gold 国际动态 被 kw 判 政策法规 的 10 条 ===")
    for r in labeled:
        if r.get("label_sub") == "国际动态" and r["sub_kw"] == "政策法规":
            print(f"  {(r.get('title_zh') or r.get('title',''))[:64]}")
            print(f"      src={r.get('source','')[:20]} dim={r.get('dimension','')}")


if __name__ == "__main__":
    main()
