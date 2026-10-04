#!/usr/bin/env python3
r"""退役三库改名 → 素材库双链修复（2026-10-04 切库配套，P5 收尾）。

问题：退役三库（数据库/政策库/媒体库）→ 素材库 的迁移会按 url 去重。同一条素材若
在素材库已存在但**文件名不同**（文件名净化去掉了 `_:`、发布日期口径由 `date` 换成
`published_at` 等），旧库文件就不迁移、直接归档；此时 wiki/实体页里指向**旧文件名**的
`[[双链]]` 就成了断链（本次 13 处）。

做法：以 url 为桥，把「旧库文件名 → 素材库里同 url 的文件名」建成重命名映射，
再扫全库改写指向旧名的双链（保留 `|别名` 与 `#标题`）。

用法：
    python -X utf8 scripts/fix_retired_lib_links.py                 # dry-run（默认）
    python -X utf8 scripts/fix_retired_lib_links.py --apply
    python -X utf8 scripts/fix_retired_lib_links.py --legacy-dirs cache/retired-libs-2026-10-04
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "Notes"
SC = NOTES / "素材库"
WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(#[^\]\|]*)?(\|[^\]]*)?\]\]")
URL_RE = re.compile(r'^url:\s*"?([^"\n]+)"?\s*$', re.M)
CODE_SPLIT_RE = re.compile(r"(```.*?```|`[^`\n]*`)", re.DOTALL)


def rename_map(legacy_dirs: list[Path]) -> dict[str, str]:
    """旧库文件名（不含扩展名）→ 素材库文件名（不含扩展名，同 url 且名字不同）。

    双链目标不写 `.md`，故映射两侧都用 stem。

    守卫：旧名若**当前库内已存在同名页**（如 P4 政策实体页 `实体/政策/<政策全名>`），
    说明该链接已有合法落点，**不改写**——改写会把入链从实体页抢到素材笔记上（本次实测
    造成 2 个实体页变孤立节点）。
    """
    idx = json.loads((ROOT / "cache" / "mat-index.json").read_text(encoding="utf-8"))
    url2stem = {v["url"]: Path(v["path"]).stem for v in idx.values() if v.get("url")}
    sc_stems = {p.stem for p in SC.rglob("*.md")}
    vault_stems = {p.stem for p in NOTES.rglob("*.md")}   # 退役库已移出 Notes，此处即当前库
    out: dict[str, str] = {}
    stolen_guard: list[str] = []
    for base in legacy_dirs:
        if not base.exists():
            continue
        for f in base.rglob("*.md"):
            if f.stem in sc_stems or f.name.startswith("ai-index"):
                continue
            if f.stem in vault_stems:
                stolen_guard.append(f.stem)
                continue
            m = URL_RE.search(f.read_text(encoding="utf-8", errors="replace"))
            if not m:
                continue
            new = url2stem.get(m.group(1).strip())
            if new and new != f.stem:
                out[f.stem] = new
    if stolen_guard:
        print(f"（守卫跳过：旧名在当前库已有同名页 {len(stolen_guard)} 个，如 {stolen_guard[:2]}）")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="写盘（默认 dry-run）")
    ap.add_argument("--legacy-dirs", default="", help="逗号分隔的退役库目录（默认自动找 cache/retired-libs-*）")
    ap.add_argument("--roots", default="素材库,实体,政策wiki")
    args = ap.parse_args()

    if args.legacy_dirs:
        dirs = [Path(p) for p in args.legacy_dirs.split(",") if p.strip()]
    else:
        dirs = sorted((ROOT / "cache").glob("retired-libs-*"))
    rmap = rename_map(dirs)
    print(f"退役库目录: {[d.name for d in dirs]}｜重命名映射 {len(rmap)} 条")
    if not rmap:
        return 0

    changed = 0
    hits: Counter[str] = Counter()
    for root in [r.strip() for r in args.roots.split(",") if r.strip()]:
        for f in (NOTES / root).rglob("*.md"):
            text = f.read_text(encoding="utf-8", errors="replace")
            if "[[" not in text:
                continue
            parts = CODE_SPLIT_RE.split(text)
            touched = False
            for i in range(0, len(parts), 2):  # 偶数下标 = 正文（跳过代码）
                def repl(m: re.Match[str]) -> str:
                    nonlocal touched
                    tgt = m.group(1).strip()
                    if tgt in rmap:
                        touched = True
                        hits[f"{tgt} → {rmap[tgt]}"] += 1
                        return f"[[{rmap[tgt]}{m.group(2) or ''}{m.group(3) or ''}]]"
                    return m.group(0)
                parts[i] = WIKILINK_RE.sub(repl, parts[i])
            if touched:
                changed += 1
                if args.apply:
                    f.write_text("".join(parts), encoding="utf-8")
                print(f"  {'改写' if args.apply else '待改写'} {f.relative_to(ROOT)}")
    print(f"\n模式: {'APPLY' if args.apply else 'DRY-RUN'}｜涉及文件 {changed} 个｜链接 {sum(hits.values())} 处")
    for k, v in hits.most_common(20):
        print(f"  {v}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
