#!/usr/bin/env python3
"""素材库同 url 去重（2026-09-23，知识图谱重构 P2 遗留①）。

背景：素材库 12297 个 .md 中存在 564 组同 url 重复（可移除 1644 个），
来源：历史多次导出窗口差异 + 早期工具以 "[dup2]" 后缀改名而非删除。

策略（安全优先）：
1. 按 frontmatter url 分组；组内保留"最优"文件（正文更长 > 有关联实体段 > 标题更长 > mtime 新）
2. 其余**移入备份目录** cache/dedup-backup-<date>/（保留相对路径，零丢失）
3. 断链补丁：把其余文件正文里的 [[被删名]] / [[被删名|别名]] / [[被删名#锚]] 改指向保留文件
4. 输出 manifest JSON（每组决策 + 断链补丁计数）

用法：
    python scripts/dedup_material.py --dry-run   # 只统计不动文件
    python scripts/dedup_material.py --apply     # 执行
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SC = ROOT / "Notes" / "素材库"
CACHE = ROOT / "cache"
WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(#[^\]\|]*)?(\|[^\]]*)?\]\]")


def fm_field(text: str, field: str) -> str:
    m = re.search(rf"^{field}:\s*(.*)$", text, re.M)
    return m.group(1).strip() if m else ""


def score_file(fp: Path, text: str) -> tuple:
    """越大越好。优先正文完整，其次避开历史遗留的 [dupN] 命名。"""
    body_m = re.search(r"^##\s*正文\s*$", text, re.M)
    body_len = 0
    if body_m:
        body_text = text[body_m.end():]
        body_len = min(len(body_text.strip()), 50000)
    has_entities = 1 if "关联实体" in text else 0
    has_related = 1 if "相关条目" in text else 0
    title_m = re.search(r"^#\s+(.+)$", text, re.M)
    title_len = len(title_m.group(1)) if title_m else 0
    clean_name = 0 if re.search(r"\[dup\d*\]", fp.name) else 1
    return (body_len, has_entities, has_related, clean_name, title_len, fp.stat().st_mtime)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际执行（默认 dry-run）")
    args = ap.parse_args()

    by_url: dict[str, list[Path]] = defaultdict(list)
    for f in SC.rglob("*.md"):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        url = fm_field(text, "url").strip('"')
        if url:
            by_url[url].append(f)

    groups = {u: fs for u, fs in by_url.items() if len(fs) > 1}
    total_removable = sum(len(fs) - 1 for fs in groups.values())
    print(f"dry-run={not args.apply} | 重复组: {len(groups)} | 可移除: {total_removable}")
    if not groups:
        return 0

    backup_dir = CACHE / f"dedup-backup-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    manifest = {"generated_at": datetime.now(timezone.utc).isoformat(), "mode": "apply" if args.apply else "dry-run",
                "groups": len(groups), "removed": 0, "link_patches": 0, "decisions": []}

    # 先收集全部决策
    decisions = []  # (url, keep, [dups])
    for url, files in sorted(groups.items()):
        scored = sorted(((score_file(f, f.read_text(encoding="utf-8", errors="replace")), f) for f in files),
                        key=lambda t: t[0], reverse=True)
        keep = scored[0][1]
        dups = [f for _, f in scored[1:]]
        decisions.append((url, keep, dups))

    # 被删名 → 保留名 映射（用于断链补丁）
    name_map: dict[str, str] = {}
    for url, keep, dups in decisions:
        for d in dups:
            name_map[d.stem] = keep.stem

    if args.apply:
        backup_dir.mkdir(parents=True, exist_ok=True)
        # 1) 移走重复文件
        for url, keep, dups in decisions:
            for d in dups:
                dest = backup_dir / d.relative_to(SC)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(d), str(dest))
                manifest["removed"] += 1
        # 2) 断链补丁：全库扫描 [[被删名...]] → [[保留名...]]
        deleted_stems = set(name_map)
        for f in SC.rglob("*.md"):
            text = f.read_text(encoding="utf-8", errors="replace")
            changed = 0

            def repl(m: re.Match) -> str:
                nonlocal changed
                stem, anchor, alias = m.group(1), m.group(2) or "", m.group(3) or ""
                if stem in deleted_stems:
                    changed += 1
                    return f"[[{name_map[stem]}{anchor}{alias}]]"
                return m.group(0)

            new_text = WIKILINK_RE.sub(repl, text)
            if changed:
                f.write_text(new_text, encoding="utf-8")
                manifest["link_patches"] += changed
        manifest["decisions"] = [
            {"url": u, "keep": str(k.relative_to(SC)), "removed": [str(d.relative_to(SC)) for d in ds]}
            for u, k, ds in decisions]
        out = CACHE / "dedup-manifest.json"
        out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"已移除 {manifest['removed']} 个（备份于 {backup_dir.name}），断链补丁 {manifest['link_patches']} 处")
        print(f"manifest: {out}")
    else:
        for url, keep, dups in decisions[:5]:
            print(f"  [样本] keep={keep.name[:50]} <- 删 {len(dups)} 个")
        print("  …（--apply 执行）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
