# -*- coding: utf-8 -*-
"""P2 三库合并迁移：政策库 + 媒体库 + 数据库 → 素材库/（统一 qmd）。

流程：
1. 构建 source → (type, rel_dir) 映射（政策库=政策，媒体库=媒体）
2. 收集数据库 qmd 的 url 集合（去重用）
3. backfill 素材层「独有」条目（url 不在数据库的）→ 素材库/政策|媒体/（补多维标签）
4. 拷贝数据库 qmd（url 与素材层重复的，用数据库版，天然去重）→ 素材库/ 对应子目录
5. 拷贝数据库 attachments/ → 素材库/attachments/（图片路径按目录深度修正）

用法：
    # dry-run（只统计，不写文件）
    python scripts/merge_libraries.py --dry-run
    # 实际执行
    python scripts/merge_libraries.py

安全性：原 政策库/媒体库/数据库 目录不动，仅新增 素材库/；验证无误后由人工删除原目录。
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from backfill_ontology import (  # noqa: E402
    backfill, build_site_id_map, to_qmd,
)

NOTES = ROOT / "Notes"
OUT = NOTES / "素材库"


def read_field(path: Path, key: str) -> str:
    """读 md/qmd 的 frontmatter 字段值（去引号）。"""
    t = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
    if not m:
        return ""
    mm = re.search(rf'^{key}:\s*"?([^"\n]*)"?', m.group(1), re.M)
    return (mm.group(1).strip() if mm else "")


def build_source_dir_map() -> dict[str, tuple[str, str]]:
    """source → (type, rel_dir)。政策库=政策（按 国家/机构），媒体库=媒体（按 媒体源）。"""
    mapping: dict[str, tuple[str, str]] = {}
    for base, typ in [("政策库", "政策"), ("媒体库", "媒体")]:
        base_dir = NOTES / base
        if not base_dir.exists():
            continue
        for p in base_dir.rglob("*.md"):
            if not p.is_file() or "_files" in str(p) or "attachments" in str(p):
                continue
            if p.name in ("ai-index.md", "政策库.md", "媒体库.md"):
                continue
            src = read_field(p, "source")
            if src:
                rel = str(p.parent.relative_to(base_dir))
                mapping[src] = (typ, rel)
    return mapping


def collect_db_urls() -> set[str]:
    urls: set[str] = set()
    db_dir = NOTES / "数据库"
    if not db_dir.exists():
        return urls
    for p in db_dir.rglob("*.md"):
        if p.is_file() and "_files" not in str(p):
            u = read_field(p, "url")
            if u:
                urls.add(u)
    return urls


def fix_image_paths(text: str, rel_full: str) -> str:
    """修正 qmd 正文 attachments/xxx → (../)*attachments/xxx（按目录深度）。"""
    depth = rel_full.count("/") + 1
    prefix = "../" * depth
    return text.replace("attachments/", prefix + "attachments/")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只统计，不写文件")
    args = ap.parse_args()

    source_map = build_source_dir_map()
    db_urls = collect_db_urls()
    site_id_map = build_site_id_map()
    print(f"[info] source 映射 {len(source_map)} 源 | 数据库 url {len(db_urls)} 个 | site_id 映射 {len(site_id_map)} 源")

    # 统计
    stats = {"backfill": 0, "dup_skip": 0, "db_copy": 0, "db_fallback": 0}

    # ── 1. 拷贝数据库 qmd（优先：数据库版 21 字段更完整，天然去重）──
    db_dir = NOTES / "数据库"
    planned_paths: set[Path] = set()
    if db_dir.exists():
        for p in db_dir.rglob("*.md"):
            if not p.is_file() or "_files" in str(p):
                continue
            src = read_field(p, "site") or read_field(p, "site_name")
            typ, rel = source_map.get(src, (None, None))
            if typ is None:
                typ, rel = "其他", src or "unknown"
                stats["db_fallback"] += 1
            rel_full = f"{typ}/{rel}"
            out_path = OUT / rel_full / p.name
            planned_paths.add(out_path)
            stats["db_copy"] += 1
            if not args.dry_run:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                text = p.read_text(encoding="utf-8", errors="replace")
                if "attachments/" in text:
                    text = fix_image_paths(text, rel_full)
                out_path.write_text(text, encoding="utf-8")

    # ── 2. backfill 素材层独有（遇与数据库同名 → 加 [dupN] 后缀，避免覆盖丢内容）──
    for base, typ in [("政策库", "政策"), ("媒体库", "媒体")]:
        base_dir = NOTES / base
        library = "policy" if typ == "政策" else "media"
        for p in base_dir.rglob("*.md"):
            if not p.is_file() or "_files" in str(p) or "attachments" in str(p):
                continue
            if p.name in ("ai-index.md", "政策库.md", "媒体库.md"):
                continue
            url = read_field(p, "url")
            if url and url in db_urls:
                stats["dup_skip"] += 1
                continue
            # 素材层独有 → backfill
            item = backfill(p, site_id_map, library)
            if item is None:
                continue
            rel = str(p.parent.relative_to(base_dir))
            out_path = OUT / typ / rel / (p.stem + ".md")
            # 覆盖保护：与数据库 qmd 同名 → 加 [dupN] 后缀
            if out_path in planned_paths:
                n = 2
                while (OUT / typ / rel / f"{p.stem} [dup{n}].md") in planned_paths:
                    n += 1
                out_path = OUT / typ / rel / f"{p.stem} [dup{n}].md"
            planned_paths.add(out_path)
            stats["backfill"] += 1
            if not args.dry_run:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(to_qmd(item), encoding="utf-8")

    # ── 3. 拷贝 attachments ──
    att_src = db_dir / "attachments"
    if att_src.exists():
        stats["attachments"] = sum(1 for _ in att_src.iterdir() if _.is_file())
        if not args.dry_run:
            att_dst = OUT / "attachments"
            att_dst.mkdir(parents=True, exist_ok=True)
            for f in att_src.iterdir():
                if f.is_file():
                    shutil.copy2(f, att_dst / f.name)

    # ── 报告 ──
    total = stats["backfill"] + stats["db_copy"]
    print(f"\n[统计]")
    print(f"  素材层独有 backfill: {stats['backfill']} 条")
    print(f"  素材层重复跳过(用数据库版): {stats['dup_skip']} 条")
    print(f"  数据库 qmd 拷贝: {stats['db_copy']} 条（fallback 到其他/: {stats['db_fallback']}）")
    print(f"  attachments 文件: {stats.get('attachments', 0)} 个")
    print(f"  合并后素材库总 qmd: {total} 条")
    if args.dry_run:
        print("\n[dry-run] 未写任何文件。确认数字无误后去掉 --dry-run 执行。")


if __name__ == "__main__":
    main()
