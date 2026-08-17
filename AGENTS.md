# AGENTS.md — 项目指引（后续 agent 必读）

> 本文件给所有进入本仓库的 AI agent（Claude Code / Cursor / Codex / Gemini CLI / Hermes 等）提供权威指引。
> **改代码前先读本文件，涉及打分/标签/运维必须先读对应标准文档。**

## 项目是什么

绿色低碳动态雷达（Green Hot News）——聚合国内外绿色低碳动态，**四维覆盖：政策 / 技术 / 金融 / AI科技**。
数据流：服务器每 30 分钟抓取 19 个源 → `data/*.json`（网站数据）+ `Notes/政策库|媒体库/`（Obsidian 素材）→ 人工策展 → `Notes/政策wiki/`。

## 📐 文档权威（改代码前必读）

| 文档 | 权威范围 | 何时必须参考 |
|------|---------|-------------|
| **`docs/打分体系标准.md`** | **打分公式的唯一权威** | **任何涉及打分/评分/排序的代码改动，必须严格参照此文档实现，不得自创公式** |
| `docs/标签体系标准.md` | 标签/关键词体系 | 新增标签、修改关键词、auto_tag 相关改动 |
| `docs/服务器部署与运维.md` | SSH/部署/同步 | 任何服务器操作（WSL 下必须用 cmd.exe + Windows OpenSSH，见文档"WSL 操作服务器"章节） |
| `docs/todo.md` | 项目待办与方向 | 每次会话开始时检查，按勾选状态推进 |

## ⚠️ 打分体系铁律（2026-08-14 v2.0）

1. **打分公式 = `docs/打分体系标准.md` 定义的 v2.0 五维模型**：
   内容强度 30（按维度自适应）+ 来源权威 25 + 主题相关 25 + 人物 10 + 时效 10 = 0-100
2. **内容强度必须按四维自适应**（政策看文件/技术看突破/金融看信号/AI看落地）——禁止退回 v1.0 那种"只认政策文件"的单维度类型分（那是技术/AI 被压分的教训）
3. **修改打分 = 修改 `docs/打分体系标准.md` + `scripts/update_news.py` 两处，必须同步**，并跑一轮 `python3.11 scripts/update_news.py --obsidian-dir . --window-hours 96` 验证分布
4. 评分相关前端字段：`score` / `score_level` / `score_breakdown{source,strength,topic,people,freshness}` / `dimension`（注意是 `strength` 不是 `type`）

## 🗂️ 关键架构（一句话版）

- 抓取：`scripts/update_news.py`（26 源，`fetch_*` 函数 + `BUILTIN_SOURCES` 注册；AI 全链条源走 `AI_SITES` 白名单直通，GitHub 开源趋势走 `TECH_SITES` 直通）
- 打分：`score_item()` → `score_content_strength()`（按维度自适应）/ `score_topic()` / `score_people()` / `score_freshness()`
- 四维分类：`categorize_dimension()`（优先级 AI科技 > 金融 > 技术 > 政策；AI 判定用标题关键词+词边界正则（radarai 额外看摘要，防反爬水印误判）；技术榜只放绿色低碳技术——GitHub 开源趋势（radarai）AI 项目归 AI科技榜，非 AI 项目落回技术兜底）
- 前端：`index.html`（顶部综合榜 + 政策/技术/金融/AI科技 四维榜）+ `assets/app.js` + `assets/styles.css`
- 服务器：`/opt/green-hot-news/`（systemd timer 每 30 分钟，非 git 仓库，代码同步靠 scp）
- wiki：`Notes/政策wiki/` 按四维导航（政策/技术/金融/AI科技 + 人物横切），新板块归入对应维度

## 🚀 常用命令

```bash
# 本地抓取+生成数据（含打分/四维分类）
python3.11 scripts/update_news.py --obsidian-dir . --window-hours 96

# 只生成网站数据（服务器/CI 模式）
python3.11 scripts/update_news.py --output-dir data --window-hours 24

# 本地预览
python3.11 -m http.server 8899
```

## ⚡ Git 纪律

- 禁止 `rm -rf`、`git reset --hard`、`git push --force`
- 数据文件冲突：`git pull --rebase` + `git checkout --theirs data/`（接受远程）
- 服务器同步走 scp（见 docs/服务器部署与运维.md），GitHub 仅代码归档
