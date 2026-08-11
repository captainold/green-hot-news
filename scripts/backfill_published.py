#!/usr/bin/env python3
"""回填被 fix_frontmatter.py 误删的 published 字段。

fix_frontmatter.py 的 ALLOWED_KEYS 之前缺 "published"，把 frontmatter 里的
published: 行当残留 key 删掉了（2026-08-11）。本脚本从 git 历史版本的
data/published-index.json（url → published 映射）恢复：
- 扫描 Notes/ 下所有笔记
- 若笔记 frontmatter 缺 published 且 url 命中映射 → 回填
"""
import os
import re
import subprocess
from pathlib import Path

NOTES_ROOT = Path("Notes")


def load_published_index_from_git(rev: str = "HEAD~1") -> dict[str, str]:
    out = subprocess.run(
        ["git", "show", f"{rev}:data/published-index.json"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        print("git show 失败:", out.stderr)
        return {}
    import json
    return json.loads(out.stdout)


def backfill(pub_map: dict[str, str]) -> int:
    fixed = 0
    for dp, _, fs in os.walk(NOTES_ROOT):
        for f in fs:
            if not f.endswith(".md"):
                continue
            if f in ("政策库.md", "媒体库.md", "ai-index.md"):
                continue
            fp = Path(dp) / f
            content = fp.read_text(encoding="utf-8")
            if not content.startswith("---"):
                continue
            # 提取 frontmatter 边界
            lines = content.split("\n")
            seps = [i for i, l in enumerate(lines) if l.strip() == "---"]
            if len(seps) < 2:
                continue
            fm = lines[seps[0] + 1:seps[1]]
            url = ""
            has_pub = False
            for ln in fm:
                if ln.startswith("url:"):
                    url = ln.split(":", 1)[1].strip().strip('"')
                elif ln.startswith("published:"):
                    has_pub = True
            if has_pub or not url:
                continue
            pub = pub_map.get(url)
            if not pub:
                continue
            # 在 date: 行后插入 published 行
            out_lines = lines[:]
            insert_at = None
            for i, ln in enumerate(lines[seps[0] + 1:seps[1]], seps[0] + 1):
                if ln.startswith("date:"):
                    insert_at = i + 1
                    break
            if insert_at is None:
                insert_at = seps[0] + 1
            out_lines.insert(insert_at, f'published: "{pub}"')
            fp.write_text("\n".join(out_lines), encoding="utf-8")
            fixed += 1
    return fixed


if __name__ == "__main__":
    m = load_published_index_from_git()
    print("从 git 读取映射条目:", len(m))
    n = backfill(m)
    print(f"回填 published: {n} 篇笔记")
