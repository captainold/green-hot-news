#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日精选引擎（2026-09-23）。

从 data/latest-24h.json 选出当日高价值新闻，输出精选结构 digest.json：
- 打分体系严格遵循 docs/标准文档/打分体系标准.md v5.0（本脚本不打分，只消费 score 字段）
- 三层分组（政策/创新/产业，DIM_ORDER 按创新价值链）
- A 级（≥70）优先；不足时以 B+ 补足到 --min-count（标记 fallback=true）
- 每源配额防刷屏、URL 去重、旧闻过滤（published_at 超龄跳过）、已发布指纹过滤
- 每层选 1 条「今日头条」（层内最高分）

用法：
    python scripts/publish/select_daily.py                     # 默认参数
    python scripts/publish/select_daily.py --min-count 8 --max-per-dim 6
输出：data/publish/<date>/digest.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (DATA_DIR, DIM_META, DIM_ORDER, clean_summary, clean_title,
                    load_config, load_state, out_dir, today_str, utf8_console)


def parse_iso(dt_str: str) -> datetime | None:
    if not dt_str:
        return None
    try:
        return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    except ValueError:
        pass
    # 兜底：2026-09-03 15:00（无时区按 UTC，与 update_news 侧一致）
    try:
        return datetime.strptime(dt_str[:16], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def select(items: list[dict], *, min_score_a: int, min_count: int, max_per_dim: int,
           per_site: int, max_age_days: int, exclude_urls: set[str]) -> tuple[list[dict], int]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days) if max_age_days else None

    cand = []
    for it in items:
        url = (it.get("url") or "").rstrip("/")
        if not url or url in exclude_urls:
            continue
        sc = it.get("score") or 0
        if sc < min_score_a:
            continue
        pa = parse_iso(it.get("published_at") or "")
        if pa and cutoff and pa < cutoff:
            continue  # 旧闻回流过滤
        cand.append(it)

    # 分数降序 → URL 去重（同源截断标题指同一链接）
    cand.sort(key=lambda x: (-(x.get("score") or 0), x.get("site_id", "")))
    seen: set[str] = set()
    deduped = []
    for it in cand:
        u = (it.get("url") or "").rstrip("/")
        if u in seen:
            continue
        seen.add(u)
        deduped.append(it)

    # 三层分组 + 每源配额 + 每层上限
    groups: dict[str, list[dict]] = {d: [] for d in DIM_ORDER}
    per_site_n: dict[str, int] = {}
    for it in deduped:
        dim = it.get("dimension") if it.get("dimension") in DIM_ORDER else "产业"
        if len(groups[dim]) >= max_per_dim:
            continue
        sid = it.get("site_id", "")
        if per_site and per_site_n.get(sid, 0) >= per_site:
            continue
        per_site_n[sid] = per_site_n.get(sid, 0) + 1
        groups[dim].append(it)

    # 层内已按分数排序；标记头条
    picked: list[dict] = []
    for dim in DIM_ORDER:
        for rank, it in enumerate(groups[dim]):
            it = dict(it)
            it["_headline"] = rank == 0
            it["_dim_rank"] = rank
            picked.append(it)

    total = len(picked)
    return picked, total


def trim_to_count(picked: list[dict], min_count: int, max_per_dim: int) -> list[dict]:
    """层内保序裁剪到 min_count 条（每层至少留 1）。"""
    if len(picked) <= min_count:
        return picked
    kept: list[dict] = []
    dim_quota: dict[str, int] = {}
    # 先每层保 1（头条），再按层间轮流（分数序已破坏，按 (_dim_rank, -score) 交错填充）
    by_dim: dict[str, list[dict]] = {}
    for it in picked:
        by_dim.setdefault(it.get("dimension") or "产业", []).append(it)
    for dim, lst in by_dim.items():
        if lst:
            kept.append(lst[0])
            dim_quota[dim] = 1
    dim_cycle = sorted(by_dim.keys(), key=lambda d: -max(i.get("score") or 0 for i in by_dim[d]))
    while len(kept) < min_count:
        added = False
        for dim in dim_cycle:
            if dim_quota[dim] >= max_per_dim:
                continue
            lst = by_dim[dim]
            if dim_quota[dim] < len(lst):
                kept.append(lst[dim_quota[dim]])
                dim_quota[dim] += 1
                added = True
                if len(kept) >= min_count:
                    break
        if not added:
            break
    return kept


def decorate(it: dict) -> dict:
    """输出干净条目（去掉下划线临时字段，附清洗后的展示字段）。"""
    title = clean_title(it.get("title", ""))
    return {
        "id": it.get("id", ""),
        "url": (it.get("url") or "").rstrip("/"),
        "title": title,
        "summary": clean_summary(title, it.get("summary", "")),
        "site_name": it.get("site_name", ""),
        "published_date": (it.get("published_at") or "")[:10],
        "dimension": it.get("dimension", ""),
        "sub_dimension": it.get("sub_dimension", ""),
        "region": it.get("region", ""),
        "score": it.get("score", 0),
        "score_level": it.get("score_level", ""),
        "headline": bool(it.get("_headline")),
        "dim_rank": int(it.get("_dim_rank", 0)),
    }


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description="每日精选引擎")
    parser.add_argument("--data", default=str(DATA_DIR / "latest-24h.json"))
    parser.add_argument("--min-score", type=int, default=None, help="A级线，默认读配置")
    parser.add_argument("--min-count", type=int, default=None, help="目标条数，默认读配置")
    parser.add_argument("--max-per-dim", type=int, default=None)
    parser.add_argument("--per-site", type=int, default=None)
    parser.add_argument("--max-age-days", type=int, default=None)
    parser.add_argument("--date", default=None, help="产物目录日期，默认今天")
    args = parser.parse_args()

    cfg = load_config().get("selection", {})
    min_score_a = args.min_score if args.min_score is not None else cfg.get("min_score_a", 70)
    min_count = args.min_count if args.min_count is not None else cfg.get("min_count", 8)
    max_per_dim = args.max_per_dim if args.max_per_dim is not None else cfg.get("max_per_dim", 6)
    per_site = args.per_site if args.per_site is not None else cfg.get("per_site", 2)
    max_age_days = args.max_age_days if args.max_age_days is not None else cfg.get("max_age_days", 7)

    try:
        data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ 读取数据失败: {e}")
        return 1
    items = data.get("items", [])
    state = load_state()
    exclude = set(state.get("published_urls", []))

    picked, total_a = select(items, min_score_a=min_score_a, min_count=min_count,
                             max_per_dim=max_per_dim, per_site=per_site,
                             max_age_days=max_age_days, exclude_urls=exclude)
    picked = trim_to_count(picked, min_count, max_per_dim)
    decorated = [decorate(it) for it in picked]
    # 重算 headline（trim 后仍以 dim_rank==0 为准）
    for it in decorated:
        it["headline"] = it["dim_rank"] == 0

    date = args.date or today_str()
    odir = out_dir(date)
    digest = {
        "date": date,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_generated_at": data.get("generated_at", ""),
        "source_window_hours": data.get("window_hours", 0),
        "site_count": data.get("site_count", 0),
        "candidate_count_a": total_a,
        "count": len(decorated),
        "dim_counts": {d: sum(1 for i in decorated if i["dimension"] == d) for d in DIM_ORDER},
        "fallback": total_a < min_count,
        "items": decorated,
    }
    out = odir / "digest.json"
    out.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"✅ 精选 {len(decorated)} 条（A线≥{min_score_a} 共 {total_a} 条候选，"
          f"fallback={'是' if digest['fallback'] else '否'}）")
    for d in DIM_ORDER:
        n = digest["dim_counts"][d]
        if n:
            heads = [i["title"] for i in decorated if i["dimension"] == d and i["headline"]]
            print(f"  {DIM_META[d]['icon']} {d}×{n}  头条: {heads[0] if heads else '-'}")
    print(f"📄 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
