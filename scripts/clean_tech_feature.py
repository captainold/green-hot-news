#!/usr/bin/env python3.11
"""tech_feature 回填后的清理（2026-08-24）——正文输入后 LLM 偶尔"刹不住"：
1. 把"无"写成解释长文（"该新闻未涉及绿色低碳…无法提取"）→ 归一化为「无」
2. 列表/长文格式（arXiv 论文、投研报告）→ 截断到第一句/50 字内

用法：
    python3.11 scripts/clean_tech_feature.py            # dry-run 对比
    python3.11 scripts/clean_tech_feature.py --apply    # 实际写回 qmd + data JSON
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = ROOT / "Notes" / "数据库"
MAX_LEN = 50

# 明确的"无"表述 → 归一化为「无」
_NO_PATTERNS = [
    r'无相关技术特征', r'无法提取', r'未涉及绿色低碳', r'未发现.{0,10}技术特征',
    r'不属于绿色低碳', r'不涉及绿色低碳', r'因此无相关', r'因此无法',
    r'技术特征[:：]?\s*无[（(]', r'未涉及.{0,15}技术参数', r'无.{0,10}技术特征可提取',
]

_RE_TF = re.compile(r'^tech_feature:\s*"?([^"\n]*)"?\s*$', re.M)


def clean_tf(tf: str) -> str:
    """归一化 + 截断一条 tech_feature（保守：不误伤"引导语+列表"的有特征输出）。"""
    tf = (tf or "").strip()
    if not tf:
        return tf
    # 1. 归一化"纯无"：去前缀后是"无"，或单行纯解释（无换行列表符号）
    t = re.sub(r'^技术特征[:：]\s*', '', tf)
    if re.match(r'^无[（(。]', t) or t in ("无", "None"):
        return "无"
    # 非绿色低碳引导语（arXiv AI/医疗/机器人论文）：明确说"非绿色低碳"→ 判"无"
    if re.search(r'(并非|不属于|不涉及|未涉及)绿色低碳', tf):
        return "无"
    # 去"技术特征："前缀（内容对的冗余前缀）
    tf = re.sub(r'^技术特征[:：]\s*', '', tf)
    has_list = bool(re.search(r'\n\s*[-*\d]', tf))  # 含列表要点 → 有实质内容
    if not has_list and any(re.search(p, t) for p in _NO_PATTERNS):
        return "无"
    # 2. 超长（>50字）硬截断，保留前 50 字（不做复杂的引导语/列表提取，避免误伤）
    if len(tf) > MAX_LEN:
        tf = tf[:MAX_LEN]
    return tf.strip()


def process_qmd(fp: Path) -> tuple[str, str] | None:
    txt = fp.read_text(encoding="utf-8", errors="ignore")
    m = _RE_TF.search(txt)
    if not m:
        return None
    old = m.group(1).strip()
    new = clean_tf(old)
    if new == old:
        return None
    return old, new


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    # 1. 清理 qmd
    changes: list[tuple[str, str, str]] = []  # (file, old, new)
    for fp in sorted(NOTES_DIR.glob("*.qmd")):
        r = process_qmd(fp)
        if r:
            old, new = r
            changes.append((fp.name, old, new))

    # 2. 同步 data JSON（按 url → 清理后的值）
    #    先收集 qmd 里 url → new tf（从 qmd frontmatter 读 url）
    url_to_new: dict[str, str] = {}
    for fp in sorted(NOTES_DIR.glob("*.qmd")):
        txt = fp.read_text(encoding="utf-8", errors="ignore")
        m_url = re.search(r'^url:\s*"?([^"\n]+)"?\s*$', txt, re.M)
        m_tf = _RE_TF.search(txt)
        if m_url and m_tf:
            tf = clean_tf(m_tf.group(1).strip())
            if m_tf.group(1).strip() != tf:
                url_to_new[m_url.group(1).strip()] = tf

    json_updated = 0
    for fn in ("history.json", "latest-24h.json", "latest-24h-all.json"):
        path = ROOT / "data" / fn
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        is_dict = isinstance(data, dict) and "items" in data
        items = data["items"] if is_dict else data
        for it in items:
            if not isinstance(it, dict):
                continue
            u = (it.get("url") or "").strip()
            if u in url_to_new:
                it["tech_feature"] = url_to_new[u]
                json_updated += 1
        if is_dict:
            data["items"] = items
        if args.apply:
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    # 3. 报告
    print(f"qmd 清理 {len(changes)} 条，data JSON 同步 {json_updated} 条\n")
    for fn, old, new in changes:
        print(f"[{fn[:40]}]")
        print(f"  旧: {old[:60]}")
        print(f"  新: {new[:60]}")
        print()

    if args.apply:
        for fp in sorted(NOTES_DIR.glob("*.qmd")):
            txt = fp.read_text(encoding="utf-8", errors="ignore")
            m = _RE_TF.search(txt)
            if not m:
                continue
            old = m.group(1).strip()
            new = clean_tf(old)
            if new != old:
                new_txt = _RE_TF.sub(lambda _m: f'tech_feature: "{new}"', txt, count=1)
                fp.write_text(new_txt, encoding="utf-8")
        print("✅ 已写回 qmd + data JSON")
    else:
        print("Dry-run（未写回）。确认后加 --apply。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
