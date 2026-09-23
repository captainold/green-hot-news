#!/usr/bin/env python3
"""修复政策wiki中因库结构迁移导致的链接路径变化。

迁移映射：
  政策库/<站点>/            → 政策库/<中国|国际组织>/<站点>/
  政策库/<媒体站点>/        → 媒体库/<媒体站点>/
"""
import glob
import re

# 站点 → (目标库, 分组或None)
MOVE = {
    # 政策库 · 中国部委
    "国家发改委": ("政策库", "中国"),
    "国家能源局": ("政策库", "中国"),
    "生态环境部": ("政策库", "中国"),
    "工信部": ("政策库", "中国"),
    # 政策库 · 国际组织
    "IEA": ("政策库", "国际组织"),
    "IRENA": ("政策库", "国际组织"),
    "UNFCCC": ("政策库", "国际组织"),
    "World Bank Climate": ("政策库", "国际组织"),
    # 媒体库
    "中国碳交易网": ("媒体库", None),
    "中国能源报": ("媒体库", None),
    "北极星电力网": ("媒体库", None),
    "碳道": ("媒体库", None),
    "Carbon Brief": ("媒体库", None),
    "Reuters": ("媒体库", None),
}

def fix_wiki_files(pattern: str) -> int:
    fixed = 0
    for fp in glob.glob(pattern, recursive=True):
        with open(fp, encoding="utf-8") as fh:
            text = fh.read()
        new_text = text
        for site, (lib, group) in MOVE.items():
            old = f"../../政策库/{site}/"
            if group:
                new = f"../../{lib}/{group}/{site}/"
            else:
                new = f"../../{lib}/{site}/"
            new_text = new_text.replace(old, new)
        if new_text != text:
            with open(fp, "w", encoding="utf-8") as fh:
                fh.write(new_text)
            fixed += 1
            print(f"fix {fp}")
    return fixed

if __name__ == "__main__":
    n = fix_wiki_files("Notes/政策wiki/**/*.md")
    print(f"修复 {n} 个文件")
