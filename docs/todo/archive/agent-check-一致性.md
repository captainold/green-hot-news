# Agent 核查：qmd 数据库与原始 Web 页一致性

- 核查日期：2026-08-24
- 抽样：Notes/数据库/ 12 篇（绿色政策 4 / 绿色产业 4 / 科技创新 4），覆盖中/英、有图/无图、12 个不同站点、8 篇直达 URL + 4 篇 Google News URL
- 方法：`python3.11` 读 qmd `## 正文` 段，用 `scripts/article_content.py::fetch_article(url, rich=True)` 当日重抓原始页对比；图片核对 attachments 本地文件；表格对比原文 HTML `<table>`；正文逐字节 diff + 段落覆盖度（归一化包含率）

---

## 一、抽样清单

| # | 维度 | 文件 | 站点 | 判定 |
|---|------|------|------|------|
| 1 | 绿色政策 | 2026-08-14 【生态环境监测和执法将大力推进数智化转型】.qmd | 中国能源报 | **部分一致** |
| 2 | 绿色政策 | 2026-08-17 【关于印发《石油天然气发展"十五五"规划》的通知】.qmd | 国家发改委 | 一致 |
| 3 | 绿色政策 | 2026-08-10 Assessing the Global Temperature and Precipitation in July 2026.qmd | 美国NOAA | 一致 |
| 4 | 绿色政策 | 2026-08-13 What can I expect to pay for heating this winter.qmd | 美国EIA | 一致* |
| 5 | 绿色产业 | 2026-08-14 15.77GWh！7月储能项目集中并网….qmd | CNESA储能联盟 | **部分一致** |
| 6 | 绿色产业 | 2026-08-14 全国碳排放权交易市场累计成交量突破9亿吨….qmd | 碳道 | 一致 |
| 7 | 绿色产业 | 2026-08-17 Analysis The two largest reservoirs in the US….qmd | Carbon Brief | 一致 |
| 8 | 绿色产业 | 2026-08-01 Agora appoints new director for Southeast Asia….qmd | Agora·能源转型 | 一致 |
| 9 | 科技创新 | 2026-08-16 471亿，全球最大的大模型中介，卖身了.qmd | 36氪 | **不一致（源站反爬）** |
| 10 | 科技创新 | 2026-08-21 中国信通院牵头的ITU大模型边缘侧推理系统….qmd | 虎嗅 | **不一致（源站反爬）** |
| 11 | 科技创新 | 2023-11-28 Introducing The ForestBench Project.qmd | Climate Change AI | 一致 |
| 12 | 科技创新 | 2026-08-17 Qwen3.8 27B - Intelligence, Performance & Price Analysis.qmd | Artificial Analysis | 一致 |

\* EIA：正文正确、标题正确，但 frontmatter url 含 `&t;=8` 参数分号残留（数据层瑕疵，源站恰好容忍）。

**汇总：一致 8/12（67%）、部分一致 2/12（17%）、不一致 2/12（17%）、源站失效 0。**

---

## 二、差异类型统计（12 篇，可多选）

| 差异类型 | 篇数 | 涉及文件 |
|---|---|---|
| 正文丢失 / 截断 | 0 | — |
| 导航垃圾 / 页面 chrome 混入正文 | 2 | 中国能源报、CNESA |
| 图片未下载（保留原始 URL） | 3 | NOAA、Climate Change AI、中国能源报（2 张 UI 图标） |
| 附件缺失（attachments/ 指向文件不存在） | 0 | —（10 张引用全部存在） |
| 表格丢失 | 0 | —（Artificial Analysis 的表格保留；其余原文无 `<table>`） |
| 反爬导致正文无效（抓到的是挑战页） | 2 | 36氪（火山引擎）、虎嗅（阿里云 WAF） |
| 标题问题（qmd 侧） | 3 | 中国能源报/发改委【】截断、Artificial Analysis 去 "(xhigh)" |
| 其他残留（原始 HTML 片段 / 私用区乱码 / base64 data URI） | 3 | 虎嗅、CNESA、36氪 |
| 源站失效（404 / 无法访问） | 0 | — |

---

## 三、一致率估算

- **正文逐字节一致率：10/12 = 83%**——10 篇 qmd 正文与当日重抓内容**逐字节相同**（含 2 篇反爬页，因抓取结果本身被忠实保存）。
- **有效正文一致率：10/10 = 100%**——剔除 2 篇反爬页后，其余 10 篇正文主体全部完整（2 篇仅混入页面 chrome，正文本体无损）。
- **标题正确率：10/12 = 83%**——qmd 标题均来自 feed 且基本正确；中国能源报【】包裹缺"“十五五”时期"前缀、Artificial Analysis 被去掉 "(xhigh)"（微差）。注：提取器 `page_title` 有 4 篇返回错误/空值（碳道→"相关信息"、CNESA→"产业观察"、36氪/虎嗅→空），但**不影响 qmd 标题**（qmd 用 feed 标题）。
- **图片下载成功率：10/10（引用 attachments 的全部存在）**；3 篇未下载、静默回退原始 URL。

**结论：转换管线（update_news → data/*.json → export_qmd.py）无损，问题全部出在抓取/提取层。**

---

## 四、主要问题点（具体证据）

### 1. 反爬挑战页被当作正文入库（最严重）
- **36氪** `2026-08-16 471亿，全球最大的大模型中介，卖身了.qmd`：`## 正文` 全文为——
  > `![](data:image/png;base64,iVBORw0KGgo...)` + `火山引擎` + `正在进行安全检测...` + `为保障您的访问安全，系统正在检测当前网络环境...`
  即火山引擎反爬中间页文本，**非文章内容**；正文还混入 1 个 base64 data URI 占位图。
- **虎嗅** `2026-08-21 中国信通院牵头的ITU大模型边缘侧推理系统….qmd`：`## 正文` 为阿里云 WAF 挑战页的 JS 片段——
  > `id="traceid">TraceID: 2f5e3b80...` + `var requestInfo = {...}` + `appkey: "CF_APP_WAF"`（两次抓取仅 TraceID 变化，其余逐字节相同）。
- 两站均为中文科技媒体 WAF 站点。**虎嗅共 35 篇、36氪 27 篇**，全库存在同类污染风险 → 建议全库扫描 `安全检测/WAF/TraceID/captcha/CF_APP_WAF` 特征。

### 2. 导航/推荐模块混入正文（extract_rich 内容容器过宽）
- **中国能源报**（全库最大源站，125 篇）正文尾部混入：
  > `精彩视频 START / ## 精彩视频 / [4条站内链接] / 精彩图集 START / ## 精彩图集 / [4条链接] / 页面滑动标题置顶 / "十五五"时期生态环境监测和执法将大力推进数智化转型 / 分享到：`
  约 600 字符的侧栏推荐模块 + 置顶标题 + 分享按钮 UI 文案。
- **CNESA** 正文头部混入页面栏目块：`# 产业观察` + 重复标题 + `在 2026-08-14 发布`（栏目名/日期 chrome）。

### 3. 图片下载策略不一致且静默回退
- 成功：CNESA 6 张、Carbon Brief 4 张 → `attachments/<md5>.png`，文件全部存在。
- 未下载（保留原始 URL）：NOAA 头图（`...1200x480%20Global%20July%202026.png?itok=...`）、Climate Change AI 2 张（climatechange.ai 图片 404，已知源站问题）、中国能源报 2 张（`detail_5.png/detail_9.png`，实为 UI 图标而非正文图）。
- 下载失败时无任何标记（如 alt 占位或失败日志），静默回退 URL。

### 4. 标题与 URL 数据层瑕疵
- 中国能源报/发改委 qmd 标题为【】包裹截断版（缺"“十五五”时期"前缀）。
- EIA frontmatter：`url: "https://www.eia.gov/tools/faqs/faq.php?id=867&t;=8"` —— `&t;` 分号残留（疑似导出时实体化），属数据层污染；源站恰好容忍，正文仍正确。

### 5. markdown 清洗不彻底
- 虎嗅正文含原始 HTML 片段（`id="traceid">...</div>`）；CNESA 正文尾部残留私用区 Unicode 字形（` `，icon font 解码产物）；36氪混入 base64 data URI。

---

## 五、严重问题 Top 5

1. **反爬挑战页静默入库为"正文"（36氪、虎嗅）**——正文无任何文章内容；同源站 62 篇有同类污染风险。属抓取层问题（非转换丢失），需全库特征扫描 + 重抓。
2. **导航/推荐模块混入正文（中国能源报，125 篇最大源站；CNESA）**——extract_rich 选择器过宽，需收窄内容容器并做尾部推荐模块过滤。
3. **图片下载失败静默回退原始 URL（3 篇）**——无标记、无告警；且混入 UI 图标（中国能源报）与 base64 占位图（36氪）。
4. **标题污染与 URL 参数损坏（【】截断标题 ×2、EIA `&t;=8` 分号）**——影响检索与展示一致性。
5. **原始 HTML/私用区乱码/data URI 残留（虎嗅、CNESA、36氪）**——`_clean_rich_body` 清洗不彻底。

---

## 六、附：核查方法说明

- 段落覆盖度：归一化（NFKC、去空白标点、去 markdown 语法）后按段落做包含率匹配，双向计算（qmd→原文、原文→qmd）；Carbon Brief 唯一"缺失"段（"Both Lake Mead and Lake Powell are located..."）为行内链接导致的匹配假阴性，非真实丢失。
- 表格：原文 `<table>` 计数 vs qmd markdown 表格块；Artificial Analysis 原文表格为 JS div 渲染（HTML 无 `<table>`），qmd 中 markdown 表格系提取器 div-table 转换产物，判定保留成功。
- 反爬页判别：抓取内容与 qmd 逐字节一致（含动态 TraceID 外），且内容为挑战页特征文本。
