# AGENTS.md — 项目指引（后续 agent 必读）

> 本文件给所有进入本仓库的 AI agent（Claude Code / Cursor / Codex / Gemini CLI / Hermes 等）提供权威指引。
> **改代码前先读本文件，涉及打分/标签/运维必须先读对应标准文档。**

## 项目是什么

绿色低碳动态雷达（Green Hot News）——聚合国内外绿色低碳动态，**四维覆盖：政策 / 产业 / 市场信号 / AI**（四维=四个观察窗口而非互斥分类：政策=部委发文动向、产业=企业进展兜底、市场信号=碳市场/绿色资本、AI=AI×绿色落地；2026-08-20 由「政府/行业/金融/AI」改名，见 docs/打分体系标准.md v2.2）。
数据流：服务器每 30 分钟抓取 69 个源 → `data/*.json`（网站数据）+ `Notes/政策库|媒体库/`（Obsidian 素材）→ 人工策展 → `Notes/政策wiki/`。

## 📐 文档权威（改代码前必读）

| 文档 | 权威范围 | 何时必须参考 |
|------|---------|-------------|
| **`docs/打分体系标准.md`** | **打分公式的唯一权威** | **任何涉及打分/评分/排序的代码改动，必须严格参照此文档实现，不得自创公式** |
| `docs/标签体系标准.md` | 标签/关键词体系 | 新增标签、修改关键词、auto_tag 相关改动 |
| `docs/服务器部署与运维.md` | SSH/部署/同步 | 任何服务器操作（WSL 下必须用 cmd.exe + Windows OpenSSH，见文档"WSL 操作服务器"章节） |
| `docs/todo.md` | 项目待办与方向 | 每次会话开始时检查，按勾选状态推进 |

## ⚠️ 打分体系铁律（2026-08-14 v2.0）

1. **打分公式 = `docs/打分体系标准.md` 定义的 v2.2 五维模型**：
   内容强度 30（按维度自适应）+ 来源权威 25 + 主题相关 25 + 人物 10 + 时效 10 = 0-100
2. **内容强度必须按四维自适应**（政策看文件/产业看突破/市场信号看信号/AI看落地）——禁止退回 v1.0 那种"只认政策文件"的单维度类型分（那是技术/AI 被压分的教训）
3. **修改打分 = 修改 `docs/打分体系标准.md` + `scripts/update_news.py` 两处，必须同步**，并跑一轮 `python3.11 scripts/update_news.py --obsidian-dir . --window-hours 96` 验证分布
4. 评分相关前端字段：`score` / `score_level` / `score_breakdown{source,strength,topic,people,freshness}` / `dimension`（注意是 `strength` 不是 `type`）

## 🗂️ 关键架构（一句话版）

- 抓取：`scripts/update_news.py`（70 源，`fetch_*` 函数 + `BUILTIN_SOURCES` 注册；AI 全链条源走 `AI_SITES` 白名单直通，GitHub 开源趋势走 `TECH_SITES` 直通但需绿色/AI 词过滤，人形机器人源走 `ROBOT_SITES` 直通，36氪/虎嗅等 AI 综合媒体走 `AI_MEDIA_SITES` 过滤，X 平台快讯走 `X_SITES` + `X_ACCOUNTS` 账号白名单过滤（2026-08-19 零成本方案：x.com 账号页 SSR 含 schema.org Microdata，requests 直抓，无需 API key）；Google News 源一律单主题词 query + when:30d——括号 OR 语法返回全站混合内容，勿用）
- 打分：`score_item()` → `score_content_strength()`（按维度自适应）/ `score_topic()` / `score_people()` / `score_freshness()`
- 四维分类：`categorize_dimension()`（**2026-08-20 观察窗口化：政策/产业/市场信号/AI**；优先级 AI_SITES直通 > 政府强词(仅标题) > 金融词 > 双碳核心词(A1 双碳优先) > AI词 > 行业词 > 政策库默认政策 > 政策弱词 > 产业兜底；技术突破归产业档，radarai 需绿色/AI 词过滤）
- 前端：`index.html`（两区布局：上方排行榜——主题×周期(日/周/月)×区域(国内/国际)切换；下方实时时间线——跟随筛选、60s 轮询新条目自动插入高亮）+ `assets/app.js` + `assets/styles.css`；数据源 `data/history.json`（62 天累积，含 `region` 字段）+ `data/latest-24h.json`
- 服务器：`/opt/green-hot-news/`（systemd timer 每 30 分钟，非 git 仓库，代码同步靠 scp）
- wiki：`Notes/政策wiki/` 按四维导航（政策/产业/市场信号/AI + 人物横切），新板块归入对应维度

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

### 多终端并行开发纪律（2026-08-19 老温确认：会同时开多个终端写不同功能）

**不用分支隔离**（同一工作目录下 `git checkout` 会重写工作区文件，互相踩踏；独立 clone 又太重）。用三层纪律：

1. **提交纪律**：`git add`/`git commit` 前先 `git diff HEAD --stat` 确认改动范围；update_news.py 等单文件多人改的场景，只 add 自己负责的文件，别人的半成品改动**不要**带进自己的 commit（用 `git add -p` 挑自己的 hunk，或等对方自己提交）
2. **区域约定**：update_news.py 按功能区域切分（fetch 函数区 / BUILTIN_SOURCES / SOURCE_SCORE / SITE_LAYOUT / 关键词区 / 白名单组），并行会话尽量写不同区域，冲突最小；临时探测脚本统一 `scripts/_probe_*.py` 前缀
3. **部署纪律**：谁最后收尾谁 scp 到服务器；scp 前对比服务器 md5 确认同步方向；部署前必须 `py_compile` + 确认 BUILTIN_SOURCES 注册无悬空引用（防半成品崩服务器 timer）
