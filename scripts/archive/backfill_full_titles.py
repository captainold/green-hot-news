#!/usr/bin/env python3
"""用详情页完整标题回填被截断的笔记标题。

背景（2026-08-11）：部分源（碳交易网等）列表页链接文本被截断
（如 "世界银行发布《2026年碳定价发展现状与未"），抓取时以列表页文本
当标题 → 笔记标题/JSON 标题不完整。article_content 已改为优先 h1
完整标题并清理站点后缀。

本脚本：对每个笔记抓详情页，若详情页标题更长则更新：
- frontmatter 的 # 标题行（正文标题）
- 文件名（保留日期前缀）
- 提示 JSON 需重新生成
只处理标题 < 30 字符的笔记（长标题基本没截断）。
"""
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from article_content import fetch_article  # noqa: E402

NOTES_ROOT = Path("Notes")
SKIP = {"政策库.md", "媒体库.md", "ai-index.md"}
MAX_TITLE_LEN = 30  # 只有短标题才可能被截断


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


def fix_one(fp: Path) -> tuple[Path, str]:
    txt = fp.read_text(encoding="utf-8")
    fm = parse_fm(txt)
    url = fm.get("url", "")
    if not url:
        return fp, "no url"
    # 现有标题（正文第一行 # 标题）
    m = re.search(r"^# (.+)$", txt, re.M)
    if not m:
        return fp, "no # title"
    cur_title = m.group(1).strip()
    # 标题长但带站点后缀的也要修（如 "…通知】-国家发展和改革委员会"）
    has_site_suffix = re.search(
        r"(网|官网|委员会|政府|部$|中心|门户)$", cur_title) and len(cur_title) < 60
    if len(cur_title) >= MAX_TITLE_LEN and not has_site_suffix:
        return fp, "already long"
    res = fetch_article(url)
    if not res:
        return fp, "fetch failed"
    page_title = (res.get("title") or "").strip()
    if not page_title:
        return fp, "no page title"
    # 详情页标题更好：更长，或当前标题是它的超集（带站点后缀）
    if len(page_title) <= len(cur_title) and page_title not in cur_title:
        return fp, f"no better title ({len(page_title)}<={len(cur_title)})"
    # 更新正文标题
    new_txt = txt.replace(f"# {cur_title}", f"# {page_title}", 1)
    # 更新 frontmatter title 字段（如果有）
    new_txt = re.sub(r'^title: ".*"$', f'title: "{page_title}"', new_txt, flags=re.M)
    fp.write_text(new_txt, encoding="utf-8")
    # 重命名文件（保留日期前缀）
    safe = re.sub(r'[<>:"/\\|?*]', "_", page_title)[:80].strip()
    date_pref = re.match(r"^(\d{4}-\d{2}-\d{2} )", fp.name)
    new_name = (date_pref.group(1) if date_pref else "") + safe + ".md"
    if new_name != fp.name:
        new_fp = fp.with_name(new_name)
        if not new_fp.exists():
            fp.rename(new_fp)
            return new_fp, f"renamed+title ({len(page_title)})"
    return fp, f"title updated ({len(page_title)})"


def main() -> int:
    files = []
    for dp, _, fs in os.walk(NOTES_ROOT):
        for f in fs:
            if not f.endswith(".md") or f in SKIP:
                continue
            fp = Path(dp) / f
            txt = fp.read_text(encoding="utf-8")
            m = re.search(r"^# (.+)$", txt, re.M)
            if m and len(m.group(1).strip()) < MAX_TITLE_LEN:
                files.append(fp)
    print(f"疑似短标题待回填: {len(files)} 篇")
    if not files:
        return 0
    ok = skip = 0
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(fix_one, fp): fp for fp in files}
        for fut in as_completed(futs):
            fp, msg = fut.result()
            if msg.startswith(("title updated", "renamed")):
                ok += 1
                print(f"✓ {msg:30s} {fp.name[:40]}")
            else:
                skip += 1
    print(f"\n完成: 回填 {ok}, 跳过 {skip}")
    print("注意: JSON 标题需重新运行 update_news.py 或手动刷新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
