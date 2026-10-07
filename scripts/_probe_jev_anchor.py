#!/usr/bin/env python3.11
"""P0 追加实验：内容强度「问法」对照（A 现状 / B 频率锚定 / C 三问 noul 合成）。

背景（2026-09-23 P0 实测 30 条）：关键词 vs Jev 的内容强度一致率只有 3/30 = 10%，
方向一边倒（Jev 更高 23 条），档位分布塌在「重要级 25 分」；而关键词轨 62.3% 落兜底分。
**两条判定器都退化成"常数判定器"，方向相反**。所以要分清是「Jev 判不准」还是「问法不对」。

本实验对同一批抽样跑三种问法（问题定义与合成逻辑都在 scripts/jev_client.py，单一来源）：
  A 现状四档        —— 纯定性描述
  B 频率锚定四档    —— 显式给出各档应占比例
  C 三问 noul 合成  —— 改问"是否历史性首次 / 是否关键节点 / 是否缺少可验证信息"，档位在本仓库合成
判读要点（P0 结论）：**A/B 无方差 → 无法排序；C 是唯一有区分度的形态。**

用法：python3.11 scripts/_probe_jev_anchor.py [--n 30] [--seed 7]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

spec = importlib.util.spec_from_file_location("un", str(ROOT / "scripts" / "update_news.py"))
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)

import jev_client as jc          # noqa: E402
import sample_snapshot as snap    # noqa: E402
import score_diff_monitor as sdm  # noqa: E402  复用它的 random_sample

FORMS = [("A", "A_现状四档"), ("B", "B_频率锚定四档"), ("C", "C_三问noul合成")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    if not jc.is_enabled():
        print("Jev 不可用（缺 JEV_API_KEY 或已熔断）")
        return 2

    random.seed(args.seed)
    d = json.load(open(ROOT / "data" / "history.json", encoding="utf-8"))
    items = [i for i in d.get("items", []) if isinstance(i, dict) and i.get("sub_dimension")]
    sample = sdm.random_sample(items, args.n)
    snapshot = snap.save(f"jev-anchor-n{len(sample)}-seed{args.seed}", sample, corpus=items,
                         extra={"seed": args.seed, "forms": [f for f, _ in FORMS]})
    print(f"样本 {len(sample)} 条（seed={args.seed}）｜dialect={jc.dialect()}｜"
          f"model={jc._load_cfg('JEV_MODEL')}")
    print(f"语料快照 {snapshot.name}（语料 {snap.corpus_fingerprint(items)}）\n")

    stats: dict[str, dict] = {}
    per_item: dict[str, dict[str, dict]] = {}
    for form, name in FORMS:
        rows = []
        fails = 0
        for it in sample:
            sub = it["sub_dimension"]
            res, dt, err = jc.judge_strength(
                it, form=form,
                fallback=un.DEFAULT_STRENGTH_BY_SUB.get(sub, un.DEFAULT_STRENGTH))
            if res is None:
                fails += 1
                continue
            rows.append({
                "sub": sub,
                "title": (it.get("title_zh") or it.get("title") or "")[:34],
                "kw": un.score_content_strength(sub, it.get("title", ""), it.get("summary", "")),
                "level": res["level"],
                "score": res["score"],
                "conf": res.get("conf"),
                "lat": round(dt, 2),
            })
        dist = Counter(r["level"] for r in rows)
        agree = sum(1 for r in rows if r["kw"] == r["score"])
        stats[name] = {
            "n": len(rows), "fail": fails,
            "dist": {f"L{k}": dist.get(k, 0) for k in range(4)},
            "agree_kw": agree,
            "rate": round(agree / len(rows) * 100, 1) if rows else 0,
            "lat_p50": sorted(r["lat"] for r in rows)[len(rows) // 2] if rows else 0,
        }
        per_item[name] = {r["title"]: r for r in rows}

    print("=== 档位分布对比（L3=里程碑 30 / L2=重要 25 / L1=进展 20 / L0=常规=按细类兜底）===")
    print(f"{'问法':<18}{'有效':>4}{'失败':>5}   L3    L2    L1    L0   一致率      p50")
    for _, name in FORMS:
        s = stats[name]
        dist = s["dist"]
        print(f"{name:<18}{s['n']:>4}{s['fail']:>5}  "
              f"{dist['L3']:>4}  {dist['L2']:>4}  {dist['L1']:>4}  {dist['L0']:>4}  "
              f"{s['agree_kw']:>2}/{s['n']:<3}={s['rate']:>5}%  {s['lat_p50']:>4}s")

    base = FORMS[0][1]
    print("\n=== 逐条对照（细类 | 标题 | 关键词 | A | B | C）===")
    for title, ra in per_item[base].items():
        cells = []
        for _, name in FORMS:
            rb = per_item[name].get(title)
            cells.append("  -" if rb is None else f"{rb['score']:>3}")
        print(f"[{ra['sub']}] {title:<36} {ra['kw']:>3} | " + " | ".join(cells))

    hist_path = ROOT / "data" / "jev-probe-history.json"
    hist = []
    if hist_path.exists():
        try:
            hist = json.loads(hist_path.read_text(encoding="utf-8"))
        except Exception:
            hist = []
    hist.append({
        "ts": datetime.now(timezone.utc).isoformat(), "kind": "anchor-experiment",
        "dialect": jc.dialect(), "model": jc._load_cfg("JEV_MODEL"),
        "seed": args.seed, "sample": len(sample), "snapshot": snapshot.name,
        "variants": stats,
    })
    hist_path.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已追加到 data/jev-probe-history.json（累计 {len(hist)} 次探测）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
