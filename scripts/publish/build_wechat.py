#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公众号每日图文内容生成（2026-09-23）。

从 digest.json 生成：
1. wechat-article.md —— 图文文章正文（微信编辑器友好排版：短句、层标签、原文链接）
2. 可选上传草稿箱（--draft，需 config.local.json 配 appid/secret；走官方 API，存草稿不群发）

用法：
    python scripts/publish/build_wechat.py               # 只生成 markdown
    python scripts/publish/build_wechat.py --draft       # 生成 + 传草稿箱（首次运行自动拿 token）
输出：data/publish/<date>/wechat-article.md；--draft 时打印 media_id
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import DIM_META, DIM_ORDER, out_dir, today_str, utf8_console

SITE = "ywm.life"


def build_markdown(digest: dict) -> str:
    date = digest["date"]
    dc = digest.get("dim_counts", {})
    n = digest["count"]
    L: list[str] = []
    L.append(f"🌿 绿色低碳动态雷达 · {date} 每日精选")
    L.append("")
    L.append(f"今日从 {digest.get('site_count', 0)} 个信源中精选 **{n} 条**高价值动态："
             f"🏛️ 政策 {dc.get('政策', 0)} ｜ 🔬 创新 {dc.get('创新', 0)} ｜ 💼 产业 {dc.get('产业', 0)}。"
             "按「为什么 → 可能吗 → 成了吗」的创新价值链三层速览。")
    L.append("")

    for dim in DIM_ORDER:
        group = [i for i in digest["items"] if i["dimension"] == dim]
        if not group:
            continue
        meta = DIM_META[dim]
        L.append(f"## {meta['icon']} {dim}层 · {meta['tagline']}")
        L.append("")
        for it in group:
            star = "⭐ 今日焦点：" if it.get("headline") else ""
            region = f"{it['region']} · " if it.get("region") else ""
            L.append(f"### {star}{it['title']}")
            L.append("")
            if it.get("summary"):
                L.append(it["summary"])
                L.append("")
            sub = f" · {it['sub_dimension']}" if it.get("sub_dimension") else ""
            L.append(f"> {region}{it['site_name']}{sub} ｜ ⭐ {it['score']} 分（{it['score_level']} 级）｜ "
                     f"[阅读原文]({it['url']})")
            L.append("")

    L.append("---")
    L.append("")
    L.append(f"📌 打分说明：六维模型（内容强度 30 / 来源权威 20 / 主题相关 25 / 人物 10 / 时效 10 / 技术成熟度 5），"
             f"A 级 ≥70。完整实时榜单见 [{SITE}](https://{SITE})。")
    L.append("")
    L.append("*数据截至 " + digest.get("source_generated_at", "")[:10] + " · 每日 08:30 自动更新*")
    return "\n".join(L) + "\n"


# ---------- 微信草稿箱 API（官方，urllib 零依赖） ----------

def _token(appid: str, secret: str) -> str:
    q = urllib.parse.urlencode({"grant_type": "client_credential", "appid": appid, "secret": secret})
    with urllib.request.urlopen(f"https://api.weixin.qq.com/cgi-bin/token?{q}", timeout=15) as r:
        d = json.loads(r.read())
    if "access_token" not in d:
        raise RuntimeError(f"获取 access_token 失败: {d}")
    return d["access_token"]


def _thumb_media_id(token: str, png_path: Path) -> str:
    """上传永久图片素材作封面（thumb_media_id 必需）。"""
    q = urllib.parse.urlencode({"access_token": token, "type": "image"})
    boundary = "----ghnBoundary7d9f"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"; "
            f"filename=\"{png_path.name}\"\r\nContent-Type: image/png\r\n\r\n").encode() \
        + png_path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"https://api.weixin.qq.com/cgi-bin/material/add_material?{q}",
                                 data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read())
    if "media_id" not in d:
        raise RuntimeError(f"上传封面失败: {d}")
    return d["media_id"]


def push_draft(appid: str, secret: str, title: str, md_path: Path, cover_png: Path) -> str:
    import re as _re
    token = _token(appid, secret)
    # 简易 md → 富文本（微信草稿只认 HTML）：标题/引用/链接/粗体
    html_parts: list[str] = []
    for raw in md_path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        esc = (line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        if line.startswith("### "):
            t = esc[4:]
            m = _re.search(r"\[阅读原文\]\((.*?)\)", t)
            if m:
                t = t.replace(m.group(0), f"<a href='{m.group(1)}'>阅读原文</a>").replace("**", "")
            html_parts.append(f"<h3 style='margin:28px 0 12px;font-size:17px;'>{t.strip()}</h3>")
        elif line.startswith("## "):
            html_parts.append(f"<h2 style='margin:34px 0 14px;font-size:19px;color:#166534;'>{esc[3:].strip()}</h2>")
        elif line.startswith("> "):
            html_parts.append(f"<blockquote style='margin:8px 0;padding:8px 12px;border-left:3px solid #16a34a;"
                              f"color:#888;font-size:13px;'>{esc[2:].strip()}</blockquote>")
        elif line.startswith("**") and line.endswith("**"):
            html_parts.append(f"<p style='font-weight:700;'>{line.strip('*')}</p>")
        elif line:
            t = esc
            t = _re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
            t = _re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"<a href='\2'>\1</a>", t)
            html_parts.append(f"<p style='margin:10px 0;line-height:1.8;'>{t}</p>")
    content = "".join(html_parts)
    thumb = _thumb_media_id(token, cover_png)
    q = urllib.parse.urlencode({"access_token": token})
    payload = {
        "articles": [{
            "title": title[:64],
            "author": "绿色低碳动态雷达",
            "digest": f"今日 {digest_count(md_path)} 条高价值动态精选 · 政策/创新/产业三层速览"[:120],
            "content": content,
            "thumb_media_id": thumb,
            "need_open_comment": 1,
            "only_fans_can_comment": 0,
        }]
    }
    req = urllib.request.Request(f"https://api.weixin.qq.com/cgi-bin/draft/add?{q}",
                                 data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    if "media_id" not in d:
        raise RuntimeError(f"存草稿失败: {d}")
    return d["media_id"]


def digest_count(md_path: Path) -> int:
    import re as _re
    txt = md_path.read_text(encoding="utf-8")
    return len(_re.findall(r"^### ", txt, flags=_re.M))


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description="公众号内容生成")
    parser.add_argument("--date", default=None)
    parser.add_argument("--draft", action="store_true", help="上传到公众号草稿箱")
    args = parser.parse_args()

    date = args.date or today_str()
    odir = out_dir(date)
    digest = json.loads((odir / "digest.json").read_text(encoding="utf-8"))

    md = build_markdown(digest)
    md_path = odir / "wechat-article.md"
    md_path.write_text(md, encoding="utf-8")
    print(f"✅ {md_path}")

    if args.draft:
        from common import load_config
        cfg = load_config().get("wechat", {})
        appid, secret = cfg.get("appid", ""), cfg.get("appsecret", "")
        if not appid or not secret:
            print("❌ 未配置 wechat.appid/appsecret（scripts/publish/config.local.json），跳过草稿箱")
            return 1
        cover = odir / "xhs" / "cover.png"
        if not cover.exists():
            print("❌ 缺封面图（先跑 render_cards.py 生成 cover.png）")
            return 1
        title = f"绿色低碳每日精选 {date}｜{'政策' if digest['dim_counts'].get('政策') else ''}..."
        media_id = push_draft(appid, secret, title, md_path, cover)
        print(f"✅ 草稿箱 media_id: {media_id}\n（登录 mp.weixin.qq.com → 草稿箱 预览/群发）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
