#!/usr/bin/env python3.11
"""tech_feature 正文回填——用 trafilatura 正文重新提取技术特征（2026-08-24）。

背景：extract_tech_feature 原本只喂 title+summary（summary 常为空/导语），
导致大量有技术细节的新闻（技术参数在正文里）被判「无」。现加正文输入后，
批量回填 Layer2/3 + tech_feature 空/无 + qmd 有正文的条目。

流程：
1. 读 tech-feature-index.json 缓存（url → tech_feature，避免重复调 LLM）
2. 遍历 Notes/数据库/*.qmd，解析 frontmatter + ## 正文 节
3. 候选 = layer∈{Layer2,Layer3} 且 tech_feature∈{空,"无"} 且正文非空 且不在缓存
4. 并发 4 调 extract_tech_feature(title, summary, content) 重新提取
5. 提取到特征（非「无」非空）→ 回填 qmd frontmatter + 写缓存
6. 幂等 + 断点续跑（每 10 条落盘缓存）

用法：
    python3.11 scripts/backfill_tech_feature.py --limit 50   # 试点
    python3.11 scripts/backfill_tech_feature.py              # 全量
    python3.11 scripts/backfill_tech_feature.py --dry-run    # 只统计不提取
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import tech_feature as tf  # noqa: E402

NOTES_DIR = ROOT / "Notes" / "数据库"
CACHE_PATH = ROOT / "data" / "tech-feature-index.json"
CONTENT_MAX = 2000

# frontmatter 字段正则
_RE_LAYER = re.compile(r'^layer:\s*"?([^"\n]+)"?\s*$', re.M)
_RE_TF = re.compile(r'^tech_feature:\s*"?([^"\n]*)"?\s*$', re.M)
_RE_URL = re.compile(r'^url:\s*"?([^"\n]+)"?\s*$', re.M)
_RE_TITLE = re.compile(r'^title:\s*"?(.+?)"?\s*$', re.M)
_RE_BODY = re.compile(r'^##\s*正文\s*$', re.M)
_RE_SUMMARY = re.compile(r'^##\s*摘要\s*$', re.M)


def load_cache() -> dict[str, str]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _clean_body(body: str) -> str:
    """正文清洗：去 markdown 符号，留实质文字。"""
    body = re.sub(r'^---\s*\n?', '', body)  # 去分隔线
    body = re.sub(r'^#\s.*\n', '', body)    # 去重复标题行
    body = re.sub(r'!\[[^\]]*\]\([^)]*\)', '', body)  # 图片
    body = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', body)  # 链接留文字
    body = re.sub(r'[#*_>`|]', '', body)    # 去 markdown 符号
    body = re.sub(r'\s+', ' ', body).strip()
    return body[:CONTENT_MAX]


def parse_qmd(fp: Path) -> dict | None:
    """解析 qmd：返回 {url, title, layer, tech_feature, summary, content} 或 None。"""
    try:
        txt = fp.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    m_layer = _RE_LAYER.search(txt)
    m_tf = _RE_TF.search(txt)
    m_url = _RE_URL.search(txt)
    m_title = _RE_TITLE.search(txt)
    if not m_layer or not m_tf:
        return None
    layer = m_layer.group(1).strip()
    tf_val = m_tf.group(1).strip()
    if layer not in ("Layer 2", "Layer 3"):
        return None
    if tf_val not in ("", "无", "None", "null"):
        return None
    # 摘要节
    summary = ""
    m_sum = _RE_SUMMARY.search(txt)
    if m_sum:
        seg = txt[m_sum.end():]
        m_next = re.search(r'^##\s', seg, re.M)
        summary = (seg[:m_next.start()] if m_next else seg).strip()[:500]
    # 正文节
    content = ""
    m_body = _RE_BODY.search(txt)
    if m_body:
        seg = txt[m_body.end():]
        content = _clean_body(seg)
    if len(content) < 50:
        return None  # 正文太短，不值得重提
    return {
        "path": fp,
        "url": (m_url.group(1).strip() if m_url else ""),
        "title": (m_title.group(1).strip() if m_title else ""),
        "layer": layer,
        "tech_feature": tf_val,
        "summary": summary,
        "content": content,
    }


def update_qmd_tf(fp: Path, new_tf: str) -> None:
    """回填 qmd frontmatter 的 tech_feature 字段。"""
    txt = fp.read_text(encoding="utf-8", errors="ignore")
    new_txt = _RE_TF.sub(lambda m: f'tech_feature: "{new_tf}"', txt, count=1)
    fp.write_text(new_txt, encoding="utf-8")


def sync_data_json(filled: dict[str, str]) -> int:
    """按 url 回填 data/*.json 的 tech_feature 字段（空才回填，不覆盖已有值）。"""
    updated = 0
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
            if u in filled and not it.get("tech_feature"):
                it["tech_feature"] = filled[u]
                updated += 1
        if is_dict:
            data["items"] = items
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"  data JSON 回填：{updated} 条 tech_feature", flush=True)
    return updated


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（0=全量）")
    ap.add_argument("--dry-run", action="store_true", help="只统计候选，不提取")
    args = ap.parse_args()

    cache = load_cache()
    qmd_files = sorted(NOTES_DIR.glob("*.qmd"))

    # 收集候选
    candidates: list[dict] = []
    for fp in qmd_files:
        info = parse_qmd(fp)
        if not info:
            continue
        key = info["url"] or info["title"]
        if key in cache and cache[key] and cache[key] != "无":
            continue  # 已提取过且非"无"，跳过
        if key in cache and cache[key] == "无":
            # 之前判"无"（无正文时），现在有正文了 → 值得重提
            pass
        candidates.append(info)
        if args.limit and len(candidates) >= args.limit:
            break

    print(f"候选（Layer2/3 + tf空/无 + 有正文）: {len(candidates)} 条", flush=True)
    if args.dry_run or not candidates:
        return 0

    saved = 0
    filled = 0
    still_none = 0
    filled_map: dict[str, str] = {}  # url → 新提取的 tech_feature（用于 data JSON 同步）

    def _extract(info: dict):
        return info, tf.extract_tech_feature(info["title"], info["summary"], info["content"])

    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(_extract, c): c for c in candidates}
        for i, fut in enumerate(as_completed(futs), 1):
            info, result = fut.result()
            key = info["url"] or info["title"]
            if result and result != "无":
                update_qmd_tf(info["path"], result)
                cache[key] = result
                if info["url"]:
                    filled_map[info["url"]] = result
                filled += 1
                print(f"  [{i}/{len(candidates)}] ✅ {result[:40]} | {info['title'][:40]}", flush=True)
            else:
                cache[key] = "无"
                still_none += 1
                print(f"  [{i}/{len(candidates)}] · 无 | {info['title'][:40]}", flush=True)
            saved += 1
            if saved % 10 == 0:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n完成：提取到特征 {filled} 条 / 仍无 {still_none} 条（共 {saved}）", flush=True)
    if filled_map:
        sync_data_json(filled_map)
    print(f"缓存已更新：{len(cache)} 条 → {CACHE_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
