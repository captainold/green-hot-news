# AGENTS.md — 项目指引（后续 agent 必读）

> 本文件给所有进入本仓库的 AI agent（Claude Code / Cursor / Codex / Gemini CLI / Hermes 等）提供权威指引。
> **改代码前先读本文件，涉及打分/标签/运维必须先读对应标准文档。**

## 项目是什么

绿色低碳创新动态雷达（Green Hot News）——聚合国内外绿色低碳动态，**三层覆盖：政策 / 创新 / 产业**（2026-08-26 v5.0 中性命名，按**创新价值链**排序：政策=政府发文·国际动态（为什么）、创新=技术研发·基础研究·社会创新（可能吗）、产业=企业经营·金融资本（成了吗）；三层不按领域区分，科技/文化/工业/社会学按**技术阶段/性质**入层，见 docs/标准文档/打分体系标准.md v5.0）。
数据流：服务器每 30 分钟抓取 70 个源 → `data/*.json`（网站数据）+ `Notes/政策库|媒体库/`（Obsidian 素材）→ 人工策展 → `Notes/政策wiki/` + `Notes/数据库/`（qmd 多维标签数据库，正文走 mihomo 代理抓取）。

## 📐 文档权威（改代码前必读）

| 文档 | 权威范围 | 何时必须参考 |
|------|---------|-------------|
| docs/标准文档/本体与标签词典.md | 多维标签系统的唯一权威 | 任何涉及分类/标签/TRL/国际分类/技术特征/qmd 的改动，必须参照此文档 |
| **`docs/标准文档/打分体系标准.md`** | **打分公式的唯一权威** | **任何涉及打分/评分/排序的代码改动，必须严格参照此文档实现，不得自创公式** |
| `docs/标准文档/标签体系标准.md` | 标签/关键词体系 | 新增标签、修改关键词、auto_tag 相关改动 |
| `docs/服务器部署与运维.md` | SSH/部署/同步 | 任何服务器操作（WSL 下必须用 cmd.exe + Windows OpenSSH，见文档"WSL 操作服务器"章节） |
| `docs/todo/todo.md` | 项目待办与方向 | 每次会话开始时检查，按勾选状态推进 |

### 📁 docs 目录规则（2026-08-26 老温定稿）

- **`docs/标准文档/`**：权威标准类文档（打分体系标准、本体与标签词典、标签体系标准等关键规范）。**新增标准/规范类文档一律放此目录**，并同步更新本表。
- **`docs/todo/`**：全部待办文件（todo.md 长期待办 + 每日 todolist + 调研/核查报告）。**新增待办、当日工作日志、调研报告一律放此目录**。
- docs/ 根目录只保留设计（底层数据库构建方法等）、方案（tech_feature 提取方案等）、运维（服务器部署与运维）等非标准、非待办文档。

## ⚠️ 打分体系铁律（2026-08-26 v5.0）

1. **打分公式 = `docs/标准文档/打分体系标准.md` 定义的 v5.0 六维模型**：
   内容强度 30（按七细类自适应）+ 来源权威 20 + 主题相关 25 + 人物 10 + 时效 10 + 技术成熟度 TRL 5 = 0-100
2. **内容强度必须按七细类自适应**（政策法规看文件/国际动态看协议/技术研发看突破/基础研究看发表/社会创新看机制模式创新/企业经营看进展/金融资本看信号）——禁止退回 v1.0 那种"只认政策文件"的单维度类型分（那是技术/AI 被压分的教训）
3. **修改打分 = 修改 `docs/标准文档/打分体系标准.md` + `scripts/update_news.py` 两处，必须同步**，并跑一轮 `python3.11 scripts/update_news.py --obsidian-dir . --window-hours 96` 验证分布
4. 评分相关前端字段：`score` / `score_level` / `score_breakdown{source,strength,topic,people,freshness,trl}` / `dimension`（三层中文：政策/创新/产业） / `sub_dimension`（七细类）/ `trl`（注意是 `strength` 不是 `type`）

## 🗂️ 关键架构（一句话版）

- 抓取：`scripts/update_news.py`（70 源，`fetch_*` 函数 + `BUILTIN_SOURCES` 注册；AI 全链条源走 `AI_SITES` 白名单直通，GitHub 开源趋势走 `TECH_SITES` 直通但需绿色/AI 词过滤，人形机器人源走 `ROBOT_SITES` 直通，36氪/虎嗅等 AI 综合媒体走 `AI_MEDIA_SITES` 过滤，X 平台快讯走 `X_SITES` + `X_ACCOUNTS` 账号白名单过滤（2026-08-19 零成本方案：x.com 账号页 SSR 含 schema.org Microdata，requests 直抓，无需 API key）；Google News 源一律单主题词 query + when:30d——括号 OR 语法返回全站混合内容，勿用）
- 打分：`score_item()` → `score_content_strength()`（按维度自适应）/ `score_topic()` / `score_people()` / `score_freshness()`
- 三层分类：`categorize_dimension()`（**2026-08-26 v5.0：政策/创新/产业 + 七细类**；优先级 DIM_SITE_OVERRIDE > AI_SITES 分流 > TECH_SITES(创新·技术研发) > 政府强词(仅标题) > 国际动态词 > 金融词 > 双碳核心词(A1 双碳优先) > 社会创新词 > AI 词分流 > 基础研究窄词 > 技术研发词 > 企业经营词 > 政策库默认 > 政策弱词 > 产业兜底；**AI 按技术阶段分流**：论文/研究报告→创新·基础研究、模型/产品发布→产业·企业经营、其余研发→创新·技术研发；碳普惠/碳账户/绿色金融产品→产业层（老温 08-26 决策）；radarai 需绿色/AI 词过滤）
- 前端：`index.html`（两区布局：上方排行榜——主题×周期(日/周/月)×区域(国内/国际)切换；下方实时时间线——跟随筛选、60s 轮询新条目自动插入高亮）+ `assets/app.js` + `assets/styles.css`；数据源 `data/history.json`（62 天累积，含 `region` 字段）+ `data/latest-24h.json`
- 服务器：`/opt/green-hot-news/`（systemd timer 每 30 分钟，非 git 仓库，代码同步靠 scp；正文抓取经 mihomo 代理 → 夏威夷家宽出口，见 docs/服务器部署与运维.md）
- wiki：`Notes/政策wiki/` 按三层导航（政策/创新/产业 + 人物横切），新板块归入对应层

## 🚀 常用命令

```bash
# 本地抓取+生成数据（含打分/三层分类）
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
