#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""修「文件名结尾带点/空格」的地雷（2026-10-04）。

背景：`export_qmd._safe_filename` 按字节截断标题，截断点正好落在空格上时会留下
**结尾空格**（实测 122 个，集中在 美国DOE/EPA/NOAA 等英文长标题源）。这种名字：
- NTFS/Win32 无法正常创建或打开（会被静默改名），git 在同目录下可能反复冲突
- `verify_graph.resolve()` 会对链接目标 `strip()` → 引用它的链接**永远解析不到**

两件事一起做（原子）：
1. 重命名：`X .md` → `X.md`（去掉 stem 首尾空格与结尾点）
2. 改写引用：全库 `[[X \|别名]]` / `[[X ]]` → 指向新名

安全闸门：目标文件不存在、同目录无大小写不敏感孪生、源文件在 Notes/ 内。
用法：python -X utf8 scripts/fix_space_names.py [--apply]
"""
from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NOTES = ROOT / "Notes"
LINK = re.compile(r"\[\[([^\]\|#]+?)(\\?\|[^\]]*)?\]\]")


def clean_stem(stem: str) -> str:
    return stem.strip().rstrip(".").strip()


def legacy_stem(title: str) -> str:
    """旧 `_safe_filename` 的口径（截断后不再去首尾空格/点）——仅用于诊断/交叉核对。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", title or "").strip()
    b = s[:80].encode("utf-8")[:200]
    return b.decode("utf-8", "ignore") or "untitled"


def _note_id(text: str) -> str:
    m = re.search(r'^id:\s*"?([^"\n]+)', text[:900], re.M)
    return m.group(1) if m else ""


def _current_files() -> dict[str, list[pathlib.Path]]:
    out: dict[str, list[pathlib.Path]] = {}
    for p in NOTES.rglob("*.md"):
        if ".obsidian" in p.parts:
            continue
        i = _note_id(p.read_text(encoding="utf-8", errors="replace"))
        if i:
            out.setdefault(i, []).append(p)
    return out


def build_legacy_map(files: list[pathlib.Path]) -> dict[str, str]:
    """旧名 → 新名。**只认真正带尾空格/点的名字**，不再用「标题≠文件名」的启发式。

    2026-10-04 教训：早先版本用 frontmatter title 反推旧名（12826 条），
    把 `机构：[[Artificial Analysis]]` 这类实体链接误改成 `[[2026-08-07 Artificial Analysis]]`。
    现在两个来源都只取「stem != clean_stem(stem)」：
    1. 磁盘上还存在的旧名文件（改名之前跑）
    2. git 索引里的旧名（改名之后跑，靠 frontmatter id 配到当前干净名）
    """
    out: dict[str, str] = {}
    cur = _current_files()
    for p in files:                       # 来源 1：磁盘旧名
        clean = clean_stem(p.stem)
        if clean and clean != p.stem:
            new = p.with_name(clean + p.suffix)
            if new.exists():
                i = _note_id(p.read_text(encoding="utf-8", errors="replace"))
                new = (cur.get(i) or [None])[0] or new
            out[p.stem] = new.stem
    # 来源 2：git 索引旧名（已改名、磁盘上已无）
    r = subprocess.run(["git", "-C", str(NOTES), "-c", "core.quotepath=false",
                        "ls-files", "-z", "--", "素材库"],
                       capture_output=True)
    for raw in r.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8")
        stem = pathlib.PurePosixPath(rel).stem
        clean = clean_stem(stem)
        if not clean or clean == stem or stem in out:
            continue
        blob = subprocess.run(["git", "-C", str(NOTES), "show", f":0:{rel}"],
                              capture_output=True)
        i = _note_id(blob.stdout.decode("utf-8", "replace"))
        cands = [q for q in cur.get(i, []) if q.stem == clean_stem(q.stem)]
        if cands:
            out[stem] = cands[0].stem
    return out


def rewrite_refs(targets: dict[str, str]) -> int:
    """把指向旧名的 wikilink 改写为新名。"""
    fixed = 0
    soft = {k.strip().rstrip("."): v for k, v in targets.items()}
    for p in NOTES.rglob("*.md"):
        if ".obsidian" in p.parts:
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        if "[[" not in t:
            continue
        orig = t

        def sub(m: re.Match) -> str:
            raw, alias = m.group(1), m.group(2) or ""
            for key in (raw, raw.rstrip("\\"), raw.rstrip("\\").strip(),
                        raw.rstrip("\\").strip().rstrip(".")):
                if key in targets and key != targets[key]:
                    return f"[[{targets[key]}{alias}]]"
                if key in soft and key != soft[key]:
                    return f"[[{soft[key]}{alias}]]"
            return m.group(0)

        t = LINK.sub(sub, t)
        if t != orig:
            p.write_text(t, encoding="utf-8")
            fixed += 1
    return fixed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--refs-only", action="store_true",
                    help="只按 frontmatter title 反推旧名并重写引用（改名已完成时补跑）")
    args = ap.parse_args()

    files = [p for p in NOTES.rglob("*.md") if ".obsidian" not in p.parts]
    if args.refs_only:
        legacy = build_legacy_map(files)
        print(f"反推旧名 {len(legacy)} 个")
        n = rewrite_refs(legacy) if args.apply else 0
        print(f"引用改写：{n} 个文件" if args.apply else "dry-run：加 --apply 执行")
        return 0

    targets: dict[str, str] = {}      # 旧 stem → 新 stem
    for p in files:
        c = clean_stem(p.stem)
        if c and c != p.stem:
            targets[p.stem] = c

    print(f"待改名 {len(targets)} 个")
    done = 0
    skipped: list[str] = []
    for old, new in sorted(targets.items()):
        srcs = [p for p in files if p.stem == old]
        for src in srcs:
            dst = src.with_name(new + src.suffix)
            if dst.exists():
                # 26 组实测都是同名 dup 双胞胎（一条直连 url + 一条 Google News url，id 不同，
                # 都不能删）→ 按 export_qmd 既有约定加 〔mat-xxxxxx〕 后缀区分
                t = src.read_text(encoding="utf-8", errors="replace")[:900]
                mid = re.search(r'^id:\s*"?mat/([0-9a-f]+)', t, re.M)
                if not mid:
                    skipped.append(f"{src.name!r}（目标已存在且无 mat id）")
                    continue
                dst = src.with_name(f"{new} 〔mat-{mid.group(1)[:6]}〕{src.suffix}")
                if dst.exists():
                    skipped.append(f"{src.name!r}（目标与孪生都已存在）")
                    continue
                new_actual = f"{new} 〔mat-{mid.group(1)[:6]}〕"
            else:
                new_actual = new
            twin = [q for q in src.parent.iterdir()
                    if q.name.casefold() == dst.name.casefold() and q.name != src.name]
            if twin:
                skipped.append(f"{src.name!r}（大小写孪生 {twin[0].name!r}）")
                continue
            print(f"  {'改名' if args.apply else '待改名'} {src.relative_to(ROOT)}"
                  f"  →  {dst.name}")
            targets[old] = new_actual
            if args.apply:
                src.rename(dst)
            done += 1

    # 引用改写（含 [[X |别名]] 里 X 末尾空格的写法）
    if args.apply and targets:
        print(f"引用改写：{rewrite_refs(targets)} 个文件")
    for s in skipped[:10]:
        print(f"  ⏭ 跳过 {s}")
    print(f"{'已改名' if args.apply else 'dry-run'}: {done} 个"
          f"{'，加 --apply 执行' if not args.apply else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
