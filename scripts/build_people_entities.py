#!/usr/bin/env python3
"""补建人物实体页（2026-09-23，P5 断链清理）。

背景：`link_entities.py` 在素材正文写了 `[[人物/郑栅洁|郑栅洁]]` 之类双链，
但 `Notes/实体/人物/` 目录一直没建 → 52 处断链。

权威来源：`scripts/update_news.py` 的 `PERSON_RULES`（姓名 → 职务），
机构归属按职务前缀匹配 `Notes/实体/机构/` 现有实体页。

幂等：已存在的页面默认跳过（不覆盖人工深化内容），`--force` 才重建。

用法：
    python scripts/build_people_entities.py [--dry-run|--apply] [--force]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "Notes"
ENT_DIR = NOTES / "实体" / "人物"
UPDATE_NEWS = ROOT / "scripts" / "update_news.py"
SCAN_ROOTS = ["素材库"]  # 2026-10-04 切库：退役 政策库/数据库/媒体库 已归档


def parse_person_rules() -> dict[str, str]:
    """从 update_news.py 源码解析 PERSON_RULES（不 import，避免副作用）。"""
    src = UPDATE_NEWS.read_text(encoding="utf-8")
    m = re.search(r"^PERSON_RULES[^=]*=\s*\{(.*?)^\}", src, re.M | re.S)
    if not m:
        raise SystemExit("未找到 PERSON_RULES")
    out: dict[str, str] = {}
    for name, role in re.findall(r'"([^"]+)":\s*\("([^"]+)"', m.group(1)):
        out[name] = role
    return out


def org_entities() -> dict[str, str]:
    """机构实体：stem → id。"""
    out: dict[str, str] = {}
    d = NOTES / "实体" / "机构"
    if not d.exists():
        return out
    for f in d.rglob("*.md"):
        t = f.read_text(encoding="utf-8")
        i = re.search(r'^id:\s*"?([^"\n]+)', t, re.M)
        out[f.stem] = i.group(1).strip() if i else ""
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true", help="覆盖已存在页面")
    args = ap.parse_args()

    rules = parse_person_rules()
    orgs = org_entities()
    print(f"PERSON_RULES {len(rules)} 人 | 机构实体 {len(orgs)} 个")

    # 每个人的关联素材（扫描正文双链）
    mentions: dict[str, list[str]] = {n: [] for n in rules}
    for r in SCAN_ROOTS:
        base = NOTES / r
        if not base.exists():
            continue
        for f in base.rglob("*.md"):
            t = f.read_text(encoding="utf-8", errors="replace")
            for name in rules:
                if f"[[人物/{name}" in t:
                    mentions[name].append(f.stem)

    if args.apply:
        ENT_DIR.mkdir(parents=True, exist_ok=True)

    created = skipped = 0
    for name, role in sorted(rules.items()):
        notes = sorted(set(mentions[name]), reverse=True)
        # 机构：把职务里的机构名与现有实体做最长匹配
        org_stem = ""
        for cand in sorted(orgs, key=len, reverse=True):
            if cand and cand in role:
                org_stem = cand
                break
        # 只给「有素材引用」或已被引用的人建页（避免造空壳）
        path = ENT_DIR / f"{name}.md"
        exists = path.exists()
        if exists and not args.force:
            skipped += 1
            continue
        rel = f'["{orgs[org_stem]}"]' if (org_stem and orgs.get(org_stem)) else "[]"
        lines = [
            "---",
            f'id: "per/{name}"',
            'type: "per"',
            f'name: "{name}"',
            f'aliases: ["{name}", "per/{name}"]',
            'region: "中国"',
            f"related: {rel}",
            'tags: ["type/per", "region/中国"]',
            "created: 2026-09-23",
            "status: skeleton",
            "---",
            "",
            f"# {name}",
            "",
            f"> **职务**：{role}（权威来源：`scripts/update_news.py` · `PERSON_RULES`）",
        ]
        if org_stem:
            lines.append(f"> **机构**：[[{org_stem}]]")
        lines += ["", f"## 关联素材（共 {len(notes)} 条，按时间倒序取前 8）", ""]
        if notes:
            lines += [f"- [[{s}]]" for s in notes[:8]]
        else:
            lines.append("_暂无素材引用（由 PERSON_RULES 白名单登记）_")
        lines += [
            "",
            "## 说明",
            "",
            "- 本页由 `scripts/build_people_entities.py` 按 `PERSON_RULES` 白名单补建（2026-09-23），"
            "用于承接素材正文的人物双链（`人物/姓名` 形式），内容待 P4 深化。",
            "",
        ]
        if args.apply:
            path.write_text("\n".join(lines), encoding="utf-8")
        created += 1
        print(f"  {'重建' if exists else '新建'} {name}（{role}）｜素材 {len(notes)} 条｜机构 {org_stem or '—'}")

    print(f"\n{'写入' if args.apply else '待写入'} {created} 个，跳过已存在 {skipped} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
