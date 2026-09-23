# -*- coding: utf-8 -*-
"""P2 三库合并迁移 · 素材层 md → 统一 qmd（补多维标签 + author 清洗回填）。

复用 update_news.py 的分类器（categorize_dimension / classify_* / score_item），
把素材层（政策库/媒体库）的 7 字段简易 frontmatter 补齐为 21 字段多维标签 qmd，
与数据库 qmd 规范对齐。

用法：
    # 小批验证（先跑这个看字段映射）
    python3.11 scripts/backfill_ontology.py --input Notes/政策库 --output Notes/_backfill_test --limit 100
    python3.11 scripts/backfill_ontology.py --input Notes/媒体库 --output Notes/_backfill_test --limit 100
    # 全量（合并迁移时用，先备份）
    python3.11 scripts/backfill_ontology.py --input Notes/政策库 --output Notes/素材库/政策
    python3.11 scripts/backfill_ontology.py --input Notes/媒体库 --output Notes/素材库/媒体

设计：
- title 从正文第一个 `# ` 行提取（素材层 frontmatter 无 title 字段）
- site_id 从数据库 qmd 动态提取映射 + 手动补 4 个缺失
- author 清洗：污染特征（时间：/（RSS）/公众号：等）→ 丢弃；真司局名 → 回填
- tech_feature 留空（LLM 提取，后续 backfill_tech_feature 单独补）
- related 留空（P3 双链迁移再做）
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from update_news import (  # noqa: E402
    categorize_dimension, classify_trl, classify_eu_taxonomy,
    classify_isic, classify_gics, classify_ipc, classify_enabling_tech,
    extract_topic_tags, detect_region, score_item,
)

# 数据库 qmd 未覆盖的 source → site_id 手动补（2026-09-14 实测缺失 4 个）
MANUAL_SITE_ID = {
    "生态环境部·解读": "mee_jiedu",
    "UNEP": "unep",
    "CSIS": "csis",
    "高盛Insights": "goldman",
}

# author 污染特征（命中即丢弃，不回填）
# 保留：政策库司局名（环资司/价格司）+ 媒体库转载来源（人民日报/央视新闻/财联社）
# 丢弃：图片标注（界面图库）/模板变量（{{content.source}}）/未知/RSS标注/时间戳
AUTHOR_POLLUTION = [
    "时间：", "（RSS）", "（rss）", "· ", "公众号：", "Hacker News",
    "The Verge", "RSS", "IT之家", "GitHub Blog", "Cursor Blog",
    "图库", "图片", "{{", "未知", "Blog", "LMSYS", "Chatbot", "Feed",
]


def build_site_id_map() -> dict[str, str]:
    """从数据库 qmd 动态提取 site → site_id 映射，叠加手动补充。"""
    mapping: dict[str, str] = {}
    qmd_dir = ROOT / "Notes" / "数据库"
    if qmd_dir.exists():
        for p in qmd_dir.rglob("*.md"):
            if not p.is_file() or "_files" in str(p):
                continue
            t = p.read_text(encoding="utf-8", errors="replace")
            m = re.match(r"^---\s*\n(.*?)\n---", t, re.S)
            if not m:
                continue
            ft = m.group(1)
            s = re.search(r'^site:\s*"([^"]*)"', ft, re.M)
            sid = re.search(r'^site_id:\s*"([^"]*)"', ft, re.M)
            if s and sid and s.group(1) not in mapping:
                mapping[s.group(1)] = sid.group(1)
    mapping.update(MANUAL_SITE_ID)
    return mapping


def parse_md(path: Path) -> dict:
    """解析素材层 md：frontmatter 字段 + 正文标题。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    body = text
    if m:
        ft = m.group(1)
        body = text[m.end():]
        for line in ft.splitlines():
            mm = re.match(r'^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$', line)
            if mm:
                fm[mm.group(1)] = mm.group(2).strip()
    # title 从正文第一个 # 标题
    title = ""
    mt = re.search(r'^#\s+(.+)$', body, re.M)
    if mt:
        title = mt.group(1).strip()
    if not title:
        title = path.stem
    # 去掉文件名日期前缀（"2025-07-08 标题" → "标题"）
    title = re.sub(r'^\d{4}-\d{2}-\d{2}\s+', "", title)
    return {"fm": fm, "title": title, "body": body}


def _clean_list(v) -> list[str]:
    """把 frontmatter 值转成 list（兼容 [a,b] 或 "x"）。"""
    v = (v or "").strip()
    if not v or v == "[]":
        return []
    if v.startswith("["):
        inner = v[1:-1]
        return [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
    return [v.strip('"').strip("'")]


def clean_author(author: str) -> str:
    """author 清洗：污染 → 空，真司局名 → 回填。"""
    author = (author or "").strip().strip('"')
    if not author:
        return ""
    for p in AUTHOR_POLLUTION:
        if p in author:
            return ""
    # 过滤纯日期/时间类污染
    if re.match(r'^[\d\s:：\-\.]+$', author):
        return ""
    return author[:80]


def to_iso(published: str, date: str) -> str:
    """published("2025-07-08 13:47") / date("2025-07-08") → ISO 带时区。"""
    s = (published or "").strip().strip('"')
    d = (date or "").strip().strip('"')
    if s and re.match(r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}', s):
        s = s.replace(" ", "T")
        return s + ("+08:00" if "+" not in s and "Z" not in s else "")
    if d and re.match(r'^\d{4}-\d{2}-\d{2}', d):
        return d + "T00:00:00+08:00"
    return ""


def backfill(path: Path, site_id_map: dict, library: str) -> dict | None:
    """单条 md → qmd frontmatter dict（补全多维标签）。"""
    parsed = parse_md(path)
    fm = parsed["fm"]
    title = parsed["title"]
    summary = (fm.get("summary") or "").strip().strip('"')
    source = (fm.get("source") or "").strip().strip('"')
    site_id = site_id_map.get(source, "unknown")

    # 重跑分类器补多维标签
    dim, sub = categorize_dimension(site_id, title, summary, library)
    trl = classify_trl(title, summary)
    eu_tax = classify_eu_taxonomy(title, summary)
    isic = classify_isic(site_id, title, summary)
    gics = classify_gics(title, summary)
    ipc = classify_ipc(title, summary)
    enabling = classify_enabling_tech(title, summary)
    topics = extract_topic_tags(title)
    region = detect_region(site_id, title)
    people = _clean_list(fm.get("people"))

    published_at = to_iso(fm.get("published", ""), fm.get("date", ""))
    now = datetime.now(timezone.utc)
    sc = score_item(site_id, title, summary, people, published_at, now, sub, trl)

    author = clean_author(fm.get("author", ""))

    return {
        "title": title,
        "title_zh": "",
        "url": (fm.get("url") or "").strip().strip('"'),
        "site": source,
        "site_id": site_id,
        "dimension": dim,
        "layer": {"政策": "Layer 1", "产业": "Layer 2", "创新": "Layer 3"}.get(dim, ""),
        "sub_dimension": sub,
        "trl": trl,
        "eu_taxonomy": eu_tax,
        "isic": isic,
        "gics": gics,
        "ipc": ipc,
        "enabling_tech": enabling,
        "tech_feature": "",
        "topics": topics,
        "region": region,
        "people": people,
        "score": sc["score"],
        "score_level": sc["score_level"],
        "published_at": published_at,
        "author": author,
        "summary": summary,
    }


def _yaml_scalar(v) -> str:
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[" + ", ".join(_yaml_scalar(x) for x in v) + "]"
    return '""'


def to_qmd(item: dict) -> str:
    """qmd frontmatter + 正文（标题/摘要段）。"""
    lines = ["---"]
    for k in ["title", "title_zh", "url", "site", "site_id", "dimension", "layer",
              "sub_dimension", "trl", "eu_taxonomy", "isic", "gics", "ipc",
              "enabling_tech", "tech_feature", "topics", "region", "people",
              "score", "score_level", "published_at", "author"]:
        lines.append(f"{k}: {_yaml_scalar(item.get(k))}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {item['title']}")
    lines.append("")
    if item.get("url"):
        lines.append(f"[原文链接]({item['url']})")
        lines.append("")
    lines.append(f"> 来源: {item['site']} | 发布时间: {item['published_at']} | 评分: {item['score']} ({item['score_level']})")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.append(item.get("summary") or "（无摘要）")
    lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--limit", type=int, default=0, help="小批验证：只处理前 N 条")
    args = ap.parse_args()

    input_dir = Path(args.input)
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 按输入目录判断 library（政策库 → policy，媒体库 → media）
    library = "policy" if "政策库" in str(input_dir) else "media"

    site_id_map = build_site_id_map()
    print(f"[info] 输入: {input_dir} | 输出: {output_dir} | library: {library} | 映射 {len(site_id_map)} 源")

    md_files = [p for p in input_dir.rglob("*.md")
                if p.is_file() and "_files" not in str(p) and "attachments" not in str(p)
                and p.name not in ("ai-index.md", "政策库.md", "媒体库.md")]
    if args.limit:
        md_files = md_files[:args.limit]

    done = 0
    unknown_site = {}
    for p in md_files:
        item = backfill(p, site_id_map, library)
        if item is None:
            continue
        # 记录 unknown site
        if item["site_id"] == "unknown":
            unknown_site[item["site"]] = unknown_site.get(item["site"], 0) + 1
        # 保持相对目录结构（政策库→国家/机构/xxx）
        rel = p.relative_to(input_dir)
        out_path = output_dir / rel.with_suffix(".md")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(to_qmd(item), encoding="utf-8")
        done += 1

    print(f"[done] 处理 {done} 条")
    if unknown_site:
        print(f"[warn] unknown site（无 site_id 映射）:")
        for k, v in sorted(unknown_site.items()):
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
