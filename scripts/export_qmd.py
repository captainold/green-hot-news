"""qmd 导出器——把 data/*.json 的条目导出为 .qmd 数据库记录（护城河：本地 Obsidian 多维检索）。

每条新闻生成一个 .qmd 文件：YAML frontmatter 含全部多维标签（layer/taxonomy/enabling_tech/trl/tech_feature），
正文含标题/摘要/技术特征/原文链接。放在 Notes/数据库/ 目录（扁平，靠 frontmatter 标签多维检索，而非树状目录）。

用法：
    python3.11 scripts/export_qmd.py                     # 默认导出 latest-24h.json → Notes/数据库/
    python3.11 scripts/export_qmd.py --input data/history.json --output Notes/数据库

幂等：同 url 已存在的文件跳过（除非 --force）。
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _safe_filename(title: str) -> str:
    """去文件系统非法字符 + 控制长度。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", title or "").strip()
    return s[:80] or "untitled"


def _date_of(item: dict) -> str:
    """取发布日期（YYYY-MM-DD），无则取首次抓取。"""
    for key in ("published_at", "first_seen_at"):
        v = (item.get(key) or "")[:10]
        if v:
            return v
    return "undated"


def build_frontmatter(item: dict) -> dict:
    """从 JSON 条目提取多维标签，构建 YAML frontmatter 字段（taxonomy 展平为独立字段，便于 Obsidian 检索）。"""
    tax = item.get("taxonomy") or {}
    return {
        "title": item.get("title", ""),
        "title_zh": item.get("title_zh", ""),
        "url": item.get("url", ""),
        "site": item.get("site_name", ""),
        "site_id": item.get("site_id", ""),
        "dimension": item.get("dimension", ""),
        "layer": item.get("layer", ""),
        "sub_dimension": item.get("sub_dimension", ""),
        "trl": item.get("trl", ""),
        "eu_taxonomy": tax.get("eu_taxonomy", ""),
        "isic": tax.get("isic", ""),
        "gics": tax.get("gics", ""),
        "ipc": tax.get("ipc", ""),
        "enabling_tech": item.get("enabling_tech") or [],
        "tech_feature": item.get("tech_feature", ""),
        "topics": item.get("topics") or [],
        "region": item.get("region", ""),
        "people": item.get("people") or [],
        "score": item.get("score", 0),
        "score_level": item.get("score_level", ""),
        "published_at": item.get("published_at", ""),
    }


def _yaml_scalar(v) -> str:
    """标量转 YAML（字符串加引号，列表转 [a, b]，空转 ""）。"""
    if isinstance(v, str):
        # 含特殊字符用双引号
        s = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[" + ", ".join(_yaml_scalar(x) for x in v) + "]"
    return '""'


def build_qmd(item: dict) -> str:
    """构建完整 qmd 内容：YAML frontmatter + 正文。"""
    fm = build_frontmatter(item)
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {_yaml_scalar(v)}")
    lines.append("---")
    lines.append("")

    title = item.get("title", "")
    url = item.get("url", "")
    site = item.get("site_name", "")
    published = item.get("published_at", "")
    score = item.get("score", 0)
    level = item.get("score_level", "")
    summary = (item.get("summary") or "").strip()
    tech_feature = (item.get("tech_feature") or "").strip()
    title_zh = (item.get("title_zh") or "").strip()

    lines.append(f"# {title}")
    lines.append("")
    if title_zh and title_zh != title:
        lines.append(f"*{title_zh}*")
        lines.append("")
    if url:
        lines.append(f"[原文链接]({url})")
        lines.append("")
    meta = f"> 来源: {site} | 发布时间: {published} | 评分: {score} ({level})"
    lines.append(meta)
    lines.append("")
    if summary:
        lines.append("## 摘要")
        lines.append("")
        lines.append(summary)
        lines.append("")
    if tech_feature:
        lines.append("## 技术特征")
        lines.append("")
        lines.append(tech_feature)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def export(input_path: Path, output_dir: Path, force: bool = False) -> int:
    """导出条目为 qmd，返回写入的文件数。"""
    if not input_path.exists():
        print(f"  输入不存在: {input_path}")
        return 0
    data = json.loads(input_path.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    output_dir.mkdir(parents=True, exist_ok=True)

    # 已存在的 qmd 文件 → 按 url 去重（除非 force）
    existing_urls: set[str] = set()
    if not force:
        for f in output_dir.glob("*.qmd"):
            try:
                text = f.read_text(encoding="utf-8")
                m = re.search(r'^url:\s*"([^"]+)"', text, re.MULTILINE)
                if m:
                    existing_urls.add(m.group(1))
            except Exception:
                continue

    written = 0
    skipped = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        url = item.get("url", "")
        if url and url in existing_urls:
            skipped += 1
            continue
        fname = f"{_date_of(item)} {_safe_filename(item.get('title', ''))}.qmd"
        (output_dir / fname).write_text(build_qmd(item), encoding="utf-8")
        if url:
            existing_urls.add(url)
        written += 1
    print(f"  {input_path.name}: 写入 {written} 条，跳过 {skipped} 条（已存在）→ {output_dir}")
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="qmd 数据库导出器")
    ap.add_argument("--input", default=str(ROOT / "data" / "latest-24h.json"))
    ap.add_argument("--output", default=str(ROOT / "Notes" / "数据库"))
    ap.add_argument("--force", action="store_true", help="覆盖已存在的同名文件")
    args = ap.parse_args()

    total = export(Path(args.input), Path(args.output), args.force)
    print(f"完成，共写入 {total} 条 qmd")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
