#!/usr/bin/env python3.11
"""①a 收紧前置取证：从 gold-set.jsonl 提取可执行的修复证据清单。

产出（终端 + data/kw-tighten-evidence.json）：
  A. 假里程碑清单：kw 给 30（L3）而老温标 ≤2 的每一条 + 命中的具体词表线索
  B. 漏判重要级清单：kw 给 ≤L0/L1 而 老温标 2 的条目
  C. 细类错分矩阵明细：gold 细类 vs kw 细类 不一致的每一条
  D. 改前基线（gold 命中率/分布 + 全库强度分布）——改后对比用
"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from datetime import datetime, timezone
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

LEVELS = [3, 2, 1, 0]
SUBS = ["政策法规", "国际动态", "技术研发", "基础研究", "社会创新", "企业经营", "金融资本"]
OUT = ROOT / "data" / "kw-tighten-evidence.json"


def level_of(score):
    return {30: 3, 25: 2, 20: 1}.get(score, 0)


def main() -> None:
    rows = [json.loads(l) for l in (ROOT / "data" / "gold-set.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    labeled = [r for r in rows if r.get("label_strength") is not None]

    # ── A/B 强度证据 ─────────────────────────────────────────────
    fake_ms, missed = [], []
    for r in labeled:
        kw_sc = un.score_content_strength(r["sub_kw"], r.get("title", ""), r.get("summary", ""))
        kw_lv = level_of(kw_sc)
        g = r["label_strength"]
        rec = {"id": r["id"][:12], "sub_kw": r["sub_kw"], "title": (r.get("title_zh") or r.get("title", ""))[:60],
               "kw_score": kw_sc, "kw_level": kw_lv, "gold": g, "note": r.get("label_note") or ""}
        if kw_lv == 3 and g <= 2:
            fake_ms.append(rec)
        if kw_lv <= 1 and g == 2:
            missed.append(rec)

    # ── C 细类证据（只统计有细类标注的）──────────────────────────
    sub_dis = []
    for r in labeled:
        if not r.get("label_sub") or r["label_sub"] == r["sub_kw"]:
            continue
        sub_dis.append({"id": r["id"][:12], "gold_sub": r["label_sub"], "kw_sub": r["sub_kw"],
                        "title": (r.get("title_zh") or r.get("title", ""))[:60],
                        "note": r.get("label_note") or ""})

    # ── D 改前基线 ───────────────────────────────────────────────
    # gold 命中
    def gold_stats():
        pairs = []
        for r in labeled:
            kw_sc = un.score_content_strength(r["sub_kw"], r.get("title", ""), r.get("summary", ""))
            pairs.append((r["label_strength"], level_of(kw_sc)))
        exact = sum(1 for g, q in pairs if g == q) / len(pairs)
        near = sum(1 for g, q in pairs if abs(g - q) <= 1) / len(pairs)
        dist = Counter(q for _, q in pairs)
        return {"n": len(pairs), "exact": round(exact, 3), "near1": round(near, 3),
                "kw_dist": {str(k): dist.get(k, 0) for k in LEVELS}}

    sub_pairs = [(r["label_sub"], r["sub_kw"]) for r in labeled if r.get("label_sub")]
    sub_acc = sum(1 for g, q in sub_pairs if g == q) / len(sub_pairs)

    # 全库分布（3613 条）
    d = json.load(open(ROOT / "data" / "history.json", encoding="utf-8"))
    items = [i for i in d.get("items", []) if isinstance(i, dict) and i.get("sub_dimension")]
    full_dist = Counter()
    for it in items:
        full_dist[level_of(un.score_content_strength(it["sub_dimension"], it.get("title", ""),
                                                     it.get("summary", "")))] += 1
    full_sub = Counter(i["sub_dimension"] for i in items)

    ev = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "A_fake_milestones": fake_ms,
        "B_missed_important": missed,
        "C_sub_misassign": sub_dis,
        "D_baseline": {
            "gold_strength": gold_stats(),
            "gold_sub_acc": round(sub_acc, 3),
            "corpus_n": len(items),
            "corpus_strength_dist": {str(k): full_dist.get(k, 0) for k in LEVELS},
            "corpus_sub_dist": dict(full_sub),
        },
    }
    OUT.write_text(json.dumps(ev, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"A 假里程碑（kw=30 而 gold≤2）：{len(fake_ms)} 条")
    for r in fake_ms:
        print(f"  [{r['sub_kw']}] {r['title']}  (kw={r['kw_score']}→L3, gold=L{r['gold']})")
    print(f"\nB 漏判重要（kw≤L1 而 gold=2）：{len(missed)} 条")
    for r in missed:
        print(f"  [{r['sub_kw']}] {r['title']}  (kw=L{r['kw_level']}, gold=L2)")
    print(f"\nC 细类错分：{len(sub_dis)} 条")
    cc = Counter((r["gold_sub"], r["kw_sub"]) for r in sub_dis)
    for (g, q), n in cc.most_common():
        print(f"  gold {g} → kw {q}：{n} 条")
    print(f"\nD 基线：gold 强度命中 {gold_stats()['exact']*100:.1f}%｜细类命中 {sub_acc*100:.1f}%")
    print(f"  gold 上 kw 档位分布 {gold_stats()['kw_dist']}")
    print(f"  全库（{len(items)} 条）强度分布 {ev['D_baseline']['corpus_strength_dist']}")
    print(f"  全库细类分布 {dict(full_sub)}")
    print(f"\n→ {OUT.name}")


if __name__ == "__main__":
    main()
