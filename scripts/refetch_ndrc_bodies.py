#!/usr/bin/env python3
"""重抓发改委笔记正文（TRS_Editor span 布局修复后）。

背景（2026-08-11）：发改委通知公告的正文在 div.TRS_Editor 里，段落是
span+<br/> 布局（无 p 标签），旧 extract 拿不到 → 200 篇正文过薄。
article_content 已修复（强优先 TRS_Editor + span/br fallback）。
本脚本对正文 <100 字的发改委笔记重新抓取正文替换。
"""
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from article_content import fetch_article  # noqa: E402

TARGET_DIR = Path("Notes/政策库/中国/国家发改委")
MIN_BODY = 100


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


def refetch_one(fp: Path) -> tuple[Path, str]:
    txt = fp.read_text(encoding="utf-8")
    fm = parse_fm(txt)
    url = fm.get("url", "")
    if not url:
        return fp, "no url"
    res = fetch_article(url)
    if not res:
        return fp, "fetch failed"
    content = (res.get("content") or "").strip()
    if len(content) < MIN_BODY:
        return fp, f"still thin ({len(content)})"
    # 替换 ## 正文 之后的内容
    lines = txt.split("\n")
    out: list[str] = []
    replaced = False
    for line in lines:
        if line.strip().startswith("## 正文"):
            out.append("## 正文")
            out.append("")
            out.append(content)
            out.append("")
            replaced = True
            break
        out.append(line)
    if not replaced:
        return fp, "no 正文 section"
    fp.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return fp, f"ok({len(content)} chars)"


def main() -> int:
    files = []
    for dp, _, fs in os.walk(TARGET_DIR):
        for f in fs:
            if not f.endswith(".md"):
                continue
            fp = Path(dp) / f
            txt = fp.read_text(encoding="utf-8")
            idx = txt.find("## 正文")
            body = txt[idx + len("## 正文"):].strip() if idx > 0 else ""
            if len(body) < MIN_BODY:
                files.append(fp)
    print(f"正文过薄待重抓: {len(files)} 篇")
    if not files:
        return 0
    ok = fail = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(refetch_one, fp): fp for fp in files}
        for fut in as_completed(futs):
            fp, msg = fut.result()
            if msg.startswith("ok"):
                ok += 1
            else:
                fail += 1
            print(f"{'✓' if msg.startswith('ok') else '✗'} {msg:30s} {fp.name[:40]}")
    print(f"\n完成: 重抓 {ok}, 失败/仍薄 {fail}")
    return 0


if __name__ == "__main__":
    import os
    sys.exit(main())
