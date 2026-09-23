"""Fix wiki links pointing into 政策库.

Two known failure modes:
1. Typo prefix `../../policy/../../政策库/` → `../../政策库/`
2. Filename truncated/washed (title used instead of sanitized filename):
   fuzzy-match against actual files under Notes/政策库 and rewrite.

Usage:
    python3.11 scripts/fix_wiki_links.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WIKI_DIR = Path("Notes/政策wiki")
BASE = Path("Notes/政策库")


def actual_files() -> dict[str, list[str]]:
    """Map rel-name (without .md) -> absolute path for all notes (政策库+媒体库)."""
    out: dict[str, list[str]] = {}
    for root in (Path("Notes/政策库"), Path("Notes/媒体库")):
        for p in root.rglob("*.md"):
            if p.name in ("政策库.md", "媒体库.md", "ai-index.md"):
                continue
            out.setdefault(p.name[:-3], []).append(str(p))
    return out


def fuzzy_find(link_part: str, files: dict[str, list[str]]) -> str | None:
    """Match a possibly-truncated/washed link name to real files.

    Returns the unique real rel-path (relative to Notes/) or None.
    """
    base_name = link_part.split("/")[-1]
    # exact
    if base_name in files:
        cands = files[base_name]
        if len(cands) == 1:
            return cands[0].replace(".md", "")
        return None
    # prefix: link name is a truncated version of the real filename
    prefix_matches = [n for n in files if n.startswith(base_name) and len(n) > len(base_name)]
    # also allow real name being a prefix of the link (extra chars in link)
    suffix_matches = [n for n in files if base_name.startswith(n)]
    # date-prefixed rename: link uses the bare title, real file is "YYYY-MM-DD title"
    # (dedup 2026-08-11 removed the bare-title duplicates)
    dated_matches = [n for n in files if re.match(r"^\d{4}-\d{2}-\d{2} ", n) and n.endswith(base_name)]
    all_m = set(prefix_matches) | set(suffix_matches) | set(dated_matches)
    if len(all_m) == 1:
        return files[next(iter(all_m))][0].replace(".md", "")
    return None


def main() -> int:
    files = actual_files()
    total_fixed = 0
    for p in sorted(WIKI_DIR.rglob("*.md")):
        content = p.read_text(encoding="utf-8")
        changed = False

        # pass 1: typo prefix
        new_content = content.replace("../../policy/../../政策库/", "../../政策库/")
        if new_content != content:
            changed = True

        # pass 2: fuzzy-fix remaining broken [[...]] links
        def repl(m: re.Match) -> str:
            nonlocal changed
            whole = m.group(0)
            inner = m.group(1)
            path_part = re.split(r"\\?\|", inner)[0]
            alias = inner[len(path_part):]  # includes |alias or \|alias
            t = p.parent / path_part
            if t.exists() or (t.parent / (t.name + ".md")).exists():
                return whole  # already fine
            # try ../../政策库/... or ../../媒体库/... relative form
            if path_part.startswith("../../政策库/"):
                rel = path_part[len("../../政策库/"):]
            elif path_part.startswith("../../媒体库/"):
                rel = path_part[len("../../媒体库/"):]
            elif path_part.startswith("政策库/"):
                rel = path_part[len("政策库/"):]
            elif path_part.startswith("媒体库/"):
                rel = path_part[len("媒体库/"):]
            else:
                return whole
            real = fuzzy_find(rel, files)
            if real is None:
                return whole
            # real 形如 "Notes/政策库/..." 或 "Notes/媒体库/..."，转成相对路径
            lib_prefix = "../../" if real.startswith("Notes/") else "../"
            rel_path = real[len("Notes/"):] if real.startswith("Notes/") else real
            fixed = f"[[{lib_prefix}{rel_path}{alias}]]"
            changed = True
            return fixed

        content2 = re.sub(r"\[\[([^\[\]]+?)\]\]", repl, new_content)
        if content2 != content:
            p.write_text(content2, encoding="utf-8")
            total_fixed += 1
            print(f"fixed: {p.name}")

    # report
    print(f"\nfiles rewritten: {total_fixed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
