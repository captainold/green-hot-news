# Green Hot News · 绿色政策雷达

国内外最新绿色低碳政策聚合站。自动抓取政府、国际组织、行业媒体的绿色低碳政策动态，通过 GitHub Actions 定时更新，GitHub Pages 部署为静态站点。

## 在线入口

- 线上页面：`https://captainold.github.io/green-hot-news/`

## 1 分钟上手

想 fork 自己的版本：

1. Fork 本仓库
2. 在 GitHub Pages 里开启 Pages（Settings → Pages → Source: GitHub Actions）
3. 保留 `.github/workflows/update-news.yml`，它会定时更新 `data/*`
4. 可选：把你的 OPML base64 内容放进 GitHub Secret `FOLLOW_OPML_B64`

本地运行：

```bash
git clone https://github.com/captainold/green-hot-news.git
cd green-hot-news
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/update_news.py --output-dir data --window-hours 24
python -m http.server 8080
```

打开 `http://localhost:8080`

## 覆盖范围

### 国内政策源
- 国家发改委 RSS
- 生态环境部
- 工信部
- 国家能源局
- 中国能源报
- 中国环境报

### 国际政策源
- IEA (International Energy Agency)
- IRENA (International Renewable Energy Agency)
- UNFCCC News
- World Bank Climate
- Carbon Brief
- Reuters Clean Energy

### 行业聚合
- 北极星电力网
- 碳道
- 中国碳交易网

## 数据输出

- `data/latest-24h.json` — 24小时绿色政策信号
- `data/latest-24h-all.json` — 24小时全量数据
- `data/source-status.json` — 源健康状态

## GitHub 自动更新

工作流：`.github/workflows/update-news.yml`

- 定时：每 30 分钟
- 任务：执行抓取命令并提交 `data/*`
- 部署：自动部署到 GitHub Pages

## 项目背景

本项目是中咨公司气候处绿色低碳咨询工作的基础设施。通过持续追踪国内外绿色低碳政策动态，支撑政策研究、项目评审和战略咨询工作。

作者：老温 (captainold) · 中咨公司气候处
