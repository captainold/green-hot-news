#!/usr/bin/env python3
"""_probe_region.py — detect_region 修复验证"""
import sys

sys.path.insert(0, "scripts")
import update_news as un

cases = [
    # (site_id, title, 期望)
    ("tanpaifang", "欧委会批准马耳他6000万欧元社会气候计划，ETS2建筑交通2028扩围前首笔南欧缓冲资金落地", "欧盟"),
    ("tanpaifang", "哥斯达黎加2020-2023年REDD+净移除1028万吨,通过联合国技术评审", "国际"),
    ("tanpaifang", "欧盟ETS拟2029扩展航空至EEA外5000公里航班", "欧盟"),
    ("tanpaifang", "美国国会重新提出《碳移除领导法案》（CDRLA）", "美国"),
    ("tanpaifang", "印度DGCA拟强制国际航班碳排放报告+SAF掺混", "印度"),
    ("chinaenergy", "天然气库存跌至新低，欧洲能源危机“凛冬将至”？", "欧盟"),
    ("chinaenergy", "财经观察：中国新能源车，“本土化细节”震动日本", "中国"),
    ("chinaenergy", "梦百合美国南卡工厂突发火灾 已投保财产险未造成人员伤亡", "美国"),
    ("chinanecc", "国家节能中心公共服务网 - 节能研究", "中国"),
    ("pbc", "中澳（大利亚）两国央行续签双边本币互换协议", "中国"),
    ("radarai", "affaan-m/everything-claude-code", "国际"),
    ("allnet", "今年以来我国生态环境质量持续向好", "中国"),
    ("huxiu", "Anthropic支付15亿美元和解盗版图书训练AI诉讼", "中国"),
    ("us_doe", "Transmission Facility Financing - Department of Energy", "美国"),
    ("mongabay", "How plastic infiltrates Amazonian wildlife", "国际"),
    ("x", "Q&A: What does China's 15th five-year plan for coal mean", "中国"),
    ("reuters", "EU weighing options to support industry in carbon market overhaul", "欧盟"),
    ("reuters", "US exit of key UN climate treaty criticized", "美国"),
]
ok = 0
for sid, title, want in cases:
    got = un.detect_region(sid, title)
    mark = "✓" if got == want else f"✗ (want {want})"
    if got == want:
        ok += 1
    print(f"  [{mark}] {sid:<12} → {got:<4} | {title[:50]}")
print(f"\n{ok}/{len(cases)} 通过")
