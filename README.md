# Green Hot News · 绿色低碳动态雷达

国内外最新绿色低碳动态聚合站：**政策 + 技术 + 金融 + AI科技** 四维覆盖。自动抓取政府、国际组织、行业媒体、绿色科技媒体、AI 全链条媒体、全网热榜的绿色低碳动态（24 源），通过新加坡服务器定时更新，Nginx 部署为静态站点，Obsidian 笔记库双向同步。内置**打分体系 v2.0**（内容强度按四维自适应 + 来源权威 + 主题相关 + 人物 + 时效，五维加权 0-100），前端**综合榜 + 四维榜**展示 + 分数徽章（S/A/B/C/D 等级）。

## 在线入口

- 线上页面：`https://ywm.life`（新加坡服务器 Nginx 直出，顶部综合评分排行榜 + 政策/技术/金融/AI科技 四维榜）
- 管理面板：`https://ywm.life/admin/`（消息源健康监控，Basic Auth 保护，不公开；账号见 docs/服务器部署与运维.md）
- GitHub 镜像：`https://captainold.github.io/green-hot-news/`（仅代码归档，CI 已禁用）
- Obsidian 笔记库：`C:\Users\wenyu\Documents\Obsidian_wen\green-hot-news\Notes\`
- 服务器部署与运维文档：[docs/服务器部署与运维.md](docs/服务器部署与运维.md)

## 架构总览（2026-08-14 现状）

```
新加坡服务器 47.82.211.111 (Alibaba Cloud Linux 3)
├── systemd timer: green-policy.timer（每30分钟）
│     └→ green-policy-sync.sh
│           ├─ 1. update_news.py 抓取 24 个源
│           │     ├─ 官方部委/国际组织 → Notes/政策库/
│           │     ├─ 媒体/热榜/AI → Notes/媒体库/（四维分类 + 打分 v2.0）
│           │     └─ 生成 data/*.json 网站数据（含 score/dimension 字段）
│           ├─ 2. Notes/ git commit + push → /srv/git/green-policy-materials.git
│           └─ 3. data/ 站点数据更新（nginx 直接服务）
└── nginx: https://ywm.life → /opt/green-hot-news/

本地 Windows (Obsidian)
└── Obsidian Git 插件 (basePath=Notes)
      ├─ 每15分钟 auto-pull ← 服务器 bare 仓库
      ├─ 每15分钟 auto-save (commit)
      └─ 每30分钟 auto-push → 服务器 bare 仓库
```

## 覆盖范围（25 个源，2026-08-14 服务器为准）

### 国内政策源（政策库 · 中国）
- 国家发改委、生态环境部、生态环境部·解读、国家能源局、工信部

### 国际政策源（政策库 · 国际组织）
- IEA、IRENA、UNFCCC、World Bank Climate

### 行业媒体（媒体库）
- Carbon Brief、Reuters Energy、北极星电力网、中国碳交易网、碳道、中国能源报

### 绿色科技/AI（媒体库）
- **Climate Change AI**（AI×气候交叉）、**中国科技网**（科技日报）、**CleanTechnica**（清洁技术）

### AI 领域全链条（媒体库 · 2026-08-14 AI 维度扩充）
> 理论 → 模型 → 市场 → 商业 全覆盖，AI_SITES 白名单直通（不进绿色关键词过滤）
- **OpenAI**（模型发布一手，RSS 限量 30）
- **arXiv cs.AI**（理论前沿，RSS 限量 30）
- **机器之心 / 量子位**（中文 AI 头部媒体，Google News fallback）
- **VentureBeat AI**（国际 AI 商业，RSS 限量 30）
- **AIHOT**（`aihot.virxact.com`，AI 行业动态聚合：X/公众号/RSS 几十源，精选 RSS 每 30 分钟抓取，带热度与 AI 评分；2026-08-14 接入）

### 全网热点（媒体库 · 2026-08-13 新增）
- **allnet.hot**（`https://api.allnet.hot/api/open/v1`）：抓取微博热搜、知乎热榜、今日头条热榜、澎湃热榜、IT之家最新 5 个榜单
- 靠 `POLICY_KEYWORDS`（碳/能源/气候/环保/ESG…）过滤，只保留绿色政策相关热榜条目
- API Key：本地 `.env` / 服务器 `/etc/green-policy.env`（`ALLNET_API_KEY`），未配置时静默跳过

## 本地运行

```bash
# 依赖
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 首次：复制 .env.example → .env，填入 ALLNET_API_KEY

# 抓取 + 导出 Obsidian 笔记
python3.11 scripts/update_news.py --obsidian-dir . --window-hours 720

# 只生成网站数据
python3.11 scripts/update_news.py --output-dir data --window-hours 24
```

## 四维定位（2026-08-14 主题升级）

| 维度 | 定位 | 信源 |
|------|------|------|
| 🏛️ 政策 | 制度锚点 | 4部委 + 官方解读 + 4国际组织 |
| 🔋 技术 | 产业脉搏 | 中国能源报、北极星、CleanTechnica |
| 💰 金融 | 市场温度计 | 碳交易网、碳道、Carbon Brief |
| 🤖 AI科技 | 新视野（理论→模型→市场→商业 + 交叉） | OpenAI、arXiv·AI、机器之心、量子位、VentureBeat AI、Climate Change AI、中国科技网 |

## 数据输出

- `data/latest-24h.json` — 24小时绿色动态信号（过滤后，含 `score`/`score_level`/`score_breakdown`/`dimension` 字段）
- `data/latest-24h-all.json` — 24小时全量数据
- `data/source-status.json` — 24 个源健康状态
- `data/published-index.json` — 发布时间索引
- `data/title-index.json` — 完整标题索引
- `data/summary-index.json` — 摘要索引（前端可展开摘要，News Minimalist 风格）

## 同步机制

- **服务器 → 本地**：服务器每 30 分钟抓取并提交，本地 Obsidian Git 插件每 15 分钟 `git pull`（经 SSH 别名 `sg-moltbot` → 47.82.211.111）
- **本地 → 服务器**：Obsidian 内编辑 wiki/笔记，插件每 30 分钟 `git push`
- **SSH 通道**：Windows `C:\Users\wenyu\.ssh\`（密钥 `moltbot260130.pem` + config 别名 `sg-moltbot`），注意本地 DNS 有代理劫持（198.18.x fake-ip），必须用 IP/别名而非域名
- **代码通道**：GitHub `captainold/green-hot-news` 仅归档，CI 已禁用

## 项目背景

本项目是中咨公司气候处绿色低碳咨询工作的基础设施。通过持续追踪国内外绿色低碳政策动态，支撑政策研究、项目评审和战略咨询工作。

作者：老温 (captainold) · 中咨公司气候处
