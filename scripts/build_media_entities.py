# -*- coding: utf-8 -*-
"""补建媒体源实体页（org 类信息源，51 个）——关系图谱内联前置。
老温决策（2026-09-14）：媒体源并入 org，不独立成类。
幂等：实体页存在则跳过。
"""
from pathlib import Path

ROOT = Path(r"C:\Users\wenyu\Documents\Obsidian_wen\green-hot-news")
NOTES = ROOT / "Notes"
ENTITY = NOTES / "实体" / "机构"

# (name, region, desc)
MEDIA = [
    ("36氪", "中国", "科技创投媒体，聚焦 AI 与大模型产业"),
    ("Agora·能源转型", "国际", "能源转型智库"),
    ("AIHOT", "中国", "AI 资讯聚合"),
    ("Artificial Analysis", "国际", "AI 模型评测"),
    ("arXiv·AI", "国际", "AI 学术预印本平台"),
    ("Brookings", "美国", "公共政策智库"),
    ("Bruegel", "欧盟", "经济政策智库"),
    ("CAP", "美国", "进步政策智库"),
    ("Carbon Brief", "英国", "气候科学媒体"),
    ("Carnegie", "美国", "国际事务智库"),
    ("Chatham House", "英国", "国际事务智库"),
    ("CleanTechnica", "美国", "清洁技术媒体"),
    ("Climate Change AI", "国际", "AI×气候研究社区"),
    ("CNESA储能联盟", "中国", "储能产业联盟"),
    ("CSIS", "美国", "战略研究智库"),
    ("E3G", "国际", "气候智库"),
    ("Euractiv·欧盟", "欧盟", "欧盟政策媒体"),
    ("Green Builder Media", "美国", "绿色建筑媒体"),
    ("IEEE Spectrum", "国际", "工程技术媒体"),
    ("Mongabay", "国际", "环保媒体"),
    ("OpenAI", "美国", "AI 公司"),
    ("PIIE", "美国", "国际经济智库"),
    ("RadarAI·GitHub趋势", "国际", "开源项目趋势"),
    ("RAND", "美国", "政策研究智库"),
    ("Reuters", "国际", "国际通讯社"),
    ("TERI·印度能源与资源所", "印度", "能源环境研究所"),
    ("The Robot Report", "美国", "机器人媒体"),
    ("VentureBeat AI", "美国", "AI 科技媒体"),
    ("X平台", "国际", "社交平台"),
    ("中国家电网", "中国", "家电行业媒体"),
    ("中国环境报", "中国", "环境媒体"),
    ("中国碳交易网", "中国", "碳市场媒体"),
    ("中国科技网", "中国", "科技媒体"),
    ("中国能源报", "中国", "能源媒体"),
    ("全网热点", "中国", "热点聚合"),
    ("北极星电力网", "中国", "电力行业媒体"),
    ("千家网", "中国", "智能家居媒体"),
    ("机器之心", "中国", "AI 科技媒体"),
    ("澎湃新闻", "中国", "综合媒体"),
    ("碳道", "中国", "碳市场媒体"),
    ("绿色和平", "国际", "环保组织"),
    ("虎嗅", "中国", "科技商业媒体"),
    ("财新", "中国", "财经媒体"),
    ("量子位", "中国", "AI 科技媒体"),
    ("高盛", "美国", "投行"),
    ("高盛Insights", "美国", "投行研究"),
    ("Hot or Cool Institute", "德国", "气候生活方式研究所"),
    ("Nature Biotechnology", "国际", "生物技术期刊"),
    ("Nature Climate Change", "国际", "气候科学期刊"),
    ("Nature Sustainability", "国际", "可持续科学期刊"),
    ("经济管理学刊", "中国", "经济管理期刊"),
]


def gen_page(name, region, desc):
    fid = f"org/media/{name}"
    fields = [
        "---",
        f'id: "{fid}"',
        'type: "org"',
        f'name: "{name}"',
        f'aliases: ["{name}", "{fid}"]',
        f'region: "{region}"',
        "topics: []",
        "related: []",
        'tags: ["type/org", "source/media"]',
        'created: "2026-09-14"',
        "---",
        "",
        f"# {name}",
        "",
        f"> {desc}。信息源实体（媒体/智库/期刊），关联素材按 site 字段聚合。",
        "",
        "## 关联内容",
        "",
        "```dataview",
        'TABLE date AS "日期", title AS "标题", dimension AS "层级"',
        'FROM "Notes/素材库"',
        f'WHERE site = "{name}"',
        "SORT date DESC",
        "LIMIT 50",
        "```",
        "",
    ]
    return "\n".join(fields)


def main():
    created = 0
    skipped = 0
    for name, region, desc in MEDIA:
        dst = ENTITY / f"{name}.md"
        if dst.exists():
            skipped += 1
            continue
        dst.write_text(gen_page(name, region, desc), encoding="utf-8")
        created += 1
    print(f"新建媒体源实体页: {created} | 跳过(已存在): {skipped}")


if __name__ == "__main__":
    main()
