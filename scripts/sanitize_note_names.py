#!/usr/bin/env python3
r"""笔记文件名净化（2026-09-23，P5 断链清理）。

背景：X/社交源标题被按 100 字符截断，产生两类**无法被 Obsidian 双链**的文件名：
1. 结尾/开头带空格（`...Southeast Asia to .md`）——`[[...]]` 目标会被 strip，永远对不上
2. 含 `#`（hashtag）、`[`/`]`、`|`、`^` 等 `[[ ]]` 语法字符，链接在语法层就断裂

做法：只改**文件名**，不动内容；非法字符换全角（`#`→`＃`、`[`→`【`、`]`→`】`、`|`→`｜`），
首尾空白剔除，连续空格折叠为单空格。之后由 `fix_graph_links.py` 重指正文双链。

幂等；`--dry-run` 默认。

用法：
    python scripts/sanitize_note_names.py [--apply] [--roots 素材库,数据库,政策库,媒体库]
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "Notes"
CACHE = ROOT / "cache"
REPL = {"#": "＃", "[": "【", "]": "】", "|": "｜", "^": "＾", "*": "＊",
        "?": "？", ":": "：", '"': "＂", "<": "＜", ">": "＞"}


def sanitize(stem: str) -> str:
    s = stem.strip()
    s = re.sub(r"\s+", " ", s)
    for k, v in REPL.items():
        s = s.replace(k, v)
    s = s.rstrip(" .")          # Windows 不允许结尾点/空格
    return s.strip() or "未命名"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--roots", default="素材库,数据库,政策库,媒体库")
    args = ap.parse_args()

    renames: list[tuple[Path, Path]] = []
    for r in args.roots.split(","):
        base = NOTES / r
        if not base.exists():
            continue
        for f in base.rglob("*.md"):
            new = sanitize(f.stem)
            if new != f.stem:
                renames.append((f, f.with_name(new + ".md")))

    # 冲突检查
    conflicts = [(a, b) for a, b in renames if b.exists() and b != a]
    print(f"mode={'apply' if args.apply else 'dry-run'} | 待改名 {len(renames)} 个")
    for a, b in renames[:12]:
        print(f"   {a.name[:62]}\n     → {b.name[:62]}")
    if conflicts:
        print(f"\n⚠️ 目标已存在（跳过）: {len(conflicts)}")
        for a, b in conflicts[:5]:
            print("   ", a.name[:50], '→', b.name[:50])

    done = []
    for a, b in renames:
        if b.exists() and b != a:
            continue
        if args.apply:
            a.rename(b)
        done.append([str(a.relative_to(NOTES)), str(b.relative_to(NOTES))])

    print(f"\n{'已改名' if args.apply else '将改名'} {len(done)} 个")
    if args.apply and done:
        CACHE.mkdir(exist_ok=True)
        (CACHE / "p5-rename-map.json").write_text(json.dumps(
            {"at": datetime.now(timezone.utc).isoformat(), "renames": done},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print("改名映射 → cache/p5-rename-map.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
