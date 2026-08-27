# Green Hot News · 绿色低碳创新动态雷达

国内外最新绿色低碳动态聚合站：**政策 + 创新 + 产业** 三层覆盖（2026-08-26 v5.0 中性命名，按创新价值链排序：政策=政府发文·国际动态 / 创新=技术研发·基础研究·社会创新 / 产业=企业经营·金融资本）。自动抓取政府、国际组织、行业媒体、绿色科技媒体、AI 全链条媒体、学术期刊、社会创新智库、GitHub 开源趋势、全网热榜的绿色低碳动态（75 源），通过新加坡服务器定时更新，Nginx 部署为静态站点，Obsidian 笔记库双向同步。内置**打分体系 v5.0**（内容强度按七细类自适应 + 来源权威 + 主题相关 + 人物 + 时效 + 技术成熟度 TRL，六维加权 0-100）。前端**三区布局**：顶部**主题排行榜**（政策/创新/产业三层切换，主题/周期/区域/分数段四组切换器，按综合分排名）+ 中部**动态时间线**（跟随筛选、新条目自动插入高亮滚动、加载更早）+ 底部**关系图谱**（主题/Layer/国际分类/交叉技术四维切换），「📋 一键复制概要」当日高分浓缩转发。

## 在线入口

- 线上页面：`https://ywm.life` （your world message ）（新加坡服务器 Nginx 直出，排行榜 + 实时时间线 + 「📋 当日浓缩」一键复制转发）
- 管理面板：`https://ywm.life/admin/`（消息源健康监控，Basic Auth 保护，不公开；账号见 docs/服务器部署与运维.md）
- GitHub 镜像：`https://captainold.github.io/green-hot-news/`（仅代码归档，CI 已禁用）
- Obsidian 笔记库：`C:\Users\wenyu\Documents\Obsidian_wen\green-hot-news\Notes\`
- 服务器部署与运维文档：[docs/服务器部署与运维.md](docs/服务器部署与运维.md)

## 反馈与评分标准（2026-08-27 反馈渠道方案）

- **评分标准（公开版）**：https://ywm.life/score-standard.html —— 六维打分模型规则框架公开（实现细节关键词表不公开），首页卡片悬停评分徽章可看六维分解
- **意见反馈**：首页「📮 反馈」按钮，或直接
  - 邮箱：`feedback@ywm.life`（Cloudflare Email Routing 转发，每周日自动汇总进待办）
  - GitHub Issue：[green-hot-news-feedback](https://github.com/captainold/green-hot-news-feedback)（标签：bug / 新闻线索 / 评分异议 / 建议）
  - 微信群：暂缓（等出现第一批真实反馈后建群，公告文案见 docs/群公告文案-草案.md）
- 主程序代码保持私有（green-hot-news），反馈仓库公开——打分标准透明可讨论，实现细节保留

## 架构总览（2026-08-19 现状）

```
新加坡服务器 47.82.211.111 (Alibaba Cloud Linux 3)
├── systemd timer: green-policy.timer（每30分钟）
│     └→ green-policy-sync.sh
│           ├─ 1. update_news.py 抓取 75 个源
│           │     ├─ 官方部委/国际组织 → Notes/政策库/
│           │     ├─ 媒体/热榜/AI/学术/智库 → Notes/媒体库/（三层分类 + 打分 v5.0）
│           │     └─ 生成 data/*.json 网站数据（含 score/dimension/sub_dimension 字段）
│           ├─ 2. Notes/ git commit + push → /srv/git/green-policy-materials.git
│           └─ 3. data/ 站点数据更新（nginx 直接服务）
└── nginx: https://ywm.life → /opt/green-hot-news/

本地 Windows (Obsidian)
└── Obsidian Git 插件 (basePath=Notes)
      ├─ 每15分钟 auto-pull ← 服务器 bare 仓库
      ├─ 每15分钟 auto-save (commit)
      └─ 每30分钟 auto-push → 服务器 bare 仓库
```

## 覆盖范围（75 个源，2026-08-27 服务器为准）

### 国内政策源（政策库 · 中国）
- 国家发改委、生态环境部、生态环境部·解读、国家能源局、工信部、**中央网信办**（2026-08-27 接入：网信政务栏目直抓，网信/AI 治理政策；WAF 按 UA/出口挡，独立直连）、中国人民银行（新闻发布+政策文件）、NCSC 国家气候中心、环境规划院 CAEP、国家节能中心（官网直抓，官方解读/一图读懂，2026-08-19 接入）

### 国际政策源（政策库 · 国际组织 + 主要国家）
- 国际组织：IEA、IRENA、UNFCCC、World Bank Climate、欧盟委员会、Euractiv·欧盟
- 美国：EPA、DOE、NOAA、EIA、FERC、加州 CARB（Google News 搜 site + when:7d，7 天宽窗口）
- 日本：环境省、经产省 METI、资源能源厅 ANRE
- 印度：PIB 新闻局

### 国际智库（媒体库 · 2026-08-17 / 08-19 接入）
> 权威能源/气候智库的深度分析与政策评论，更新周级~双周级 → 网站数据用 21 天宽窗口
- **E3G**（伦敦气候与能源智库，RSS）、**Agora Energiewende**（柏林能源转型智库，news-events 列表页）、**TERI**（印度能源与资源研究所，press-release 列表页）
- **Brookings 布鲁金斯**、**Bruegel 布鲁盖尔**、**PIIE 彼得森**、**CSIS**、**Chatham House 查塔姆**、**Carnegie 卡内基**、**RAND 兰德**、**CAP 美国进步中心**、**高盛**（全部 Google News 单主题词 query + when:30d，2026-08-19 书签批次接入；高盛官方站索引差，用「"Goldman Sachs"+主题词」搜媒体转述研报观点）

### 碳市场/绿色金融（媒体库）
- 上海环交所（碳交易）、中国碳交易网、碳道、Carbon Brief、**财新**（Google News 中文碳词，2026-08-19 接入）

### 行业媒体（媒体库）
- Reuters Energy、北极星电力网、中国能源报、中国环境报、CNESA 储能联盟、**澎湃新闻**（Google News 中文绿色词，2026-08-19 接入）、**36氪 / 虎嗅**（AI_MEDIA_SITES 过滤：命中绿色词或 AI 词才入库，2026-08-19 接入）

### 绿色科技/AI（媒体库）
- **Climate Change AI**（AI×气候交叉）、**中国科技网**（科技日报）、**CleanTechnica**（清洁技术）

### 社会创新/可持续消费学术严肃源（媒体库 · 2026-08-26 接入，填补社会创新维度）
> 老温拍板「偏学术和严肃讨论，不要娱乐生活类」——支撑 创新·社会创新 细类（制度/机制/模式/消费/行为研究）
- **Nature Sustainability**（可持续科学顶级学术期刊，RSS；ACADEMIC_SITES 直通：社会创新词命中→创新·社会创新，否则创新·基础研究）
- **Hot or Cool Institute**（柏林 1.5°C 生活方式研究所，news 卡片抓取；SOCIAL_THINKTANK_SITES 直通创新·社会创新）
- **UNEP 联合国环境署**（RSS，政策库·国际组织；可持续消费/生活方式类→创新·社会创新）

### AI 领域全链条（媒体库 · 2026-08-14 AI 维度扩充）
> 理论 → 模型 → 市场 → 商业 全覆盖，AI_SITES 白名单直通（不进绿色关键词过滤）
- **OpenAI**（模型发布一手，RSS 限量 30）
- **arXiv cs.AI**（理论前沿，RSS 限量 30）
- **机器之心 / 量子位**（中文 AI 头部媒体，Google News fallback）
- **VentureBeat AI**（国际 AI 商业，RSS 限量 30）
- **AIHOT**（`aihot.virxact.com`，AI 行业动态聚合：X/公众号/RSS 几十源，精选 RSS 每 30 分钟抓取，带热度与 AI 评分；2026-08-14 接入）
- **Artificial Analysis**（AI 模型评测/API 市场数据，Google News，AI_SITES 直通，2026-08-19 接入）
- **Climate Change AI**（AI×气候交叉机构，2026-08-17 起全链条归 AI 榜——其产出均为机器学习应对气候项目，避免 NeurIPS 工作坊/ML 基准等项目落进产业榜）

### 技术趋势（媒体库 · 2026-08-14 新增）
> GitHub 开源项目热度追踪，TECH_SITES 白名单直通；AI 项目按关键词（标题+摘要）归 AI 榜，非 AI 项目归产业维度（2026-08-17 调整：产业榜只放绿色低碳技术，不再整源强制归产业）
- **RadarAI·GitHub趋势**（`radarai.top/trends`）：聚合 GitHub Trending 开源项目（中文摘要+star），抓 `/api/trends` JSON 取前 40 条；DeepSeek/ollama/stable-diffusion 等 AI 项目进 AI科技榜，其余归「技术」维度；无发布时间走收录时间兜底

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

## 三层定位（2026-08-26 v5.0 重构）

| 层 | 定位 | 细类 | 信源 |
|------|------|------|------|
| 🏛️ 政策 | 制度锚点（为什么） | 政策法规 / 国际动态 | 国内 9 部委/机构 + 官方解读 + 6 国际组织 + 美日印官方 + UNEP |
| 🧪 创新 | 技术种子（可能吗） | 技术研发 / 基础研究 / 社会创新 | arXiv·AI、Nature Sustainability、Hot or Cool、Climate Change AI、中国科技网 |
| ⚙️ 产业 | 产业脉搏（成了吗） | 企业经营 / 金融资本 | 中国能源报、北极星、CleanTechnica、RadarAI·GitHub趋势、碳交易网、碳道、Carbon Brief、财新、高盛 |

> AI 按技术阶段分流（v5.0）：论文/研究报告→创新·基础研究，模型/产品发布→产业·企业经营，其余研发→创新·技术研发。

## 数据输出

- `data/latest-24h.json` — 24小时绿色动态信号（过滤后，含 `score`/`score_level`/`score_breakdown`/`dimension`/`sub_dimension`/`trl`/`region` 字段）
- `data/latest-24h-all.json` — 24小时全量数据
- `data/history.json` — 62 天历史累积（2026-08-17：排行榜日/周/月周期切换数据源；去重按规范化标题 `_title_dedup_key`——2026-08-19 修复 Google News 聚合 URL base64 每次抓取不同导致同新闻 x8 重复，含 `region` 字段）
- `data/source-status.json` — 75 个源健康状态
- `data/daily-digest.md` — 当日高分浓缩版（评分 ≥70 A 级以上，三层精选，可直接转发；`scripts/daily_digest.py` 生成，服务器每次抓取后自动更新）
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
