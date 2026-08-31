#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经济指标长期监控抓取（2026-08-31 老温拍板，一期美国/全球，二期中国指标待加）。

数据源：FRED 免费 CSV 端点（fredgraph.csv），零 key 零成本（同 X 平台 SSR 直抓思路）。
框架：沃什产业链四层——上游要素投入 / 中游运营+劳动力 / 下游终端需求 / 宏观反馈。
输出：data/econ-indicators.json（时序累积，幂等追加，单指标失败不阻塞整体）。

用法：
    python3.11 scripts/fetch_econ_indicators.py [--output-dir data] [--years 3]

口径说明（页面亦标注）：
- CRB 综合指数 FRED 无对应 ID → 用 WTI/布伦特/铜/天然气 4 个代表性商品代替
- PDFP（国内私人最终购买）无直接序列 → 合成：PCEC96 季度均值 + GPDIC1（十亿 chained 2017 美元）
- 应届毕业生吸收 → 16-24 岁失业率（LNS14000036）近似
- CP（企业利润）同时归上游资本回报 + 中游利润，两组均展示
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

UTC = timezone.utc
SH_TZ = timezone(timedelta(hours=8))
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
# ⚠️ 2026-08-31 实测：FRED 对带自定义浏览器 UA 的 requests 请求挂起（Read timed out），
# 无 headers 裸 requests 稳定秒回（36 序列 38.5s 全通）。故不设 UA、不用 Session 复用连接。
TIMEOUT = 20
RETRIES = 2

# ── 指标清单（FRED ID 全部实测 200，2026-08-31 验证）────────────────────────────
# freq: D=日 W=周 M=月 Q=季
# groups: 所属产业链层（可多组，CP 归上游+中游）
ECON_INDICATORS: list[dict] = [
    # ── 上游：生产要素与资本投入 ──
    {"id": "DCOILWTICO",    "name": "WTI 原油",          "unit": "美元/桶",        "freq": "D", "groups": ["upstream"], "desc": "西德克萨斯中质原油现货价，输入型通胀前沿指标"},
    {"id": "DCOILBRENTEU",  "name": "布伦特原油",        "unit": "美元/桶",        "freq": "D", "groups": ["upstream"], "desc": "欧洲基准原油，全球定价锚"},
    {"id": "PCOPPUSDM",     "name": "铜价",              "unit": "美元/吨",        "freq": "D", "groups": ["upstream"], "desc": "全球铜现货价（LME，美元/吨），工业金属与经济景气风向标"},
    {"id": "DHHNGSP",       "name": "天然气（亨利港）",  "unit": "美元/百万英热",  "freq": "D", "groups": ["upstream"], "desc": "美国亨利港天然气现货价"},
    {"id": "PNFIC1",        "name": "非住宅固定投资",    "unit": "十亿美元(2017)",  "freq": "Q", "groups": ["upstream"], "desc": "实际私人非住宅固定投资——企业扩产/AI 基建真金白银（chained 2017）"},
    {"id": "GPDIC1",        "name": "私人国内投资总额",  "unit": "十亿美元(2017)",  "freq": "Q", "groups": ["upstream"], "desc": "实际私人国内投资总额（chained 2017），资本投入总盘子"},
    {"id": "CP",            "name": "企业税后利润",      "unit": "十亿美元",        "freq": "Q", "groups": ["upstream", "midstream"], "desc": "企业税后利润（CP），资本回报与利润抗压能力代理"},
    # ── 中游：企业运营与劳动力 ──
    {"id": "UNRATE",        "name": "失业率",            "unit": "%",              "freq": "M", "groups": ["midstream"], "desc": "U-3 失业率，劳动力核心指标"},
    {"id": "IC4WSA",        "name": "四周平均初请失业金", "unit": "千人",           "freq": "W", "groups": ["midstream"], "desc": "四周移动平均初请失业金——沃什重点提的早期信号", "scale": 0.001},
    {"id": "PAYEMS",        "name": "非农就业",          "unit": "千人",           "freq": "M", "groups": ["midstream"], "desc": "非农就业总人数（月度就业增长）"},
    {"id": "CIVPART",       "name": "劳动参与率",        "unit": "%",              "freq": "M", "groups": ["midstream"], "desc": "劳动力供给健康度"},
    {"id": "JTSJOL",        "name": "职位空缺",          "unit": "千人",           "freq": "M", "groups": ["midstream"], "desc": "JOLTS 职位空缺——劳动力需求"},
    {"id": "JTSQUR",        "name": "离职率",            "unit": "%",              "freq": "M", "groups": ["midstream"], "desc": "JOLTS 离职率（周转率）——员工议价能力信号"},
    {"id": "LNS14000036",   "name": "16-24岁失业率",     "unit": "%",              "freq": "M", "groups": ["midstream"], "desc": "青年失业率——应届毕业生吸纳能力近似口径"},
    # ── 下游：终端需求与消费 ──
    {"id": "PCEC96",        "name": "实际消费支出",      "unit": "十亿美元(2017)",  "freq": "M", "groups": ["downstream"], "desc": "实际个人消费支出（chained 2017）——终端需求基本盘"},
    {"id": "PDFP",          "name": "国内私人最终购买",  "unit": "十亿美元(2017)",  "freq": "Q", "groups": ["downstream"], "desc": "合成口径：PCEC96 季度均值 + GPDIC1（消费+私人投资），沃什看重的纯净需求指标"},
    {"id": "GDPC1",         "name": "实际 GDP",          "unit": "十亿美元(2017)",  "freq": "Q", "groups": ["downstream"], "desc": "实际国内生产总值（chained 2017）"},
    # ── 宏观反馈：物价体系与金融条件 ──
    {"id": "PCEPI",         "name": "PCE 物价指数",      "unit": "指数(2017=100)", "freq": "M", "groups": ["macro"], "desc": "美联储法定通胀标尺"},
    {"id": "PCEPILFE",      "name": "核心 PCE",          "unit": "指数(2017=100)", "freq": "M", "groups": ["macro"], "desc": "剔除食品能源的 PCE——政策锚"},
    {"id": "CPIAUCSL",      "name": "CPI",               "unit": "指数(1982-84=100)", "freq": "M", "groups": ["macro"], "desc": "居民消费价格指数"},
    {"id": "CPILFESL",      "name": "核心 CPI",          "unit": "指数(1982-84=100)", "freq": "M", "groups": ["macro"], "desc": "剔除食品能源的 CPI"},
    {"id": "MICH",          "name": "密歇根通胀预期",    "unit": "%",              "freq": "M", "groups": ["macro"], "desc": "密歇根大学 1 年期通胀预期"},
    {"id": "T5YIFR",        "name": "5y5y 远期盈亏平衡", "unit": "%",              "freq": "D", "groups": ["macro"], "desc": "5 年/5 年远期通胀预期——市场脱锚监控"},
    {"id": "AHETPI",        "name": "平均时薪",          "unit": "美元/小时",      "freq": "M", "groups": ["macro"], "desc": "私人非农平均时薪（工资增长）"},
    {"id": "DFF",           "name": "联邦基金有效利率",  "unit": "%",              "freq": "D", "groups": ["macro"], "desc": "政策利率的货币市场传导"},
    {"id": "SOFR",          "name": "SOFR 隔夜利率",     "unit": "%",              "freq": "D", "groups": ["macro"], "desc": "担保隔夜融资利率——美元融资基准"},
    {"id": "DGS2",          "name": "2 年期国债收益率",   "unit": "%",              "freq": "D", "groups": ["macro"], "desc": "短端利率——政策预期"},
    {"id": "DGS10",         "name": "10 年期国债收益率", "unit": "%",              "freq": "D", "groups": ["macro"], "desc": "长端利率——增长与通胀预期"},
    {"id": "DGS30",         "name": "30 年期国债收益率", "unit": "%",              "freq": "D", "groups": ["macro"], "desc": "超长端利率"},
    {"id": "DTWEXBGS",      "name": "广义美元指数",      "unit": "指数(2006=100)", "freq": "D", "groups": ["macro"], "desc": "美元对主要贸易伙伴广义汇率——国际定价基准"},
    {"id": "BUSLOANS",      "name": "商业工业贷款",      "unit": "十亿美元",        "freq": "W", "groups": ["macro"], "desc": "C&I 贷款——信贷流入实体经济的阀门"},
    {"id": "NFCI",          "name": "金融状况指数",      "unit": "指数",           "freq": "W", "groups": ["macro"], "desc": "芝加哥联储全国金融状况指数（正=收紧）"},
    {"id": "BAMLH0A0HYM2",  "name": "高收益债利差",      "unit": "%",              "freq": "D", "groups": ["macro"], "desc": "ICE BofA 高收益债期权调整利差——风险偏好"},
    {"id": "BAMLC0A0CM",    "name": "投资级债利差",      "unit": "%",              "freq": "D", "groups": ["macro"], "desc": "ICE BofA 投资级债期权调整利差"},
    {"id": "SP500",         "name": "标普 500",          "unit": "指数",           "freq": "D", "groups": ["macro"], "desc": "美国股市——财富效应渠道"},
    {"id": "VIXCLS",        "name": "VIX 波动率",        "unit": "指数",           "freq": "D", "groups": ["macro"], "desc": "恐慌指数"},
    {"id": "CSUSHPINSA",    "name": "Case-Shiller 房价", "unit": "指数(2000=100)", "freq": "M", "groups": ["macro"], "desc": "美国 20 城房价指数（季调）——利率敏感行业"},
    {"id": "WALCL",         "name": "美联储资产负债表",  "unit": "十亿美元",        "freq": "W", "groups": ["macro"], "desc": "联储总资产——流动性深度（CSV 原始单位百万美元，÷1000）", "scale": 0.001},
    {"id": "RRPONTSYD",     "name": "隔夜逆回购",        "unit": "十亿美元",        "freq": "D", "groups": ["macro"], "desc": "ON RRP 用量——流动性阀门"},
]

GROUPS = [
    ("upstream",   "⛏️ 上游 · 要素投入"),
    ("midstream",  "🏭 中游 · 运营与劳动力"),
    ("downstream", "🛒 下游 · 终端需求"),
    ("macro",      "🎯 宏观反馈 · 物价与金融条件"),
]

GROUP_KEY_OF = {g["id"]: g for g in ECON_INDICATORS}


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def fetch_series(series_id: str, cosd: str) -> list[list]:
    """抓单个 FRED 序列 CSV → [[date, value], ...]（升序，跳过缺失值）。

    FRED CSV 缺失值记 '.' 或空；单序列直抓返回纯 CSV（多序列才返回 zip）。
    不带自定义 UA/不复用连接（见文件头注释）；失败自动重试 RETRIES 次。
    """
    last_err: Exception | None = None
    for attempt in range(RETRIES + 1):
        try:
            r = requests.get(FRED_CSV, params={"id": series_id, "cosd": cosd}, timeout=TIMEOUT)
            r.raise_for_status()
            rows: list[list] = []
            reader = csv.DictReader(io.StringIO(r.text))
            if not reader.fieldnames:
                return rows
            value_col = reader.fieldnames[1] if len(reader.fieldnames) > 1 else series_id
            for row in reader:
                date_s = (row.get("observation_date") or "").strip()
                val_s = (row.get(value_col) or "").strip()
                if not date_s or not val_s or val_s == ".":
                    continue
                try:
                    val = float(val_s)
                except ValueError:
                    continue
                rows.append([date_s, val])
            return rows
        except Exception as e:
            last_err = e
    raise last_err if last_err else RuntimeError(f"fetch {series_id} failed")


def aggregate_quarterly(monthly_rows: list[list]) -> list[list]:
    """月度序列 → 季度均值（PDFP 合成用）：[[date, value], ...] 按季度首日输出。"""
    buckets: dict[str, list[float]] = {}
    for date_s, val in monthly_rows:
        q = f"{date_s[:4]}-{1 + (int(date_s[5:7]) - 1) // 3 * 3:02d}-01"
        buckets.setdefault(q, []).append(val)
    return [[q, round(sum(vs) / len(vs), 2)] for q, vs in sorted(buckets.items())]


def merge_rows(existing: list[list], new_rows: list[list]) -> list[list]:
    """幂等合并：按日期去重（新值覆盖旧值），升序输出。"""
    merged: dict[str, float] = {d: v for d, v in existing}
    for d, v in new_rows:
        merged[d] = v
    return [[d, merged[d]] for d in sorted(merged)]


def clip_rows(rows: list[list], years: int) -> list[list]:
    """裁剪到近 N 年。"""
    cutoff = (utc_now() - timedelta(days=365 * years)).strftime("%Y-%m-%d")
    return [[d, v] for d, v in rows if d >= cutoff]


def scale_rows(rows: list[list], scale: float) -> list[list]:
    """单位换算：FRED CSV 原始单位 → 展示单位（如 IC4WSA 人→千人 ÷1000）。"""
    if scale == 1.0:
        return rows
    return [[d, round(v * scale, 2)] for d, v in rows]


def build_pdfp(cosd: str) -> list[list] | None:
    """合成 PDFP：PCEC96 季度均值 + GPDIC1（季度，chained 2017 美元）。"""
    try:
        pcec = fetch_series("PCEC96", cosd)
        gpdic = fetch_series("GPDIC1", cosd)
    except Exception:
        return None
    if not pcec or not gpdic:
        return None
    q_pcec = aggregate_quarterly(pcec)
    q_gpdic = {d: v for d, v in gpdic}
    out = []
    for d, v in q_pcec:
        if d in q_gpdic:
            out.append([d, round(v + q_gpdic[d], 2)])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="经济指标长期监控（FRED 免费 CSV）")
    parser.add_argument("--output-dir", default="data", help="输出目录")
    parser.add_argument("--years", type=int, default=3, help="保留近 N 年（默认 3）")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "econ-indicators.json"

    # 读已有（幂等续跑）
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8")) or {}
        except Exception:
            existing = {}

    now = utc_now()
    cosd = (now - timedelta(days=365 * (args.years + 1))).strftime("%Y-%m-%d")  # 多拉 1 年余量

    series_out: dict = {}
    ok, fail = 0, 0
    # PDFP 合成需要 PCEC96/GPDIC1，先算好存临时
    pdfp_rows = build_pdfp(cosd)

    for spec in ECON_INDICATORS:
        sid = spec["id"]
        old = (existing.get("series") or {}).get(sid, {})
        old_rows = old.get("history", []) if isinstance(old, dict) else []
        try:
            if sid == "PDFP":
                rows = pdfp_rows or []
            else:
                rows = fetch_series(sid, cosd)
                rows = scale_rows(rows, spec.get("scale", 1.0))
            rows = merge_rows(old_rows, rows)
            rows = clip_rows(rows, args.years)
            if not rows:
                print(f"  ⚠️  {sid} {spec['name']}: 无数据", flush=True)
                fail += 1
                continue
            series_out[sid] = {
                "id": sid,
                "name": spec["name"],
                "unit": spec["unit"],
                "freq": spec["freq"],
                "groups": spec["groups"],
                "desc": spec["desc"],
                "points": len(rows),
                "latest": {"date": rows[-1][0], "value": rows[-1][1]},
                "history": rows,
            }
            ok += 1
            print(f"  ✅ {sid:14s} {spec['name']:12s} {len(rows):5d} 点  最新 {rows[-1][0]} = {rows[-1][1]}", flush=True)
        except Exception as e:
            print(f"  ❌ {sid} {spec['name']}: {e}", flush=True)
            fail += 1
            # 保留旧数据（若有），不丢历史
            if old_rows:
                series_out[sid] = old

    # 分组索引
    groups = []
    for gkey, gname in GROUPS:
        ids = [sid for sid, s in series_out.items() if gkey in s.get("groups", [])]
        if ids:
            groups.append({"key": gkey, "name": gname, "series": ids})

    payload = {
        "generated_at": now.astimezone(SH_TZ).isoformat(timespec="seconds"),
        "source": "FRED fredgraph.csv (free, no key)",
        "years": args.years,
        "groups": groups,
        "series": series_out,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"\n  📊 econ-indicators.json 写入完成：{ok} 序列 OK / {fail} 失败，共 {len(series_out)} 序列，{path}", flush=True)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
