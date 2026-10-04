#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""板块页「自动快照 / 时间线」生成器（P4-③，2026-10-04）。

设计原则（重要）：
- 板块页（`Notes/政策wiki/<板块>/<板块>.md`）里的人工章节（现状快照/制度与政策/趋势判断）
  **一律不碰**；本脚本只在页尾维护一个带标记的机器块：
      <!-- board-auto:start -->  …  <!-- board-auto:end -->
  标记块内容每次整体重写，因此**不要手工编辑块内内容**。
- 默认 dry-run；`--apply` 才写盘；`--clean` 删除机器块（完全可逆）。

板块 → 素材匹配（素材笔记按 `topics` 字段挂板块）：
- topics 任一命中（可选 keywords 再筛、exclude_keywords 反筛）
- 或按 region / sub_dimension / people 过滤（国际政策、人物两个横切板块）
"""
from __future__ import annotations

import argparse
import datetime
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WIKI = ROOT / "Notes" / "政策wiki"
MAT = ROOT / "Notes" / "素材库"
START = "<!-- board-auto:start -->"
END = "<!-- board-auto:end -->"

# 板块配置：topics=素材 topics 任一命中；keywords=标题/摘要再筛；exclude_keywords=反筛
BOARDS: dict[str, dict] = {
    "碳市场": {"topics": ["碳市场"]},
    "新能源": {"topics": ["新能源", "储能", "电动车", "化石能源"]},
    "电力改革": {"topics": ["电力"]},
    "工业绿色转型": {"topics": ["节能降碳", "循环经济"]},
    "环境保护": {"topics": ["环境保护"]},
    "气候变化": {"topics": ["气候变化"]},
    "绿色金融": {"topics": ["绿色金融"]},
    "AI与能碳": {"topics": ["AI科技"],
               "keywords": ["能源", "碳", "电力", "储能", "绿色", "节能", "光伏", "电网"]},
    "AI进展": {"topics": ["AI科技"],
             "exclude_keywords": ["能源", "碳", "电力", "储能", "绿色", "节能"]},
    "国际政策": {"region_not": "中国", "sub_dimension": "国际动态"},
    "人物": {"people": True},
}

FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.S)


def parse_note(p: pathlib.Path) -> dict | None:
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = FM_RE.match(text)
    if not m:
        return None
    fm: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return {
        "path": p,
        "stem": p.stem,
        "title": fm.get("title", "") or p.stem,
        "date": (fm.get("published_at", "") or "")[:10],
        "score": int(float(fm["score"])) if fm.get("score", "").replace(".", "", 1).isdigit() else 0,
        "dimension": fm.get("dimension", ""),
        "sub_dimension": fm.get("sub_dimension", ""),
        "site": fm.get("site", ""),
        "topics": [x.strip().strip('"') for x in re.findall(r"[^\[\],]+", fm.get("topics", "")) if x.strip()],
        "region": fm.get("region", ""),
        "people": [x.strip().strip('"') for x in re.findall(r"[^\[\],]+", fm.get("people", "")) if x.strip()],
        "text": text[:4000],
    }


def load_mat() -> list[dict]:
    out = []
    for p in MAT.rglob("*.md"):
        n = parse_note(p)
        if n:
            out.append(n)
    return out


def match_board(n: dict, cfg: dict) -> bool:
    if cfg.get("people") and not n["people"]:
        return False
    if cfg.get("sub_dimension") and n["sub_dimension"] != cfg["sub_dimension"]:
        return False
    if cfg.get("region_not") and n["region"] == cfg["region_not"]:
        return False
    if cfg.get("topics") and not (set(cfg["topics"]) & set(n["topics"])):
        return False
    blob = n["title"] + " " + n["text"]
    if cfg.get("keywords") and not any(k in blob for k in cfg["keywords"]):
        return False
    if cfg.get("exclude_keywords") and any(k in blob for k in cfg["exclude_keywords"]):
        return False
    return True


def _dedupe(items: list[dict]) -> list[dict]:
    """同一篇文章的两条 url（站点直连 + Google News 聚合，见 dupN 评估报告）在板块里
    会重复出现（标题只差 `〔mat-xxxxxx〕`/`【dupN】` 后缀）。按「日期 + 规范化标题」去重，
    保留评分最高的一条。"""
    best: dict[tuple[str, str], dict] = {}
    for n in items:
        t = re.sub(r"[【〔](dup\d+|mat-[0-9a-f]+)[】〕]", "", n["title"])
        t = re.sub(r"[\s\-–—:：,，.。!！?？'\"“”‘’]+", "", t).lower()[:36]
        k = (n["date"], t)
        cur = best.get(k)
        if cur is None or n["score"] > cur["score"]:
            best[k] = n
    return list(best.values())


def board_block(name: str, cfg: dict, items: list[dict], days: int, limit: int) -> str:
    today = datetime.date.today()
    since = (today - datetime.timedelta(days=days)).isoformat()
    recent = _dedupe([n for n in items if n["date"] >= since])
    recent.sort(key=lambda n: (n["date"], n["score"]), reverse=True)
    d3 = {"政策": 0, "创新": 0, "产业": 0}
    for n in recent:
        d3[n["dimension"]] = d3.get(n["dimension"], 0) + 1
    avg = round(sum(n["score"] for n in recent) / len(recent), 1) if recent else 0.0
    high = [n for n in recent if n["score"] >= 75]
    why = []
    if cfg.get("topics"):
        why.append("topics: " + "/".join(cfg["topics"]))
    if cfg.get("keywords"):
        why.append("含词 " + "/".join(cfg["keywords"][:4]))
    if cfg.get("exclude_keywords"):
        why.append("排除 " + "/".join(cfg["exclude_keywords"][:4]))
    if cfg.get("sub_dimension"):
        why.append(f"细类={cfg['sub_dimension']} 且非中国")
    if cfg.get("people"):
        why.append("含人物")
    lines = [
        START,
        f"## 自动快照 / 时间线（机器生成，近 {days} 天）",
        "",
        f"> 生成于 {today.isoformat()}｜数据源 `Notes/素材库`｜匹配：{'；'.join(why)}",
        f"> 本节由 `scripts/build_board_snapshots.py` 维护，**块内请勿手工编辑**（每次整体重写）；"
        f"人工内容请写在上方章节。全库匹配 {len(items)} 条。",
        "",
        f"**近 {days} 天 {len(recent)} 条**：政策 {d3.get('政策', 0)}｜创新 {d3.get('创新', 0)}"
        f"｜产业 {d3.get('产业', 0)}｜均分 {avg}｜≥75 分 {len(high)} 条",
        "",
    ]
    if recent:
        lines += ["### 时间线（按发布时间倒序）", "",
                  "| 日期 | 评分 | 层级·细类 | 条目 |", "|---|---|---|---|"]
        for n in recent[:limit]:
            dim = f"{n['dimension']}·{n['sub_dimension']}" if n["sub_dimension"] else n["dimension"]
            disp = n["title"].replace("|", "｜")[:60]
            lines.append(f"| {n['date']} | {n['score']} | {dim} | [[{n['stem']}\\|{disp}]] |")
        lines.append("")
    if high:
        lines += [f"### 近 {days} 天高分（≥75）", ""]
        for n in high[:12]:
            lines.append(f"- **{n['score']}** [[{n['stem']}\\|{n['title'][:52]}]]"
                         f"（{n['date']}｜{n['site']}）")
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="不传则 dry-run")
    ap.add_argument("--clean", action="store_true", help="删除机器块")
    ap.add_argument("--board", default="", help="只处理某板块")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=30, help="时间线最多几条")
    ap.add_argument("--print", dest="do_print", action="store_true", help="打印生成内容")
    args = ap.parse_args()

    pages = sorted(p for p in WIKI.glob("*/*.md") if p.stem != "📚 绿色政策 Wiki")
    if args.board:
        pages = [p for p in pages if p.stem == args.board]
    if not pages:
        print("没有匹配的板块页")
        return 1

    mat = load_mat()
    print(f"素材库载入 {len(mat)} 条")
    stats = []
    for p in pages:
        name = p.stem
        cfg = BOARDS.get(name)
        if not cfg:
            print(f"⚠ 未配置板块，跳过：{name}")
            continue
        text = p.read_text(encoding="utf-8")
        if args.clean:
            if START in text and END in text:
                new = re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n?",
                             "", text, flags=re.S).rstrip() + "\n"
                if args.apply:
                    p.write_text(new, encoding="utf-8")
                print(f"  {'清理' if args.apply else '待清理'} {name}")
            continue
        items = [n for n in mat if match_board(n, cfg)]
        block = board_block(name, cfg, items, args.days, args.limit)
        if args.do_print and (not args.board or args.board == name):
            print("\n" + "=" * 70 + f"\n{name}\n" + "=" * 70)
            print(block)
        if START in text and END in text:
            new = re.sub(re.escape(START) + r".*?" + re.escape(END), block, text, flags=re.S)
            action = "刷新"
        else:
            # 插在「素材索引」之前（索引当页脚更自然），没有该章节则追加到页尾
            anchor = re.search(r"^##\s*素材索引\s*$", text, re.M)
            if anchor:
                new = text[:anchor.start()].rstrip() + "\n\n" + block + "\n\n" + text[anchor.start():]
            else:
                new = text.rstrip() + "\n\n" + block + "\n"
            action = "插入" if anchor else "追加"
        if args.apply and new != text:
            p.write_text(new, encoding="utf-8")
        stats.append((name, len(items), action))
    if not args.clean:
        print(f"\n{'板块':<12}{'全库匹配':>8}  动作")
        for name, n, action in stats:
            print(f"{name:<12}{n:>8}  {action if args.apply else action + '（dry-run）'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
