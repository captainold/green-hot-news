#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日发布工作流总入口（2026-09-23）。

流程：精选 → 小红书卡片 → 小红书文案 → 公众号 markdown（可选草稿箱）
半自动设计：跑完后人工过目，用随附的发布指引完成最后一步。

用法：
    python scripts/publish/daily_publish.py --all            # 全流程（不含草稿箱）
    python scripts/publish/daily_publish.py --all --draft    # 全流程 + 公众号草稿箱
    python scripts/publish/daily_publish.py --refresh        # 先本地刷新数据（兜底）
输出：data/publish/<date>/
    digest.json            精选结构
    xhs/card-*.png         小红书卡片（封面+内容+尾卡）
    xhs-post.md            小红书文案（标题+正文+标签）
    wechat-article.md      公众号图文正文
    publish-checklist.md   人工发布指引
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, out_dir, today_str, utf8_console


def run_step(script: str, *extra: str) -> bool:
    cmd = [sys.executable, str(Path(__file__).parent / script), *extra]
    print(f"\n▶ {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=ROOT)
    return r.returncode == 0


def write_checklist(odir: Path, date: str, n: int) -> None:
    p = odir / "publish-checklist.md"
    p.write_text(f"""# 发布清单 · {date}

## 1. 小红书（App 手动发，浏览器自动化有风控风险）
1. 打开 `xhs/` 目录，按 01 封面 → 02… 内容 → 末尾尾卡顺序上传图片
2. 文案：复制 `xhs-post.md`（TITLE 行 = 标题，其余 = 正文，已含话题标签）
3. 发布后把笔记链接记到本文件末尾

## 2. 微信公众号（mp.weixin.qq.com）
- 方式 A（推荐）：登录公众号后台 → 图文新建 → 粘贴 `wechat-article.md` 内容
  （Obsidian/Typora 打开该文件 → 全选复制 → 微信编辑器粘贴，格式自动保留）
- 方式 B：已配 appid/appsecret 时，重跑 `python scripts/publish/daily_publish.py --draft`
  → 草稿箱自动出现本文，后台点群发即可

## 3. 收尾
- 发布完成后运行：`python scripts/publish/mark_published.py --date {date}`
  （把本批 URL 记入已发布指纹，明日精选自动去重）

---
- 产物：{n} 条精选
- 生成时间：{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')}
- 小红书笔记链接：
- 公众号文章链接：
""", encoding="utf-8")
    print(f"✅ {p}")


def main() -> int:
    utf8_console()
    parser = argparse.ArgumentParser(description="每日发布工作流")
    parser.add_argument("--date", default=None)
    parser.add_argument("--all", action="store_true", help="跑全流程")
    parser.add_argument("--refresh", action="store_true", help="先本地刷新数据（兜底）")
    parser.add_argument("--draft", action="store_true", help="公众号传草稿箱")
    args = parser.parse_args()
    date = args.date or today_str()

    if args.refresh:
        print("⏳ 本地刷新数据（兜底；服务器 timer 正常时可跳过）……")
        subprocess.run([sys.executable, str(ROOT / "scripts" / "update_news.py"),
                        "--obsidian-dir", ".", "--window-hours", "96"], cwd=ROOT)

    if not args.all:
        parser.error("请给 --all（或 --refresh 单独刷新）")
        return 2

    odir = out_dir(date)
    ok = True
    ok &= run_step("select_daily.py", "--date", date)
    ok &= run_step("render_cards.py", "--date", date)
    ok &= run_step("build_xhs.py", "--date", date)
    ok &= run_step("build_wechat.py", "--date", date)
    if not ok:
        print("❌ 有步骤失败，检查上方输出")
        return 1

    import json
    digest = json.loads((odir / "digest.json").read_text(encoding="utf-8"))
    write_checklist(odir, date, digest["count"])

    if args.draft:
        ok &= run_step("build_wechat.py", "--date", date, "--draft")

    print(f"\n🎉 全流程完成 → {odir}")
    print("下一步：人工过目 digest.json/卡片/文案 → 按 publish-checklist.md 发布")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
