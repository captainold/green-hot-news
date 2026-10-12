#!/usr/bin/env bash
# Green Policy Radar — 定时抓取 + 整理 + 提交素材层
#
# ⚠️ 本文件是服务器 /opt/green-hot-news/green-policy-sync.sh 的**版本控制副本**
#    （2026-10-12 起纳入仓库；此前只存在于服务器，改动不入库）。
#    修改后部署：scp green-policy-sync.sh root@47.82.211.111:/opt/green-hot-news/ && \
#                ssh ... "chmod +x /opt/green-hot-news/green-policy-sync.sh && bash -n /opt/green-hot-news/green-policy-sync.sh"
#    行尾必须是 LF（Windows write_text 默认 CRLF 会毁 shebang —— 2026-10-08 踩坑）。
set -euo pipefail
cd /opt/green-hot-news

export PATH="/root/.local/bin:$PATH"

# 1) 抓取新闻 + 导出 Obsidian 笔记 + 生成网站数据
.venv/bin/python scripts/update_news.py --obsidian-dir . --window-hours 96

# 1.05) 素材索引每日重建（派生缓存 cache/mat-index.json + ai-index-*.md）
#   为什么必须有这一步（2026-10-12 流量事故）：export_qmd 判重优先读 cache/mat-index.json，
#   索引里没有的 url 会被当成新条目**重抓正文**。索引只由本脚本重建 → 不重建 = 索引冻结，
#   冻结之后新增的条目每轮都重抓（实测单轮 ~140MB 走 qqpw 家宽代理，节点流量超额主因）。
#   （export_qmd.export() 另有落盘路径兜底判重，双保险；本步是让存量走快路径。）
if [ -f cache/mat-index.json ]; then
    IDX_AGE=$(( $(date +%s) - $(stat -c %Y cache/mat-index.json) ))
else
    IDX_AGE=999999
fi
if [ "$IDX_AGE" -gt 72000 ]; then   # 20h：每天重建一次（扫描 1.6 万笔记约 1 分钟）
    .venv/bin/python scripts/build_material_index.py --apply >/dev/null 2>&1 \
        || echo "⚠ mat-index rebuild failed (export 兜底判重仍生效)"
fi

# 1.1) 空摘要增量补抓（S0-A2，2026-10-09 老温批可）：新条目中空摘要的补正文摘要——
#      限额 60 条/轮（历史积压自动逐轮消化）+ 失败冷却（cache/web-summary-cache.json 7 天）；
#      写回 data/*.json + 素材库 md frontmatter（持久层，主流程每轮回读）。
#      失败不阻断主流程；systemd 环境自带 HTTPS_PROXY（夏威夷家宽出口）。
#   2026-10-12 降频：改为**每小时一批**（原来每轮 30 分钟一批）——补抓与导出抢同一条家宽出口，
#      轮内并发把单轮代理流量顶高（实测 60 条 ≈ 29MB/轮）；每小时 60 条 + 3 并发，日总量不变峰值减半。
BF_LAST_FILE=cache/.summary-backfill-last
if [ -f "$BF_LAST_FILE" ]; then
    BF_AGE=$(( $(date +%s) - $(stat -c %Y "$BF_LAST_FILE") ))
else
    BF_AGE=999999
fi
if [ "$BF_AGE" -gt 3300 ]; then     # 55 分钟：每小时最多一批
    touch "$BF_LAST_FILE"
    .venv/bin/python scripts/backfill_web_summaries.py --apply --limit 60 --workers 3 \
        || echo "summary backfill failed"
fi

# 1.5) 健康追踪（管理面板 admin/data/ 数据源）
.venv/bin/python scripts/health_tracker.py || echo "health tracker failed"

# 1.6) 当日高分浓缩版（前端「📋 当日浓缩」数据源；失败不阻断主流程）
.venv/bin/python scripts/daily_digest.py >/dev/null || echo "daily digest failed"

# 1.7) 数据质量检查（QA：只报告不修复，输出 data/qa-report.json + qa-report.md，供人工/agent 会话开始时审阅）
.venv/bin/python scripts/qa_check.py || echo "qa check failed"



# 2) 素材层 git 提交（服务器生成 + 本地 Obsidian 手工编辑双向同步）
if [ -d /srv/git/green-policy-materials.git ]; then
    # 2a) 提交服务器侧新生成/修改的笔记（无改动则跳过）
    git -C /opt/green-hot-news/Notes add -A
    if ! git -C /opt/green-hot-news/Notes diff --cached --quiet; then
        git -C /opt/green-hot-news/Notes -c user.name="green-policy-bot" \
            -c user.email="bot@ywm.life" \
            commit -m "sync: update materials $(date -u '+%Y-%m-%d %H:%M UTC')"
    fi
    # 2b) 双向同步竞态修复（2026-08-14 v2）：
    #     -X theirs：索引文件（ai-index.md / 媒体库.md / 政策库.md）两端都会重写，
    #     冲突必然发生 → 自动取远程（本地 Obsidian）版本，rebase 不中断；
    #     服务器新笔记文件正常重放。素材层内容文件服务器只新增不修改，
    #     非索引文件冲突概率≈0。万一仍失败（rename/delete 等）→ abort 保留下周期。
    git -C /opt/green-hot-news/Notes pull --rebase -X theirs origin master --quiet || {
        echo "⚠ notes rebase conflict — abort, retry next cycle"
        git -C /opt/green-hot-news/Notes rebase --abort 2>/dev/null || true
    }
    # 2c) push；失败只提示（下个周期自动重试，不在此嵌套 pull 避免 rebase 卡住）
    if ! git -C /opt/green-hot-news/Notes push origin master --quiet; then
        echo "⚠ notes push deferred — retry next cycle"
    fi
fi

# 3) 站点数据提交（供 nginx 直接服务 /opt/green-hot-news）
if [ -d /opt/green-hot-news/.git ]; then
    git -C /opt/green-hot-news add data/ admin/index.html index.html assets/ scripts/ 2>/dev/null || true
    if ! git -C /opt/green-hot-news diff --cached --quiet; then
        git -C /opt/green-hot-news -c user.name="green-policy-bot" \
            -c user.email="bot@ywm.life" \
            commit -m "sync: update site data $(date -u '+%Y-%m-%d %H:%M UTC')" || true
    fi
fi

echo "✓ $(date '+%Y-%m-%d %H:%M:%S') sync done"
