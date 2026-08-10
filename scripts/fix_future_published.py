"""Fix publish times that were double-shifted +8h (naive Beijing treated as UTC).

Backstory: an earlier conversion script parsed EVERY `> 发布时间:` line with
dateutil, assumed naive = UTC, and converted to Beijing (+8h). Detail-page
times from Chinese sites (already Beijing, naive) got shifted +8h too, landing
in the FUTURE (e.g. page says 2026-08-10 17:08, stored 2026-08-11 01:08).

Detection: a publish time (as UTC) LATER than the note's first-seen (scrape)
time is impossible → it was polluted. Fix: subtract 8h.

Usage: python3.11 scripts/fix_future_published.py
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SH = timezone(timedelta(hours=8))
UTC = timezone.utc

FM_PUB_RE = re.compile(r'^published: "([^"]+)"')
BODY_PUB_RE = re.compile(r"^> 发布时间: (.+)$")
FIRST_SEEN_RE = re.compile(r"^> 首次抓取: (.+?) UTC")

def parse_dt(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None

def fix_file(p: Path) -> tuple[str, str | None]:
    lines = p.read_text(encoding="utf-8").split("\n")
    pub_val: str | None = None
    first_seen: datetime | None = None
    for line in lines:
        m = BODY_PUB_RE.match(line)
        if m:
            pub_val = m.group(1).strip()
        m2 = FIRST_SEEN_RE.match(line)
        if m2:
            fs = parse_dt(m2.group(1))
            first_seen = fs.replace(tzinfo=UTC) if fs else None
    if not pub_val or first_seen is None:
        return str(p), None
    pub_dt = parse_dt(pub_val)
    if pub_dt is None:
        return str(p), None
    # stored time is Beijing-naive; convert to UTC for comparison
    pub_utc = pub_dt.replace(tzinfo=SH).astimezone(UTC)
    if pub_utc <= first_seen:
        return str(p), None  # fine (publish before scrape)
    # polluted: shift back in 8h steps until publish <= scrape (a real publish
    # can never be later than its first scrape). Some notes were shifted twice.
    fixed_dt = pub_dt
    for _ in range(4):
        fixed_dt = fixed_dt - timedelta(hours=8)
        if fixed_dt.replace(tzinfo=SH).astimezone(UTC) <= first_seen:
            break
    fixed_str = fixed_dt.strftime("%Y-%m-%d %H:%M")
    new_lines = []
    for line in lines:
        m = BODY_PUB_RE.match(line)
        if m:
            new_lines.append(f"> 发布时间: {fixed_str}")
            continue
        m2 = FM_PUB_RE.match(line)
        if m2:
            new_lines.append(f'published: "{fixed_str}"')
            continue
        new_lines.append(line)
    p.write_text("\n".join(new_lines), encoding="utf-8")
    return str(p), fixed_str

def main() -> int:
    base = Path("Notes/政策库")
    fixed = 0
    for p in sorted(base.rglob("*.md")):
        if p.name in ("政策库.md", "ai-index.md"):
            continue
        _, new_val = fix_file(p)
        if new_val:
            fixed += 1
            print(f"  fixed {p.name[:45]:48s} → {new_val}")
    print(f"\nfixed {fixed} notes")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
