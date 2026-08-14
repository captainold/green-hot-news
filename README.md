# Green Hot News · 绿色低碳动态雷达

国内外最新绿色低碳动态聚合站：**政策 + 技术 + 金融 + AI科技** 四维覆盖。自动抓取政府、国际组织、行业媒体、绿色科技媒体、全网热榜的绿色低碳动态，通过新加坡服务器定时更新，Nginx 部署为静态站点，Obsidian 笔记库双向同步。内置五维打分体系（来源权威/政策类型/主题相关/人物/时效），前端双栏展示 + 分数徽章。

## 在线入口

- 线上页面：`https://ywm.life`（新加坡服务器 Nginx 直出，双栏：官方新闻｜媒体新闻）
- GitHub 镜像：`https://captainold.github.io/green-hot-news/`（仅代码归档，CI 已禁用）
- Obsidian 笔记库：`C:\Users\wenyu\Documents\Obsidian_wen\green-hot-news\Notes\`
- 服务器部署与运维文档：[docs/服务器部署与运维.md](docs/服务器部署与运维.md)

## 架构总览（2026-08 现状）

```
新加坡服务器 47.82.211.111 (Alibaba Cloud Linux 3)
├── systemd timer: green-policy.timer（每30分钟）
│     └→ green-policy-sync.sh
│           ├─ 1. update_news.py 抓取 15 个源
│           │     ├─ 官方部委/国际组织 → Notes/政策库/
│           │     ├─ 媒体/热榜 → Notes/媒体库/（关键词过滤）
│           │     └─ 生成 data/*.json 网站数据
│           ├─ 2. Notes/ git commit + push → /srv/git/green-policy-materials.git
│           └─ 3. data/ 站点数据更新（nginx 直接服务）
└── nginx: https://ywm.life → /opt/green-hot-news/

本地 Windows (Obsidian)
└── Obsidian Git 插件 (basePath=Notes)
      ├─ 每15分钟 auto-pull ← 服务器 bare 仓库
      ├─ 每15分钟 auto-save (commit)
      └─ 每30分钟 auto-push → 服务器 bare 仓库
```

## 覆盖范围（19 个源）

### 国内政策源（政策库 · 中国）
- 国家发改委、生态环境部、国家能源局、工信部

### 国际政策源（政策库 · 国际组织）
- IEA、IRENA、UNFCCC、World Bank Climate

### 行业媒体（媒体库）
- Carbon Brief、Reuters Energy、北极星电力网、中国碳交易网、碳道、中国能源报

### 绿色科技/AI（媒体库 · 2026-08-14 主题升级新增）
- **Climate Change AI**（AI×气候交叉，blog 列表页抓取，取最新 12 条）
- **中国科技网**（科技日报，首页实时 + 关键词过滤）
- **CleanTechnica**（清洁技术第一站，RSS；走关键词过滤去车企商业噪音）

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

## 数据输出

- `data/latest-24h.json` — 24小时绿色政策信号（过滤后）
- `data/latest-24h-all.json` — 24小时全量数据
- `data/source-status.json` — 16 个源健康状态
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
