#!/usr/bin/env python3
"""_probe_title_sim.py — 验证详情页标题覆盖的相似度门槛"""
import sys
sys.path.insert(0, "scripts")
from update_news import _title_similar

cases = [
    # (详情页title, 列表title, 期望是否覆盖)
    ("国家节能中心公共服务网 - 节能研究", "“双碳”战略引领催生绿色生产力", False),
    ("Latest commit", "axios_axios", False),
    ("The Go Programming Language", "golang_go", False),
    ("Longer wells boost Permian crude oil and natural gas production",
     "Longer wells boost Permian crude oil and natural gas production", False),
    ("中国人民银行关于印发《非银行支付机构分类评级管理办法》的通知（银发〔2025〕250号）",
     "中国人民银行关于印发《非银行支付机构分类评级管理办法》的通知（银发〔20...", True),
    ("NEW | Solar power surge in 2025 stalls rise in fossil electricity worldwide ⚡📈 Clean power growth outpaced global electricity demand last year – with solar alone supplying THREE-QUARTERS of the increase in demand ☀️ https://t.co/DXKYLw479L",
     "NEW _ Solar power surge in 2025 stalls rise in fossil electricity worldwide ⚡📈 C", True),
    ("Consensus uses GPT‑5 and the Responses API to complete weeks of research in minutes",
     "Consensus accelerates research with GPT-5 and Responses API", False),
]
allok = True
for a, b, want in cases:
    r = _title_similar(a, b)
    ok = (r >= 0.5) == want
    allok = allok and ok
    print(f"  [{'OK' if ok else 'FAIL'}] similar={r:.2f} 覆盖={r >= 0.5} (want {want}) | {b[:34]}...")
print(f"\n{'ALL PASS' if allok else 'SOME FAILED'}")
sys.exit(0 if allok else 1)
