


- [x] 标签体系
- [ ] 政策库文件，不是按照wiki方式组织的。而是按照单位。
	- [ ] 政策库按照国家、部委部门来分，这里也要包含从部委网站上发布的专家解读。
	- [ ] 媒体库，指的是除了政府网站上其他的媒体和专家的评论解读。 
	- [ ] 还应该增加一个人名标签，这个怎么反映到wiki里面呢？ 
- [ ] 建立打分筛选机制，打分体系。这个是我的核心卖点，代表我的品味。现在的tags效果还不好。
- [ ] 

- [x] 完善新闻源
	- [x] green-hot-news 
	- [x] allnet.hot
- [ ] obsidian新闻政策库是否完整？
- [ ] 能下载的都下载，形成数据库。
- [ ] 当日高分浓缩版，供我转发到群里和朋友圈，还有自媒体。

- [x] 添加这个：全网热点聚合：6ef1d8f4-8745-437c-a1e4-8c525ed8e971   https://api.allnet.hot/api/open/v1
	- [x] 服务器 /opt/green-hot-news 接入 fetch_allnet（15个源，systemd定时已生效）
	- [x] 本地 scripts/update_news.py 同步 + .env 保存 Key + 脚本自动加载
	- [x] .gitignore 忽略 .env（防 Key 泄露）

- [x] 本地 Obsidian ↔ 新加坡服务器自动同步（2026-08-13）
	- [x] Windows SSH 通道：moltbot260130.pem + config 别名 sg-moltbot（IP 直连，避开本地 DNS fake-ip）
	- [x] Notes/ origin 改为 sg-moltbot:/srv/git/green-policy-materials.git
	- [x] Obsidian Git 插件 basePath=Notes，autoPull 15min / autoSave 15min / autoPush 30min

- [x] 吸收这个项目：C:\Users\wenyu\Projects\archive\news-collection


| 项目                                 | 目标                                                                                                                         | 截止  | 状态                         |
| ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | --- | -------------------------- |
| green hot news                     | 包括政策库、技术库、消息库等。<br>历史积累和最新news。手机网页访问。agent访问。<br>最终是要办一个论坛社区。可以先从注册和身份认证，为今后社区化做准备。<br>                                   |     | 现在我是有了一个绿色政策雷达，green news。服务器部署+Obsidian同步已完成。 |
| zero-carbon-park-workbench Private | 工作台。这里可以让大家上传自己的资料，在我的服务器上。方便我收集资料？（这个也会比较敏感。）咨询师真正需要的是**自动化数据填报、合规性自查、标准框架格式化导出、多源资料的精准溯源**。报告功能应定位为“协同与智能化助手”，而非“自动代写器”。 |     |                            |

我是做个综合的个人关心的重要信息的雷达，还是做一个绿色政策雷达呢？ 

