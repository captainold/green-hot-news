#!/usr/bin/env python3
"""重新抓取碳交易网笔记正文，替换掉带推荐列表污染的旧正文。

背景（2026-08-11）：碳交易网详情页右侧推荐列表/相关阅读混入正文
（39 篇）。article_content.py 已加 GARBAGE_SELECTORS 源头过滤
(.tanlistbox_right/.list_r_b_x/.list_img_news/.about-read)。
本脚本用修复后的 extractor 重新抓取每篇正文并替换。

安全：只重写 "## 正文" 之后的部分；frontmatter/标题/原文链接保留；
抓取失败的文件跳过（保持原状）。
"""
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


def refresh_one(fp: Path) -> tuple[Path, str]:
    txt = fp.read_text(encoding="utf-8")
    fm = parse_fm(txt)
    url = fm.get("url", "")
    if not url or "google" in url or "news.google" in url:
        return fp, "skip(no url)"
    res = fetch_article(url)
    if not res:
        return fp, "fetch failed"
    content = (res.get("content") or "").strip()
    if len(content) < MIN_BODY:
        return fp, f"content too short ({len(content)})"
    # 重建文件：保留 frontmatter + 标题 + 原文链接 + 来源行，替换 ## 正文
    new_lines: list[str] = []
    in_fm = False
    fm_done = False
    replaced = False
    for line in txt.split("\n"):
        if not fm_done:
            new_lines.append(line)
            if line.strip() == "---" and not in_fm:
                in_fm = True
            elif in_fm and line.strip() == "---":
                fm_done = True
            continue
        if line.strip().startswith("## 正文"):
            new_lines.append("## 正文")
            new_lines.append("")
            new_lines.append(content)
            new_lines.append("")
            replaced = True
            break
        new_lines.append(line)
    if not replaced:
        return fp, "no 正文 section"
    fp.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    return fp, f"ok({len(content)} chars)"


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    files = sorted(TARGET_DIR.rglob("*.md"))
    if args.dry_run:
        print(f"将重新抓取 {len(files)} 篇碳交易网笔记的正文")
        return 0

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(refresh_one, fp): fp for fp in files}
        for fut in as_completed(futs):
            fp, msg = fut.result()
            if msg.startswith("ok"):
                ok += 1
                print(f"✓ {fp.name[:45]} | {msg}")
            else:
                fail += 1
                print(f"✗ {fp.name[:45]} | {msg}")
    print(f"\n完成: 刷新 {ok}, 失败/跳过 {fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
