#!/usr/bin/env python3.11
"""v5.2 kw 收紧检查包（2026-09-30）：逐条 before/after 对照 + 汇总。

三方数据：gold 标注（gold-set.jsonl）× 冻结旧 kw 预测（gold-set-predictions.json）
× 当前 kw 判定（实时调用 update_news 的 score_content_strength / categorize_dimension）。
输出：data/kw-tighten-review.md（供老温检查）
"""
import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("un", ROOT / "scripts" / "update_news.py")
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)

gold = [json.loads(l) for l in (ROOT / "data" / "gold-set.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
frozen = {r["id"]: r for r in json.loads((ROOT / "data" / "gold-set-predictions.json").read_text(encoding="utf-8"))["rows"]}
LEVEL = {3: "里程碑30", 2: "重要25", 1: "进展20", 0: "常规兜底"}

# 真实 site_id / library 只能从 history.json 按 url 反查（gold 记录里没有这两个字段；
# 用错 library 会让"外源政府→国际动态"改判规则失效 → 细类/强度都会失真）
_hist = json.loads((ROOT / "data" / "history.json").read_text(encoding="utf-8")).get("items", [])
meta = {it.get("url"): (it.get("site_id", ""), it.get("library", "media")) for it in _hist if it.get("url")}
_src2site = {}
for it in _hist:
    _src2site.setdefault(it.get("site_name", ""), (it.get("site_id", ""), it.get("library", "media")))


def kw_level_of(score: int | None) -> int:
    return {30: 3, 25: 2, 20: 1}.get(score, 0)


rows = []
miss_meta = 0
for g in gold:
    if g.get("label_strength") is None:
        continue
    sid, lib = meta.get(g.get("url") or "", ("", ""))
    if not sid:
        sid, lib = _src2site.get(g.get("source", ""), ("", "media"))
        miss_meta += 1
    sub, _ = (un.categorize_dimension(sid, g.get("title") or "", g.get("summary") or "", lib), None)
    sub = sub[1] if isinstance(sub, tuple) else sub
    score = un.score_content_strength(sub, g.get("title") or "", g.get("summary") or "")
    old = frozen.get(g["id"], {}).get("kw", {})
    gl = g["label_strength"]
    rows.append({
        "id": g["id"], "title": (g.get("title_zh") or g.get("title") or "")[:46],
        "src": g.get("source", ""), "lib": lib, "gold": gl, "gold_sub": g.get("label_sub", ""),
        "old": old.get("level"), "old_sub": g.get("sub_kw", ""),
        "new": kw_level_of(score), "new_sub": sub, "new_score": score,
    })
if miss_meta:
    print(f"⚠️ {miss_meta} 条未能按 url 反查 site_id（已回落源名映射）")
print(f"library 分布: {dict(Counter(r['lib'] for r in rows).most_common())}")

fake_before = [r for r in rows if r["old"] == 3 and r["gold"] <= 2]
fake_after = [r for r in rows if r["new"] == 3 and r["gold"] <= 2]
miss_before = [r for r in rows if r["old"] is not None and r["old"] < r["gold"]]
miss_after = [r for r in rows if r["new"] < r["gold"]]

print(f"假里程碑（kw=30 而 gold≤2）：{len(fake_before)} → {len(fake_after)}")
print(f"漏判（kw<gold）：{len(miss_before)} → {len(miss_after)}")
hit_b = sum(1 for r in rows if r["old"] == r["gold"]) / len(rows) * 100
hit_a = sum(1 for r in rows if r["new"] == r["gold"]) / len(rows) * 100
near_b = sum(1 for r in rows if r["old"] is not None and abs(r["old"] - r["gold"]) <= 1) / len(rows) * 100
near_a = sum(1 for r in rows if abs(r["new"] - r["gold"]) <= 1) / len(rows) * 100
print(f"强度档位完全命中：{hit_b:.1f}% → {hit_a:.1f}%｜±1：{near_b:.1f}% → {near_a:.1f}%")
sub_hit_b = sum(1 for r in rows if r["gold_sub"] and r["old_sub"] == r["gold_sub"]) / max(1, sum(1 for r in rows if r["gold_sub"])) * 100
sub_hit_a = sum(1 for r in rows if r["gold_sub"] and r["new_sub"] == r["gold_sub"]) / max(1, sum(1 for r in rows if r["gold_sub"])) * 100
print(f"细类命中：{sub_hit_b:.1f}% → {sub_hit_a:.1f}%")
print("旧分布:", dict(Counter(r["old"] for r in rows).most_common()))
print("新分布:", dict(Counter(r["new"] for r in rows).most_common()))
print("gold分布:", dict(Counter(r["gold"] for r in rows).most_common()))

md = ["# v5.2 kw 收紧检查包（2026-09-30）", "",
      f"样本：gold set **{len(rows)} 条**（含 1 条缺细类标注）。旧 = 2026-09-29 冻结预登记，新 = v5.2 词表。", "",
      "## 一、总账", "",
      "| 指标 | 旧 | 新 |", "|---|---|---|",
      f"| 强度档位完全命中 | {hit_b:.1f}% | **{hit_a:.1f}%** |",
      f"| 强度 ±1 命中 | {near_b:.1f}% | **{near_a:.1f}%** |",
      f"| 细类命中 | {sub_hit_b:.1f}% | **{sub_hit_a:.1f}%** |",
      f"| **假里程碑（kw=30 而老温判≤重要）** | **{len(fake_before)} 条** | **{len(fake_after)} 条** |",
      f"| 漏判（kw<gold） | {len(miss_before)} 条 | {len(miss_after)} 条 |",
      "", "档位分布（旧/新/gold）：",
      f"- 旧 `{dict(sorted(Counter(r['old'] for r in rows).items(), reverse=True))}`",
      f"- 新 `{dict(sorted(Counter(r['new'] for r in rows).items(), reverse=True))}`",
      f"- gold `{dict(sorted(Counter(r['gold'] for r in rows).items(), reverse=True))}`", "",
      "## 二、原 13 条假里程碑：逐条 after 对照", "",
      "| # | 老温判 | 旧 | 新 | 标题 | 细类（gold→新） |", "|---|---|---|---|---|---|"]
for i, r in enumerate(fake_before, 1):
    chg = "✅" if r["new"] == r["gold"] else ("🟡±1" if abs(r["new"] - r["gold"]) <= 1 else "⬆️仍高")
    md.append(f"| {i} | {LEVEL[r['gold']]} | {LEVEL.get(r['old'],'?')} | {LEVEL[r['new']]} {chg} | {r['title']} | "
              f"{r['gold_sub']}→{r['new_sub']} |")
md += ["", "## 三、全量分歧表（gold 与新旧 kw 不一致者）", "",
       "| 老温判 | 旧kw | 新kw | 标题 | 细类 gold→新 | 源 |", "|---|---|---|---|---|---|"]
for r in sorted(rows, key=lambda x: -x["gold"]):
    if r["gold"] == r["new"] and r["old"] == r["new"]:
        continue
    md.append(f"| {LEVEL[r['gold']]} | {LEVEL.get(r['old'],'?')} | {LEVEL[r['new']]} | {r['title']} | "
              f"{r['gold_sub']}→{r['new_sub']} | {r['src']} |")
out = ROOT / "data" / "kw-tighten-review.md"
out.write_text("\n".join(md) + "\n", encoding="utf-8")
print(f"\n→ {out}")
