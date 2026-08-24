#!/usr/bin/env python3.11
"""存量图片清理（2026-08-24 老温需求配套）：移除 qmd 里无信息量的图片
（新闻配图/垃圾图标）+ 删除不再被引用的孤儿附件。

判定复用 article_content._is_informative_image（白名单：Fig/图N/示意/架构/
流程/数据/趋势/chart/diagram 等有信息量信号，跳过 icon/logo/avatar/二维码/人物照/空alt）。

用法：
    python3.11 scripts/clean_images.py             # dry-run 统计
    python3.11 scripts/clean_images.py --apply     # 实际写回 + 删孤儿附件
"""
from __future__ import annotations

import argparse
import re
import sys
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / "Notes" / "数据库"
ATT_DIR = NOTES_DIR / "attachments"

spec = importlib.util.spec_from_file_location("ac", str(ROOT / "scripts" / "article_content.py"))
ac = importlib.util.module_from_spec(spec)
sys.modules["ac"] = ac
spec.loader.exec_module(ac)

IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    # 1. 清理 qmd 里的垃圾图
    removed_total = 0
    kept_total = 0
    files_changed = 0
    for fp in sorted(NOTES_DIR.glob("*.qmd")):
        try:
            txt = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        removed = 0
        kept = 0

        def _clean(m: "re.Match[str]") -> str:
            nonlocal removed, kept
            alt, src = m.group(1).strip(), m.group(2).strip()
            if ac._is_informative_image(alt, src):
                kept += 1
                return m.group(0)
            removed += 1
            return ""  # 移除垃圾图

        new_txt = IMG_RE.sub(_clean, txt)
        # 移除图片后压掉多余空行
        new_txt = re.sub(r"\n{3,}", "\n\n", new_txt)
        if new_txt != txt:
            files_changed += 1
            if args.apply:
                fp.write_text(new_txt, encoding="utf-8")
        removed_total += removed
        kept_total += kept

    # 2. 删孤儿附件（清理后不再被任何 qmd 引用的 attachments 文件）
    referenced: set[str] = set()
    for fp in NOTES_DIR.glob("*.qmd"):
        try:
            txt = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in re.finditer(r"\]\(attachments/([^)]+)\)", txt):
            referenced.add(m.group(1))
    orphans = [f for f in ATT_DIR.iterdir() if f.is_file() and f.name not in referenced]

    print(f"清理 {files_changed} 个 qmd | 移除垃圾图 {removed_total} | 保留有信息量图 {kept_total}")
    print(f"孤儿附件 {len(orphans)} 个（attachments/ 共 {len(list(ATT_DIR.iterdir()))} 文件）")
    if args.apply:
        for f in orphans:
            try:
                f.unlink()
            except Exception:
                pass
        print("✅ 已写回 qmd + 删除孤儿附件")
    else:
        print("Dry-run（未写回）。确认后加 --apply。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
