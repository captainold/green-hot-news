# -*- coding: utf-8 -*-
"""P3 关系图谱内联：给素材库 qmd 生成「关联实体」段（[[实体]] 双链）。

让每个素材条目通过双链连到实体页（机构/媒体源 + 地区 + 主题 + 技术），
Obsidian 图谱视图才能看到「实体节点(hub) + 素材节点 + 边」的网络。

映射：
- site → 机构/媒体源实体（77 个）
- region → 地区实体（6 个）
- topics → 主题/技术实体（缺失的映射：节能降碳→工业绿色转型）
- enabling_tech → 技术实体（AI→tec/AI；能源→新能源；环境→环境保护）

用法：
    python scripts/link_entities.py --dry-run   # 只统计
    python scripts/link_entities.py --limit 100 # 小批
    python scripts/link_entities.py             # 全量
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "Notes"

# 手动补充映射（字段值 → 实体标题），缺失实体用
MANUAL_MAP = {
    "能源": "新能源",        # enabling_tech 能源 → top/新能源
    "环境": "环境保护",      # enabling_tech 环境 → top/环境保护
    "节能降碳": "工业绿色转型",  # topics 节能降碳 → top/工业绿色转型
}


def parse_fm(text: str) -> str:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    return m.group(1) if m else ""


def build_entity_map() -> dict[str, str]:
    """构建 值(name/aliases) → 实体标题 映射（机构/技术/地区 + wiki 主题）。"""
    mapping: dict[str, str] = {}
    # 机构/技术/地区实体页
    for d in ["机构", "技术", "地区"]:
        for p in (NOTES / "实体" / d).rglob("*.md"):
            fm = parse_fm(p.read_text(encoding="utf-8", errors="replace"))
            name = re.search(r'^name:\s*"([^"]*)"', fm, re.M)
            ali = re.search(r'^aliases:\s*\[(.*)\]', fm, re.M)
            vals = [p.stem]
            if name:
                vals.append(name.group(1))
            if ali:
                vals += [x.strip().strip('"') for x in ali.group(1).split(",") if x.strip()]
            for v in vals:
                if v:
                    mapping.setdefault(v, p.stem)
    # wiki 主题实体（top/*）
    for p in (NOTES / "政策wiki").rglob("*.md"):
        fm = parse_fm(p.read_text(encoding="utf-8", errors="replace"))
        if re.search(r'^type:\s*"top"', fm, re.M):
            ali = re.search(r'^aliases:\s*\[(.*)\]', fm, re.M)
            vals = [p.stem]
            if ali:
                vals += [x.strip().strip('"') for x in ali.group(1).split(",") if x.strip()]
            for v in vals:
                if v:
                    mapping.setdefault(v, p.stem)
    mapping.update(MANUAL_MAP)
    return mapping


def gen_entity_links(fm: str, mapping: dict) -> list[str]:
    """从 qmd frontmatter 提取 site/region/topics/enabling_tech，映射为实体标题。"""
    links: list[str] = []

    def field(key: str) -> str:
        m = re.search(rf'^{key}:\s*"([^"]*)"', fm, re.M)
        return m.group(1) if m else ""

    def list_field(key: str) -> list[str]:
        m = re.search(rf'^{key}:\s*\[(.*)\]', fm, re.M)
        if not m or not m.group(1).strip():
            return []
        return [x.strip().strip('"') for x in m.group(1).split(",") if x.strip()]

    site = field("site")
    if site in mapping:
        links.append(f"机构：[[{mapping[site]}]]")

    region = field("region")
    if region in mapping:
        links.append(f"地区：[[{mapping[region]}]]")

    for t in list_field("topics"):
        if t in mapping:
            links.append(f"主题：[[{mapping[t]}]]")

    for e in list_field("enabling_tech"):
        if e in mapping:
            links.append(f"技术：[[{mapping[e]}]]")

    # 去重（保序）
    seen = set()
    out = []
    for l in links:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    mapping = build_entity_map()
    print(f"[info] 实体映射 {len(mapping)} 个值")

    qmds = [p for p in (NOTES / "素材库").rglob("*.md") if p.is_file()]
    if args.limit:
        qmds = qmds[:args.limit]

    updated = 0
    skipped_has = 0
    no_links = 0
    link_stat = {"机构": 0, "地区": 0, "主题": 0, "技术": 0}

    for p in qmds:
        text = p.read_text(encoding="utf-8", errors="replace")
        if "## 关联实体" in text:
            skipped_has += 1
            continue
        fm = parse_fm(text)
        if not fm:
            continue
        links = gen_entity_links(fm, mapping)
        if not links:
            no_links += 1
            continue
        for l in links:
            link_stat[l.split("：")[0]] += 1
        # 追加"关联实体"段
        block = "\n## 关联实体\n\n" + "\n".join(f"- {l}" for l in links) + "\n"
        updated += 1
        if not args.dry_run:
            p.write_text(text.rstrip() + "\n\n" + block, encoding="utf-8")

    print(f"\n[统计]")
    print(f"  处理 qmd: {len(qmds)}")
    print(f"  生成关联实体段: {updated}")
    print(f"  已有跳过: {skipped_has}")
    print(f"  无实体可关联: {no_links}")
    print(f"  链接类型分布: {link_stat}")
    if args.dry_run:
        print("\n[dry-run] 未写文件。")


if __name__ == "__main__":
    main()
