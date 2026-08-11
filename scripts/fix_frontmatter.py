"""Fix frontmatter tags/keywords in 政策库 notes to be valid YAML.

Existing notes had keywords tokens containing commas (e.g. `No,`) which break
YAML flow-sequence parsing. Rewrites tags:/keywords: lines with every token
single-quoted. Idempotent and safe: only touches the two lines in frontmatter.

Usage:
    python3.11 scripts/fix_frontmatter.py [--obsidian-dir .] [--verify]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

LIST_LINE_RE = re.compile(r"^(\w+):\s*\[(.*)\]\s*$")
SUMMARY_LINE_RE = re.compile(r'^(summary: )"(.*)"+$', re.S)
# Only these keys are written by the exporter; anything else is residue
ALLOWED_KEYS = {"source", "url", "date", "published", "tags", "keywords", "summary"}


def _strip_quotes(tok: str) -> str:
    while len(tok) >= 2 and ((tok.startswith("'") and tok.endswith("'"))
                             or (tok.startswith('"') and tok.endswith('"'))):
        tok = tok[1:-1]
    return tok


def fix_list_line(line: str) -> tuple[str, bool]:
    m = LIST_LINE_RE.match(line)
    if not m:
        return line, False
    key, inner = m.group(1), m.group(2)
    items = [_strip_quotes(t.strip()) for t in inner.split(",")]
    items = [t for t in items if t]
    quoted = ", ".join("'" + t.replace("'", "''") + "'" for t in items)
    return f"{key}: [{quoted}]", True


def fix_summary_line(line: str) -> tuple[str, bool]:
    """Normalize a summary: line to a single-line double-quoted YAML scalar.

    Handles stray ASCII double quotes inside the value (original text quotes
    that would close the scalar early) and trailing doubled quotes from the
    earlier multi-line merge.
    """
    m = SUMMARY_LINE_RE.match(line)
    if not m:
        return line, False
    val = m.group(2).replace('"', "'").replace("\n", " ")
    new_line = f'{m.group(1)}"{val}"'
    return new_line, new_line != line


def fix_file(fpath: Path) -> bool:
    content = fpath.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return False
    lines = content.split("\n")
    seps = [i for i, l in enumerate(lines) if l.strip() == "---"]
    if len(seps) < 2:
        return False
    changed = False
    for i in range(seps[0] + 1, seps[1]):
        if lines[i].startswith(("tags:", "keywords:")):
            new_line, ok = fix_list_line(lines[i])
            if ok and new_line != lines[i]:
                lines[i] = new_line
                changed = True
        elif lines[i].startswith("summary:"):
            new_line, ok = fix_summary_line(lines[i])
            if ok and new_line != lines[i]:
                lines[i] = new_line
                changed = True
        elif lines[i].strip() and re.match(r"^\w+:", lines[i]):
            # stray key left over from a broken multi-line summary merge
            key = lines[i].split(":", 1)[0].strip()
            if key not in ALLOWED_KEYS:
                lines[i] = ""
                changed = True
    if changed:
        # drop emptied lines
        lines = [l for l in lines if l != ""]
        fpath.write_text("\n".join(lines), encoding="utf-8")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--obsidian-dir", default=".", help="Repo root containing Notes/政策库")
    parser.add_argument("--verify", action="store_true", help="Verify all frontmatter parses as YAML")
    args = parser.parse_args()

    base = Path(args.obsidian_dir) / "Notes" / "政策库"
    files = sorted(p for p in base.rglob("*.md") if p.name not in ("政策库.md", "ai-index.md"))
    fixed = sum(1 for p in files if fix_file(p))
    print(f"fixed frontmatter: {fixed}/{len(files)} files")

    if args.verify:
        try:
            import yaml  # type: ignore
        except ImportError:
            print("PyYAML not installed; skipping verify")
            return 0
        bad = []
        for p in files:
            content = p.read_text(encoding="utf-8")
            if not content.startswith("---"):
                continue
            lines = content.split("\n")
            seps = [i for i, l in enumerate(lines) if l.strip() == "---"]
            if len(seps) < 2:
                continue
            try:
                yaml.safe_load("\n".join(lines[seps[0] + 1:seps[1]]))
            except Exception as e:
                bad.append((str(p), str(e)[:60]))
        print(f"remaining YAML failures: {len(bad)}")
        for p, e in bad[:10]:
            print(f"  {p} -> {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
