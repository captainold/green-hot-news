#!/usr/bin/env python3
"""AI 互打双链接（2026-08-27 P3）：给 Notes/数据库/*.qmd 生成相关条目双链。

流程：规则候选（标签/细类相似度 top N）→ LLM 精选（SiliconFlow DeepSeek-V4-Pro
从候选中选 3-5 条最相关）→ 写 qmd frontmatter `related` 字段 + 正文「相关条目」段。

设计遵循 llm-batch-enrichment 技能：
- 缓存全部结果（含空/失败）key=url；幂等（已有 related 跳过）；断点续跑
- 定期 flush 缓存；逐条异常隔离；进度输出 flush=True
- 规则候选已足够好，LLM 只做精选排序（prompt 小、max_tokens 小）

用法：
    python3.11 scripts/link_qmd_items.py --limit 10        # 小批验证
    python3.11 scripts/link_qmd_items.py --days 30         # 只处理最近 30 天
    python3.11 scripts/link_qmd_items.py                   # 全量（后台跑，可断点续跑）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import requests  # noqa: E402

HISTORY = ROOT / "data" / "history.json"
QMD_DIR = ROOT / "Notes" / "数据库"
CACHE_PATH = ROOT / "data" / "qmd-links-cache.json"

SF_BASE = "https://api.siliconflow.cn/v1"
# 2026-08-27 实测：V4-Pro（reasoning）处理此 prompt 60-120s+ 超时；
# V3 1.9s 返回完美 JSON——相关性选择不需要深度推理，用 V3
SF_MODEL = "deepseek-ai/DeepSeek-V3"
CANDIDATES_N = 8
SELECT_N = 4
MIN_INTERVAL = 0.6  # QPS 控制
_FATAL_STATUS = {401, 402, 403, 429}

PROMPT_TEMPLATE = """你是绿色低碳情报数据库的关联编辑。给定主条目和候选条目，选出 {n} 条与主条目内容**最相关、最有价值**的关联（跨领域隐形关联加分：政策↔产业落地、技术↔金融信号、研究↔应用）。

主条目：{title}（{sub}·{dim}）
摘要：{summary}

候选条目：
{candidates}

只输出 JSON（无其他文字）：{{"selected": [序号数组]}}"""


def _env_key() -> str:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("siliconflow_api_key="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def load_items() -> list[dict]:
    data = json.loads(HISTORY.read_text(encoding="utf-8"))
    return data.get("items", data) if isinstance(data, dict) else data


def load_qmd_map() -> dict[str, Path]:
    """url → qmd 文件路径（frontmatter 的 url 字段匹配）。"""
    m: dict[str, Path] = {}
    for f in QMD_DIR.glob("*.qmd"):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            mm = re.search(r'^url:\s*"([^"]+)"', text, re.MULTILINE)
            if mm:
                m[mm.group(1)] = f
        except Exception:
            continue
    return m


def _tags_of(item: dict) -> set:
    t = set(item.get("topics") or [])
    t.update(item.get("enabling_tech") or [])
    tax = item.get("taxonomy") or {}
    for v in tax.values():
        if v:
            t.add(v)
    if item.get("sub_dimension"):
        t.add(item["sub_dimension"])
    if item.get("dimension"):
        t.add(item["dimension"])
    return t


def rule_candidates(item: dict, items: list[dict], qmd_urls: set[str], n: int = CANDIDATES_N) -> list[dict]:
    """规则候选：标签重叠 + 标题关键词重叠，取 top n（只含已有 qmd 的条目）。"""
    my_tags = _tags_of(item)
    my_title = (item.get("title") or "").lower()
    scored = []
    for other in items:
        url = other.get("url", "")
        if url == item.get("url") or url not in qmd_urls:
            continue
        o_tags = _tags_of(other)
        overlap = len(my_tags & o_tags)
        if overlap == 0:
            continue
        # 标题关键词重叠（去标点后 2+ 字符词）
        o_title = (other.get("title") or "").lower()
        my_words = {w for w in re.split(r"[\W_]+", my_title) if len(w) >= 2}
        o_words = {w for w in re.split(r"[\W_]+", o_title) if len(w) >= 2}
        word_hit = len(my_words & o_words)
        score = overlap * 2 + word_hit
        if score >= 2:
            scored.append((score, other))
    scored.sort(key=lambda x: -x[0])
    return [o for _, o in scored[:n]]


def llm_pick(item: dict, candidates: list[dict]) -> list[int]:
    """LLM 精选：返回选中的候选序号（1-based）。失败返回空。"""
    key = _env_key()
    if not key:
        return []
    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(f"{i}. {c.get('title', '')[:80]}（{c.get('sub_dimension', '')}·{c.get('dimension', '')}）")
    prompt = PROMPT_TEMPLATE.format(
        n=SELECT_N,
        title=(item.get("title") or "")[:80],
        sub=item.get("sub_dimension", ""),
        dim=item.get("dimension", ""),
        summary=(item.get("summary") or "")[:250],
        candidates="\n".join(lines),
    )
    time.sleep(MIN_INTERVAL)
    try:
        r = requests.post(
            f"{SF_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": SF_MODEL,
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 200, "temperature": 0},
            timeout=(15, 60),
        )
        if r.status_code in _FATAL_STATUS:
            return []
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        mm = re.search(r"\{.*\}", content, re.S)
        if not mm:
            return []
        data = json.loads(mm.group(0))
        idx = [int(x) for x in data.get("selected", [])]
        return [i for i in idx if 1 <= i <= len(candidates)]
    except Exception:
        return []


def update_qmd(path: Path, related_titles: list[str]) -> bool:
    """frontmatter 加 related 字段 + 正文追加「相关条目」段。返回是否修改。"""
    text = path.read_text(encoding="utf-8", errors="ignore")
    if "related:" in text.split("---", 2)[1] if text.startswith("---") else False:
        return False  # 幂等：已有 related 跳过
    rel_yaml = "[" + ", ".join(f'"{t[:60]}"' for t in related_titles) + "]"
    # frontmatter 末尾（第二个 --- 前）插入 related
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False
    fm = parts[1].rstrip() + "\n" + f"related: {rel_yaml}\n"
    new_text = "---" + fm + "---" + parts[2]
    # 正文加相关条目段（放在「技术特征」段后、文件末尾前）
    block = "\n## 相关条目\n\n" + "\n".join(f"- [[{t[:60]}]]" for t in related_titles) + "\n"
    if "## 相关条目" not in new_text:
        new_text = new_text.rstrip() + "\n" + block
    path.write_text(new_text, encoding="utf-8")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="AI 互打双链接")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（小批验证）")
    ap.add_argument("--days", type=int, default=0, help="只处理最近 N 天（按 published_at/first_seen_at）")
    args = ap.parse_args()

    items = load_items()
    qmd_map = load_qmd_map()
    print(f"条目 {len(items)} 条，qmd 文件 {len(qmd_map)} 个", flush=True)
    if not qmd_map:
        print("❌ 无 qmd 映射（检查 Notes/数据库）", file=sys.stderr)
        return 1

    cache = _load_cache()
    processed = skipped = linked = 0
    now = time.time()
    for item in items:
        url = item.get("url", "")
        if url not in qmd_map:
            continue
        # 窗口过滤
        if args.days > 0:
            ts = item.get("published_at") or item.get("first_seen_at") or ""
            try:
                import datetime as _dt
                t = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                if now - t > args.days * 86400:
                    continue
            except Exception:
                pass
        # 幂等：已有 related 的 qmd 跳过
        qmd_text = qmd_map[url].read_text(encoding="utf-8", errors="ignore")
        fm_part = qmd_text.split("---", 2)[1] if qmd_text.startswith("---") else ""
        if "related:" in fm_part:
            skipped += 1
            continue
        # 缓存命中
        if url in cache:
            cached = cache[url]
            if cached:
                if update_qmd(qmd_map[url], cached):
                    linked += 1
            processed += 1
            continue

        cands = rule_candidates(item, items, set(qmd_map.keys()))
        if len(cands) < 2:
            cache[url] = []
            processed += 1
            continue
        picked = llm_pick(item, cands)
        if not picked:
            # LLM 失败：规则候选兜底（取前 3，保证有链接）
            picked = list(range(1, min(4, len(cands) + 1)))
        titles = [cands[i - 1].get("title", "")[:60] for i in picked]
        titles = [t for t in titles if t and t != (item.get("title") or "")[:60]]
        if not titles:
            cache[url] = []
            processed += 1
            continue
        cache[url] = titles
        if update_qmd(qmd_map[url], titles):
            linked += 1
        processed += 1
        if processed % 25 == 0:
            _save_cache(cache)
            print(f"进度 {processed}（链接 {linked}，跳过 {skipped}）", flush=True)
        if args.limit and processed >= args.limit:
            break

    _save_cache(cache)
    print(f"完成：处理 {processed}，生成链接 {linked}，跳过（已有）{skipped}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
