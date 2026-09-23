#!/usr/bin/env python3
"""为已有笔记回填 author（来源单位）字段。

背景（2026-08-11）：原文网页常带"来源：产业司/中国证券报/深圳晚报"等
发文单位信息，之前没抓取。article_content.fetch_article 现在返回
source_org。本脚本扫描笔记，对缺少 author 的重新抓取 URL 提取来源单位，
写入 frontmatter（author:）和正文元信息行（> 作者:）。

只处理 source 为发改委/工信部/生态环境部/中国能源报/中国碳交易网 的笔记
（这些站有来源元信息）；跳过 Google News 链接和无正文的链接卡。
"""
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from article_content import fetch_article  # noqa: E402

NOTES_ROOT = Path("Notes")
SKIP = {"政策库.md", "媒体库.md", "ai-index.md"}
# 这些源详情页带"来源"元信息
ORG_SOURCES = {"国家发改委", "工信部", "生态环境部", "中国能源报", "中国碳交易网"}


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


def backfill_one(fp: Path, force: bool = False) -> tuple[Path, str]:
    txt = fp.read_text(encoding="utf-8")
    fm = parse_fm(txt)
    if fm.get("author") and not force:
        return fp, "already has author"
    url = fm.get("url", "")
    if not url or "news.google" in url:
        return fp, "skip(google/no url)"
    res = fetch_article(url)
    if not res:
        return fp, "fetch failed"
    org = (res.get("source_org") or "").strip()
    if not org:
        return fp, "no source_org on page"
    # 写入 frontmatter author 行（在 keywords 行后）
    lines = txt.split("\n")
    out: list[str] = []
    inserted = False
    for line in lines:
        out.append(line)
        if not inserted and line.startswith("keywords:"):
            out.append(f'author: "{org.replace(chr(34), chr(39))}"')
            inserted = True
    # 正文元信息行：在 "> 首次抓取:" 行后加 "> 作者:"
    if inserted:
        out2: list[str] = []
        added = False
        for line in out:
            out2.append(line)
            if not added and line.startswith("> 首次抓取:"):
                out2.append(f"> 作者: {org}")
                added = True
        fp.write_text("\n".join(out2), encoding="utf-8")
        return fp, f"author={org}"
    return fp, "no keywords line"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--force", action="store_true", help="覆盖已有 author 的笔记")
    args = ap.parse_args()

    files = []
    for dp, _, fs in os.walk(NOTES_ROOT):
        for f in fs:
            if not f.endswith(".md") or f in SKIP:
                continue
            fp = Path(dp) / f
            txt = fp.read_text(encoding="utf-8")
            fm = parse_fm(txt)
            if fm.get("source") in ORG_SOURCES and (not fm.get("author") or args.force):
                files.append(fp)
    print(f"待回填 author: {len(files)} 篇 (force={args.force})")
    if args.dry_run:
        for fp in files[:20]:
            fm = parse_fm(fp.read_text(encoding="utf-8"))
            print(f"  {fm.get('source','?')} | {fp.name[:45]}")
        return 0

    ok = no_org = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(backfill_one, fp, args.force): fp for fp in files}
        for fut in as_completed(futs):
            fp, msg = fut.result()
            if msg.startswith("author="):
                ok += 1
            elif msg == "no source_org on page":
                no_org += 1
            else:
                fail += 1
            if msg.startswith("author=") or msg == "no source_org on page":
                print(f"  {msg:30s} {fp.name[:45]}")
    print(f"\n完成: 回填 {ok}, 页面无来源 {no_org}, 失败/跳过 {fail}")
    return 0


if __name__ == "__main__":
    import os
    main()
