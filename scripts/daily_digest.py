#!/usr/bin/env python3
"""当日高分浓缩版生成器（2026-08-17）。

从 data/latest-24h.json 取评分 ≥ --min-score（默认 70，A 级以上）条目，
四维分组、清洗标题/摘要噪音、每源配额（防刷屏）、新鲜度过滤（默认 7 天内），
生成可直接转发微信群 / 朋友圈 / 自媒体的文本。

输出：data/daily-digest.md（纯文本风格 markdown，微信粘贴友好）

用法：
    python3.11 scripts/daily_digest.py                 # 默认 top 15
    python3.11 scripts/daily_digest.py --top 10 --output /tmp/d.md
    python3.11 scripts/daily_digest.py --all           # 全部 A 级以上条目
    python3.11 scripts/daily_digest.py --per-site 3    # 每源最多 3 条

服务器 green-policy-sync.sh 每次抓取后调用，前端「当日浓缩」弹窗读取展示。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DIM_ICON = {"政策": "🏛️", "技术": "🔋", "金融": "💰", "AI科技": "🤖"}
DIM_ORDER = ["政策", "技术", "金融", "AI科技"]
TOTAL_SITES = 47  # 雷达信源总数（README/信息收集目标列表同步维护）


def clean_title(title: str) -> str:
    """标题清洗：去「摘要：」尾巴、小编/天前水印、"- 站点名"冗余、折叠空白。"""
    t = re.sub(r"\s+", " ", title or "").strip()
    if "摘要：" in t:
        t = t.split("摘要：", 1)[0].strip()
    # 去尾部 "小编 3天前" / "编辑 3天前" 类水印
    t = re.sub(r"[\u4e00-\u9fff]{0,6}(小编|编辑)\s*[^\u4e00-\u9fff]*\d*[天小时分]?前\s*$", "", t)
    # 去尾部 " - 站点名" / " - 来源" 冗余
    t = re.sub(r"\s*[-–—]\s*[^，。；！？、\s]{2,24}$", "", t).strip()
    return t


def _flat_pos(s: str, k: int) -> int:
    """去空白后第 k 个字符在原文 s 中的位置（用于按扁平长度精确截取原文）。"""
    n = 0
    for i, ch in enumerate(s):
        if ch.isspace():
            continue
        if n == k:
            return i
        n += 1
    return len(s)


def clean_summary(title: str, summary: str) -> str:
    """摘要清洗：取「摘要：」后正文、去水印/文章来源/重复标题、限长 90 字。"""
    s = re.sub(r"\s+", " ", summary or "").strip()
    if not s:
        return ""
    if "摘要：" in s:
        s = s.split("摘要：", 1)[1].strip()
    s = re.sub(r"发布时间：\d{4}-\d{2}-\d{2}\s*", "", s)
    s = re.sub(r"[\u4e00-\u9fff]{0,6}(小编|编辑)\s*[^\u4e00-\u9fff]*\d*[天小时分]?前", "", s)
    # 文章来源水印（"文章来源:中国石化报 李忠东 2026-07-16 14:18" 等）
    s = re.sub(r"^文章来源[:：]\s*[^\s，。；]{1,24}\s*\d{4}[-/]\d{2}[-/]\d{2}\s*\d{2}:\d{2}\s*", "", s)
    # 摘要开头若重复标题（含 "通 知"→"知" 这类残字），循环截掉（上海环交所格式最多重复两遍）。
    # 只截「标题与摘要实际重合的公共前缀」，按扁平索引映射回原文，避免空格错位/多截正文
    t_flat = re.sub(r"\s+", "", title)
    s_flat = re.sub(r"\s+", "", s)
    for _ in range(3):
        if len(t_flat) <= 4:
            break
        skip = 0
        while skip < 3 and not s_flat[skip:].startswith(t_flat[:12]):
            skip += 1
        if skip >= 3:
            break
        common = 0
        while (skip + common < len(s_flat) and common < len(t_flat)
               and s_flat[skip + common] == t_flat[common]):
            common += 1
        if common < 12:
            break
        start = _flat_pos(s, skip)
        end = _flat_pos(s, skip + common)
        s = (s[:start] + s[end:]).strip(" ，。、：;；:,.·-—")
        s_flat = re.sub(r"\s+", "", s)
    return s[:90].rstrip("，。、；：,.;: ") + ("…" if len(s) > 90 else "")
    return s[:90].rstrip("，。、；：,.;: ") + ("…" if len(s) > 90 else "")


def fmt_date(iso_str: str) -> str:
    """2026-08-14T08:08:00Z → 08-14。"""
    if not iso_str:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso_str)
    return f"{m.group(2)}-{m.group(3)}" if m else ""


def parse_iso(dt_str: str) -> datetime | None:
    """解析 ISO 时间（daily_digest 独立脚本，不复用 update_news 的 dateutil）。"""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?", dt_str or "")
    if not m:
        return None
    try:
        dt = datetime(*[int(x) for x in m.groups()[:6] if x is not None], tzinfo=timezone.utc)
    except Exception:
        return None
    return dt


def build_digest(items: list[dict], top: int, min_score: int, generated_at: str,
                 per_site: int = 2, max_age_days: int = 7, site_count: int = TOTAL_SITES) -> str:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days) if max_age_days else None

    cand: list[dict] = []
    for i in items:
        sc = i.get("score") or 0
        if sc < min_score:
            continue
        pa = parse_iso(i.get("published_at") or "")
        if pa and cutoff and pa < cutoff:
            continue  # 太旧（旧闻回流：工信部 gzdt 曾翻出 2025-12 旧文）
        cand.append(i)
    cand.sort(key=lambda x: -(x.get("score") or 0))

    # 按 URL 去重（同源截断标题会指向同一链接，如碳交易网 "…(ECMI)$54.74" 与 "…(E"）
    seen_url: set[str] = set()
    cand = [i for i in cand
            if (i.get("url") or "").rstrip("/") not in seen_url
            and not seen_url.add((i.get("url") or "").rstrip("/"))]

    # 每源配额（防同源刷屏，如上海环交所碳市场高频条目）
    picked: list[dict] = []
    per_site_n: dict[str, int] = {}
    for i in cand:
        sid = i.get("site_id", "")
        if per_site and per_site_n.get(sid, 0) >= per_site:
            continue
        per_site_n[sid] = per_site_n.get(sid, 0) + 1
        picked.append(i)
        if top and len(picked) >= top:
            break

    by_dim: dict[str, list[dict]] = {}
    for it in picked:
        by_dim.setdefault(it.get("dimension") or "其他", []).append(it)

    lines: list[str] = []
    lines.append("🌿 绿色低碳动态雷达 · 当日高分浓缩")
    lines.append(f"📅 {generated_at[:10]} ｜ {site_count} 个信源 ｜ A级以上精选 {len(picked)} 条")
    lines.append("")

    for dim in DIM_ORDER:
        group = by_dim.get(dim, [])
        if not group:
            continue
        lines.append(f"【{DIM_ICON.get(dim, '')} {dim} · {len(group)} 条】")
        for idx, it in enumerate(group, 1):
            title = clean_title(it.get("title", ""))
            site = it.get("site_name", "")
            d = fmt_date(it.get("published_at", ""))
            meta = f"{site}" + (f" · {d}" if d else "")
            lines.append(f"{idx}. {title}（{meta}）⭐{it.get('score')}")
            summ = clean_summary(title, it.get("summary", ""))
            if summ:
                lines.append(f"　　{summ}")
            url = (it.get("url") or "").strip()
            if url:
                lines.append(f"🔗 {url}")
            lines.append("")
        lines.append("")

    dist = " / ".join(f"{DIM_ICON[d]} {d} {len(by_dim.get(d, []))}" for d in DIM_ORDER if by_dim.get(d))
    lines.append(f"📊 分布：{dist}")
    lines.append("")
    lines.append(f"—— 绿色低碳动态雷达 · {TOTAL_SITES} 信源 · 政策/技术/金融/AI科技 四维 ——")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="当日高分浓缩版生成器")
    parser.add_argument("--data", default="data/latest-24h.json", help="数据文件")
    parser.add_argument("--output", default="data/daily-digest.md", help="输出文件")
    parser.add_argument("--top", type=int, default=15, help="最多条数（0 = 全部）")
    parser.add_argument("--min-score", type=int, default=70, help="最低分数（A 级=70）")
    parser.add_argument("--per-site", type=int, default=2, help="每源最多条数（防刷屏）")
    parser.add_argument("--max-age-days", type=int, default=7, help="最长时间（天），0 = 不限")
    args = parser.parse_args()

    try:
        d = json.loads(Path(args.data).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ 读取数据失败: {e}", file=sys.stderr)
        return 1
    items = d.get("items", d) if isinstance(d, dict) else d
    text = build_digest(items, args.top, args.min_score, d.get("generated_at", ""),
                        args.per_site, args.max_age_days, d.get("site_count", TOTAL_SITES))
    Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    print(f"\n✅ 已写入 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
