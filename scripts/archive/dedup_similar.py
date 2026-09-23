#!/usr/bin/env python3.11
"""标题相似度去重——清理 data/*.json 里"同 URL + 标题变体"的真重复条目。

背景（2026-08-24 去重治理 P0）：merge_history 只用 _title_dedup_key（标题规范化
精确匹配）去重，但同一篇新闻被抓多次时标题常有变体——截断（"明确2030年前" vs
"明确2"）、标点差异（，vs ,）、源名后缀（"…研讨会召开" vs "…研讨会召开-上海环境能源交易所"）、
措辞微调（"部分美国" vs "多家美国"）——导致 title_key 不同而漏去重。

策略（保守，避免误删）：
- 仅对「原始 URL 完全相同 + 标题相似度 ≥ 阈值」判重（同 URL 不同文如微博热搜榜、
  GitHub 趋势的描述 vs 仓库名，标题相似度低 → 不删，仅报告）。
- 每组保留最优：score 高优先 → 标题更长（更完整）→ 有 title_zh 优先。

用法：
    python3.11 scripts/dedup_similar.py            # dry-run，只报告
    python3.11 scripts/dedup_similar.py --apply    # 实际清理并写回

幂等：可重复运行。写回前自动备份到 data/*.json.bak-dedup。
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
THRESHOLD = 0.80
MIN_LEN = 8  # 标题太短不做相似判重，避免误杀


def _norm(t: str) -> str:
    return re.sub(r"[\s\u3000\-_—–()（）【】\[\]「」『』・,，.。:：;；/\\|]", "", (t or "").lower())


def _similar(a: str, b: str, threshold: float) -> bool:
    a, b = (a or "").strip(), (b or "").strip()
    if len(a) < MIN_LEN or len(b) < MIN_LEN:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


def _is_suffix_of(shorter: str, longer: str) -> bool:
    """shorter 是否是 longer 去掉源名后缀后的版本（longer = shorter + "-源名"）。"""
    if not longer.startswith(shorter):
        return False
    rest = longer[len(shorter):]
    return bool(rest) and rest[0] in "-—–|·"


def _is_dup(a: str, b: str, threshold: float) -> bool:
    """两条标题是否判重：相似度超阈值，或前缀截断关系（列表页抓取截断）。"""
    a, b = (a or "").strip(), (b or "").strip()
    if _similar(a, b, threshold):
        return True
    # 前缀截断：短标题是长标题的前缀（同 URL 组内基本是抓取截断，如"明确2" vs "明确2030年前…"）
    if len(a) >= MIN_LEN and len(b) >= MIN_LEN:
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        if longer.startswith(shorter) and len(longer) - len(shorter) >= 3:
            return True
    return False


def _keep(a: dict, b: dict) -> dict:
    """同组重复里挑最优保留。score 高 → 无源名后缀 → 标题长 → 有 title_zh。"""
    sa, sb = a.get("score", 0), b.get("score", 0)
    if sa != sb:
        return a if sa > sb else b
    # 无源名后缀优先（"-上海环境能源交易所" 等脏后缀应被清理，而非保留）
    ta, tb = a.get("title", ""), b.get("title", "")
    if _is_suffix_of(ta, tb):
        return a
    if _is_suffix_of(tb, ta):
        return b
    # 标题长优先（截断场景保留完整标题）
    if len(ta) != len(tb):
        return a if len(ta) > len(tb) else b
    return a if a.get("title_zh") else b


def dedup_items(items: list[dict], threshold: float = THRESHOLD):
    """返回 (去重后列表, 报告列表)。报告每项为 (url, 保留标题, 删除标题, 相似度)。"""
    by_url: dict[str, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        u = (it.get("url") or "").strip()
        if u:
            by_url[u].append(i)

    remove: set[int] = set()
    report: list[tuple[str, str, str, float]] = []
    for u, idx in by_url.items():
        if len(idx) < 2:
            continue
        # 组内两两相似聚成连通分量，每分量保留最优
        n = len(idx)
        parent = list(range(n))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[rx] = ry

        for a in range(n):
            for b in range(a + 1, n):
                if _is_dup(items[idx[a]].get("title", ""), items[idx[b]].get("title", ""), threshold):
                    union(a, b)

        comps: dict[int, list[int]] = defaultdict(list)
        for k in range(n):
            comps[find(k)].append(idx[k])

        for _, members in comps.items():
            if len(members) < 2:
                continue
            # 用 _keep 比较逻辑挑最优（score → 无后缀 → 标题长 → title_zh）
            best = members[0]
            for m in members[1:]:
                if _keep(items[m], items[best]) is items[m]:
                    best = m
            for m in members:
                if m == best:
                    continue
                remove.add(m)
                report.append((
                    u, items[best].get("title", ""), items[m].get("title", ""),
                    SequenceMatcher(None, items[best].get("title", ""), items[m].get("title", "")).ratio(),
                ))
    kept = [it for i, it in enumerate(items) if i not in remove]
    return kept, report, remove


def process_file(path: Path, apply: bool, threshold: float) -> int:
    if not path.exists():
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    is_dict = isinstance(data, dict) and "items" in data
    items = data["items"] if is_dict else data
    kept, report, remove = dedup_items(items, threshold)
    if report:
        print(f"\n=== {path.name}：{len(items)} 条 → 去重 {len(remove)} 条（保留 {len(kept)}）===")
        for u, bt, dt, r in report:
            print(f"  [删] 相似度 {r:.2f} | {dt[:35]!r}")
            print(f"      保留: {bt[:35]!r}")
            print(f"      url: {u[:70]}")
    if apply and remove:
        bak = path.with_suffix(path.suffix + ".bak-dedup")
        shutil.copy2(path, bak)
        if is_dict:
            data["count"] = len(kept)
            data["items"] = kept
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        else:
            path.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
        print(f"  ✅ 已写回 {path.name}（备份 {bak.name}）")
    return len(remove)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际清理并写回（默认 dry-run）")
    ap.add_argument("--threshold", type=float, default=THRESHOLD, help=f"标题相似度阈值（默认 {THRESHOLD}）")
    args = ap.parse_args()

    total = 0
    for fn in ("history.json", "latest-24h.json", "latest-24h-all.json"):
        total += process_file(ROOT / "data" / fn, args.apply, args.threshold)
    print(f"\n{'实际清理' if args.apply else 'Dry-run（未写回）'}：共 {total} 条重复待删")
    if not args.apply:
        print("确认无误后加 --apply 实际清理。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
