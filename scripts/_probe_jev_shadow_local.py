#!/usr/bin/env python3.11
"""P2 影子模式本地验证（走本机 TokenHub 网关，小样本）。

校验两件事：① rec["jev_shadow"] 正确写入；② **score 完全不变**（铁律）。
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent
os.environ["JEV_SHADOW"] = "1"
os.environ["JEV_SHADOW_MAX"] = os.environ.get("N", "6")

spec = importlib.util.spec_from_file_location("un", ROOT / "scripts" / "update_news.py")
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)

items = json.loads((ROOT / "data" / "latest-24h.json").read_text(encoding="utf-8"))["items"]
sample = items[:int(os.environ["JEV_SHADOW_MAX"])]
before = [(r.get("score"), (r.get("score_breakdown") or {}).get("strength")) for r in sample]
report = un._run_jev_shadow(sample, ROOT / "data")
after = [(r.get("score"), (r.get("score_breakdown") or {}).get("strength")) for r in sample]

print("\n=== score 前后对比（必须完全一致）===")
print("一致:", before == after, "|", before, "->", after)
print("\n=== 逐条影子判定 ===")
for r in sample:
    sh = r.get("jev_shadow") or {}
    print(f"  kw[{r.get('sub_dimension','')}/{sh.get('kw_score')}] "
          f"jev[{sh.get('sub','')}(conf={sh.get('sub_conf')}) L{sh.get('level_C')}/A{sh.get('level_A')} "
          f"green={sh.get('is_green')} noise={sh.get('is_noise')} {sh.get('sec')}s] "
          f"{(r.get('title') or '')[:38]}")
print("\n=== 汇总报告 ===")
print(json.dumps(report, ensure_ascii=False, indent=1)[:1200])
