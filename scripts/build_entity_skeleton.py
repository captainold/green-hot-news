# -*- coding: utf-8 -*-
"""P1 实体骨架生成器：建 Notes/实体/ 目录（机构/技术/地区）+ 给 wiki 板块加 id。
幂等：实体页存在则跳过；wiki frontmatter 已有 id 则跳过。
"""
from pathlib import Path

ROOT = Path(r"C:\Users\wenyu\Documents\Obsidian_wen\green-hot-news")
NOTES = ROOT / "Notes"
ENTITY = NOTES / "实体"

# ============ 机构实体（26） ============
# id / name(全称) / aliases(简称) / region / topics / source_keys(source·site 原始值) / desc
ORGS = [
    ("org/cn/国家发改委", "国家发展和改革委员会", ["国家发改委", "发改委", "NDRC"], "中国",
     ["碳市场", "新能源", "电力改革", "工业绿色转型", "节能降碳"],
     ["国家发改委"], "中国宏观经济管理部门，统筹碳达峰碳中和、能源价格与绿色低碳政策。"),
    ("org/cn/国家能源局", "国家能源局", ["能源局", "NEA"], "中国",
     ["新能源", "电力改革", "储能", "化石能源"], ["国家能源局"],
     "中国能源行业主管部门，负责新能源、电力、油气等能源政策与规划。"),
    ("org/cn/生态环境部", "生态环境部", ["生态环境部", "生态环境部·解读", "MEE"], "中国",
     ["环境保护", "气候变化", "碳市场"], ["生态环境部", "生态环境部·解读"],
     "中国生态环境保护主管部门，负责污染防治、气候应对与碳市场建设。"),
    ("org/cn/工信部", "工业和信息化部", ["工信部", "工业和信息化部", "MIIT"], "中国",
     ["工业绿色转型", "电动车", "新能源"], ["工信部"],
     "中国工业主管部门，负责绿色制造、工业节能降碳与新能源汽车产业。"),
    ("org/cn/中国人民银行", "中国人民银行", ["央行", "人民银行", "PBOC"], "中国",
     ["绿色金融", "碳市场"], ["中国人民银行"],
     "中国央行，负责绿色金融标准、碳减排支持工具与货币政策。"),
    ("org/cn/中央网信办", "中央网络安全和信息化委员会办公室", ["中央网信办", "网信办", "CAC"], "中国",
     ["AI科技", "工业绿色转型"], ["中央网信办"],
     "中国网信主管机构，负责数字化绿色化协同转型（双化协同）政策。"),
    ("org/cn/国家节能中心", "国家节能中心", ["节能中心"], "中国",
     ["节能降碳", "工业绿色转型"], ["国家节能中心"],
     "节能降碳政策研究与推广机构，发布能效领跑者等节能信息。"),
    ("org/cn/上海环交所", "上海环境能源交易所", ["上海环交所", "上海环境能源交易所"], "中国",
     ["碳市场", "绿色金融"], ["上海环交所"],
     "全国碳排放权交易市场运行机构，负责碳配额交易与碳市场建设。"),
    ("org/cn/环境规划院CAEP", "生态环境部环境规划院", ["环境规划院", "环境规划院CAEP", "CAEP"], "中国",
     ["环境保护", "碳市场", "气候变化"], ["环境规划院CAEP"],
     "生态环境部直属研究机构，负责生态环境规划与碳市场配额方案研究。"),
    ("org/cn/NCSC国家气候中心", "国家气候中心", ["NCSC", "NCSC国家气候中心", "国家气候中心"], "中国",
     ["气候变化"], ["NCSC国家气候中心"],
     "中国气象局下属国家气候中心，负责气候监测预测与气候变化研究。"),
    ("org/int/IEA", "国际能源署", ["IEA", "国际能源署", "International Energy Agency"], "国际",
     ["化石能源", "新能源", "储能", "电力改革"], ["IEA"],
     "国际能源治理权威机构，发布能源展望、能效与清洁能源分析。"),
    ("org/int/IRENA", "国际可再生能源署", ["IRENA", "国际可再生能源署"], "国际",
     ["新能源", "储能", "电动车"], ["IRENA"],
     "国际可再生能源权威机构，发布可再生能源统计、成本与展望。"),
    ("org/int/UNEP", "联合国环境规划署", ["UNEP", "联合国环境规划署"], "国际",
     ["环境保护", "气候变化"], ["UNEP"],
     "联合国环境权威机构，发布排放差距报告、环境展望。"),
    ("org/int/UNFCCC", "联合国气候变化框架公约", ["UNFCCC", "联合国气候变化框架公约"], "国际",
     ["气候变化", "国际政策"], ["UNFCCC"],
     "联合国气候治理核心机制，负责 COP 会议与巴黎协定执行。"),
    ("org/int/WorldBankClimate", "世界银行", ["World Bank Climate", "世界银行", "World Bank"], "国际",
     ["绿色金融", "气候变化"], ["World Bank Climate"],
     "世界银行气候领域，负责气候融资与低碳发展贷款。"),
    ("org/us/美国DOE", "美国能源部", ["美国DOE", "DOE", "美国能源部"], "美国",
     ["新能源", "储能", "电动车", "化石能源"], ["美国DOE"],
     "美国能源主管部门，负责清洁能源研发、核能与电网现代化。"),
    ("org/us/美国EPA", "美国环境保护署", ["美国EPA", "EPA", "美国环保署"], "美国",
     ["环境保护", "气候变化"], ["美国EPA"],
     "美国环境主管机构，负责污染排放标准与气候法规。"),
    ("org/us/美国EIA", "美国能源信息署", ["美国EIA", "EIA", "美国能源信息署"], "美国",
     ["化石能源", "新能源", "电力改革"], ["美国EIA"],
     "美国能源数据权威机构，发布能源供需统计与展望。"),
    ("org/us/美国FERC", "美国联邦能源监管委员会", ["美国FERC", "FERC", "美国联邦能源监管委员会"], "美国",
     ["电力改革", "新能源"], ["美国FERC"],
     "美国电力市场与电网监管机构，负责输配电价与市场规则。"),
    ("org/us/美国NOAA", "美国国家海洋和大气管理局", ["美国NOAA", "NOAA", "美国国家海洋和大气管理局"], "美国",
     ["气候变化", "环境保护"], ["美国NOAA"],
     "美国海洋大气权威机构，负责气候监测、极端天气与海洋研究。"),
    ("org/us/加州CARB", "加州空气资源委员会", ["加州CARB", "CARB", "加州空气资源委员会"], "美国",
     ["环境保护", "电动车", "碳市场"], ["加州CARB"],
     "美国加州环境监管机构，负责低碳燃料标准与碳交易。"),
    ("org/eu/欧盟委员会", "欧盟委员会", ["欧盟委员会", "欧委会", "European Commission"], "欧盟",
     ["国际政策", "碳市场", "新能源", "气候变化"], ["欧盟委员会"],
     "欧盟行政机构，负责绿色新政、碳边境调节机制(CBAM)与能源政策。"),
    ("org/jp/日本环境省", "日本环境省", ["日本环境省", "环境省", "MOE Japan"], "日本",
     ["环境保护", "气候变化", "节能降碳"], ["日本环境省"],
     "日本环境主管机构，负责脱碳、循环经济与环保政策。"),
    ("org/jp/日本经产省", "日本经济产业省", ["日本经产省", "经产省", "METI"], "日本",
     ["新能源", "电力改革", "化石能源"], ["日本经产省"],
     "日本产业能源主管机构，负责 GX 转型、电力市场与能源安全。"),
    ("org/jp/日本资源能源厅", "日本资源能源厅", ["日本资源能源厅", "资源能源厅", "ANRE"], "日本",
     ["新能源", "化石能源", "储能"], ["日本资源能源厅"],
     "日本经产省下属能源机构，负责能源供需、石油储备与再生能源政策。"),
    ("org/in/印度PIB", "印度新闻信息局", ["印度PIB", "PIB", "印度新闻信息局"], "印度",
     ["新能源", "气候变化", "环境保护"], ["印度PIB"],
     "印度政府新闻发布机构，发布印度各部委能源与气候政策动态。"),
]

# ============ 技术实体（10） ============
# id / name / aliases / topics
TECHS = [
    ("tec/光伏", "光伏", ["光伏发电", "太阳能", "PV", "solar"], ["新能源"]),
    ("tec/风电", "风电", ["风力发电", "风能", "wind"], ["新能源"]),
    ("tec/储能", "储能", ["电池储能", "新型储能", "energy storage"], ["储能", "新能源"]),
    ("tec/氢能", "氢能", ["绿氢", "制氢", "氢燃料电池", "hydrogen"], ["新能源"]),
    ("tec/核电", "核电", ["核能", "核电站", "nuclear"], ["新能源"]),
    ("tec/生物质", "生物质", ["生物质能", "生物燃料", "biomass"], ["新能源"]),
    ("tec/CCUS", "CCUS/碳捕集", ["CCUS", "碳捕集", "碳封存", "碳移除"], ["碳市场", "气候变化"]),
    ("tec/电动车", "电动车/动力电池", ["电动车", "新能源汽车", "动力电池", "EV"], ["电动车"]),
    ("tec/电网", "电网/新型电力系统", ["电网", "新型电力系统", "电力系统", "智能电网"], ["电力改革"]),
    ("tec/AI", "AI（交叉赋能）", ["人工智能", "AI", "机器学习", "大模型"], ["AI科技"]),
]

# ============ 地区实体（6） ============
REGS = [
    ("reg/中国", "中国", ["中国", "China"], "中国"),
    ("reg/欧盟", "欧盟", ["欧盟", "EU", "European Union"], "欧盟"),
    ("reg/美国", "美国", ["美国", "USA", "United States"], "美国"),
    ("reg/印度", "印度", ["印度", "India"], "印度"),
    ("reg/日本", "日本", ["日本", "Japan"], "日本"),
    ("reg/国际", "国际", ["国际", "全球", "global"], "国际"),
]

# ============ 主题实体（10，= wiki 板块加 id） ============
# (文件相对路径, id, aliases)
TOPICS = [
    ("政策wiki/气候变化/气候变化.md", "top/气候变化", ["气候变化", "全球变暖", "气候"]),
    ("政策wiki/环境保护/环境保护.md", "top/环境保护", ["环境保护", "生态环境", "污染防治"]),
    ("政策wiki/工业绿色转型/工业绿色转型.md", "top/工业绿色转型", ["工业绿色转型", "绿色制造", "零碳工厂"]),
    ("政策wiki/国际政策/国际政策.md", "top/国际政策", ["国际政策", "国际动态", "全球治理"]),
    ("政策wiki/AI进展/AI进展.md", "top/AI进展", ["AI进展", "AI科技", "人工智能进展"]),
    ("政策wiki/AI与能碳/AI与能碳.md", "top/AI与能碳", ["AI与能碳", "AI能碳", "算电协同"]),
    ("政策wiki/新能源/新能源.md", "top/新能源", ["新能源", "可再生能源"]),
    ("政策wiki/电力改革/电力改革.md", "top/电力改革", ["电力改革", "电力", "电力市场"]),
    ("政策wiki/碳市场/碳市场.md", "top/碳市场", ["碳市场", "碳交易", "碳排放权交易"]),
    ("政策wiki/绿色金融/绿色金融.md", "top/绿色金融", ["绿色金融", "ESG", "气候投融资"]),
]


def yaml_lines(fields: dict) -> str:
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, list):
            if v:
                items = ", ".join(f'"{x}"' for x in v)
                lines.append(f"{k}: [{items}]")
            else:
                lines.append(f"{k}: []")
        elif isinstance(v, str):
            lines.append(f'{k}: "{v}"')
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def gen_org_page(o) -> str:
    fid, name, aliases, region, topics, src_keys, desc = o
    fields = {
        "id": fid, "type": "org", "name": name,
        "aliases": list(dict.fromkeys([name] + aliases + [fid])),
        "region": region, "topics": topics, "related": [],
        "tags": [f"type/org", f"region/{region}"],
        "created": "2026-09-14",
    }
    where = " OR ".join(f'source = "{k}" OR site = "{k}"' for k in src_keys)
    body = f"""# {name}

> {desc}

## 关联内容

```dataview
TABLE date AS "日期", title AS "标题", dimension AS "层级"
FROM "Notes/政策库" OR "Notes/媒体库" OR "Notes/数据库"
WHERE {where}
SORT date DESC
LIMIT 50
```
"""
    return yaml_lines(fields) + "\n\n" + body


def gen_tech_page(t) -> str:
    fid, name, aliases, topics = t
    fields = {
        "id": fid, "type": "tec", "name": name,
        "aliases": list(dict.fromkeys([name] + aliases + [fid])),
        "region": "", "topics": topics, "related": [],
        "tags": [f"type/tec", f"topic/{topics[0]}"] if topics else [f"type/tec"],
        "created": "2026-09-14",
    }
    where = " OR ".join(f'contains(topics, "{x}")' for x in topics)
    body = f"""# {name}

> 绿色低碳交叉技术实体。相关条目按 topics 聚合（P2 补 tech 字段后精确化）。

## 关联内容

```dataview
TABLE date AS "日期", title AS "标题", dimension AS "层级"
FROM "Notes/数据库"
WHERE {where}
SORT date DESC
LIMIT 50
```
"""
    return yaml_lines(fields) + "\n\n" + body


def gen_reg_page(r) -> str:
    fid, name, aliases, region = r
    fields = {
        "id": fid, "type": "reg", "name": name,
        "aliases": list(dict.fromkeys([name] + aliases + [fid])),
        "region": region, "topics": [], "related": [],
        "tags": [f"type/reg", f"region/{region}"],
        "created": "2026-09-14",
    }
    body = f"""# {name}

> 地区实体。相关条目按 region 字段聚合。

## 关联内容

```dataview
TABLE date AS "日期", title AS "标题", dimension AS "层级"
FROM "Notes/数据库"
WHERE region = "{region}"
SORT date DESC
LIMIT 50
```
"""
    return yaml_lines(fields) + "\n\n" + body


def main():
    created = 0
    skipped = 0

    # 机构
    for o in ORGS:
        fid, name = o[0], o[1]
        # 文件名用简称（第一个 alias 或 name 的短形式）
        fname = fid.split("/")[-1]
        dst = ENTITY / "机构" / f"{fname}.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            skipped += 1
            continue
        dst.write_text(gen_org_page(o), encoding="utf-8")
        created += 1

    # 技术
    for t in TECHS:
        fname = t[0].split("/")[-1]
        dst = ENTITY / "技术" / f"{fname}.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            skipped += 1
            continue
        dst.write_text(gen_tech_page(t), encoding="utf-8")
        created += 1

    # 地区
    for r in REGS:
        fname = r[0].split("/")[-1]
        dst = ENTITY / "地区" / f"{fname}.md"
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            skipped += 1
            continue
        dst.write_text(gen_reg_page(r), encoding="utf-8")
        created += 1

    # 主题（给 wiki 板块加 id/type/aliases）
    wiki_updated = 0
    for rel, fid, aliases in TOPICS:
        p = NOTES / rel
        if not p.exists():
            print(f"[WARN] wiki 文件不存在: {rel}")
            continue
        text = p.read_text(encoding="utf-8")
        if f'id: "{fid}"' in text:
            skipped += 1
            continue
        # 在 frontmatter 的 tags 行后插入 id/type/aliases
        alias_str = ", ".join(f'"{a}"' for a in aliases + [fid])
        insert = f'id: "{fid}"\ntype: "top"\naliases: [{alias_str}]'
        # 找 tags 行
        if "tags:" in text.split("---")[1]:
            lines = text.splitlines()
            out = []
            in_fm = False
            done = False
            for ln in lines:
                out.append(ln)
                if not done and ln.startswith("tags:"):
                    out.append(insert)
                    done = True
            new_text = "\n".join(out)
        else:
            # 无 tags 行，插到第一个 --- 后
            new_text = text.replace("---\n", "---\n" + insert + "\n", 1)
        p.write_text(new_text, encoding="utf-8")
        wiki_updated += 1

    print(f"新建实体页: {created}")
    print(f"跳过（已存在）: {skipped}")
    print(f"wiki 板块加 id: {wiki_updated}")


if __name__ == "__main__":
    main()
