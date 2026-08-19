#!/usr/bin/env python3
"""_rebuild_title_index.py — 从已修复的 Notes 素材重建 title-index.json（防污染版）。

跳过站名/导航标题（公共服务网、即将离开、.gov 后缀、机构名等），
确保 CI 回填不再引入坏标题。用法：python3 _rebuild_title_index.py [notes根目录]
"""
import json, re, sys
from pathlib import Path

BAD_H1 = re.compile(
    r"公共服务网|即将离开|\.gov\)|\(EIA\)|\(NOAA\)|\(EPA\)|\(DOE\)|"
    r"U\.S\. Energy Information Administration|California Air Resources Board|"
    r"Federal Energy Regulatory Commission|National Hurricane Center|"
    r"Southwestern Power Administration|Snow Station Information|"
    r"^Computer Science\s*>|^GitHub - |^#?\s*国家节能中心公共服务网"
)

def rebuild(notes_root="Notes", out="data/title-index.json"):
    mapping = {}
    skipped = 0
    for p in Path(notes_root).rglob("*.md"):
        if p.name in ("政策库.md", "媒体库.md", "ai-index.md"):
            continue
        try:
            c = p.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(r"^# (.+)$", c, re.M)
        um = re.search(r"^url:\s*(\S+)", c, re.M)
        if not m or not um:
            continue
        h1 = m.group(1).strip()
        if BAD_H1.search(h1):
            skipped += 1
            continue
        mapping[um.group(1)] = h1
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"重建 {out}: {len(mapping)} 条（跳过坏标题 {skipped} 条）")

if __name__ == "__main__":
    rebuild(sys.argv[1] if len(sys.argv) > 1 else "Notes",
            sys.argv[2] if len(sys.argv) > 2 else "data/title-index.json")
