#!/usr/bin/env python3
"""知识图谱校验（2026-09-23，P5 / 规范 §六）。

检查项：
1. **断链**：`[[目标]]` 是否可解析（可解析集合 = 全库 .md stem ∪ frontmatter aliases ∪ id）
2. **related 规范**：素材库 related 必须是 `mat/<12位>` 形式且能在库内解析（P3 迁移后）
3. **id 完整性/唯一性**：素材库 + 实体 + wiki 是否都有 id；id 是否有重复
4. **孤立节点**：实体页/wiki 主题页的入链数（0 入链 = 孤立，图谱里看不见）

用法：
    python scripts/verify_graph.py [--quiet]
退出码：0 = 无断链且 id 无重复；1 = 有问题
"""
from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "Notes"
SC = NOTES / "素材库"
FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]")
CODE_SPLIT_RE = re.compile(r"(```.*?```|`[^`\n]*`)", re.DOTALL)


def body_links(text: str) -> list[str]:
    """正文里的 [[...]] 目标（跳过代码块与行内代码）。"""
    out: list[str] = []
    parts = CODE_SPLIT_RE.split(text)
    for i in range(0, len(parts), 2):
        out += WIKILINK_RE.findall(parts[i])
    return out


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


def fm_scalar(fm: str, name: str) -> str:
    m = re.search(rf'^{name}:\s*["\']?([^"\'\n]+)', fm, re.M)
    return m.group(1).strip() if m else ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    all_md = [p for p in NOTES.rglob("*.md") if ".obsidian" not in p.parts]
    name_index: dict[str, set[str]] = defaultdict(set)   # 链接名 → 命中笔记 key
    id_owner: dict[str, list[str]] = defaultdict(list)

    def idx(name: str, key: str) -> None:
        if name:
            name_index[name].add(key)

    for p in all_md:
        key = str(p.relative_to(NOTES).with_suffix(""))
        idx(p.stem, key)                                   # 仅文件名
        idx(key.replace("\\", "/"), key)                   # 相对路径
        idx(f"{p.parent.name}/{p.stem}", key)              # 父目录/文件名
        try:
            fm = fm_of(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for a in fm_list(fm, "aliases"):
            idx(a, key)
        i = fm_scalar(fm, "id")
        if i:
            idx(i, key)
            id_owner[i].append(key)

    dup_ids = {k: v for k, v in id_owner.items() if len(v) > 1}
    resolvable = set(name_index)

    # 扫描链接
    broken: Counter[str] = Counter()
    broken_by_file: dict[str, list[str]] = defaultdict(list)
    inbound: Counter[str] = Counter()
    sc_no_id = 0
    sc_total = 0
    rel_bad: list[tuple[str, str]] = []
    rel_no_field = 0
    id_set = set(id_owner)

    def resolve(t: str) -> set[str]:
        """按 Obsidian 语义解析链接目标：原样 / 去反斜杠 / 末段（文件名）。"""
        t = t.strip().replace("\\", "/")
        hits = name_index.get(t)
        if hits:
            return hits
        if "/" in t:
            hits = name_index.get(t.rsplit("/", 1)[-1])
            if hits:
                return hits
        return set()

    for p in all_md:
        rel = str(p.relative_to(NOTES))
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = fm_of(text)
        for t in body_links(text):
            hits = resolve(t)
            if hits:
                for k in hits:
                    inbound[k] += 1
            else:
                broken[t.strip()] += 1
                if len(broken_by_file[rel]) < 5:
                    broken_by_file[rel].append(t.strip())
        if p.parent == SC or SC in p.parents:
            sc_total += 1
            if not fm_scalar(fm, "id"):
                sc_no_id += 1
            rels = fm_list(fm, "related")
            if not rels:
                rel_no_field += 1
            for r in rels:
                if not r.startswith("mat/") or r not in id_set:
                    rel_bad.append((rel, r))

    total_broken = sum(broken.values())
    # 伪链接：表格数字、Markdown 示例标签、代码片段——本身不是笔记链接
    PSEUDO = re.compile(r"^[\d\s,.\-+%|()]+$")

    def is_pseudo(t: str) -> bool:
        if PSEUDO.match(t):
            return True
        if any(k in t for k in ("$", "==", "&&", "||", "\\n")):
            return True
        return t in {"Blog", "Paper", "Model card", "Colab example", "GitHub", "Demo"}

    pseudo = Counter({t: c for t, c in broken.items() if is_pseudo(t)})
    real = Counter({t: c for t, c in broken.items() if t not in pseudo})
    total_real = sum(real.values())
    print(f"扫描 {len(all_md)} 个 md | 可解析名 {len(resolvable)} 个")
    print(f"断链: {total_real} 处 / 去重目标 {len(real)} 个 "
          f"（另有伪链接 {sum(pseudo.values())} 处：表格数字/示例标签/代码）")
    print(f"id 重复: {len(dup_ids)} 个")
    print(f"素材库: {sc_total} 个 | 缺 id: {sc_no_id} | related 非 mat-id: {len(rel_bad)} | 无 related 字段: {rel_no_field}")

    if real:
        print("\n未解析目标（全部）：")
        for t, c in real.most_common(30):
            print(f"   {c:5d}  {t}")
    if pseudo:
        print("\n伪链接样本：")
        for t, c in pseudo.most_common(6):
            print(f"   {c:5d}  {t[:70]}")
    if dup_ids:
        print("\nid 重复：")
        for k, v in list(dup_ids.items())[:5]:
            print(f"   {k}: {v}")
    if rel_bad:
        print("\nrelated 非法样本：")
        for rel, r in rel_bad[:5]:
            print(f"   {rel} -> {r}")

    # 孤立节点（实体页 + wiki 主题页 0 入链）
    orphans = []
    for p in list((NOTES / "实体").rglob("*.md")) + list((NOTES / "政策wiki").rglob("*.md")):
        key = str(p.relative_to(NOTES).with_suffix(""))
        if inbound.get(key, 0) == 0:
            orphans.append(key)
    print(f"\n孤立节点（0 入链）: {len(orphans)}")
    for o in orphans[:15]:
        print("   ", o)

    return 1 if (total_real or dup_ids or rel_bad or sc_no_id) else 0


if __name__ == "__main__":
    raise SystemExit(main())
