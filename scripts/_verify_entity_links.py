# -*- coding: utf-8 -*-
"""断链检查：扫描素材库 qmd 的 [[实体]] 链接，验证目标文件存在。"""
import re
from pathlib import Path
from collections import Counter

NOTES = Path(r"C:\Users\wenyu\Documents\Obsidian_wen\green-hot-news\Notes")

# 构建 Notes 下所有文件名（不含扩展名）→ 路径 映射
all_names: dict[str, list[Path]] = {}
for p in NOTES.rglob("*"):
    if p.is_file() and p.suffix in (".md",):
        all_names.setdefault(p.stem, []).append(p)

# 扫描素材库 qmd 的 [[...]] 链接
broken = Counter()
total_links = 0
for p in (NOTES / "素材库").rglob("*.md"):
    if not p.is_file():
        continue
    text = p.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]", text):
        target = m.group(1).strip()
        # 跳过带路径的（如 ../../xxx）
        if "/" in target or "\\" in target:
            continue
        total_links += 1
        if target not in all_names:
            broken[target] += 1

print(f"素材库 [[实体]] 链接总数: {total_links}")
print(f"断链目标数: {len(broken)}")
for t, c in broken.most_common(20):
    print(f"  [[{t}]]: {c} 次")
