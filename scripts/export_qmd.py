"""qmd 导出器——把 data/*.json 的条目导出为 .qmd 数据库记录（护城河：本地 Obsidian 多维检索）。

架构（2026-08-24 老温定稿）：**qmd 为主格式，md 为副本**。
- 主：Notes/数据库/*.qmd —— 多维标签 frontmatter + 富文本全文（图片/表格/结构）+ 技术特征
- 副本：Notes/数据库/*.md —— 内容相同，兼容 Obsidian 原生生态（插件/工具只认 .md 的场景）
- 图片附件：Notes/数据库/attachments/（md5 命名，qmd/md 内相对路径引用）

用法：
    python3.11 scripts/export_qmd.py                     # 默认 latest-24h.json → Notes/数据库/
    python3.11 scripts/export_qmd.py --input data/history.json --output Notes/数据库
    python3.11 scripts/export_qmd.py --limit 10          # 小批验证（先看质量再全量）
    python3.11 scripts/export_qmd.py --force             # 重新抓取正文（覆盖已有）
    python3.11 scripts/export_qmd.py --refresh-frontmatter  # 只重建 YAML 多维标签（正文保留，不重抓——分类规则/打分规则改后的历史刷新）

幂等：已有正文的 qmd 跳过（除非 --force）；图片附件 md5 命名天然去重。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import article_content  # noqa: E402

# 正文抓取并发（qmd 全量 984 条 × 2-5s 抓取 + 图片下载，串行太久）
_FETCH_WORKERS = 4
# 正文有效长度阈值（低于视为抓取失败/导航垃圾页）
_MIN_BODY_CHARS = 200


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
        s = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[" + ", ".join(_yaml_scalar(x) for x in v) + "]"
    return '""'


def build_qmd(item: dict, content: str = "") -> str:
    """构建完整 qmd 内容：YAML frontmatter + 元信息 + 摘要 + 正文（富文本）+ 技术特征。"""
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
    if content:
        lines.append("## 正文")
        lines.append("")
        lines.append(content)
        lines.append("")
    if tech_feature:
        lines.append("## 技术特征")
        lines.append("")
        lines.append(tech_feature)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def fetch_rich_body(item: dict, att_dir: Path, session) -> tuple[str, int]:
    """抓取富文本正文 + 下载图片附件。

    返回 (markdown_content, 图片数)。失败返回 ("", 0)。
    """
    url = item.get("url", "")
    if not url:
        return "", 0
    # arxiv 高分论文（score >= 55）抓 PDF 全文替代 abs 页摘要（2026-08-24 老温定）
    if "arxiv.org/abs" in url and (item.get("score") or 0) >= 55:
        pdf_text = article_content.fetch_arxiv_pdf(url, session=session)
        if pdf_text:
            return pdf_text, 0  # PDF 全文纯文本，无图片附件
    res = article_content.fetch_article(url, session=session, rich=True)
    if not res or not res.get("content"):
        return "", 0
    content: str = res["content"] or ""
    if len(content) < _MIN_BODY_CHARS:
        return "", 0
    # 下载正文图片 → attachments/（相对路径引用；referer=原页面 URL 解决防盗链）
    content, n_img = article_content.download_images(content, att_dir, session=session, referer=url)
    return content, n_img


def export(input_path: Path, output_dir: Path, force: bool = False,
           limit: int = 0, md_copy: bool = False,
           only_sites: Optional[set] = None) -> int:
    """导出条目为 qmd（qmd 主格式），返回写入的文件数。

    md_copy=True（2026-08-24 起默认关闭）：额外写一份 .md 副本。
    老温定稿「qmd 为主格式」——Obsidian Quarto 插件已可用，md 副本
    会在 Obsidian 文件浏览器造成同名双文件干扰，默认不再生成。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import requests as _req

    if not input_path.exists():
        print(f"  输入不存在: {input_path}")
        return 0
    data = json.loads(input_path.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    output_dir.mkdir(parents=True, exist_ok=True)
    att_dir = output_dir / "attachments"

    # 已存在的 qmd 文件 → 按 url 去重；已有正文的跳过（幂等）
    existing_urls: set[str] = set()
    for f in output_dir.glob("*.qmd"):
        try:
            text = f.read_text(encoding="utf-8")
            m = re.search(r'^url:\s*"([^"]+)"', text, re.MULTILINE)
            if m:
                existing_urls.add(m.group(1))
        except Exception:
            continue

    # 待处理：新 url + （force 或 旧文件无正文）
    pending: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # 只导出指定站点（2026-08-27：us_doe/openai 服务器 403 无正文，
        # 本地 Clash 出口可抓 → --only-sites 定向重导出回填正文）
        if only_sites and item.get("site_id") not in only_sites:
            continue
        url = item.get("url", "")
        if url and url in existing_urls:
            fname = f"{_date_of(item)} {_safe_filename(item.get('title', ''))}.qmd"
            fpath = output_dir / fname
            if not force and fpath.exists():
                txt = fpath.read_text(encoding="utf-8", errors="ignore")
                if "## 正文" in txt and len(txt) > _MIN_BODY_CHARS + 400:
                    continue  # 已有正文，跳过
            pending.append(item)
            continue
        pending.append(item)
    if limit:
        pending = pending[:limit]

    if not pending:
        print(f"  {input_path.name}: 无待导出条目（全部已有正文）→ {output_dir}")
        return 0

    print(f"  {input_path.name}: {len(pending)} 条待导出（含正文抓取+图片下载）→ {output_dir}")
    session = _req.Session()
    session.headers.update({"User-Agent": article_content.BROWSER_UA,
                            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})

    written = 0
    no_body = 0
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as ex:
        futs = {ex.submit(fetch_rich_body, it, att_dir, session): it for it in pending}
        for fut in as_completed(futs):
            it = futs[fut]
            try:
                content, n_img = fut.result()
            except Exception:
                content, n_img = "", 0
            if not content:
                no_body += 1
            fname = f"{_date_of(it)} {_safe_filename(it.get('title', ''))}.qmd"
            qmd_text = build_qmd(it, content)
            (output_dir / fname).write_text(qmd_text, encoding="utf-8")
            if md_copy:
                # md 副本（默认关闭——Obsidian 同名双文件干扰，见 export docstring）
                (output_dir / fname.replace(".qmd", ".md")).write_text(qmd_text, encoding="utf-8")
            if it.get("url"):
                existing_urls.add(it["url"])
            written += 1
            if written % 20 == 0:
                print(f"    进度 {written}/{len(pending)}（无正文 {no_body}）", flush=True)

    print(f"  {input_path.name}: 写入 {written} 条 qmd（{no_body} 条无正文），图片附件 → {att_dir}")
    return written


def backfill_images(output_dir: Path, md_copy: bool = False) -> int:
    """补图模式（2026-08-24）：对已有正文的 qmd 只做图片下载补全。

    首次全量导出时部分源站图 404/超时失败（保留原 URL）——重跑正文浪费，
    此模式只提取正文中的 http 图片 → 下载到 attachments/ → 重写 qmd+md。
    404 死链自动保留原 URL（Obsidian 点击可打开）。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import requests as _req

    output_dir = Path(output_dir)
    att_dir = output_dir / "attachments"
    files = [f for f in output_dir.glob("*.qmd")
             if re.search(r"!\[[^\]]*\]\(https?://", f.read_text(encoding="utf-8", errors="ignore"))]
    if not files:
        print("  无待补图 qmd（正文无 http 图片引用）")
        return 0
    print(f"  {len(files)} 个 qmd 待补图 → {att_dir}")

    session = _req.Session()
    session.headers.update({"User-Agent": article_content.BROWSER_UA})

    def _work(f: Path) -> int:
        text = f.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^## 正文\s*$", text, re.M)
        if not m:
            return 0
        # 从 frontmatter 读 url 作为 Referer（防盗链）
        m_url = re.search(r'^url:\s*"?([^"\n]+)"?\s*$', text, re.M)
        referer = m_url.group(1).strip() if m_url else ""
        body = text[m.end():]
        new_body, n = article_content.download_images(body, att_dir, session=session, referer=referer)
        if n == 0:
            return 0
        new_text = text[:m.end()] + new_body
        f.write_text(new_text, encoding="utf-8")
        if md_copy:
            md = f.with_suffix(".md")
            if md.exists():
                md.write_text(new_text, encoding="utf-8")
        return n

    total = 0
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as ex:
        futs = {ex.submit(_work, f): f for f in files}
        for fut in as_completed(futs):
            total += fut.result()
    print(f"  补图完成：{total} 张（404 死链自动保留原 URL）")
    return total


def refresh_frontmatter(input_path: Path, output_dir: Path) -> int:
    """仅刷新 frontmatter 模式（2026-08-25）：不重抓正文，只重建 YAML 头部多维标签。

    用途：分类规则/打分规则改进后，历史 qmd 的 frontmatter 标签过时——
    全量重导会重抓正文（浪费 + 服务器禁 --force），此模式按 url 匹配
    已存在的 qmd，用最新 JSON 重建 frontmatter，正文部分原样保留。

    返回刷新的文件数；新条目（JSON 有、磁盘无）跳过，留待主流程增量导出。
    """
    if not input_path.exists():
        print(f"  输入不存在: {input_path}")
        return 0
    data = json.loads(input_path.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    # url → item（同 url 取最后一条）
    by_url: dict[str, dict] = {}
    for it in items:
        if isinstance(it, dict) and it.get("url"):
            by_url[it["url"]] = it

    refreshed = 0
    skipped_no_fm = 0
    fm_re = re.compile(r"^---\n.*?\n---\n", re.DOTALL | re.MULTILINE)
    for f in sorted(output_dir.glob("*.qmd")):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        m_url = re.search(r'^url:\s*"([^"]+)"', text, re.MULTILINE)
        if not m_url:
            skipped_no_fm += 1
            continue
        item = by_url.get(m_url.group(1))
        if not item:
            continue  # 该 url 不在本次输入 JSON（可能是其他输入文件导出的），跳过
        new_fm = build_frontmatter(item)
        lines = ["---"]
        for k, v in new_fm.items():
            lines.append(f"{k}: {_yaml_scalar(v)}")
        lines.append("---")
        new_head = "\n".join(lines) + "\n"
        m = fm_re.match(text)
        if not m:
            skipped_no_fm += 1
            continue
        if m.group(0) == new_head:
            continue  # frontmatter 未变化，跳过写盘
        f.write_text(new_head + text[m.end():], encoding="utf-8")
        refreshed += 1
    print(f"  {input_path.name}: 刷新 {refreshed} 个 qmd frontmatter"
          f"（无 frontmatter/格式异常 {skipped_no_fm}，新条目待主流程增量导出）")
    return refreshed


def main() -> int:
    ap = argparse.ArgumentParser(description="qmd 数据库导出器（qmd 主 + md 副本 + 富文本全文）")
    ap.add_argument("--input", default=str(ROOT / "data" / "latest-24h.json"))
    ap.add_argument("--output", default=str(ROOT / "Notes" / "数据库"))
    ap.add_argument("--force", action="store_true", help="重新抓取正文（覆盖已有）")
    ap.add_argument("--limit", type=int, default=0, help="只导出前 N 条（小批验证用）")
    ap.add_argument("--backfill-images", action="store_true",
                    help="补图模式：只对已有正文的 qmd 下载图片（不重抓正文）")
    ap.add_argument("--refresh-frontmatter", action="store_true",
                    help="仅刷新 frontmatter：按 url 重建 YAML 多维标签，正文保留（不重抓）")
    ap.add_argument("--md-copy", action="store_true",
                    help="额外写 .md 副本（默认关闭——Obsidian 同名双文件干扰）")
    ap.add_argument("--only-sites", default="",
                    help="只导出指定 site_id（逗号分隔，如 us_doe,openai）——定向重导出/回填用")
    args = ap.parse_args()

    out = Path(args.output)
    if args.backfill_images:
        total = backfill_images(out, md_copy=args.md_copy)
        print(f"完成，共补图 {total} 张")
        return 0
    if args.refresh_frontmatter:
        total = refresh_frontmatter(Path(args.input), out)
        print(f"完成，共刷新 {total} 个 qmd frontmatter")
        return 0
    only = {s.strip() for s in args.only_sites.split(",") if s.strip()}
    total = export(Path(args.input), out, args.force, args.limit, args.md_copy,
                   only_sites=only or None)
    print(f"完成，共写入 {total} 条 qmd")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
