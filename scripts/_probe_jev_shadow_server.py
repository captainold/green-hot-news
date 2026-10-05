#!/usr/bin/env python3.11
"""P2 影子模式服务器实测（native 直连，小样本 8 条，校验 score 不变）。"""
import importlib.util
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path("/opt/green-hot-news")
spec = importlib.util.spec_from_file_location("un", ROOT / "scripts" / "update_news.py")
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)

print("dialect:", un.jev_client.dialect(), "| base:", un.jev_client._load_cfg("JEV_BASE_URL"),
      "| model:", un.jev_client._load_cfg("JEV_MODEL"), "| shadow:", un.jev_client.shadow_enabled())
items = json.loads((ROOT / "data" / "latest-24h.json").read_text(encoding="utf-8"))["items"]
sample = items[:8]
before = [(r.get("score"), (r.get("score_breakdown") or {}).get("strength")) for r in sample]
rep = un._run_jev_shadow(sample, ROOT / "data")
after = [(r.get("score"), (r.get("score_breakdown") or {}).get("strength")) for r in sample]
print("\nscore 前后一致:", before == after)
print("样本:", before, "->", after)
for r in sample:
    sh = r.get("jev_shadow") or {}
    print(f"  kw[{r.get('sub_dimension','')}/{sh.get('kw_score')}] "
          f"jev[{sh.get('sub','')}(c={sh.get('sub_conf')}) L{sh.get('level_C')}/A{sh.get('level_A')} "
          f"err={sh.get('err','')[:40]} {sh.get('sec')}s] {(r.get('title') or '')[:34]}")
print("\n报告:", json.dumps({k: rep.get(k) for k in
      ("dialect", "model", "n", "judged", "failed", "wall_sec", "latency_p50", "latency_max",
       "sub_agree_pct", "level_agree_pct", "level_near1_pct")}, ensure_ascii=False))
