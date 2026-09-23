# 数据质量检查报告（QA）
生成时间：2026-09-03T08:49:58.490169+00:00
数据源：latest-24h.json（508 条）

## 总评分：**91.0**（A 级）
- 🔴 error：2 条  🟡 warn：10 条  🔵 info：268 条

## 问题清单（按严重级）

### 🔴 ERROR（2）
- [美国FERC] title_zh 与原文完全相同（翻译失败回退）
  → https://news.google.com/rss/articles/CBMiywFBVV95cUxQQmhqRTE3ZTVTREd4eWdpS0ZPRzNNUC1LdlhLYV9iMmNzQ3Z5SWQ2UlJYZkZmbm80dV9qc21tSmtqNUhRZ2w1QWxPd3ZyOE8yUHJVcFh2MGo1YUJJR3d3cUFpRGR1UFdkR1B4MHJvRzNoRGw5cnhTaWtnakZCeWE5aUt2Sm5oUXpNVHlVV1FWM0daOTBQRnBGRnlxSE9HZDFDVFJnSEk5TmhGUFRmUTdQS0dFYnRCMEIwbXVnOWptUFNHVXVxSkx3bGswWQ?oc=5
- [Nature Sustainability] 标题含 HTML 实体/标签残留: Contributions of traffic to daily PM<sub>2.5</sub> exposure 
  → https://www.nature.com/articles/s41893-026-01925-5

### 🟡 WARN（10）
- [OpenAI] title_zh 机翻残留英文: ATV Big Air Tour通过ChatGPT将3天的工作变成3小时
  → https://openai.com/index/atv-big-air-tour
- [Mongabay] title_zh 机翻残留英文: 蒂亚戈·卡拉伊（Tiago Karaí）和劳迪西亚·贝尼特（Laudiceia Benites）帮助收复瓜拉尼土地。上个
  → https://news.mongabay.com/2026/09/tiago-karai-and-laudiceia-benites-helped-reclaim-guarani-land-they-died-with-their-children-in-an-accident-last-month/
- [印度PIB] title_zh 机翻残留英文: CCI批准TPG Nicobar SG Pte.收购Aseem Infrastructure Finance Limit
  → https://news.google.com/rss/articles/CBMiaEFVX3lxTE1SOS1velVKeTRXaDVocno0eWpteEgtSC1sNDN6MTU3M255YmRZSnV5TWRYUi1uaXZmN3FmNTZkOUhVWjZSOGQ3SHNoRDItaFZPdWpNWDBFRGtNSnEwbUg2U29KbkR5Mjct?oc=5
- [Nature Biotechnology] title_zh 机翻残留英文: 普遍存在的RT-qPCR人工产物通过RNA靶向CRISPR放大了RNA敲除
  → https://www.nature.com/articles/s41587-026-03291-1
- [印度PIB] title_zh 机翻残留英文: Shripad Naik部长为Bambolim和Agassaim抽水站的两个并网太阳能项目揭幕
  → https://news.google.com/rss/articles/CBMifEFVX3lxTFBXeTl1LU5ZeDBZcDBYYmUxWUlyLW9ZeVNJSzBFX0Rkak9xN3pyMkJUb0FWUHB1dXpoelNJUkFnRGtvaDdVN1FRUGROWGRCNGQxbEMzZGkzLWFDcmROMG9LZ2hzV0ZWeGJ5NEZpbjhTOXJWckRldTFjMGZmNW0?oc=5
- [印度PIB] title_zh 机翻残留英文: 印度加快稀土和锂勘探;到2030年国内稀土永久磁铁产能将达到5，000吨：Jitendra Singh博士在Lok Sa
  → https://news.google.com/rss/articles/CBMicEFVX3lxTE13VGZ6eVBBMmNUUlZTaFhJMER4b1psbXAxYnd0aEt5WUYzY0JMbnpZcl9iaVYtdlZRQ2JMUnNhOXNvVElraTJuN3FTUERqM184dUN2YUdrdkVkUkVvcWFLNjJGS050Qm1FaWVVMTJOTHc?oc=5
- [印度PIB] title_zh 机翻残留英文: 为农村发展而促进融合：DDWS呼吁各邦/州在《VB-G RAM G法案》的框架下，整合JJM 2.0和SBM-G 2.0
  → https://news.google.com/rss/articles/CBMiaEFVX3lxTE84NzJlbTdhOXNGcHVKSzF4eFZNU1lEa2RKUS1vTG56WXIwMUdrUWlsQVRIZmZHZHdPTzdJa0JOYWpDZUkzSFJzVXpxYmVQOU4xMG5iUmg4UWlrRGFoNlpfNU9xSTdhQUlf?oc=5
- [TERI·印度能源与资源所] title_zh 机翻残留英文: “TERI创始人日”：部长Shri Pabitra Margherita发表第25届Darbari Seth纪念演讲
  → https://www.teriin.org/press-release/teri-founders-day-minister-shri-pabitra-margherita-delivers-25th-darbari-seth
- 最新24h无条目（可能正常低更新）: ['agora', 'americanprogress', 'brookings', 'bruegel', 'cenews', 'chinanecc', 'cnesa', 'csis']
- 摘要为空占比偏高: 275/508 (54%)

### 🔵 INFO（268）
- [财新] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiZEFVX3lxTE1WQmtoVXozdGtzMHBzZExsZ0JwalM2c2MwZURfbzA5Ymx1V3E4d1NETzJiMTNGb21HMUVKQXZhMnF6VzhpaFd0WHpMbFZGRlNkTUhLdE4wZkwwcEsxRkxxdGNOd3o?oc=5
- [虎嗅] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiU0FVX3lxTE5XU3F3ZWFIZTllTnhmdW9sU0JDT2dqdm83cWxhYzlCcnNfQW5PZUJVbUtiV0dmUkphOFJDbWRYNGhzaS1uM1RGZ0NjTW50TWtXUXY0?oc=5
- [36氪] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiTkFVX3lxTE5HSEVxNUI2YnRnbzJRUXB3a2tkUXRNZ1ZvR0RTcGJ0djNubi1ESjlGODRmSTdXcGZuRTJSN0lTcjFXSzJWRkUtUmowdlkwUQ?oc=5
- [美国EPA] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiXkFVX3lxTE84a2liVXNFbHhmWmFNTlBfbTdmS2JleVFsNnlGdUtfd0s2dV92bERTeVZDckRRaXlSTGthb3NCV1l3R2Q0OEFrcGlrV2x4NDQ5V0dYZW9BaVJvYmJINmc?oc=5
- [虎嗅] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiX0FVX3lxTFBrNm41QjJSR1B4aUp6MjBNRlFDOW1JU1lvVUpIWFFPV3l0R3k2SWdHRGRlZ2Q1Y2NCV2FLbEdqeGk1MkQ5NXN3ZC1mQkJYVHZ4ZXowRmxCRXZfcUx0c2Vv?oc=5
- [虎嗅] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiX0FVX3lxTFB0aFZnOW5fMDc4V1A1YW1oUGREQ2VsTlNIU3hKblVGWEg3NWY1Umw5S2Fqc0xHUzJNMWU1YXNRVVpFYUUyazNWVjNrQkY1dThDQzFZZEJWVWRXaUdpVkJz?oc=5
- [美国EPA] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMimwFBVV95cUxPZUtmRE83V1A0a1ZiU0pUVU00Q3dya2RySktBN2lfejhEQnRlOXNjX3BneHJxekxLNHhCMnlkbWhNZ3EyNld5emg5eERVMWxRTTBmcmNHWFVodUtUUG5tWlJhT0RNcVFpWkFjcXJhQWppZTQ1WXcxdUV2VXp4cWlnNTJxLUgyRnFBSlR0NWpEbjZ1Y1JrN2xnN1dDUQ?oc=5
- [arXiv·AI] 标题超长(121字): When Does Information Sharing Improve Decentralized Discovery? Aggregation, Inde…
  → https://arxiv.org/abs/2609.01814
- [量子位] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiVEFVX3lxTE1ucWY5X2FJbHFFSk5hT0cybFJ0d0VBZ2tVUkRYTDY2SWZicklBc2ZCMGU3TEdwZlJ2dVR3d2NDVVBFbHBnRVZpYllIUFA3eW1RdEEzNQ?oc=5
- [虎嗅] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiX0FVX3lxTE5qWDUtaWM0amJ5UWNGN3ItbFNEUGp1d2otNHRjV2MtanA0X0xGNldybklHdjFKSWJkV09mRXZubndHLS1HWGNsTU96VEpzaWhTOTJMSmJianNtTWpteVRj?oc=5
- [美国EIA] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiX0FVX3lxTE5GSFlKTEU3YXRDUVFMemtCNXFzQXAwQnc1dkQ0SDdINC14RXU2S1lSaEtyZ2xvWWZkVzV1WUc3d1piNWNsNmFyU2FQSE9hVHVMVWZGcl9valZXX0xDUV9B?oc=5
- [澎湃新闻] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiXkFVX3lxTFBLMGZsRVc1VnV5SE9sZTM2MnBoS0tCX0VHX3RUYTNLc2wtcXB6SWNsTF9JUjZ3V0RXSWJqV0NIaURmNFROenNidHJEWFZoUG9aYUE4VVN2N1BBdHZDQ3c?oc=5
- [虎嗅] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiYEFVX3lxTFA4ZHF5a0t2b0hGbHlNb2s0X0ZCUDkzcm5LZlZJV1BJand3eFVNRTdFM0FuYUx0U0dFdncwTEQ0bjZpN0Zyejk1T0ZrNXhKdVlFRFQ4NlFBTXVJalVGUlFUNQ?oc=5
- [虎嗅] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiX0FVX3lxTE9ZdE9FamYxbDRvLVdYX3ROckxYN0xOYjJlbnk2R1drN3JDY3BocWM0bUV0V1dqdXRCbTBQejhNcThKdDdRNGNodFctWVNIZFYtNi1nTGdWQkR2SVB4cllz?oc=5
- [虎嗅] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiVEFVX3lxTE5ZUGZSNGNVOVBZb3k5VGE5QldnWXMtOS04WGlFdEd0QlZTLWU3VGpxOWpvbUlWSzFlbEMxc0RSalcwQzBXbUFEbEZQMC1WcHl0WkdibA?oc=5
- [千家网] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiYEFVX3lxTE1CTFg3OVBlMUZjRzdtZW1oalFNOHhzdHNuYUxnVnVQZUc5UHNreG9rS2pyMFFXampHZlN1S3gyR0pfNlNsUDlRWUVMbzBfSm81TEpWM3o3RTJyRHFCVVNJSg?oc=5
- [北极星电力网] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiUkFVX3lxTE9CWGtrMW9fS05lM2VjdE53RWVsMXo0YmVkaDVBWWJLdTd2M3JWYUVBYnI2UkRQSUR5dXRZYVFzMnRwdFMxektDbHZqZEYyU1dCb3c?oc=5
- [Artificial Analysis] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiY0FVX3lxTE9CWm1kZXZ5RHVKaU9uZXFVRnZad1JKQVAtYWdNUmE5ZTdfSXlBLWFCdVRCQWRtV1dpVjZRZ0ktcjNzRHJ6R3JkRk5XTXY2YWRVemNGYkhkYUJBcnpBeFdyOGlTVQ?oc=5
- [CleanTechnica] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMimAFBVV95cUxQUHRoaGg1RDl2ODl1TEh1d2ZQQThCY1ZwbUhNZkZVb2x6MmJIRVU2VjY1ZHQxbko0M2xuTDh2NFJsa0UzbTBkZ3plVTJjcUx5cmNsb1g2RTAxZXg0ZUF2M3ZqQjBQcmZmam1oY24xQ3VJbWJpLUtPQk43SE1OdHBIem1tWnBYZzhyS0d6SUZSYS1NaXVoNHJ4eA?oc=5
- [World Bank Climate] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMifEFVX3lxTE5MTlktMFRrMmw4VDdMcE9TRDIxMFZZR2ZDbTIyMlZGZ2J1QlQzRHRPZUxSUEQyaVJFVEJ2STFyUXRwYXhvbjdnYWdyWkRVLW1tWHVaUFVqSXY5TWZoU0pKVHZIbGpZMUF2emFBVHVWa2JHQ2lhazFxNHdLYTc?oc=5
- [高盛] 标题超长(133字): German Environment minister Schneider links Nepal flash floods to climate change…
  → https://news.google.com/rss/articles/CBMihAJBVV95cUxOZ0U1U3JfQmFFUUhXNlhBQzBmZFp1cncxRTBYTnFzU2x2Mjh6QmczNE9obEw0elB5N1hNNXc0dHdhRTZrRHVpdzhFRllla1ptci1rSExsTmRXT1k4TnlRTTU5a3MtQ2d0SDBQQjBWTFRvRDg2UkJxVU1PdzBxTWxQekdwdlNZREttVi1sYVhhMHZEbjA3bjJNV05HQ0xTc01VNDNocDRpdExsd1dtMmU3V1FWZklGLTFuOGJaVl9PblR1eV8tSXBibmtqNHV4YkpEWHhnV0Ixd0ZtMFBYTU5PUmlXbjg3Qmk1ZEtiZW9KWm9Ga1c4SFpNWlE4Wmd3UThvSEEtMg?oc=5
- [高盛] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMihAJBVV95cUxOZ0U1U3JfQmFFUUhXNlhBQzBmZFp1cncxRTBYTnFzU2x2Mjh6QmczNE9obEw0elB5N1hNNXc0dHdhRTZrRHVpdzhFRllla1ptci1rSExsTmRXT1k4TnlRTTU5a3MtQ2d0SDBQQjBWTFRvRDg2UkJxVU1PdzBxTWxQekdwdlNZREttVi1sYVhhMHZEbjA3bjJNV05HQ0xTc01VNDNocDRpdExsd1dtMmU3V1FWZklGLTFuOGJaVl9PblR1eV8tSXBibmtqNHV4YkpEWHhnV0Ixd0ZtMFBYTU5PUmlXbjg3Qmk1ZEtiZW9KWm9Ga1c4SFpNWlE4Wmd3UThvSEEtMg?oc=5
- [Artificial Analysis] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMibEFVX3lxTE1jVDEwRWJVNjlLM1Y4dXptdFJBRXI1M3JzTnBvVVlDSlBuSzBrd0NlbVlIUWwxY25ZMFNBWndtU2hhMzFYRDBFVnFrUThJTVdxR1RZNFJmVWVyVkh0ekFwMmpLbzMyY3E4UW43Xw?oc=5
- [美国EPA] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMigAFBVV95cUxQeUdpbmFNQk5HVng0WjFjN1dNaGhsblU1d2tZSnpoS0RpUzIzTTM5TlBXT29yUEY0QWF5RGVVQmt3NWNxTldNdEkwUXlYUy1nM1BuT0xQbDhORUhmWlV6TlptU2pmUFc3dkstVnZLdFpET0lIc0pMcldVREVEUkRYcw?oc=5
- [Carnegie] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMinAFBVV95cUxOUXQ3dTNFNmVyZW5Tak1SZkFWa19RMnpYRU1xbVlranc3WGZ1U3hVM3BBQ1EzVmI4UGtMSFpTbktUNkFFbzFEX3B4TnM1M1pNQmlSSFl5bUNLUmJneWx6NFJXdGlGcnNCX1Q3NTJMZ3MtNzVqZlFsaThEb3pEaXhOSm1jTDdqM2xJRmR1NEhfRTQzX2ozWXZhQW1hOF8?oc=5
- [Artificial Analysis] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiaEFVX3lxTE1rNUEwbGF3WXBpbncyenNKaFNlSUhRcmYwNlU2b2dvVTU5aTFFTGJrbGNVUHlaYnpyZU1xUExFaE9kNnVPM1M2OU1hN0haMk94b1dOQmJGV3lobHhTYnU1ajE3ZnBHM1NB?oc=5
- [Artificial Analysis] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiYEFVX3lxTE9hc0pmM2Z4WXNFNmZjRVZhSEZERjYxeF9KYzh2dFM0U2U4ZHE5RXhxTXhzV09JRFgzUVR1UFQzaFVkNmpmTmM1dU9nNHh0bFd5TGJIZkkzSGx2UkFRQ2dXbQ?oc=5
- [美国EPA] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMijwFBVV95cUxQZU9sd19NaE0xT2NuakRPcjBSWnB6X2daOWQ5RVY4bzhyeTJBdVQ0Unl5cWNmY3VEU0RoSmVTdTJHRDBfU3RqUTV6YVotNnluX25zUFJ4TXBjSGw1aDY0dEUyUERQQ3VfS0hkZGgzQ1FyWmdzQmh2UGppWUJ2ZlVoVElUQ09zUWNOelZob1E0OA?oc=5
- [The Robot Report] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMimgFBVV95cUxPWHNYNFRxN3BycDRWTXNuWXFXYzJoNnhvVzdya0MyS1VCN1FGeHdDbU5lZUxhTkkyT3lUaTlGWlNwd2xEOVk1d3lnZVh1UVlISnhhR1psVEdxeXNNN0Q2SnJBUlpsNy1MSTZvVWdyb2NwcEhRX3ZFUDJlQnR6a1F4aGxpZU84VlJ5WkxQUGo2ZlYtRDVzZHFiYUlR?oc=5
- [虎嗅] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiU0FVX3lxTFBYb1RxMHNZU3R2ZGw2eE1DSFg5OHpMZXYyQUlPZGxkS2hYVGxmSjVwNTJHM18xSGZTMllLMi1Ud3BfQVNaN1ZsLWQzWVZ1ZWF3ZUFB?oc=5
- [The Robot Report] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMipwFBVV95cUxOT0dLcURJU0NqUGlxaWU1elY3UkVRUlNLMWVSNi14S3QyX2tUcFg0aENEWG9kTHZQOUdObUVURzV4eDhYZ2VCUlB3cmRCT2FmeFZ6LUo4YU5aRE15RnF1Tm10MHRYRFlrMHBXd05YWGNPREd4dl92VlBTalg1NmRTWGlwc0QzRWEyMHg1cUFLMFBJOFNneDk4RS1FWTZVM1JKZTF5SVVQYw?oc=5
- [UNFCCC] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiogFBVV95cUxNMmdrZ203T1NHR3owX0N0N2g3QzVkRHY3aVhEUUhraFJCUUg3QWh6Y2NLU0lOYjMwNEI2X0NrNmlLTHpmMHRCY21ENjNqbHViVTRiNUNOS3plYnZRaHRNU2U3UWJ5RDNFejl5UU9leXpjSG0zMXJtMG5NYkhsUHFyY3NKdXNGRHdYNVpUQW5NNXltMXVDQjVWVDVBNzhzc2t0OVE?oc=5
- [Artificial Analysis] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiZkFVX3lxTFBEUlktckgwdGRlT3l1Z1BTYUZNMHlZZ0ZSalpUWDNETnVOUFhMdEVCb0JtSjN6V0xWR0ZSV0V5em9aZmVVaVZNNnN5Qjh1QjNDV3pzSXZDLWhZODBtcjFMX0oxOGd1Zw?oc=5
- [36氪] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiTkFVX3lxTE9CTHktM1BWcnYzSXdGWUFkazBSZmFVTW95UldkQmxLNDlhbjhxVkJrUkplQWtvRnhxTDRvUXktdnVGamdVSG8wemgxZGtMdw?oc=5
- [36氪] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiTkFVX3lxTE1Cblg0YjRmVUlCRkg1aTQtTl9hUkZTQkJ5Q21TT2hWYTN4MlA3b1VPcUR5ZUJtWDJCTGJiSTlYNTd4d2xXSEU2RUNWYW45dw?oc=5
- [Artificial Analysis] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMib0FVX3lxTE5XVnVLVzBzcUxNaHdobmctbFFsRm82MXdvaHY5dnlsbGI1RW9fbE5CMTRkMU1qdVJLYjZ2ZnVDbWlqbkhGX1FaUFVmVi05ZnNveEp3dGJPMzNaOUFpeWdXWlZDc2xNOVpjR01LZm1iZw?oc=5
- [Artificial Analysis] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiY0FVX3lxTFBIdVUzYXhST29pampxRjRDeGFIbWk3UFVNenkyeS1LVjM5bU05Ymp4WE9VbDdpMHBIOWlXZ0JMTy1vdl9GTjlGS3luc2tPblJKajdSZEk2S0duZHNXOThoZ25Ucw?oc=5
- [环境规划院CAEP] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMib0FVX3lxTFBkNVJ2TV9IUWRIdkJSN3VfdUtTUnhnVTVBaHJCYkNCaTRtR05DZWJ5UlJNT3VFNzVHeUlaTzJYWnVMS2w1RVMxcmMyQUthWGJfenl2bUt4VlI1U1RxWC1HdmptWU12VFE0cnRINnBsUQ?oc=5
- [环境规划院CAEP] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMib0FVX3lxTE0yUGRmNGNtUGdHXzQxSUxyaXFyY2JPNVFNUTR5Tlc4anM4UHdYTkR1cEZSR182T1hmTmFCclNURXBoUndTLVBCdFlOX0FEQy04cUFUY3RUWmltSHg5OFhSTXRtMXVjbzRNWWhBNzU2WQ?oc=5
- [UNFCCC] Google News base64 聚合链接（未抓详情页覆盖，属正常状态）
  → https://news.google.com/rss/articles/CBMiX0FVX3lxTFBKQlFaemV0OVExYWk2SHowdHVDSlZUQ1FmNWtaMjRiUGZVdGtVS0o0VlJTYm5Rbmxmd2FmbWYteHBhMzgxV3ZObmlvdjY1ODdfSHVBYm9STEZpY3MwQWVJ?oc=5
- …共 268 条，详见 JSON

## 各源条目数（Top 20）
- cac: 53
- aihot: 38
- chinaenergy: 30
- mongabay: 30
- arxiv_ai: 30
- radarai: 24
- eu_commission: 20
- india_pib: 20
- us_doe: 19
- us_eia: 15
- huxiu: 14
- therobotreport: 13
- hotorcool: 12
- ccai: 12
- artificialanalysis: 11
- jp_moe: 11
- thepaper: 10
- bjx: 10
- 36kr: 9
- us_noaa: 9

> 本报告由 qa_check.py 自动生成，只报告不修复。问题处置由人工/agent 决定。