#!/usr/bin/env python3.11
"""P0 证据复盘：从 data/jev-probe-history.json 里读出最近一次三方对照，看 noul/强度/细类的判别力。

用法：python3.11 scripts/_probe_jev_report.py [--last-n 30]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--last-n", type=int, default=30, help="挑样本量等于该值的最近一次三方对照")
    args = ap.parse_args()

    h = json.loads((ROOT / "data" / "jev-probe-history.json").read_text(encoding="utf-8"))
    cands = [x for x in h if x.get("rows") and x.get("sample") == args.last_n]
    if not cands:
        print(f"没有 sample={args.last_n} 的三方对照记录")
        return 1
    rec = cands[-1]
    rows = rec["rows"]
    print(f"记录时间 {rec['ts'][:19]}｜dialect={rec.get('dialect')}｜model={rec.get('model')}｜"
          f"样本 {len(rows)}（失败 {rec.get('fail')}）\n")

    print("== Jev 认为最像噪声的 8 条（is_noise 高）==")
    for x in sorted(rows, key=lambda z: -z["is_noise"])[:8]:
        print(f"  noise={x['is_noise']:.2f} green={x['is_green']:.2f} kw={x['kw']:>2} jev={x['jev']:>2}"
              f"  {x['title'][:46]}")
    print("\n== Jev 认为最不像绿色的 8 条（is_green 低）==")
    for x in sorted(rows, key=lambda z: z["is_green"])[:8]:
        print(f"  green={x['is_green']:.2f} noise={x['is_noise']:.2f} kw={x['kw']:>2} jev={x['jev']:>2}"
              f"  {x['title'][:46]}")

    print("\n== 档位分布 ==")
    print("  关键词:", dict(sorted(collections.Counter(x["kw"] for x in rows).items())))
    print("  Jev   :", dict(sorted(collections.Counter(x["jev"] for x in rows).items())))
    print("  Pro   :", dict(sorted(collections.Counter(x["pro"] for x in rows).items(), key=lambda kv: (kv[0] is None, kv[0]))))
    print("  Jev 七细类:", dict(collections.Counter(x["sub_jev"] for x in rows)))

    pairs = [(x["kw"], x["jev"]) for x in rows]
    same = sum(1 for a, b in pairs if a == b)
    higher = sum(1 for a, b in pairs if b > a)
    lower = sum(1 for a, b in pairs if b < a)
    print(f"\n== 方向 ==")
    print(f"  关键词 vs Jev：同 {same}｜Jev 高 {higher}｜Jev 低 {lower}")
    pp = [(x["pro"], x["jev"]) for x in rows if x["pro"] is not None]
    print(f"  Pro vs Jev  ：同 {sum(1 for a, b in pp if a == b)}/{len(pp)}"
          f"｜Jev 高 {sum(1 for a, b in pp if b > a)}｜Jev 低 {sum(1 for a, b in pp if b < a)}")
    print(f"  is_green 均值 {sum(x['is_green'] for x in rows) / len(rows):.2f}｜"
          f"is_noise 均值 {sum(x['is_noise'] for x in rows) / len(rows):.2f}｜"
          f"强度 conf 均值 {sum(x['strength_conf'] for x in rows) / len(rows):.2f}")

    print("\n== 细类分歧（关键词 → Jev）==")
    for x in rows:
        if not x["sub_ok"]:
            print(f"  [{x['sub_kw']} → {x['sub_jev']}] {x['title'][:48]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
