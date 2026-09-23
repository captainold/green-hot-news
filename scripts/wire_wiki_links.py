#!/usr/bin/env python3
r"""wiki 接线（2026-09-23，P5 孤立节点清理）。

问题：`实体/人物/` 17 页与 `实体/技术/` 中 7 页 0 入链（孤立节点）——
人物索引页用 dataview 聚合、没有指向实体页的双链；技术实体页没被任何主题页引用。

做法（幂等）：
1. `政策wiki/人物/人物.md`：`### 姓名` → `### [[姓名]]`（人物实体页 stem 命中才改）
2. 各主题页 `## 跨主题关联` 末尾补一行 `- 技术实体：[[a]] · [[b]] …`（映射见 TECH_BY_TOPIC）

用法：
    python scripts/wire_wiki_links.py [--dry-run|--apply]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "Notes"
WIKI = NOTES / "政策wiki"
PERSON_DIR = NOTES / "实体" / "人物"
TECH_DIR = NOTES / "实体" / "技术"

TECH_BY_TOPIC: dict[str, list[str]] = {
    "新能源": ["光伏", "风电", "储能", "氢能", "生物质", "核电"],
    "电力改革": ["电网", "储能", "核电"],
    "环境保护": ["CCUS"],
    "气候变化": ["CCUS"],
    "工业绿色转型": ["CCUS", "储能"],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    persons = {p.stem for p in PERSON_DIR.rglob("*.md")} if PERSON_DIR.exists() else set()
    techs = {p.stem for p in TECH_DIR.rglob("*.md")} if TECH_DIR.exists() else set()
    changed = 0

    # 1) 人物索引：标题挂实体页双链
    idx = WIKI / "人物" / "人物.md"
    if idx.exists() and persons:
        text = idx.read_text(encoding="utf-8")
        hits = 0

        def head(m: re.Match) -> str:
            nonlocal hits
            name = m.group(1).strip()
            if name in persons and f"[[{name}]]" not in m.group(0):
                hits += 1
                return f"### [[{name}]]"
            return m.group(0)

        new = re.sub(r"^### (.+)$", head, text, flags=re.M)
        if hits:
            changed += 1
            print(f"人物索引：加双链 {hits} 处")
            if args.apply:
                idx.write_text(new, encoding="utf-8")

    # 2) 主题页：跨主题关联补技术实体
    for topic, items in TECH_BY_TOPIC.items():
        page = WIKI / topic / f"{topic}.md"
        if not page.exists():
            print(f"  ⚠️ 主题页不存在，跳过: {topic}")
            continue
        valid = [t for t in items if t in techs]
        if not valid:
            continue
        text = page.read_text(encoding="utf-8")
        line = "- 技术实体：" + " · ".join(f"[[{t}]]" for t in valid)
        if "技术实体：" in text:
            continue
        m = re.search(r"^## 素材索引\s*$", text, re.M)
        if not m:
            print(f"  ⚠️ {topic} 无「素材索引」节，跳过")
            continue
        new = text[:m.start()] + line + "\n\n" + text[m.start():]
        changed += 1
        print(f"{topic}：技术实体 {'、'.join(valid)}")
        if args.apply:
            page.write_text(new, encoding="utf-8")

    print(f"\n{'已写入' if args.apply else '待写入'} {changed} 个页面")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
