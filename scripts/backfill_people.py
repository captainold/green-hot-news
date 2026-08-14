#!/usr/bin/env python3
"""Backfill `people:` frontmatter for existing Obsidian notes.

2026-08-14: 人名标签上线后，为历史笔记回填 people 字段（无需重新抓取）。
扫描 Notes/政策库 + Notes/媒体库 所有笔记，从标题/summary/正文前2000字
识别 PERSON_RULES 白名单人物，写入 frontmatter people: [...]。

幂等：已有 people 字段且内容未变的笔记跳过；--force 强制重写。

用法:
    python3.11 scripts/backfill_people.py [--obsidian-dir .] [--dry-run] [--force]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_news


def parse_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Split frontmatter (raw lines dict) from body."""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    fm_text = parts[1]
    body = parts[2]
    fm: dict[str, str] = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm, body


def get_summary(fm: dict[str, str]) -> str:
    return fm.get("summary", "").strip().strip('"').strip("'")


def extract_people_from_note(path: Path) -> list[str]:
    """Read a note's title (first # heading), summary, body → extract people."""
    content = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)
    # title: prefer `# title` heading in body, fallback to filename
    m = re.search(r"^# (.+)$", body, re.M)
    title = m.group(1).strip() if m else path.stem
    summary = get_summary(fm)
    people = update_news.extract_people(title, summary, body)
    return people


def existing_people(fm: dict[str, str]) -> list[str]:
    raw = fm.get("people", "").strip()
    if not raw:
        return []
    raw = raw.strip("[]")
    return [p.strip() for p in raw.split(",") if p.strip()]


def rewrite_note(path: Path, people: list[str], force: bool) -> str:
    """Add/update people frontmatter. Returns 'new'|'updated'|'unchanged'|'skip'."""
    content = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)
    if not fm:  # no frontmatter — leave alone
        return "skip"
    old = existing_people(fm)
    if old and not force:
        return "unchanged" if set(old) == set(people) else "skip"
    if not people:
        return "skip"  # nothing to add

    people_str = ", ".join(people)
    parts = content.split("---", 2)
    fm_text = parts[1]
    # remove existing people line, then insert after summary (or keywords/author)
    lines = fm_text.split("\n")
    lines = [ln for ln in lines if not ln.strip().startswith("people:")]
    insert_after = None
    for i, ln in enumerate(lines):
        if ln.strip().startswith("summary:"):
            insert_after = i
        elif ln.strip().startswith("author:") and insert_after is None:
            insert_after = i
        elif ln.strip().startswith("keywords:") and insert_after is None:
            insert_after = i
    new_line = f"people: [{people_str}]"
    if insert_after is not None:
        lines.insert(insert_after + 1, new_line)
    else:
        # 无 summary/author/keywords：插入到 frontmatter 最后一个字段之后
        # （append 会跑到列表末尾的空元素后，导致 people 行与 --- 粘连）
        last_idx = max(i for i, ln in enumerate(lines) if ln.strip())
        lines.insert(last_idx + 1, new_line)
    # 保证 frontmatter 以换行结束，避免与 --- 粘连
    fm_body = "\n".join(lines).rstrip("\n") + "\n"
    parts[1] = fm_body
    new_content = "---".join(parts)

    # 正文头部补 `> 人物:` 双链行（在 `> 作者:` 之后，与抓取导出格式一致）
    if people:
        people_links = "、".join(f"[[人物/{p}|{p}]]" for p in people)
        person_line = f"> 人物: {people_links}"
        if person_line not in new_content:
            # 找正文头部引用块：`> 作者:` 行之后插入；没有作者行则插在 `> 首次抓取:` 后
            anchor = None
            for a in ["> 作者:", "> 首次抓取:"]:
                idx = new_content.find(a)
                if idx != -1:
                    anchor = idx + len(a)
                    # 跳到该行末尾
                    nl = new_content.find("\n", anchor)
                    anchor = nl if nl != -1 else anchor
                    break
            if anchor is not None:
                new_content = new_content[:anchor] + "\n" + person_line + new_content[anchor:]
            else:
                # 找不到引用块：插在正文标题后
                m = re.search(r"(^# .+\n)", new_content, re.M)
                if m:
                    anchor = m.end()
                    new_content = new_content[:anchor] + "\n" + person_line + new_content[anchor:]

    path.write_text(new_content, encoding="utf-8")
    return "updated"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill people frontmatter")
    parser.add_argument("--obsidian-dir", default=".", help="Project root (contains Notes/)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--force", action="store_true", help="Rewrite even if people exists")
    args = parser.parse_args()

    notes_root = Path(args.obsidian_dir) / "Notes"
    if not notes_root.exists():
        print(f"Notes dir not found: {notes_root}")
        return 1

    stats = {"new": 0, "updated": 0, "unchanged": 0, "skip": 0}
    examples: list[str] = []
    for root, dirs, files in os_walk(notes_root):
        # 跳过知识层（政策wiki 是人工策展，脚本不碰）与 .git
        if "政策wiki" in str(Path(root).relative_to(notes_root)).split(os.sep):
            dirs[:] = []
            continue
        for f in sorted(files):
            if not f.endswith(".md"):
                continue
            p = Path(root) / f
            if p.name in ("政策库.md", "媒体库.md", "ai-index.md"):
                continue
            rel = str(p.relative_to(notes_root))
            people = extract_people_from_note(p)
            if not people:
                stats["skip"] += 1
                continue
            result = rewrite_note(p, people, args.force)
            stats[result] = stats.get(result, 0) + 1
            if result == "updated" and len(examples) < 5:
                examples.append(f"{rel} → {people}")

    print(f"notes scanned: {sum(stats.values())}")
    print(f"new: {stats['new']}  updated: {stats['updated']}  unchanged: {stats['unchanged']}  skip: {stats['skip']}")
    if examples:
        print("\nsample updates:")
        for ex in examples:
            print(f"  {ex}")
    return 0


def os_walk(path: Path):
    for root, dirs, files in os.walk(str(path)):
        if ".git" in root:
            dirs[:] = []
            continue
        yield Path(root), dirs, files


if __name__ == "__main__":
    raise SystemExit(main())
