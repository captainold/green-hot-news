#!/usr/bin/env python3
r"""素材库 md 维度命名迁移（2026-09-23）。

背景：v5.0（2026-08-26）把三层改为中性命名「政策 / 创新 / 产业」，
`scripts/migrate_dimensions.py` 只迁移了 `data/*.json`，**md frontmatter 未迁移**，
导致素材库同时存在两套命名（科技创新 456 / 绿色产业 429 / 绿色政策 339）。

映射（只改 `dimension`；`sub_dimension` 七细类已是 v5.0，不动）：
    绿色政策→政策、科技创新→创新、绿色产业→产业

幂等；`--dry-run` 默认；改动前把原 frontmatter 备份到 `cache/md-dim-backup/`。

用法：
    python scripts/migrate_md_dimensions.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SC = ROOT / "Notes" / "素材库"
CACHE = ROOT / "cache" / "md-dim-backup"
MAP = {"绿色政策": "政策", "科技创新": "创新", "绿色产业": "产业"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    changed = Counter()
    backup: dict[str, str] = {}
    for f in SC.rglob("*.md"):
        if f.name.startswith("ai-index"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'^dimension:\s*"?(.+?)"?\s*$', text, re.M)
        if not m:
            continue
        cur = m.group(1).strip()
        new = MAP.get(cur)
        if not new:
            continue
        changed[f"{cur} → {new}"] += 1
        rel = str(f.relative_to(SC))
        backup[rel] = m.group(0)
        if args.apply:
            f.write_text(text[:m.start()] + f'dimension: "{new}"' + text[m.end():],
                         encoding="utf-8")

    print(f"mode={'apply' if args.apply else 'dry-run'} | 待迁移 {sum(changed.values())} 个")
    for k, v in changed.most_common():
        print(f"  {v:6d}  {k}")
    if args.apply and backup:
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / "frontmatter-lines.json").write_text(
            json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8")
        (CACHE / "meta.json").write_text(json.dumps(
            {"at": datetime.now(timezone.utc).isoformat(), "files": len(backup),
             "mapping": MAP, "counts": dict(changed)}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"备份 {len(backup)} 行原值 → {CACHE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
