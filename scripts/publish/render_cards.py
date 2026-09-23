#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小红书卡片渲染器（2026-09-23）。

从 digest.json 生成小红书 3:4 知识卡片（封面 + 每日精选 + 尾卡）：
1. 每条新闻渲染一张 HTML 卡片（模板内嵌，绿色低碳视觉）
2. Chrome headless --screenshot 渲染为 1080×1440 PNG（零第三方依赖）

用法：
    python scripts/publish/render_cards.py                  # 默认读今天 digest.json
    python scripts/publish/render_cards.py --date 2026-09-23
输出：data/publish/<date>/xhs/card-01.png ... card-NN.png
"""
from __future__ import annotations

import argparse
import html
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, DIM_META, DIM_ORDER, out_dir, utf8_console

W, H = 1080, 1440  # 小红书 3:4

_CSS = """
* { margin:0; padding:0; box-sizing:border-box; }
body { width:1080px; height:1440px; font-family:'Microsoft YaHei','PingFang SC',sans-serif;
       background:linear-gradient(160deg,#f0fdf4 0%,#ecfeff 55%,#f7fee7 100%); overflow:hidden; }
.card { width:1080px; height:1440px; padding:64px 72px; display:flex; flex-direction:column; }
.kicker { display:flex; align-items:center; gap:16px; }
.brand { font-size:30px; font-weight:700; color:#166534; letter-spacing:2px; }
.date { font-size:26px; color:#4b5563; }
.rule { height:4px; background:linear-gradient(90deg,#16a34a,#06b6d4); border-radius:2px; margin:22px 0 0; }
.dim-badge { display:inline-flex; align-items:center; gap:12px; padding:10px 26px; border-radius:999px;
             font-size:30px; font-weight:700; }
.idx { font-size:120px; font-weight:800; line-height:1; opacity:.14; }
.title { font-size:52px; font-weight:800; line-height:1.35; color:#111827; margin-top:28px; }
.summary { font-size:32px; line-height:1.65; color:#374151; margin-top:34px; }
.meta { margin-top:auto; display:flex; align-items:center; gap:18px; font-size:26px; color:#6b7280; }
.score-chip { padding:8px 20px; border-radius:12px; font-weight:700; font-size:26px; }
.footer { margin-top:26px; padding-top:24px; border-top:2px dashed #d1d5db;
          font-size:24px; color:#9ca3af; display:flex; justify-content:space-between; }
/* 封面专用 */
.cover-brand { font-size:40px; font-weight:800; color:#166534; letter-spacing:4px; }
.cover-date { font-size:34px; color:#374151; margin-top:14px; }
.cover-title { font-size:88px; font-weight:900; line-height:1.28; color:#052e16; margin-top:70px; }
.cover-sub { font-size:34px; color:#374151; margin-top:34px; line-height:1.6; }
.headline-list { margin-top:56px; display:flex; flex-direction:column; gap:30px; }
.hl-item { background:#ffffffcc; border-radius:24px; padding:30px 34px; border-left:12px solid; }
.hl-dim { font-size:26px; font-weight:700; }
.hl-title { font-size:36px; font-weight:700; color:#111827; margin-top:8px; line-height:1.4; }
.cover-footer { margin-top:auto; text-align:center; font-size:28px; color:#6b7280; }
.cover-swipe { margin-top:16px; font-size:30px; color:#16a34a; font-weight:700; text-align:center; }
/* 尾卡 */
.stat-grid { display:grid; grid-template-columns:1fr 1fr; gap:28px; margin-top:60px; }
.stat { background:#ffffffcc; border-radius:24px; padding:38px; text-align:center; }
.stat .num { font-size:84px; font-weight:900; }
.stat .lbl { font-size:28px; color:#6b7280; margin-top:8px; }
.end-note { font-size:34px; line-height:1.8; color:#1f2937; margin-top:64px; }
"""


def _esc(s: str) -> str:
    return html.escape(s or "")


def _dim_style(dim: str) -> tuple[str, str]:
    m = DIM_META.get(dim, {"color": "#374151", "bg": "#f3f4f6"})
    return m["color"], m["bg"]


def html_cover(digest: dict) -> str:
    date = digest["date"]
    heads = [i for i in digest["items"] if i.get("headline")][:3]
    hl_html = ""
    for it in heads:
        color, bg = _dim_style(it["dimension"])
        icon = DIM_META.get(it["dimension"], {}).get("icon", "")
        hl_html += f'''
        <div class="hl-item" style="border-left-color:{color}">
          <div class="hl-dim" style="color:{color}">{icon} {_esc(it["dimension"])}层 · ⭐{_esc(str(it["score"]))}</div>
          <div class="hl-title">{_esc(it["title"])}</div>
        </div>'''
    n = digest["count"]
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{_CSS}</style></head>
<body><div class="card">
  <div class="cover-brand">🌿 绿色低碳动态雷达</div>
  <div class="cover-date">{_esc(date)} · 每日高价值新闻精选</div>
  <div class="rule"></div>
  <div class="cover-title">今日<br>绿色低碳<br>必看 {_n_cn(n)} 条</div>
  <div class="cover-sub">{_esc(str(digest.get("site_count", 0)))} 个信源 × 六维打分 × 三层精选<br>政策 · 创新 · 产业 一图看懂</div>
  <div class="headline-list">{hl_html}</div>
  <div class="cover-footer">数据截至 {_esc(digest.get("source_generated_at", "")[:10])} · 打分体系 v5.0</div>
  <div class="cover-swipe">👉 左滑看今日精选 →</div>
</div></body></html>"""


def _n_cn(n: int) -> str:
    return str(n)


def html_item(digest: dict, it: dict, page_no: int, total: int) -> str:
    color, bg = _dim_style(it["dimension"])
    icon = DIM_META.get(it["dimension"], {}).get("icon", "")
    tagline = DIM_META.get(it["dimension"], {}).get("tagline", "")
    lvl_color = {"A": "#16a34a", "B": "#0e7490"}.get(it.get("score_level", ""), "#6b7280")
    region = f'{it["region"]} · ' if it.get("region") else ""
    sub = f' · {it["sub_dimension"]}' if it.get("sub_dimension") else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{_CSS}</style></head>
<body><div class="card">
  <div class="kicker">
    <span class="brand">🌿 绿色雷达 · 今日精选</span>
    <span class="date">{_esc(digest["date"])}</span>
  </div>
  <div class="rule"></div>
  <div style="display:flex; justify-content:space-between; align-items:flex-end; margin-top:44px">
    <span class="dim-badge" style="background:{bg}; color:{color}">{icon} {_esc(it["dimension"])}层{"" if not tagline else ""}</span>
    <span class="idx">{page_no:02d}</span>
  </div>
  <div style="font-size:26px; color:{color}; margin-top:16px">{_esc(tagline)}</div>
  <div class="title">{_esc(it["title"])}</div>
  <div class="summary">{_esc(it["summary"])}</div>
  <div class="meta">
    <span class="score-chip" style="background:{bg}; color:{color}">⭐ {_esc(str(it["score"]))} 分 · {_esc(it["score_level"])} 级</span>
    <span>{_esc(region)}{_esc(it["site_name"])}{_esc(sub)}</span>
  </div>
  <div class="footer"><span>绿色低碳动态雷达 · 打分体系 v5.0</span><span>{page_no} / {total}</span></div>
</div></body></html>"""


def html_ending(digest: dict) -> str:
    dc = digest.get("dim_counts", {})
    stats = ""
    for d in DIM_ORDER:
        color, bg = _dim_style(d)
        stats += f'''
        <div class="stat" style="background:{bg}">
          <div class="num" style="color:{color}">{dc.get(d, 0)}</div>
          <div class="lbl">{DIM_META[d]["icon"]} {d}层动态</div>
        </div>'''
    top = max(digest["items"], key=lambda i: i["score"]) if digest["items"] else None
    top_html = f'<div style="margin-top:44px; font-size:30px; color:#374151">今日最高分：⭐{top["score"]} 《{_esc(top["title"][:30])}…》</div>' if top else ""
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{_CSS}</style></head>
<body><div class="card">
  <div class="cover-brand">🌿 今日雷达扫描完毕</div>
  <div class="cover-date">{_esc(digest["date"])} · 三层覆盖速览</div>
  <div class="rule"></div>
  <div class="stat-grid">{stats}</div>
  {top_html}
  <div class="end-note">
    📊 每条都经过六维打分（内容强度/来源权威/主题相关/人物/时效/技术成熟度）<br><br>
    🔍 完整榜单与原文链接：<b>ywm.life</b><br><br>
    💬 你最关注哪一条？评论区聊聊
  </div>
  <div class="cover-footer">关注我 · 每天 3 分钟看懂绿色低碳天下事</div>
</div></body></html>"""


def render_png(html_path: Path, png_path: Path) -> None:
    chrome = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    cmd = [chrome, "--headless=new", "--disable-gpu", "--no-first-run",
           "--disable-breakpad", "--crash-dumps-dir=" + str(png_path.parent),
           "--disable-features=Crashpad", "--no-sandbox",
           "--hide-scrollbars", f"--window-size={W},{H}", f"--screenshot={png_path}",
           "--virtual-time-budget=3000", html_path.as_uri()]
    r = subprocess.run(cmd, capture_output=True, timeout=60,
                       encoding="utf-8", errors="replace")
    if not png_path.exists():
        raise RuntimeError(f"Chrome 渲染失败: {(r.stderr or '')[-300:]}")


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description="小红书卡片渲染")
    parser.add_argument("--date", default=None)
    parser.add_argument("--digest", default=None, help="digest.json 路径（默认 data/publish/<date>/digest.json）")
    args = parser.parse_args()

    date = args.date or __import__("common").today_str()
    odir = out_dir(date)
    digest_path = Path(args.digest) if args.digest else odir / "digest.json"
    digest = json.loads(digest_path.read_text(encoding="utf-8"))

    xdir = odir / "xhs"
    xdir.mkdir(exist_ok=True)

    pages: list[tuple[str, str]] = [("cover", html_cover(digest))]
    total = len(digest["items"]) + 2
    for no, it in enumerate(digest["items"], start=2):
        pages.append((f"item-{no:02d}", html_item(digest, it, no, total)))
    pages.append(("ending", html_ending(digest)))

    made = []
    for name, content in pages:
        hp = xdir / f"{name}.html"
        pp = xdir / f"{name}.png"
        hp.write_text(content, encoding="utf-8")
        render_png(hp, pp)
        made.append(pp.name)
        print(f"  🖼 {pp.name}")

    (xdir / "card-plan.json").write_text(json.dumps(
        {"date": date, "cards": made, "size": f"{W}x{H}"}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ {len(made)} 张卡片 → {xdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
