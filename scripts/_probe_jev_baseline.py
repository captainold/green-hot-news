#!/usr/bin/env python3.11
"""临时探测（_probe_ 前缀）：为「TypeSafe Jev 接入方案」统计现有主流程的判定规模与薄弱点。

只读 data/*.json，不改任何数据、不发网络请求。用途：
  1. 每轮需要判定的条目量（all_items_24h ∪ green_items_24h 的规模）
  2. 七细类分布（Jev choice 的输出空间）
  3. 内容强度「关键词全部落空 → 兜底默认分」的比例（关键词最弱的地方）
  4. 主题相关分落 6 分（无任何关键词命中）的比例
  5. 若接 Jev：单轮调用量 / 单日调用量 / 成本的粗算
"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("un", str(ROOT / "scripts" / "update_news.py"))
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> None:
    d = ROOT / "data"
    hist = load(d / "history.json").get("items", [])
    all24 = load(d / "latest-24h-all.json").get("items", [])
    print(f"history.json items         : {len(hist)}")
    print(f"latest-24h-all.json items  : {len(all24)}   ← 主流程每轮实际打分/分类的规模量级")

    # 1) 细类分布（以 history 全量为样本）
    subs = Counter(i.get("sub_dimension", "?") for i in hist)
    print("\n[七细类分布 · history]")
    for k, v in subs.most_common():
        print(f"  {k:<8} {v:>5}  {v / max(1, len(hist)) * 100:5.1f}%")

    dims = Counter(i.get("dimension", "?") for i in hist)
    print("[三层分布 · history]")
    for k, v in dims.most_common():
        print(f"  {k:<8} {v:>5}  {v / max(1, len(hist)) * 100:5.1f}%")

    # 2) 内容强度：关键词全落空 = 命中兜底默认分
    fallback = 0
    fallback_by_sub: Counter = Counter()
    strength_dist: Counter = Counter()
    replayed = 0
    for it in hist:
        sub = it.get("sub_dimension")
        if not sub:
            continue
        replayed += 1
        title = it.get("title_zh") or it.get("title", "")
        got = un.score_content_strength(sub, it.get("title", ""), it.get("summary", ""))
        strength_dist[got] += 1
        default = un.DEFAULT_STRENGTH_BY_SUB.get(sub, un.DEFAULT_STRENGTH)
        if got == default:
            fallback += 1
            fallback_by_sub[sub] += 1
    print(f"\n[内容强度 · 关键词重放 {replayed} 条]")
    for k, v in sorted(strength_dist.items(), key=lambda x: -x[0]):
        print(f"  {k:>2} 分  {v:>5}  {v / max(1, replayed) * 100:5.1f}%")
    print(f"  落兜底默认分（关键词档位全未命中）: {fallback}/{replayed} = {fallback / max(1, replayed) * 100:.1f}%")
    print("  兜底分按细类：", dict(fallback_by_sub.most_common()))

    # 3) 主题相关分：6 分 = 三级关键词全未命中
    topic_dist: Counter = Counter()
    topic_floor = 0
    for it in hist:
        t = un.score_topic(it.get("title", ""), it.get("summary", ""))
        topic_dist[t] += 1
        if t == 6:
            topic_floor += 1
    print(f"\n[主题相关分 · history {len(hist)} 条] {dict(sorted(topic_dist.items(), reverse=True))}")
    print(f"  6 分（无任何主题关键词命中）= {topic_floor} 条 {topic_floor / max(1, len(hist)) * 100:.1f}%")

    # 4) 规模与成本粗算（Jev：$24.57 / 百万次决策，实测 p50 0.53s）
    per_round = len(all24)
    rounds_per_day = 48
    calls_day = per_round * rounds_per_day
    cost_m_per_call = 24.57
    print("\n[若接 Jev 的规模粗算]")
    print(f"  单轮判定条数（无缓存上限）: {per_round}")
    print(f"  单日判定条数              : {calls_day:,}（{per_round} × 48 轮）")
    print(f"  单日成本（上界，$24.57/M）: ${calls_day * cost_m_per_call / 1e6:.2f}")
    print(f"  单月成本（上界）          : ${calls_day * 30 * cost_m_per_call / 1e6:.2f}")
    print(f"  串行耗时（p50 0.53s/条）  : {per_round * 0.53 / 60:.1f} 分钟/轮（并发 4 → {per_round * 0.53 / 4 / 60:.1f} 分钟）")
    # 仅新条目（缓存命中后）的量级：history 中 24h 内新增
    new_recent = sum(1 for it in hist if (it.get("first_seen_at") or "") >= "2026-09-02")
    print(f"  参考：history 里 2026-09-02 之后首次见到的条目 {new_recent} 条（≈按天新增量级，接缓存后的真实调用量）")


if __name__ == "__main__":
    main()
