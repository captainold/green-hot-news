



- [ ] 今天要把这个动态雷达的首页展示弄得更精致和合理一些。 然后就可以给处室里看了。 有了一个好想法，嘿嘿。 
- 太丑
- 分布还不合理
- 还是要学会不同分支的工作方法
- 

- 源还要继续增加（微信公众号？）

- [ ] 建立让用户注册，然后提供信息渠道的功能。

我的排行榜为什么独特，因为我独特的品味和判断。

ai对reddit的应用权重越来越高。今后ai时代，用户个人的比重必然得到加强。也就是说，我们应该要建立自己的论坛，或者是微信群，维护自己的生态。 
- [ ] 还要关注x.com 上的。
- [ ] 要给这个项目接上agent的接口。用mcp？其他的还要防住。 
- [ ] 当日高分浓缩版，供我转发到群里和朋友圈，还有自媒体。

- [x] 还要确认：人形机器人、绿色智能家居、绿色生活，都在范围内。（2026-08-19：**确认并在范围内**——新增 7 源：人形机器人 The Robot Report/IEEE Spectrum（ROBOT_SITES 直通→AI 榜）、绿色智能家居 千家网/Green Builder Media/中国家电网（关键词过滤，POLICY_KEYWORDS 补"以旧换新"）、绿色生活 绿色和平/Mongabay（GREEN_SITES 直通）。探测放弃：高工机器人/数智网/TreeHugger/EcoWatch/Energy Star/环保在线）
- [x] 最起码要把我web收藏的，微信关注的这些都update进去啊。这个项目还真不好做。（2026-08-19：**书签批次 A~O 完成**——`inbox/bookmarks_8_19_26.html` 筛选 18 候选 → 接入 15 源：国际智库/投行 9（Brookings/Bruegel/PIIE/CSIS/Chatham/Carnegie/RAND/CAP/高盛）、中国 4（财新/国家节能中心/澎湃/36氪）、AI 2（Artificial Analysis/虎嗅）；探测放弃 3（绿证平台 JS壳/WaytoAGI RSS404/Wilson Center Google 0条）。★ 达 62 源、线上 69 源。⚠️ PITFALL：Google News 括号 OR 语法返回全站混合内容（绿色命中<10%）→ 全部改用单主题词 query + when:30d；高盛官方站索引差 → 用「"Goldman Sachs"+主题词」；金融维度 23→39 条补弱成功。后续待办：微信公众账号源、X.com、agent 接口（MCP））
- [ ] 还是应该像news学习，尽量简洁，首页上只放题目是最好的。但是背后要下载，组织自己的媒体数据库。



- [x] 这篇新闻：Strengthening democratic over sight in national security。事关国家级安全，政治、ai、民主的这样一个话题，对我来说是关注度很高的话题。请检查评分标准，针对此类话题进行优化。

- [x] Coinbase 风格的新皮肤很好，可以实施。（2026-08-19 已完成：styles.css v4 重写为 Coinbase 蓝白黑金融级质感 + DM Sans + 深/浅区块交替 + 胶囊按钮，index.html 加字体，app.js 零改动；已验证 200/数据完整。v7（08-19 二次优化）：hero 改浅色协调版——老温反馈"白底+深色大标题"突兀，页面统一浅色调，深色仅留时间线锚点；nginx 给 index.html 加 no-store 缓存头，修复 Chrome 缓存旧版导致黑底/Wave 白底显示不一致）
- [x] 四维分类讨论中（2026-08-19 老温提议，**未定稿勿改代码**）：
	- 提议：政策→政府、技术→行业、金融、AI科技→AI，即「政府/行业/金融/AI」按行为主体划分
	- 背景事实：①「技术」维度 83 条里多是行业动态（铁矿石/企业火灾/出口数据），名不副实，实际是兜底分类；②腾讯《碳中和中期报告》因标题含 AI 被 AI科技 抢走（83分），老温认为主体应是双碳行业
	- 决策点 A（核心）：AI×双碳交叉归哪边？推荐 A1 双碳优先——命中双碳核心词（碳中和/碳达峰/碳排放/碳市场/双碳）优先归行业，纯 AI 信号（大模型/智能体/OpenAI 无双碳词）才归 AI；纯 AI 源（机器之心等）仍直通 AI
	- 决策点 B：火箭回收/核电装料等技术突破并入「行业」档（技术关键词并入行业档），不做子分类（推荐）
	- 决策点 C：history.json 62 天旧 dimension（政策/技术/金融/AI科技）——推荐一次性迁移脚本重算 dimension + 重打分（因内容强度档位 key 也改）
	- 附带发现：radarai GitHub 趋势出现 vitejs/vite 等非绿色项目（TECH_SITES 直通技术兜底），改名行业后更违和，建议顺带给 radarai 加绿色主题过滤
	- **2026-08-19 已实施**：A1 双碳优先 + 政府/行业/金融/AI 主体化 + 技术突破并入行业档 + migrate_dimensions.py 迁移 1156 条 + radarai 绿色/AI 词过滤；腾讯报告→行业 73 分 A；分布 政府204/AI149/行业141/金融35
- [x] 日/夜护眼模式切换（2026-08-19 v8）：hero 右上角 🌙/☀️ 按钮，CSS 变量双主题（:root 白天 + html[data-theme="dark"] 夜晚），整页联动（hero/排行榜/时间线同主题——解决"页面白+时间线黑"割裂）；localStorage 记忆（ghn-theme）+ head 内联脚本防闪白；默认白天。已部署线上 md5 验证通过
- [x] 新闻重复修复（2026-08-19）：Google News RSS 聚合 URL 是 base64 且每次抓取不同，按 url 去重会漏（实测日本环境省一条新闻 x8 重复）。改为按规范化标题去重（_title_dedup_key：去空白/标点后小写取前120字符），三处生效：fetch_foreign_gov 跨 query、主流程 seen_items、merge_history；新增 scripts/dedup_items.py 清理存量（本地 39 条、服务器 62 条）。已部署 md5 一致
- [x] 旧源 Google News query 括号 OR → 单主题词（2026-08-19）：实测 `site:x (a OR b) when:7d` 返回该站全站混合内容（绿色命中<10%），`site:x a when:30d` 返回 70-90% 相关内容。`scripts/_split_or_queries.py`（幂等，备份 /tmp 后自动拆分）批量改 58 处——覆盖 EPA/DOE/EU/PIB/NOAA/EIA/FERC/CARB/日本三省厅/Euractiv/E3G兜底/环交所/NCSC/CAEP/环境报/机器人 7 源。验证：总量 477→482，NOAA +4/Robot Report +3/EPA +2；四维均衡 政府169/AI135/行业155/金融23。已部署
- [x] 四维趋势图（2026-08-19 v9）：排行榜上方新增 📈 四维趋势图（ECharts 5.5.1 本地自托管）——政府/行业/金融/AI 四色折线，横轴=原文发表时间（published_at 非抓取时间）、纵轴=该时段最高分（重要性峰值），tooltip 显示该时段最高分新闻标题；范围切换 当日/3天内/1周内/1月内/自定义日期；1d/3d 按小时桶、7d+/自定义按天桶；跟随日/夜主题配色。PITFALL：ECharts time 轴 data 必须 [时间戳,值] 对（纯数值数组画不出线，实测仅 350px→修复后 9600px）。已部署 md5 一致
- [x] 趋势图 v5 tooltip 标题完整显示（2026-08-19）：去掉 max-width+ellipsis+nowrap 截断（长标题"显示不全"），改为 white-space:normal 自动换行 + 容器 max-width:480px 防溢出 + word-break:break-all；行布局改 align-items:flex-start 保证多行对齐。实测 135 字符长标题完整显示。已部署 md5 一致
- [ ] 

- [x] 标签体系
- [x] 政策库文件，不是按照wiki方式组织的。而是按照单位。
	- [x] 政策库按照国家、部委部门来分，这里也要包含从部委网站上发布的专家解读。（2026-08-14：新增生态环境部·解读栏目 zcwj/zcjd/，一图读懂/专家解读/答记者问入库政策库）
	- [x] 媒体库，指的是除了政府网站上其他的媒体和专家的评论解读。 
	- [x] 还应该增加一个人名标签，这个怎么反映到wiki里面呢？（2026-08-14：people 字段 + 人物白名单 PERSON_RULES + 政策wiki/人物 板块聚合，backfill_people.py 回填历史笔记）
- [x] 建立打分筛选机制，打分体系。这个是我的核心卖点，代表我的品味。现在的tags效果还不好。（2026-08-14：**v2.0 五维打分**——内容强度30（按四维自适应）+来源权威25+主题相关25+人物10+时效10，S/A/B/C/D 等级；前端综合榜+四维榜、分数徽章+悬停五维分解。规则见 docs/打分体系标准.md）
- [x] 当日高分浓缩版，供我转发到群里和朋友圈，还有自媒体。（依赖打分体系：score>=70 即 A 级以上条目，可自动生成）（2026-08-17：**scripts/daily_digest.py** 生成 data/daily-digest.md——四维分组 + 摘要清洗 + 每源配额防刷屏 + 7 天新鲜度过滤；前端 hero 区「📋 当日浓缩」弹窗一键复制；服务器 sync.sh 每次抓取后自动生成）
	- [x] green-hot-news 
	- [x] allnet.hot
	- [x] 主题升级：绿色低碳动态雷达（2026-08-14）——政策+技术+金融+AI科技四维，新增 Climate Change AI / 中国科技网 / CleanTechnica（共19源）
	- [x] 首页四维排行榜（2026-08-14）——顶部综合榜 + 政策/技术/金融/AI科技 四维榜
	- [x] 首页两区布局重构（2026-08-17）——上方排行榜（主题 × 周期日/周/月 × 区域国内/国际 切换）+ 下方实时时间线（跟随筛选、60s 轮询新条目自动插入高亮滚动、暂停/加载更早）；数据层补 region 字段 + data/history.json 62 天累积（按 url 去重）
	- [x] AI 维度全链条扩充（2026-08-14）——AI科技维度 = 理论→模型→市场→商业 + AI×能碳交叉；新增 OpenAI/arXiv·AI/机器之心/量子位/VentureBeat AI（共24源）；wiki 新增 AI进展 板块
	- [x] 技术维度扩充（2026-08-14）——RadarAI·GitHub趋势 接入（radarai.top/trends，GitHub 开源项目热度追踪）；/api/trends JSON 取前 40 条，TECH_SITES 直通（共26源）；record 补 summary 通道参与打分/前端摘要（2026-08-17：取消 DIM_SITE_OVERRIDE 整源强制归技术——技术榜只放绿色低碳技术，AI 项目按标题+摘要关键词归 AI科技榜，非 AI 项目落回技术兜底）

- [x] 非中文标题中文翻译（2026-08-18）——`scripts/translator.py` 腾讯云 TMT 翻译（专用子账号，凭据在项目根 `.env` 的 TENCENT_SECRET_ID/KEY），record 增 `title_zh` 字段，前端非中文标题显示中文主标题+原文小字副标题；`scripts/backfill_title_zh.py` 回填历史。踩坑：① TMT 需控制台开通 + 子账号 CAM 加 QcloudTMTFullAccess；② 免费版 QPS=5，并发>5 会 RequestLimitExceeded → translator 内带退避重试 + pipeline 翻译并发降为 3；③ 日本政府域名后缀是 .go.jp 不是 .gov，标题清理正则要单独补


- [x] 添加这个：全网热点聚合：6ef1d8f4-8745-437c-a1e4-8c525ed8e971   https://api.allnet.hot/api/open/v1
	- [x] 服务器 /opt/green-hot-news 接入 fetch_allnet（15个源，systemd定时已生效）
	- [x] 本地 scripts/update_news.py 同步 + .env 保存 Key + 脚本自动加载
	- [x] .gitignore 忽略 .env（防 Key 泄露）

- [x] 本地 Obsidian ↔ 新加坡服务器自动同步（2026-08-13）
	- [x] Windows SSH 通道：moltbot260130.pem + config 别名 sg-moltbot（IP 直连，避开本地 DNS fake-ip）
	- [x] Notes/ origin 改为 sg-moltbot:/srv/git/green-policy-materials.git
	- [x] Obsidian Git 插件 basePath=Notes，autoPull 15min / autoSave 15min / autoPush 30min

- [x] 吸收这个项目：C:\Users\wenyu\Projects\archive\news-collection


| 项目                                 | 目标                                                                                                                         | 截止  | 状态                                             |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | --- | ---------------------------------------------- |
| green hot news                     | 包括政策库、技术库、消息库等。<br>历史积累和最新news。手机网页访问。agent访问。<br>最终是要办一个论坛社区。可以先从注册和身份认证，为今后社区化做准备。<br>                                   |     | 现在我是有了一个绿色政策雷达，green news。服务器部署+Obsidian同步已完成。 |
| zero-carbon-park-workbench Private | 工作台。这里可以让大家上传自己的资料，在我的服务器上。方便我收集资料？（这个也会比较敏感。）咨询师真正需要的是**自动化数据填报、合规性自查、标准框架格式化导出、多源资料的精准溯源**。报告功能应定位为“协同与智能化助手”，而非“自动代写器”。 |     |                                                |
还是要聚焦：绿色低碳动态。

包括政策，也包括技术动态，还有金融等。这里面当然也就包括了ai的和科技的。


- [x] 现在国际来源主要就是国际组织，还要确定国外的主要国家政策发布的源。（2026-08-14：两轮接入共12源——美国EPA/DOE/NOAA/EIA/FERC/加州CARB、欧盟委员会/Euractiv、印度PIB、日本环境省/经产省/资源能源厅；Google News 搜 site + when:7d；政策维度 12→62 条。白宫/DOI/NREL/GX机构 Google 索引差未接，待人工跟踪）



包括政策库、技术库、消息库等。
所以我这个就叫，==绿色低碳动态雷达==。

四维覆盖：
维度: 🏛️ 政策
信源: 4部委 + 官方解读 + 4国际组织 + 国际主要国家政策发布
────────────────────────────────────────
维度: 🔋 技术
信源: 中国能源报、北极星、CleanTechnica、RadarAI·GitHub趋势（2026-08-14）
────────────────────────────────────────
维度: 💰 金融
信源: 碳交易网、碳道、Carbon Brief
────────────────────────────────────────
维度: 🤖 AI科技
信源: OpenAI、arXiv·AI、机器之心、量子位、VentureBeat AI、Climate Change AI、中国科技网（理论→模型→市场→商业 全链条 + 交叉地带，2026-08-14 扩充）


- [x] 信息源搜集：中美欧日印五大经济体 × 8 类机构（2026-08-14：产出 docs/信息收集目标列表.md v1.0，约 380 个目标，★19 已接入 / ●P0 首批 20 类 / ○P1 第二批 / △P2 人工跟踪；2026-08-17：v1.4 ★已接入达 47 源——含中国人民银行、中国 P0 五源（环交所/NCSC/CAEP/环境报/CNESA）、美日印官方源 12 源、国际智库 3 源（E3G/Agora/TERI））
- [x] 消息源健康监控管理面板（2026-08-14：/admin/ Basic Auth 不公开，健康度+新鲜度+48h趋势+源状态表+服务器状态+日志；scripts/health_tracker.py 接入 sync.sh）
- [x] 项目骨架搭建
- [x] 信息源健康程度监控界面（2026-08-14：/admin/ 管理面板上线，见上）
- [x] 重新设计打分体系
- [x] AIHOT就直接用就行了。（2026-08-14：aihot.virxact.com 接入——精选 RSS feed.xml 每 30 分钟抓取，AI_SITES 白名单直通 AI科技 维度，25 源）
- [x] 要有一个源一览表，分门别类放好。（2026-08-14：docs/信息收集目标列表.md v1.0——中美欧日印×8类机构+国际组织，★已接入/●P0/○P1/△P2 分级，附接入路线与维护规则）
