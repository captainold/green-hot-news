#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书文案生成（2026-09-23）。

从 digest.json 生成符合小红书调性的发布包：
1. xhs-post.md —— 标题（≤20 字）+ 正文（≤1000 字，emoji 分行 + 话题标签）
2. 发布指引（浏览器自动化路径说明）

用法：python scripts/publish/build_xhs.py [--date 2026-09-23]
输出：data/publish/<date>/xhs-post.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DIM_META, DIM_ORDER, out_dir, today_str, utf8_console

SITE = "ywm.life"


def pick_title(digest: dict) -> str:
    """小红书标题 ≤20 字：优先头条冲击力，兜底数字式标题。"""
    heads = [i for i in digest["items"] if i.get("headline")]
    if heads:
        t = max(heads, key=lambda i: i["score"])
        raw = t["title"].strip("“”\"「」『』")
        if len(raw) <= 18:
            return raw
        # 截短到 18 字内可读断点（引号视作整体边界，避免停在半个词上）
        cut = raw[:18]
        for sep in ("：", "，", " ", "、", "｜", "“", "「", "『"):
            if sep in cut:
                cut = cut[:cut.rfind(sep)]
                break
        cut = cut.rstrip("“”\"「」『』，。、·—")  # 别停在半个词/引号上
        return cut + ("…" if len(raw) > len(cut) + 2 else "")
    return f"今日绿色低碳必看 {digest['count']} 条"


def build(digest: dict) -> str:
    date = digest["date"]
    n = digest["count"]
    dc = digest.get("dim_counts", {})
    title = pick_title(digest)

    L: list[str] = []
    L.append(f"🌿 每日速览 {date[5:]}｜{n} 条绿色低碳大事件")
    L.append("")
    L.append(f"每天从 {digest.get('site_count', 0)}+ 信源里筛出最值得看的动态，"
             f"政策/创新/产业三层覆盖，3 分钟看完👇")
    L.append("")
    for dim in DIM_ORDER:
        group = [i for i in digest["items"] if i["dimension"] == dim]
        if not group:
            continue
        meta = DIM_META[dim]
        L.append(f"{meta['icon']} {dim}层（{dc.get(dim, 0)}）")
        for idx, it in enumerate(group, 1):
            head = "🔥 " if it.get("headline") else "· "
            L.append(f"{head}{it['title']}")
            if it.get("headline") and it.get("summary"):
                s = it["summary"][:60]
                L.append(f"　{s}{'…' if len(it['summary']) > 60 else ''}")
        L.append("")
    L.append("📊 打分怎么看？六维模型：内容强度/来源权威/主题相关/人物/时效/技术成熟度，"
             "70 分以上才算 A 级入选。")
    L.append("")
    L.append(f"🔗 完整榜单+原文链接：{SITE}")
    L.append("")
    L.append("你最关注哪一条？评论区告诉我，明天重点追踪👇")
    L.append("")
    L.append("#碳中和 #绿色低碳 #新能源 #双碳 #政策解读 #行业动态 #可持续发展 #ESG")

    body = "\n".join(L)
    # 小红书正文上限 1000 字
    if len(body) > 1000:
        body = body[:996] + "……"
        # 保底把话题标签放回去
        body = body.rsplit("\n", 1)[0] + "\n" + "#碳中和 #绿色低碳 #新能源 #双碳 #可持续发展"
    return f"TITLE: {title}\n\n{body}\n"


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description="小红书文案生成")
    parser.add_argument("--date", default=None)
    args = parser.parse_args()
    date = args.date or today_str()
    odir = out_dir(date)
    digest = json.loads((odir / "digest.json").read_text(encoding="utf-8"))

    text = build(digest)
    out = odir / "xhs-post.md"
    out.write_text(text, encoding="utf-8")
    title = text.splitlines()[0][7:]
    body_len = len(text) - len(text.split("\n\n", 1)[0]) - 2
    print(f"✅ {out}")
    print(f"   标题（{len(title)} 字）: {title}")
    print(f"   正文 {body_len} 字 / 上限 1000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
