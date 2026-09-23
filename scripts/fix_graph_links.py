#!/usr/bin/env python3
r"""正文双链修复（2026-09-23，P5 断链清理）。

修什么（按优先级）：
1. **路径畸形**：`[[../碳市场/碳市场\]]` → 取末段规范化
2. **截断/粘连**：AI 互链当年按 ~100 字符截断标题，或把「标题+摘要+落款」整段塞进链接
   → 前缀唯一匹配回指（大小写不敏感兜底）
3. **同名歧义**：多个文件同前缀 → 用本文件 frontmatter `related`（已迁移为 mat id）消歧，
   命中唯一则回指，否则保留并报告
4. **伪链接**：表格数字、代码片段（`$cmd == "deploy"`）→ 标注跳过，不计入断链
5. 确实无目标 → 保留原样并报告（不静默丢弃）

用法：
    python scripts/fix_graph_links.py [--dry-run|--apply] [--roots 素材库,实体,政策wiki]
"""
from __future__ import annotations

import argparse
import bisect
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "Notes"
CACHE = ROOT / "cache"
FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(#[^\]\|]*)?(\|[^\]]*)?\]\]")
CODE_SPLIT_RE = re.compile(r"(```.*?```|`[^`\n]*`)", re.DOTALL)


def split_code(text: str) -> list[str]:
    """按「代码块/行内代码」切分，偶数下标才是正文（代码里的 [[...]] 不算链接）。"""
    return CODE_SPLIT_RE.split(text)


def fm_of(text: str) -> str:
    m = FM_RE.match(text)
    return m.group(1) if m else ""


def fm_list(fm: str, name: str) -> list[str]:
    m = re.search(rf"^{name}:\s*(\[.*?\])\s*$", fm, re.M)
    if m:
        return re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1))
    m2 = re.search(rf"^{name}:\s*\n((?:[ \t]+-[^\n]*\n?)+)", fm, re.M)
    if m2:
        return [ln.strip()[1:].strip().strip('"').strip("'") for ln in m2.group(1).splitlines() if ln.strip()]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--unlink", action="store_true",
                    help="仍无法解析的目标降级为纯文本（保留文字、消除断链），并写入审计日志")
    ap.add_argument("--roots", default="素材库,实体,政策wiki,数据库,政策库,媒体库")
    args = ap.parse_args()

    all_md = [p for p in NOTES.rglob("*.md") if ".obsidian" not in p.parts]
    name_index: set[str] = set()
    id2stem: dict[str, str] = {}
    stem_of: dict[Path, str] = {}
    for p in all_md:
        stem_of[p] = p.stem
        name_index.add(p.stem)
        name_index.add(str(p.relative_to(NOTES).with_suffix("")).replace("\\", "/"))
        name_index.add(f"{p.parent.name}/{p.stem}")
        fm = fm_of(p.read_text(encoding="utf-8", errors="replace"))
        for a in fm_list(fm, "aliases"):
            name_index.add(a)
        i = re.search(r'^id:\s*["\']?([^"\'\n]+)', fm, re.M)
        if i:
            name_index.add(i.group(1).strip())
            id2stem[i.group(1).strip()] = p.stem

    stems = sorted({p.stem for p in all_md})
    stems_lower = [s.lower() for s in stems]

    def candidates(t: str, ci: bool = False) -> list[str]:
        t = t.rstrip()
        if len(t) < 15:
            return []
        if ci:
            key = t.lower()
            i = bisect.bisect_left(stems_lower, key)
            out = []
            while i < len(stems_lower) and stems_lower[i].startswith(key):
                out.append(stems[i])
                i += 1
                if len(out) > 60:
                    break
            return out
        i = bisect.bisect_left(stems, t)
        out = []
        while i < len(stems) and stems[i].startswith(t):
            out.append(stems[i])
            i += 1
            if len(out) > 60:
                break
        return out

    def fuzzy(t: str, related_stems: set[str]) -> str | None:
        """前缀匹配：唯一命中直接用；多命中用本文件 related 消歧。"""
        for ci in (False, True):
            for cand in (t, t.rstrip(" ,.-——、，。")):
                if not cand:
                    continue
                hits = candidates(cand, ci)
                if len(hits) == 1:
                    return hits[0]
                if len(hits) > 1:
                    inter = [h for h in hits if h in related_stems]
                    if len(inter) == 1:
                        return inter[0]
        # 渐进头部匹配（标题+摘要粘连）
        for head in (30, 20, 15):
            if len(t) >= head:
                hits = candidates(t[:head])
                if len(hits) == 1:
                    return hits[0]
        return None

    def variants(t: str) -> list[str]:
        """目标变形：净化后的文件名可能已折叠连续空格 / 去掉尾部省略号。"""
        out = [t]
        for base in (t, re.sub(r"\s+", " ", t).strip()):
            if base and base not in out:
                out.append(base)
            trimmed = base.rstrip(".．…。 ")
            if trimmed and trimmed not in out:
                out.append(trimmed)
        return out

    def normalize(t: str) -> str:
        t = t.replace("\\", "/").strip().rstrip("/").strip()
        return t.rsplit("/", 1)[-1].strip() if t else ""

    def is_pseudo(t: str) -> bool:
        if re.fullmatch(r"[\d\s,.\-+%|()]+", t):
            return True
        return any(k in t for k in ("$", "==", "&&", "||", "\\n"))

    roots = [NOTES / r for r in args.roots.split(",")]
    targets: list[Path] = []
    for r in roots:
        if r.exists():
            targets += [p for p in r.rglob("*.md") if ".obsidian" not in p.parts]

    stats: Counter[str] = Counter()
    unresolved: Counter[str] = Counter()
    unlinked: Counter[str] = Counter()
    backup: dict[str, str] = {}

    for p in targets:
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = fm_of(text)
        related_stems = {id2stem[i] for i in fm_list(fm, "related") if i in id2stem}
        changed = 0

        def repl(m: re.Match) -> str:
            nonlocal changed
            raw, anchor, alias = m.group(1), m.group(2) or "", m.group(3) or ""
            t = raw.strip()
            if t in name_index:
                return m.group(0)
            if is_pseudo(t):
                stats["pseudo_skipped"] += 1
                return m.group(0)
            seg = normalize(t)
            if seg and seg != t and seg in name_index:
                changed += 1
                stats["path_fixed"] += 1
                return f"[[{seg}{anchor}{alias}]]"
            for cand in variants(seg) + variants(t):
                if not cand:
                    continue
                fz = fuzzy(cand, related_stems)
                if fz:
                    changed += 1
                    stats["trunc_fixed"] += 1
                    tail = fz[len(cand):].strip() if fz.startswith(cand) else ""
                    anchor_txt = anchor.lstrip("#").strip()
                    # 锚点其实是文件名被 # 截断的后半段（X 帖 hashtag）→ 锚点丢弃
                    if anchor and tail and anchor_txt.startswith(tail[:8]):
                        stats["anchor_dropped"] += 1
                        return f"[[{fz}]]"
                    return f"[[{fz}{anchor}{alias}]]"
            unresolved[t] += 1
            if args.unlink:
                changed += 1
                stats["unlinked"] += 1
                unlinked[t] += 1
                return (alias[1:].strip() if alias else t)
            return m.group(0)

        parts = split_code(text)
        for i in range(0, len(parts), 2):
            parts[i] = WIKILINK_RE.sub(repl, parts[i])
        new_text = "".join(parts)
        if changed:
            backup[str(p.relative_to(NOTES))] = text
            if args.apply:
                p.write_text(new_text, encoding="utf-8")

    print(f"mode={'apply' if args.apply else 'dry-run'} | 扫描文件 {len(targets)}")
    print("修复:", json.dumps(stats, ensure_ascii=False))
    print(f"仍无法解析: {sum(unresolved.values())} 处 / {len(unresolved)} 个目标")
    for t, c in unresolved.most_common(15):
        print(f"   {c:5d}  {t[:95]}")

    if args.apply and backup:
        out = CACHE / "p5-link-backup"
        out.mkdir(parents=True, exist_ok=True)
        (out / "originals.json").write_text(json.dumps(backup, ensure_ascii=False), encoding="utf-8")
        (out / "meta.json").write_text(json.dumps(
            {"at": datetime.now(timezone.utc).isoformat(), "files": len(backup),
             "stats": dict(stats), "unresolved": dict(unresolved),
             "unlinked": dict(unlinked)},
            ensure_ascii=False, indent=1), encoding="utf-8")
        if unlinked:
            (out / "unlinked.json").write_text(json.dumps(
                dict(unlinked), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"备份 {len(backup)} 个原文件 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
