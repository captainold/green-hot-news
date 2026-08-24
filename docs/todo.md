
## 2026-08-23 定稿的顶层设计 

docs/底层数据库构建方法 260823.qmd —— 放弃"树状文件夹"，改用多维属性标签（Metadata）构建本地垂直领域信息数据库，每一条数据以 qmd 格式保存（文档第 58 行明确）。我们都保存为qmd文档，就是要qmd的富文本优势，我们必须要抓取全文，并且有图和表格。

三维标签体系：
- ① 生命周期 Layer（1 宏观合规 / 2 产业市场 / 3 前沿科研）
- ② 国际分类 Taxonomy（EU Taxonomy / ISIC / GICS / IPC）
- ③ 交叉技术 Enabling Tech（AI / 生物 / 能源 / 环境）
- ＋ 技术特征提取（你的护城河字段，如降本曲线/设备参数）
- 并且有关系图谱显示。本地obsidian查看。

-[x] 都改成qmd存储
-[ ] 重构分类之后
	-[ ] 核查国际分类 Taxonomy（EU Taxonomy / ISIC / GICS / IPC）技术分类是否准确。
-[x] 开始构建qmd数据库
-[ ] 关系图谱内联，实现本地obsidian查看

-[ ] 中央网络安全和信息化委员会印发《促进网信企业高质量发展行动计划（2026-2030年）》这个要从官方网站抓取，添加官方网站为源。 

我的雷达要改名为：绿色低碳科技，动态雷达（这个名字好吗？ ）

过程中发现的重要问题（服务器反爬）：
- 服务器 IP（新加坡数据中心）被 Cloudflare 挡——mongabay/us_doe/openai 等全站抓不到正文（本地住宅 IP 正常 55/55）

我独特的品味和判断的排行榜

分类，从上到下：宏观政府、产业企业、基础研究技术开发

类型包括：绿色低碳、人工智能、生物科技、能源，还有其他的。
-[ ] 这个要按照国际惯例或者标准来进行组织。 

我希望：
- 第一层是绿色政策，包括：政府的政策法规和通知公告，国家间、国际组织间的动态，这个是顶层。这里要包含绿色低碳科技
- 第二层是绿色产业，包括技术、金融等领域，但是都是绿色产业的，这块还应该有技术、企业经营、金融并购，等细类的区别；但是因为我是做技术出身，所以对技术应该单独分出来，也应该是我这个网站和数据库的特色内容；
- 第三层，是科技创新，高技术领域，这块属于基础研究技术开发领域，也应该包括AI、能源、环境领域的基础研究阶段。

-[ ] 也要求对每一条新闻有一个标签的重构。

其实对应的就是资环部、高技术部的工作内容。 

-[ ] 后面要做信息源自动收集

## 2026-08-24 

真相：服务器 IP（新加坡数据中心）被 Cloudflare 挡（403）——服务器端对受保护站点全部抓不到正文！这有 git 覆盖风险——立即检查本地是否已被服务器无正文版本污染~

给服务器接上夏威夷家宽 SOCKS5 落地节点——这样服务器出口变住宅 IP，Cloudflare 就放行了！

测试一下知识dmit服务器，是否就没问题了。是否需要加上夏威夷家宽。 

🔍 IP 与服务商确认
════════════════════════════════

🖥️ 服务器（直连）：
| 项     | 值                                                                  |
|--------|---------------------------------------------------------------------|
| IP     | 47.82.211.111                                                       |
| 位置   | 新加坡 Singapore                                                    |
| 服务商 | AS45102 Alibaba (US) Technology Co., Ltd.（阿里云国际，新加坡节点） |
| 类型   | 数据中心 IP                                                         |

🌺 代理出口（当前生效）：
| 项     | 值                                                                         |
|--------|----------------------------------------------------------------------------|
| IP     | 147.81.120.142                                                             |
| 主机名 | dhcp-147-81-120-142.hawaiiantel.net（DHCP 动态分配——家宽特征）             |
| 位置   | 'Aiea, Hawaii, US（夏威夷阿伊亚）                                          |
| 服务商 | AS36149 Hawaiian Telcom Services Company, Inc.（夏威夷电信——本地家宽 ISP） |
| 类型   | 住宅/家宽 IP ✓                                                             |

════════════════════════════════
🔄 链路确认
════════════════════════════════

是一层代理（单跳 SS）：

阿里云新加坡服务器 (47.82.211.111, 数据中心IP)
   ↓ mihomo 客户端 (SS 隧道, nat.qq.pw:35102)
夏威夷电信家宽 (147.81.120.142, 住宅IP)
   ↓
访问目标网站（Cloudflare 看到住宅 IP → 放行）


- nat.qq.pw 解析到 147.81.120.142（Hawaiian Telcom 的 DHCP 地址段）——应该是你通过 NAT/穿透方案（域名 nat.qq.pw）把家里宽带映射到公网的服务
- 出口 = 夏威夷电信家宽住宅 IP → Cloudflare 不再按数据中心 IP 拦截 ✓

结论：服务器本体是阿里云新加坡，出站正文抓取走一层 SS 代理经夏威夷电信家宽（住宅 IP）落地——这就是反爬问题解决的关键！♪










- [x] 📡 **49** 个源🟢 **450** 条动态✅ 69 正常  这个在首页不需要显示了。但是要显示为今日更新了多少条动态，其中多少条，高于70分，值得您关注。
- [x] 在四维趋势图中显示的新闻，应该支持鼠标点击直接跳转到页面中这一条的位置处。（2026-08-19 已实现：点击趋势图浮窗新闻 → 先定位页面卡片并高亮，找不到则自动切"月"周期+扩展时间线让该新闻进 DOM 再定位，全程留本站不跳外部）
- [ ] 吸引用户订阅，提供新闻缩减版，注册用户可以提供信息渠道。 
- [ ] 要用ai给库里的东西互相打双链接啊。
- [ ] 分类要更精细：政策：政府文件；产业：行业动态；资本：碳市场等绿色资本；AI：




- news minimalist 设计很有启发，但是有瑕疵 
	- 就是三个维度：
		- significance
		- coverage
		- latest
	- 上面调整显示范围，并且是直方图显示；
		- 没有搜索键；
		- 奇怪的是：有了直方图下面的领域选择，为什么还有by coverage 按键？这是个小瑕疵
	- 中间逐条显示；永远是按排名从大到小
	- 下面说明和订阅；
	- bug：
		- by coverage和上方的coverage功能重合
		- by significance 

我的：
- 页面上部是：选择主题、时间段，一键复制按钮（选择范围内的文字版概要，这里面要添加上我的网站宣传）
- 中间逐条显示，有两种排序模式：
	- 重要性
	- 新到旧
	- 一页多少条，可选，这部分不能太长
- 下面是趋势
	- 用关系图谱，展现该主题，在这个时间段内的变化趋势
	- 这里就体现出其他标签在这个主题标签下的区分作用了
	- 但是数据库管理用的标签就不显示了，只显示主题标签



- [ ] 当日高分浓缩版，还要精细化。
- [ ] 要给这个项目接上agent的接口。用mcp？其他的还要防住。 


- 还是要学会不同分支的工作方法

- 源还要继续增加（微信公众号？）



## done

ai对reddit的应用权重越来越高。今后ai时代，用户个人的比重必然得到加强。也就是说，我们应该要建立自己的论坛，或者是微信群，维护自己的生态。 



- [x] 还要确认：人形机器人、绿色智能家居、绿色生活，都在范围内。（2026-08-19：**确认并在范围内**——新增 7 源：人形机器人 The Robot Report/IEEE Spectrum（ROBOT_SITES 直通→AI 榜）、绿色智能家居 千家网/Green Builder Media/中国家电网（关键词过滤，POLICY_KEYWORDS 补"以旧换新"）、绿色生活 绿色和平/Mongabay（GREEN_SITES 直通）。探测放弃：高工机器人/数智网/TreeHugger/EcoWatch/Energy Star/环保在线）
- [x] 最起码要把我web收藏的，微信关注的这些都update进去啊。这个项目还真不好做。（2026-08-19：**书签批次 A~O 完成**——`inbox/bookmarks_8_19_26.html` 筛选 18 候选 → 接入 15 源：国际智库/投行 9（Brookings/Bruegel/PIIE/CSIS/Chatham/Carnegie/RAND/CAP/高盛）、中国 4（财新/国家节能中心/澎湃/36氪）、AI 2（Artificial Analysis/虎嗅）；探测放弃 3（绿证平台 JS壳/WaytoAGI RSS404/Wilson Center Google 0条）。★ 达 62 源、线上 69 源。⚠️ PITFALL：Google News 括号 OR 语法返回全站混合内容（绿色命中<10%）→ 全部改用单主题词 query + when:30d；高盛官方站索引差 → 用「"Goldman Sachs"+主题词」；金融维度 23→39 条补弱成功。后续待办：微信公众账号源、X.com、agent 接口（MCP））
- [ ] 还是应该像news学习，尽量简洁，首页上只放题目是最好的。但是背后要下载，组织自己的媒体数据库。



- [x] 这篇新闻：Strengthening democratic over sight in national security。事关国家级安全，政治、ai、民主的这样一个话题，对我来说是关注度很高的话题。请检查评分标准，针对此类话题进行优化。

- [x] Coinbase 风格的新皮肤很好，可以实施。（2026-08-19 已完成：styles.css v4 重写为 Coinbase 蓝白黑金融级质感 + DM Sans + 深/浅区块交替 + 胶囊按钮，index.html 加字体，app.js 零改动；已验证 200/数据完整。v7（08-19 二次优化）：hero 改浅色协调版——老温反馈"白底+深色大标题"突兀，页面统一浅色调，深色仅留时间线锚点；nginx 给 index.html 加 no-store 缓存头，修复 Chrome 缓存旧版导致黑底/Wave 白底显示不一致）
- [x] 四维分类演进（2026-08-19 主体化 → 2026-08-20 观察窗口化）：
	- 提议：政策→政府、技术→行业、金融、AI科技→AI，即「政府/行业/金融/AI」按行为主体划分
	- 背景事实：①「技术」维度 83 条里多是行业动态（铁矿石/企业火灾/出口数据），名不副实，实际是兜底分类；②腾讯《碳中和中期报告》因标题含 AI 被 AI科技 抢走（83分），老温认为主体应是双碳行业
	- 决策点 A（核心）：AI×双碳交叉归哪边？推荐 A1 双碳优先——命中双碳核心词（碳中和/碳达峰/碳排放/碳市场/双碳）优先归行业，纯 AI 信号（大模型/智能体/OpenAI 无双碳词）才归 AI；纯 AI 源（机器之心等）仍直通 AI
	- 决策点 B：火箭回收/核电装料等技术突破并入「行业」档（技术关键词并入行业档），不做子分类（推荐）
	- 决策点 C：history.json 62 天旧 dimension（政策/技术/金融/AI科技）——推荐一次性迁移脚本重算 dimension + 重打分（因内容强度档位 key 也改）
	- 附带发现：radarai GitHub 趋势出现 vitejs/vite 等非绿色项目（TECH_SITES 直通技术兜底），改名行业后更违和，建议顺带给 radarai 加绿色主题过滤
	- **2026-08-19 已实施**：A1 双碳优先 + 政府/行业/金融/AI 主体化 + 技术突破并入行业档 + migrate_dimensions.py 迁移 1156 条 + radarai 绿色/AI 词过滤；腾讯报告→行业 73 分 A；分布 政府204/AI149/行业141/金融35
	- **2026-08-20 观察窗口化**：老温发现「政府/行业/金融/AI」混用两把尺子——政府/行业=行为主体、金融/AI=内容领域（金融⊂行业、AI⊂行业，层级感混乱）→ 四维改名 **政策/产业/市场信号/AI**（四个观察窗口而非互斥分类：政策=部委发文动向、产业=企业进展兜底、市场信号=碳市场/绿色资本、AI=AI×绿色落地）。同步改动：categorize_dimension 返回值 + CONTENT_STRENGTH_RULES 档位 key + score_item 默认值（update_news.py）；前端 DIMS + tab 副标题（政策·部委文件/产业·企业进展/市场信号·碳市场资本/AI·AI×绿色落地）+ dim-* 徽章类（app.js/styles.css/index.html v25/v13）；文档 打分体系标准 v2.2 + AGENTS.md + 标签标准 + README + daily_digest + build_radar_notebook + 四维透视.ipynb；migrate_dimensions.py 复用迁移 852 条，分布 政策194/产业125/市场信号37/AI148，零旧值残留。已验证（py_compile + 浏览器实测筛选/副标题渲染）。**2026-08-20 已部署**：update_news.py + 前端三件 + migrate_dimensions.py scp 服务器，迁移 528 条（历史 830 条零旧值），前端 md5 一致
- [x] **标题污染大修复（2026-08-19/20）**：Google News 收录站名/导航页 + 详情页 `<title>` 写死站名（chinanecc 全站 `<title>` 都是"国家节能中心公共服务网 - 节能研究"）导致「标题不是标题」。**三层防御**：① `article_content.extract_readable` 标题提取重构——h1/h2 遍历跳过站名/栏目/导航标题 + title 兜底（EIA 第3个h1/arXiv 分类面包屑/生态环境部跳转确认页/chinanecc 正文 h2 实测全部正确命中）；② `update_news.py` 详情页标题覆盖 + 素材标题回填加 `_title_similar`≥0.45 相似度门槛 + `_is_nav_junk_title` 过滤（站名 title 不再覆盖列表标题，坏 title-index 不再回填污染）；③ `_NAV_JUNK_TITLE_RE`/`_strip_rss_source_suffix` 增强（EIA/DOE/NOAA 长站名后缀剥离 len→70 + 导航/工具/栏目页词表 60+）。**数据修复**：本地+服务器 data JSON 修 83 删 ~50（mee 跳转提示→正确标题、cneeex 剥离"-上海环境能源交易所"、EIA/EPA/FERC/NOAA/DOE 站名与导航页删除）；Notes 素材改名 22 删 133（chinanecc 4 篇 H1 恢复 + 观测站/飓风预报/ENSO 例行页/DOE 导航页清理）；title-index.json 重建（跳坏标题 36-67 条防回填）；顺手补跑四维迁移（历史 528 条）+"待 scp 部署"的前端三件。**已部署验证**：70 源全 OK，本地/服务器 history+latest-24h 零残留，四维分布 本地 产业227/政策238/AI236/市场信号59、服务器 产业257/政策244/AI272/市场信号57
- [x] 日/夜护眼模式切换（2026-08-19 v8）：hero 右上角 🌙/☀️ 按钮，CSS 变量双主题（:root 白天 + html[data-theme="dark"] 夜晚），整页联动（hero/排行榜/时间线同主题——解决"页面白+时间线黑"割裂）；localStorage 记忆（ghn-theme）+ head 内联脚本防闪白；默认白天。已部署线上 md5 验证通过
- [x] 新闻重复修复（2026-08-19）：Google News RSS 聚合 URL 是 base64 且每次抓取不同，按 url 去重会漏（实测日本环境省一条新闻 x8 重复）。改为按规范化标题去重（_title_dedup_key：去空白/标点后小写取前120字符），三处生效：fetch_foreign_gov 跨 query、主流程 seen_items、merge_history；新增 scripts/dedup_items.py 清理存量（本地 39 条、服务器 62 条）。已部署 md5 一致
- [x] 旧源 Google News query 括号 OR → 单主题词（2026-08-19）：实测 `site:x (a OR b) when:7d` 返回该站全站混合内容（绿色命中<10%），`site:x a when:30d` 返回 70-90% 相关内容。`scripts/_split_or_queries.py`（幂等，备份 /tmp 后自动拆分）批量改 58 处——覆盖 EPA/DOE/EU/PIB/NOAA/EIA/FERC/CARB/日本三省厅/Euractiv/E3G兜底/环交所/NCSC/CAEP/环境报/机器人 7 源。验证：总量 477→482，NOAA +4/Robot Report +3/EPA +2；四维均衡 政府169/AI135/行业155/金融23。已部署
- [x] 发布时间修复——原文时间优先，抓取时间仅作判断（2026-08-20 老温发现：《碳达峰碳中和综合评价考核办法》答记者问（chinanecc 转载）标题/原文是 4-23，网页却显示 8-19）：根因链① update_news.py 写 Notes 时详情页/RSS 都无时间 → 拿**抓取当天**兜底（last resort），首抓日被 published-index.json 永久固化（chinanecc 全源 20 条全标 8-19）；② article_content.fetch_article 的 future-safety-net 只认 `%Y-%m-%d %H:%M` 格式，date-only（4-23）触发 ValueError 被误杀置 None。修复：③ update_news.py 兜底当天 → published 留空（空值不进 published-index，JSON 侧 first_seen + time_source='scraped'，前端显示「收录 X」）；④ safety net 分格式校验（date-only 判未来按天容差）；⑤ scripts/backfill_pubtimes.py（幂等）重抓 226 条可疑条目详情页——修正 124 条真实发布时间（chinanecc 全部回到 4-23 / 2024-2025 真实日期，35 条历史文章正常回显）+ 102 条改判收录时间（aihot/arxiv 等真无原文时间），修复 date-only 漏 T00:00:00 的 ISO 格式问题。验证：答记者问前端显示「2026年4月23日」+ hover「发布时间」。⏳ 待 scp 部署服务器（含 article_content.py）
- [x] 四维趋势图（2026-08-19 v9）：排行榜上方新增 📈 四维趋势图（ECharts 5.5.1 本地自托管）——政府/行业/金融/AI 四色折线，横轴=原文发表时间（published_at 非抓取时间）、纵轴=该时段最高分（重要性峰值），tooltip 显示该时段最高分新闻标题；范围切换 当日/3天内/1周内/1月内/自定义日期；1d/3d 按小时桶、7d+/自定义按天桶；跟随日/夜主题配色。PITFALL：ECharts time 轴 data 必须 [时间戳,值] 对（纯数值数组画不出线，实测仅 350px→修复后 9600px）。已部署 md5 一致
- [x] 排行榜排名+评分弱化+分段筛选（2026-08-19）：① 卡片加排名序号 1. 2. 3.（前三名金/银/铜色 .rank-1/2/3）；② 评分弱化——score-badge 从"S82"文字改为纯颜色圆点（10px，颜色=级别 S金/A绿/B蓝/C灰/D浅灰，无 S/A 字样），分数详情放摘要（"综合评分 X 分"）+ badge title hover；③ 新增"分段"筛选器（全部/85+/70-84/55-69/<55，数字区间替代 S/A/B/C/D 级别，对应阈值 S≥85/A≥70/B≥55/C≥40/D<40）。已部署 md5 一致（app.js v21 / styles.css v11）
- [x] 时间线排序修复（2026-08-19）：排序从 String.localeCompare 字符串比较改 Date.parse 时间戳数值比较（byTimeDesc）——数据混合 +08:00 与 Z 两种时区格式，"08:08+08:00" 字符串 > "03:03Z" 但实际时间更早，导致 8:08 排第一。已部署 md5 一致
- [x] 时间线暂停按钮移除（2026-08-19）：新条目插入已有"不抢滚动"保护（下方阅读时只显示"回到最新"按钮），暂停无实际意义；删 tlPaused/tlPauseBtn 状态与监听，保留"回到最新"。已部署
- [x] 笔记正文回填 + 老笔记清理（2026-08-19）：① Google News 解码成功后用真实 URL 覆盖 base64 假链接（article_content.fetch_article 返回 real_url + update_news.py 写笔记用真链），下次抓取可匹配 stale_files 自动补正文；② backfill_google_news.py 批量重抓无正文笔记，有正文率 75%→89%（2537/2835）；③ 删除 31 条 2015-2025 老笔记（Google 链接已过期、站点导航页垃圾）+ ai-index 死链同步清理
- [x] 布局调整（2026-08-19 v14）：搜索框+「当日浓缩」移到四维趋势图与排行榜之间；移除「绿色动态」mode-hint 标签（HTML+app.js 同步清理）。已部署
- [x] 趋势图迭代 v10~v13（2026-08-19）：v10 浮窗固定右上角+hideDelay+pointer-events（trigger:axis 默认跟随鼠标、追不上点不到）；v11 triggerOn 改 click（mousemove 让浮窗内容跟随刷新、选不中目标日期）；v12 数据第5元素注入 url；v13 桶内 items[] 保留全部新闻（tooltip 前3条可点）+ 彻底移除 window.open 外部跳转（点击永远留本站，找不到自动切月周期+扩展时间线分页再定位）。tooltip 全中文（title_zh 优先）。已部署（app.js v13→v20）


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

## 2026-08-25（服务器网络 + 数据库收尾）

- [x] **服务器代理落地**：mihomo（Clash.Meta）+ 夏威夷家宽 SS 节点（nat.qq.pw:35102）——服务器出口变住宅 IP（147.81.120.142），Cloudflare 反爬源恢复正文（mongabay/cleantechnica/spectrum ✓；us_doe/openai 需 JS 渲染，后续）
- [x] **正文提取换 trafilatura**（学术界标准，消灭重复造轮子）：WAF 污染 44→0、无正文 18.3%→14.3%、图片 338→804 张
- [x] **qmd 一体式导出**：update_news 主流程直接产出 qmd；md 副本移除（qmd 唯一格式，Obsidian Quarto 插件可读）
- [x] 三 agent 审查完成（docs/agent-check-*）：转换管线可靠，问题在提取层

**遗留待办（P0/P1）**：
- [x] **去重治理（2026-08-24 完成）**：真实重复 = 标题变体 38 条（截断/标点/源名后缀/微调，同 URL + 标题相似），非 agent-check 的"19.6%"（那是 normalize_url 去 query 把 cnesa/chinanecc 文章 ID、微博热搜误判为同 URL 的错误口径）。修复：`dedup_similar.py` 清理存量 + `update_news.py` 加 `_titles_similar` 标题相似度去重（防增量）。history URL 重复 45组→10组（剩的为微博热搜/GitHub 双标题等"同 URL 不同文"合理情况）。⚠️ 后续可选：GitHub/aihot 的"同 URL 双标题"需 URL 精确去重 + 白名单（微博热搜豁免）
- [ ] 多维标签回填：tech_feature 5.5% / trl 16.4% 基本空置 → LLM 批量补
- [ ] 图片防盗链攻坚：中国能源报 272 张外链（Referer 处理）
- [ ] arxiv 类面包屑/页脚混入（trafilatura 后处理清理）
- [ ] us_doe/openai 正文抓取（JS 渲染方案）
