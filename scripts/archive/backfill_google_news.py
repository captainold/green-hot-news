#!/usr/bin/env python3.11
"""回填 Google News 笔记的真实 URL + 正文（2026-08-19）。

背景：Google News base64 链接在抓取时解码可能失败 → 笔记只有标题+链接无正文，
且 frontmatter 存的是 base64 假链接。本脚本：
1. 扫描 Notes/ 下所有 frontmatter url 为 news.google.com 的 md
2. 解码真实 URL → 抓正文
3. 更新 frontmatter url（真实链接）+ 写入 ## 正文 + summary 字段
用法：python3.11 scripts/backfill_google_news.py [--limit N] [--dry-run]
"""
import argparse
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import article_content  # noqa: E402

INDEX_NAMES = {"政策库.md", "媒体库.md", "ai-index.md"}


def find_stale_notes(root: Path) -> list[Path]:
    out = []
    for p in root.rglob("*.md"):
        if p.name in INDEX_NAMES:
            continue
        c = p.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^url:\s*(\S+)", c, re.M)
        if not m:
            continue
        u = m.group(1)
        if "news.google.com" in u and "## 正文" not in c:
            out.append(p)
    return out


def process_one(p: Path, dry: bool) -> tuple[str, str, int]:
    c = p.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"^url:\s*(\S+)", c, re.M)
    if not m:
        return str(p), "no-url", 0
    old_url = m.group(1)
    res = article_content.fetch_article(old_url)
    if not res or not res.get("content"):
        return str(p), "fetch-fail", 0
    real = res.get("real_url") or old_url
    summary = (res.get("summary") or "").replace('"', "'").replace("\n", " ")
    content = res.get("content") or ""
    title = res.get("title") or ""
    if dry:
        return str(p), "would-fix", len(content)

    # 1) frontmatter url 替换为真实链接
    c = re.sub(r"^url:\s*\S+", f"url: {real}", c, count=1, flags=re.M)
    # 2) 补 summary（若缺失）——用 lambda 避免 re 模板转义问题（bad escape）
    if "summary:" not in c and summary:
        c = re.sub(r"^(keywords:.*)$",
                   lambda m: f"{m.group(1)}\nsummary: \"{summary}\"",
                   c, count=1, flags=re.M)
    # 3) 标题行替换为详情页完整标题（若更长）
    hm = re.search(r"^# (.+)$", c, re.M)
    if title and hm and len(title) > len(hm.group(1).strip()):
        c = re.sub(r"^# .+$", f"# {title}", c, count=1, flags=re.M)
    # 4) 追加正文
    if "## 正文" not in c:
        c = c.rstrip() + "\n\n## 正文\n\n" + content + "\n"
    p.write_text(c, encoding="utf-8")
    return str(p), "fixed", len(content)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（0=全部）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    stale = find_stale_notes(ROOT / "Notes")
    print(f"发现无正文 Google News 笔记: {len(stale)} 条")
    if args.limit:
        stale = stale[: args.limit]
    if args.dry_run:
        print("DRY-RUN 模式，不写入")

    ok = fail = 0
    total_chars = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(process_one, p, args.dry_run): p for p in stale}
        for fut in as_completed(futs):
            path, status, n = fut.result()
            if status == "fixed" or status == "would-fix":
                ok += 1
                total_chars += n
            else:
                fail += 1
            if ok % 25 == 0 and ok:
                print(f"  进度: 成功 {ok} / 失败 {fail} ...")
    print(f"完成: 成功 {ok}（补正文共 {total_chars} 字符）/ 失败 {fail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
