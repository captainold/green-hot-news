#!/usr/bin/env python3
"""清理被误抓的垃圾笔记：导航页/注册页/协议页/首页等。

删除清单（2026-08-11 甄别）：
- 碳道：会员专享、安装APP、ICP备案、用户使用协议、短信注册、邮箱注册
- 中国能源报：投融资·IPO（栏目导航页）
- World Bank Climate：ext_en_home（首页）、ext_en_development-topics（导航）、
  ext_en_topic_climate-change（导航）、en_news_immersive-story（正文垃圾）
"""
import os

JUNK = [
    # 碳道 6 篇
    "Notes/媒体库/碳道/会员专享（VIP）.md",
    "Notes/媒体库/碳道/安装“碳道”碳交易手机客户端新闻产生价值 资讯挖掘商机下载APP.md",
    "Notes/媒体库/碳道/沪ICP备09061909号.md",
    "Notes/媒体库/碳道/用户使用协议.md",
    "Notes/媒体库/碳道/短信快捷注册.md",
    "Notes/媒体库/碳道/邮箱快捷注册.md",
    # 中国能源报 1 篇
    "Notes/媒体库/中国能源报/投融资·IPO.md",
    # World Bank Climate 4 篇
    "Notes/政策库/国际组织/World Bank Climate/https___www.worldbank.org_ext_en_home.md",
    "Notes/政策库/国际组织/World Bank Climate/https___www.worldbank.org_ext_en_development-topics.md",
    "Notes/政策库/国际组织/World Bank Climate/https___www.worldbank.org_ext_en_topic_climate-change.md",
    "Notes/政策库/国际组织/World Bank Climate/https___www.worldbank.org_en_news_immersive-story_2025_11_11_building-resilience.md",
]


def main() -> None:
    removed = 0
    missing = []
    for fp in JUNK:
        if os.path.exists(fp):
            os.remove(fp)
            removed += 1
            print(f"删除: {fp}")
        else:
            missing.append(fp)
    print(f"\n删除 {removed} 篇垃圾笔记")
    if missing:
        print("未找到:")
        for m in missing:
            print(f"  {m}")


if __name__ == "__main__":
    main()
