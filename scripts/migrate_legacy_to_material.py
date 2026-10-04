#!/usr/bin/env python3
r"""退役三库 → 素材库 数据迁移（2026-09-23 切库配套）。

背景：P2 合并快照（素材库 10653）定格在 2026-09-15 前后，之后每 30 分钟抓到的新条目
继续落在退役三库（`Notes/数据库`、`Notes/政策库`、`Notes/媒体库`），累计约 2200 条。
切库后素材库是唯一写手，这批存量必须先搬过去，否则永久缺失。

做法（**不重抓正文**，复用三库既有正文）：
1. 以 `data/history.json` + `data/latest-24h*.json` 的 JSON 记录为准提供 v5.0 标签
   （维度/层/细类/评分/TRL/主题/地区/人物/技术特征）——三库笔记的 frontmatter 多是旧口径；
2. 正文取三库笔记的 `## 正文` 段（逐字保留），摘要/技术特征取 frontmatter 或对应段落；
3. 素材稳定 id 与落盘路径统一由 `export_qmd`（`mat/<sha1(url)[:12]>`、`素材库/<层>/<站点>/`）生成；
4. 按 url 对素材库幂等去重（读 `cache/mat-index.json`）。

用法：
    python -X utf8 scripts/migrate_legacy_to_material.py            # dry-run（默认，只报告）
    python -X utf8 scripts/migrate_legacy_to_material.py --apply
    python -X utf8 scripts/migrate_legacy_to_material.py --apply --limit 5
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import export_qmd  # noqa: E402

NOTES = ROOT / "Notes"
SC = NOTES / "素材库"
LEGACY_DIRS = [NOTES / "数据库", NOTES / "政策库", NOTES / "媒体库"]
FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
SKIP_NAMES = {"政策库.md", "媒体库.md"}
RE_SECTION = r"^##\s*{name}\s*$"


def fm_map(fm_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in fm_text.splitlines():
        if ":" in line and not line.startswith((" ", "-")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def section(body: str, name: str) -> str:
    """取 `## name` 段落正文（到下一个 `## ` 或文末）。"""
    m = re.search(RE_SECTION.format(name=name), body, re.M)
    if not m:
        return ""
    rest = body[m.end():]
    nxt = re.search(r"^##\s", rest, re.M)
    return (rest[:nxt.start()] if nxt else rest).strip()


def json_items() -> dict[str, dict]:
    """url → JSON 记录（v5.0 标签的事实源）。"""
    idx: dict[str, dict] = {}
    for name in ("history.json", "latest-24h-all.json", "latest-24h.json"):
        p = ROOT / "data" / name
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        items = d.get("items", d) if isinstance(d, dict) else d
        for it in items:
            if isinstance(it, dict) and it.get("url"):
                idx.setdefault(it["url"], it)
    return idx


def material_urls() -> dict[str, str]:
    """素材库已有 url → 相对路径（优先读 cache/mat-index.json）。"""
    cache = ROOT / "cache" / "mat-index.json"
    try:
        meta = json.loads(cache.read_text(encoding="utf-8"))
        got = {v["url"]: v["path"] for v in meta.values() if v.get("url")}
        if got:
            return got
    except Exception:
        pass
    got = {}
    for f in SC.rglob("*.md"):
        if f.name.startswith("ai-index"):
            continue
        m = re.search(r'^url:\s*"?([^"\n]+)"?\s*$', f.read_text(encoding="utf-8", errors="replace"), re.M)
        if m:
            got[m.group(1).strip()] = str(f.relative_to(SC))
    return got


def name_to_site_id() -> dict[str, str]:
    """站点中文名 → site_id（复用抓取注册表 BUILTIN_SOURCES）。"""
    try:
        import update_news as _un
        return {name: sid for _fn, sid, name in _un.BUILTIN_SOURCES}
    except Exception:
        return {}


def synthesize(url: str, fm: dict[str, str], title: str, site_id: str) -> dict:
    """无 JSON 记录时的兜底条目：标签按笔记原文，缺维度则现场跑 v5.0 分类器。

    退役政策库/媒体库笔记的 frontmatter 只有 source/url/date/tags/keywords/published/
    summary/author/people（无 dimension/score），这批约占迁移量的 47%（403/865），
    URL 已超出 history.json 62 天窗口。此处用 `categorize_dimension` 权威分类，
    评分不臆造（置 0），并在迁移报告里单列条数。
    """
    summary = fm.get("summary", "")
    dim = fm.get("dimension") or ""
    sub = fm.get("sub_dimension") or ""
    layer = fm.get("layer") or ""
    if not dim:
        try:
            import update_news as _un
            lib = _un.site_library(site_id)
            dim, sub = _un.categorize_dimension(site_id, title, summary, lib)
            layer = _un.DIM_TO_LAYER.get(dim, "Layer 2")
        except Exception:
            pass
    return {
        "title": fm.get("title") or title,
        "url": url,
        "site_name": fm.get("site") or fm.get("source") or "unknown",
        "site_id": site_id,
        "published_at": fm.get("published_at") or fm.get("published") or fm.get("date") or "",
        "dimension": dim,
        "layer": layer,
        "sub_dimension": sub,
        "trl": fm.get("trl") or "",
        "region": fm.get("region") or "",
        "score": fm.get("score") or 0,
        "summary": summary,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正写盘（默认 dry-run）")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（试跑）")
    args = ap.parse_args()

    jmap = json_items()
    have = material_urls()
    n2id = name_to_site_id()
    print(f"JSON 记录 {len(jmap)} 条｜素材库已有 url {len(have)} 条｜站点名映射 {len(n2id)} 条")

    stats = Counter()
    by_src: Counter[str] = Counter()
    fb_src: Counter[str] = Counter()
    fb_dim: Counter[str] = Counter()
    samples: list[str] = []
    added: dict[str, str] = {}

    for src_dir in LEGACY_DIRS:
        if not src_dir.exists():
            continue
        for f in sorted(src_dir.rglob("*.md")):
            if f.name.startswith("ai-index") or f.name in SKIP_NAMES:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            m = FM_RE.match(text)
            body = text[m.end():] if m else text
            fm = fm_map(m.group(1)) if m else {}
            url = (fm.get("url") or "").strip()
            if not url:
                stats["无 url"] += 1
                continue
            if url in have or url in added:
                stats["已存在跳过"] += 1
                continue
            t = re.search(r"^#\s+(.+)$", body, re.M)
            title = (fm.get("title") or (t.group(1).strip() if t else f.stem)).strip()
            site_id = fm.get("site_id") or n2id.get(fm.get("site") or fm.get("source") or "", "")
            item = jmap.get(url) or synthesize(url, fm, title, site_id)
            if url not in jmap:
                stats["无 JSON 记录"] += 1
            content = section(body, "正文")
            if not content:
                stats["无正文"] += 1
            else:
                stats["有正文"] += 1
            item = dict(item)
            item["url"] = url
            if fm.get("summary"):
                item["summary"] = fm["summary"]
            if url not in jmap:
                fb_src[src_dir.name] += 1
                fb_dim[f"{item.get('dimension')}·{item.get('sub_dimension')}"] += 1
            if not (item.get("tech_feature") or "").strip():
                tf = section(body, "技术特征")
                if tf:
                    item["tech_feature"] = tf
            if fm.get("author"):
                item.setdefault("author", fm["author"])
            target = export_qmd.target_path(item, SC, True)
            by_src[src_dir.name] += 1
            added[url] = str(target.relative_to(SC))
            if args.apply:
                target.parent.mkdir(parents=True, exist_ok=True)
                new_text = export_qmd.build_qmd(item, content)
                keep = export_qmd.extra_sections(text)
                if keep:
                    new_text = new_text.rstrip() + "\n\n" + keep + "\n"
                target.write_text(new_text, encoding="utf-8")
            if len(samples) < 5:
                samples.append(f"{src_dir.name} → 素材库/{target.relative_to(SC)}")
            stats["写入"] += 1
            if args.limit and stats["写入"] >= args.limit:
                break

    print(f"\n模式: {'APPLY' if args.apply else 'DRY-RUN'}（--limit {args.limit or '无'}）")
    print(f"待迁移/已写: {stats['写入']}｜来源分布: {dict(by_src)}")
    print(f"跳过(素材库已有): {stats['已存在跳过']}｜无 url: {stats['无 url']}｜"
          f"无 JSON 记录(用笔记原文兜底): {stats['无 JSON 记录']}")
    if fb_src:
        print(f"  兜底来源分布: {dict(fb_src)}｜兜底分类分布: {dict(fb_dim.most_common(8))}")
    print(f"正文: 有 {stats['有正文']} / 无 {stats['无正文']}")
    if samples:
        print("样本:")
        for s in samples:
            print("  " + s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
