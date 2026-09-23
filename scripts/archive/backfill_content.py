"""Backfill existing 政策库 notes with fetched article body + summary.

Idempotent: skips notes that already carry a `summary` frontmatter field.
Degrades gracefully: notes whose URL fails (404 / timeout / WAF / Google-News
redirect) stay as link-only cards and are reported in the stats.

Usage:
    python3.11 scripts/backfill_content.py --obsidian-dir . [--workers 6]
"""

from __future__ import annotations

import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from article_content import fetch_article  # noqa: E402

SKIP_FILES = {"政策库.md", "ai-index.md"}
SUMMARY_RE = re.compile(r"^summary:\s*")


def parse_frontmatter(content: str) -> dict[str, str]:
    fm: dict[str, str] = {}
    if not content.startswith("---"):
        return fm
    lines = content.split("\n")
    in_fm = False
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm


def inject_summary(content: str, summary: str) -> str:
    """Insert `summary:` line right after the keywords line in frontmatter."""
    safe = summary.replace('"', "'").replace("\n", " ")
    lines = content.split("\n")
    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.startswith("keywords:"):
            out.append(f'summary: "{safe}"')
            inserted = True
    if not inserted:  # no keywords line (shouldn't happen) — append to fm end
        for i, line in enumerate(out):
            if line.strip() == "---" and i > 0:
                out.insert(i, f'summary: "{safe}"')
                break
    return "\n".join(out)


def inject_published(content: str, published: str) -> str:
    """Add/refresh published: frontmatter + `> 发布时间:` body line."""
    if not published:
        return content
    safe = published.replace('"', "'")
    lines = content.split("\n")
    out: list[str] = []
    fm_pub_done = False
    body_pub_done = False
    for line in lines:
        if line.startswith("published:"):
            if not fm_pub_done:
                out.append(f'published: "{safe}"')
                fm_pub_done = True
            continue  # drop old value
        if line.startswith("date:") and not fm_pub_done:
            out.append(line)
            out.append(f'published: "{safe}"')
            fm_pub_done = True
            continue
        if line.startswith("> 发布时间:"):
            out.append(f"> 发布时间: {published}")
            body_pub_done = True
            continue
        if line.startswith("> 来源:") and not body_pub_done:
            out.append(line)
            out.append(f"> 发布时间: {published}")
            body_pub_done = True
            continue
        out.append(line)
    if not body_pub_done:
        out.append(f"> 发布时间: {published}")
    return "\n".join(out)


def append_body(content: str, body: str) -> str:
    if "\n## 正文" in content:
        return content
    return content.rstrip() + f"\n\n## 正文\n\n{body}\n"


def backfill_one(fpath: Path, workers: int = 0) -> tuple[str, str]:
    """Returns (fpath, status) where status in ok|pub|fail|skip|google."""
    try:
        content = fpath.read_text(encoding="utf-8")
    except Exception:
        return str(fpath), "unreadable"
    fm = parse_frontmatter(content)
    url = fm.get("url", "").strip()
    if not url:
        return str(fpath), "skip"
    if url.startswith(("https://news.google.com", "http://news.google.com")):
        return str(fpath), "google"
    has_summary = bool(fm.get("summary"))
    has_published = bool(fm.get("published"))
    if has_summary and has_published:
        return str(fpath), "skip"
    res = fetch_article(url)
    if not res:
        return str(fpath), "fail"
    summary = res.get("summary") or ""
    body = res.get("content") or ""
    published = res.get("published") or ""

    if has_summary:
        # body already archived — only refresh publish time
        if published and not has_published:
            new_content = inject_published(content, published)
            fpath.write_text(new_content, encoding="utf-8")
            return str(fpath), "pub"
        return str(fpath), "skip"
    if not summary or not body:
        return str(fpath), "fail"
    new_content = append_body(
        inject_summary(inject_published(content, published), summary), body)
    fpath.write_text(new_content, encoding="utf-8")
    return str(fpath), "ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill 政策库 notes with article bodies")
    parser.add_argument("--obsidian-dir", default=".", help="Repo root containing Notes/政策库")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--limit", type=int, default=0, help="Only backfill first N notes (testing)")
    args = parser.parse_args()

    base = Path(args.obsidian_dir) / "Notes" / "政策库"
    if not base.exists():
        print(f"✗ Not found: {base}")
        return 1

    targets: list[Path] = []
    for p in sorted(base.rglob("*.md")):
        if p.name in SKIP_FILES:
            continue
        targets.append(p)
    if args.limit:
        targets = targets[: args.limit]
    print(f"Scanning {len(targets)} notes under {base}")

    stats = {"ok": 0, "pub": 0, "fail": 0, "skip": 0, "google": 0, "unreadable": 0}
    fails: list[str] = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = [ex.submit(backfill_one, p) for p in targets]
        for fut in as_completed(futures):
            fpath, status = fut.result()
            stats[status] = stats.get(status, 0) + 1
            if status == "fail":
                fails.append(fpath)
            done += 1
            if done % 50 == 0:
                print(f"  ... {done}/{len(targets)}")

    print(f"\nDone: {done} notes")
    print(f"  ok        {stats['ok']}   (正文+摘要+发布时间已写入)")
    print(f"  pub       {stats['pub']}   (仅补发布时间)")
    print(f"  skip      {stats['skip']}   (已有 summary+published)")
    print(f"  google    {stats['google']}   (Google News 跳转链接，跳过)")
    print(f"  fail      {stats['fail']}   (404/超时/反爬，保持链接卡片)")
    if fails:
        print("\nFailed URLs (可重试):")
        for f in fails[:20]:
            print(f"  - {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
