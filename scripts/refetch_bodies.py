#!/usr/bin/env python3
"""重新抓取被误删正文的碳交易网笔记（2026-08-11 事故恢复）。

背景：strip_recommend_list.py 误把整篇正文当"推荐列表"删掉，
39 篇碳交易网笔记正文被清空。本脚本从每篇 frontmatter 的 url 重新
抓取正文 + summary，写回 ## 正文 段（保留原 frontmatter 和标题）。

用法:
  python3.11 scripts/refetch_bodies.py [--dry-run]
"""
import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from article_content import fetch_article  # noqa: E402

TARGET_DIR = Path("Notes/媒体库/中国碳交易网")
MIN_BODY = 50


def parse_fm(txt: str) -> dict[str, str]:
    fm: dict[str, str] = {}
    if not txt.startswith("---"):
        return fm
    for line in txt.split("\n")[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm


def find_empty(files: list[Path]) -> list[Path]:
    out = []
    for fp in files:
        txt = fp.read_text(encoding="utf-8")
        idx = txt.find("## 正文")
        body = txt[idx + len("## 正文"):].strip() if idx > 0 else ""
        if len(body) < MIN_BODY:
            out.append(fp)
    return out


def refetch_one(fp: Path) -> tuple[Path, str]:
    txt = fp.read_text(encoding="utf-8")
    fm = parse_fm(txt)
    url = fm.get("url", "")
    if not url or "google" in url:
        return fp, f"skip(no url/google): {url[:50]}"
    res = fetch_article(url)
    if not res:
        return fp, "fetch failed"
    content = (res.get("content") or "").strip()
    summary = (res.get("summary") or "").strip()
    if len(content) < MIN_BODY:
        return fp, f"content too short ({len(content)})"
    # 重建文件：保留 frontmatter + 标题 + 原文链接 + 来源行，替换正文
    new_lines: list[str] = []
    in_fm = False
    fm_done = False
    for line in txt.split("\n"):
        if not fm_done:
            new_lines.append(line)
            if line.strip() == "---" and not in_fm:
                in_fm = True
                continue
            if in_fm and line.strip() == "---":
                fm_done = True
                # update summary if we have one
                if summary:
                    safe = summary.replace('"', "'").replace("\n", " ")
                    new_lines.append(f'summary: "{safe}"')
                continue
            continue
        # after frontmatter: keep until ## 正文
        if line.strip().startswith("## 正文"):
            new_lines.append("## 正文")
            new_lines.append("")
            new_lines.append(content)
            new_lines.append("")
            # skip remaining old lines
            break
        new_lines.append(line)
    fp.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    return fp, f"ok({len(content)} chars)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    files = sorted(TARGET_DIR.rglob("*.md"))
    targets = find_empty(files)
    print(f"正文为空/极短: {len(targets)} 篇")
    if args.dry_run:
        for fp in targets:
            fm = parse_fm(fp.read_text(encoding="utf-8"))
            print(f"  {fp.name[:50]} | {fm.get('url','?')[:60]}")
        return 0

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(refetch_one, fp): fp for fp in targets}
        for fut in as_completed(futs):
            fp, msg = fut.result()
            if msg.startswith("ok"):
                ok += 1
                print(f"✓ {fp.name[:45]} | {msg}")
            else:
                fail += 1
                print(f"✗ {fp.name[:45]} | {msg}")
    print(f"\n完成: 成功 {ok}, 失败 {fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
