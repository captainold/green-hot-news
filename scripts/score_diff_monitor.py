#!/usr/bin/env python3.11
"""打分多轨对比监控（系统重要升级点，2026-08-26 老温定；2026-09-23 扩为三轨）。

长期观察「关键词判定」与「LLM 判定」的内容强度打分差距，持续优化 LLM 提示词。

用法：
  python3.11 scripts/score_diff_monitor.py            # 随机抽 40 条，Pro 打分，对比 + 累积
  python3.11 scripts/score_diff_monitor.py --n 60     # 自定义样本量
  python3.11 scripts/score_diff_monitor.py --model flash   # 用 Flash（便宜，用于提示词快迭代）
  python3.11 scripts/score_diff_monitor.py --jev      # 加第三轨：Jev（TypeSafe 决策模型）

三轨（2026-09-23 老温决定加 Jev 轨）：
  ① 关键词（现行主流程，可解释、零成本）
  ② LLM：DeepSeek-V4-Pro few-shot（`--model pro`/`flash`）
  ③ Jev：TypeSafe System One 决策模型（`--jev`，走 TokenHub 网关，见 scripts/jev_client.py）
  三者比较**内容强度**同一口径（30/25/20/按细类兜底）；Jev 的分歧明细 + 七细类判定一并入档。

输出：
  - 终端：一致率 + 分歧方向 + 分歧清单
  - data/score-diff-history.json：累积历史（每次跑追加一条记录，观察差距趋势）

提示词优化（老温「持续优化 LLM 提示词」）：
  - PROMPT_EXAMPLES 是 few-shot 锚定示例（v2 起引入），是本机制提示词优化的核心入口。
  - 每次发现 LLM 系统偏差（如低估产业里程碑/高估宽词），就在 EXAMPLES 里补/改对应例子。
"""
from __future__ import annotations

import importlib.util
import json
import random
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("un", str(ROOT / "scripts" / "update_news.py"))
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)

import requests
import tech_feature as tf
import jev_client as jc  # 第三轨：Jev 决策模型（TypeSafe System One，走 TokenHub 网关）
import sample_snapshot as snap  # 抽样快照：把"这次抽了哪几条"落盘（复盘问题②）

SF_BASE = "https://api.siliconflow.cn/v1"
MODELS = {
    "pro": "deepseek-ai/DeepSeek-V4-Pro",
    "flash": "deepseek-ai/DeepSeek-V4-Flash",
}

# 每细类价值判据（与打分体系标准.md v5.1 一致）
SUB_JUDGE = {
    "政策法规": "文件层级（法律>行政法规>部委规章）× 发布主体（党中央国务院>部委）。一般级=10分",
    "国际动态": "协议层级 × 气候里程碑（COP决议/气候融资 > 一般峰会 > 报告）。一般级=10分",
    "技术研发": "突破程度 × 首创性（世界首次/颠覆 > 重要进展 > 常规研发）。一般级=8分",
    "基础研究": "发现价值 × 发表层级（颠覆发现/诺奖 > 重要发表 > 常规论文）。一般级=8分",
    "社会创新": "机制层级 × 首创性（国家级机制创新 > 地方试点倡导 > 常规倡导）。一般级=8分",
    "企业经营": "里程碑 × 规模（世界级首台套/超大规模 > 重要投产签约 > 常规经营）。一般级=10分",
    "金融资本": "碳市场里程碑 × 资本规模（扩围/破纪录 > 重要融资并购 > 常规交易）。一般级=8分",
}

# ── few-shot 锚定示例（v2 提示词核心：纠正 LLM 系统偏差）─────────────────
# 说明：这些是实验（2026-08-26）发现的 LLM 典型偏差锚定——
#  ① LLM 低估「产业/资本里程碑」（装机破亿、IPO、碳市场平台 → 误给 8 分）
#  ② 关键词宽词虚高（揭牌仪式、财报金额 → 该 10 分，LLM 判对了）
# 持续优化：发现新偏差时在这里补例子。
PROMPT_EXAMPLES = [
    ("金融资本", "全球碳预算仅余130Gt、约3-4年耗尽，1.5℃红线告急", 30),
    ("金融资本", "长江存储 IPO 已受理，拟融资金额 330 亿元", 30),
    ("技术研发", "我科研团队实现海上风电驱动海水制氢", 30),
    ("企业经营", "江苏光伏装机规模突破 1 亿千瓦", 25),
    ("金融资本", "全国碳市场综合服务平台正式上线", 25),
    ("政策法规", "《中国氢能发展报告(2026)》解读：锚定规模化发展新阶段", 25),
    ("企业经营", "我国氢能产业取得积极进展，可再生氢产能不断扩增", 20),
    ("企业经营", "小米发布三个芯片，瞄准 AI 手机", 20),
    ("政策法规", "碳管理体系（南通）服务中心揭牌仪式成功举办", 10),
    ("企业经营", "华能水电：上半年净利润 43.76 亿元 同比下降 5.05%", 10),
]


def build_prompt(sub: str, title: str, summary: str) -> str:
    """组装 few-shot 打分提示词（v2）。"""
    default_score = un.DEFAULT_STRENGTH_BY_SUB.get(sub, 8)
    judge = SUB_JUDGE.get(sub, "")
    examples = "\n".join(f"[{s}] 「{t}」→ {v}" for s, t, v in PROMPT_EXAMPLES)
    return f"""你是绿色低碳动态雷达的资深新闻价值评分员。给一条新闻的"内容强度"打分（0-30 分制）。

四档分级：
- 30 分（里程碑级）：国家级/全球级的开创性、突破性、历史性事件（稀缺、影响面大、有持续关注度）
- 25 分（重要级）：高规格推进、关键节点、明确政策转向（重要但未达里程碑）
- 20 分（进展级）：有实质内容的常规进展、报告、数据发布
- 一般级（{default_score} 分）：无强信号，属普通条目

先看这些标注示例（注意：产业/资本里程碑如装机破亿、IPO、平台上线属重要甚至里程碑，不要低估）：

{examples}

现在给下面这条打分。它属于「{sub}」，价值判据：{judge}

只输出一个整数（30、25、20、{default_score}）。直接输出数字，不要解释。

标题：{title}
摘要：{summary}

分数："""


def llm_score(sub: str, title: str, summary: str, model: str) -> int | None:
    """LLM 打分，失败返回 None。"""
    key = tf._load_key()
    if not key:
        return None
    prompt = build_prompt(sub, title, summary)
    try:
        r = requests.post(
            f"{SF_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": MODELS[model],
                  "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 50, "temperature": 0},
            timeout=(20, 120),
        )
        if r.status_code != 200:
            return None
        out = r.json()["choices"][0]["message"].get("content", "").strip()
        m = re.search(r"\b(30|25|20|10|8)\b", out)
        return int(m.group(1)) if m else None
    except Exception:
        return None


def random_sample(items: list[dict], n: int) -> list[dict]:
    """随机提取：按细类等量随机抽（保证覆盖七细类 + 随机性），不足则全库随机补。"""
    by_sub: dict[str, list[dict]] = {}
    for it in items:
        by_sub.setdefault(it.get("sub_dimension", "?"), []).append(it)
    per = max(1, n // max(1, len(by_sub)))
    picked: list[dict] = []
    for lst in by_sub.values():
        picked.extend(random.sample(lst, min(per, len(lst))))
    if len(picked) < n:
        rest = [i for i in items if i not in picked]
        picked.extend(random.sample(rest, min(n - len(picked), len(rest))))
    return picked[:n]


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--model", choices=list(MODELS), default="pro")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--jev", action="store_true",
                    help="加第三轨 Jev（TypeSafe 决策模型，走 TokenHub 网关；需 .env 里 JEV_API_KEY）")
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    use_jev = args.jev
    if use_jev and not jc.is_enabled():
        print("⚠️  --jev 已开，但 Jev 不可用（缺 JEV_API_KEY 或已熔断）→ 本次仍按双轨跑\n")
        use_jev = False

    d = json.load(open(ROOT / "data" / "history.json", encoding="utf-8"))
    items = [i for i in d.get("items", d) if isinstance(i, dict) and i.get("sub_dimension")]
    sample = random_sample(items, args.n)
    snapshot = snap.save(f"score-diff-n{len(sample)}-seed{args.seed}"
                         f"{'-jev' if use_jev else ''}", sample, corpus=items,
                         extra={"seed": args.seed, "model": args.model, "jev": use_jev})
    model_name = MODELS[args.model]
    print(f"随机提取 {len(sample)} 条，模型 {args.model}（{model_name}），"
          f"{'三轨（关键词/Pro/Jev）' if use_jev else '双轨'}对比...")
    print(f"语料快照 {snapshot.name}（语料 {snap.corpus_fingerprint(items)}）\n")

    agree = 0
    diff = []
    llm_fail = 0
    jev_fail = 0
    consec_fail = 0              # LLM 连续失败计数（Pro 端点故障回落用）
    fell_back = False            # 是否已切 Flash
    requested_model = args.model                    # rec 记原始请求轨（回落不篡改历史口径）
    fb_thresh = max(5, min(10, len(sample) // 4))   # 连续失败回落阈值
    jev_lat: list[float] = []
    results = []          # (sub_kw, title, kw, lm, jev_dict|None, jev_sub, jev_lat)
    for i, it in enumerate(sample, 1):
        sub = it["sub_dimension"]
        title = it.get("title_zh") or it.get("title", "")
        summary = it.get("summary", "")
        kw = un.score_content_strength(sub, it.get("title", ""), it.get("summary", ""))
        lm = llm_score(sub, title, summary, args.model)
        # Pro 端点故障自动回落 Flash（2026-09-28 实测 SF V4-Pro 可持续 503 >12h，Flash 不受影响）：
        # 连续失败达阈值即整轨切 Flash 并在记录标注 fallback_to_flash——不静默混轨
        # （Flash 有已知系统性低偏差，混入趋势记录会污染口径）。
        if lm is None:
            consec_fail += 1
        else:
            consec_fail = 0
        if not fell_back and args.model == "pro" and consec_fail >= fb_thresh:
            fell_back = True
            args.model = "flash"
            print(f"\n⚠️  Pro 连续 {consec_fail} 条打分失败（SF 端点故障？）"
                  f"→ 剩余条目改用 Flash（记录已标注 fallback_to_flash）\n")
            lm = llm_score(sub, title, summary, args.model)
            if lm is not None:
                consec_fail = 0
        jev = None
        jdt = 0.0
        if use_jev:
            # 常规级兜底分取主流程的权威表（公式唯一权威在 update_news.py / 打分体系标准.md）
            jev, jdt, jerr = jc.judge_item(
                it, with_sub=True,
                fallback=un.DEFAULT_STRENGTH_BY_SUB.get(sub, un.DEFAULT_STRENGTH))
            if jev is None:
                jev_fail += 1
                if jev_fail <= 3:
                    print(f"  [{i}] Jev 失败：{jerr[:100]}")
            else:
                jev_lat.append(jdt)
        if lm is None and jev is None:
            llm_fail += 1 if lm is None else 0
            continue
        if lm is None:
            llm_fail += 1
        results.append((sub, title, kw, lm, jev, (jev or {}).get("sub", ""), jdt))
        if lm is not None:
            if kw == lm:
                agree += 1
            else:
                diff.append((sub, title, kw, lm))
        if i % 10 == 0:
            print(f"  进度 {i}/{len(sample)}（LLM 失败 {llm_fail}"
                  f"{'｜Jev 失败 %d' % jev_fail if use_jev else ''}）")

    n = len(results)
    llm_n = sum(1 for r in results if r[3] is not None)   # 双轨模式下 llm_n == n（行为不变）
    rate = agree / llm_n * 100 if llm_n else 0
    llm_higher = sum(1 for _, _, k, l in diff if l > k)
    kw_higher = len(diff) - llm_higher
    print(f"\n=== 对比结果 ===")
    print(f"有效样本 {n} 条（LLM 失败 {llm_fail}）")
    if fell_back:
        print("⚠️ 本次观察中途切至 Flash（Pro 连续失败），对比率含两轨混合，入趋势时注意口径")
    print(f"一致率: {agree}/{llm_n} = {rate:.1f}%")
    print(f"分歧 {len(diff)} 条：LLM 更高 {llm_higher} / 关键词更高 {kw_higher}\n")
    if diff:
        print("=== 分歧清单（标题 | 关键词→LLM）===")
        for sub, title, kw, lm in diff:
            print(f"[{sub}] {title[:40]:<42} {kw}→{lm}")

    # ── 第三轨：Jev（2026-09-23 新增，仅在 --jev 时输出/入档）────────────────
    jev_rows = [r for r in results if r[4] is not None]
    jev_stat: dict = {}
    if use_jev and jev_rows:
        jev_diffs = [(r[0], r[1], r[2], r[4]["strength"]) for r in jev_rows
                     if r[2] != r[4]["strength"]]
        jev_agree = len(jev_rows) - len(jev_diffs)
        jev_higher = sum(1 for _, _, k, j in jev_diffs if j > k)
        both = [r for r in jev_rows if r[3] is not None]
        jp_agree = sum(1 for r in both if r[4]["strength"] == r[3])
        sub_ok = sum(1 for r in jev_rows if r[5] and r[5] == r[0])
        sub_given = sum(1 for r in jev_rows if r[5])
        confs = [r[4]["conf_strength"] for r in jev_rows if r[4].get("conf_strength") is not None]
        lat_sorted = sorted(jev_lat)
        jev_stat = {
            "model": jc._load_cfg("JEV_MODEL", "TypeSafe/jev-latest"),
            "dialect": jc.dialect(),
            "sample": len(jev_rows),
            "fail": jev_fail,
            "agree_kw": jev_agree,
            "rate_kw": round(jev_agree / len(jev_rows) * 100, 1),
            "jev_higher": jev_higher,
            "kw_higher": len(jev_diffs) - jev_higher,
            "pro_pairs": len(both),
            "agree_pro": jp_agree,
            "rate_pro": round(jp_agree / len(both) * 100, 1) if both else 0,
            "sub_given": sub_given,
            "sub_agree": sub_ok,
            "rate_sub": round(sub_ok / sub_given * 100, 1) if sub_given else 0,
            "lat_p50": round(lat_sorted[len(lat_sorted) // 2], 2),
            "lat_max": round(max(jev_lat), 2),
            "conf_mean": round(sum(confs) / len(confs), 2) if confs else None,
            "low_conf": sum(1 for c in confs if c < 0.5),
            "diff_items": [{"sub": s, "title": t, "kw": k, "jev": j} for s, t, k, j in jev_diffs],
            "sub_mismatch": [{"kw": r[0], "jev": r[5], "title": r[1][:60]}
                             for r in jev_rows if r[5] and r[5] != r[0]],
        }
        print(f"\n=== 第三轨 Jev（{jev_stat['dialect']} / {jev_stat['model']}）===")
        print(f"有效 {len(jev_rows)} 条（失败 {jev_fail}）｜延迟 p50 {jev_stat['lat_p50']}s "
              f"/ max {jev_stat['lat_max']}s｜强度 confidence 均值 "
              f"{jev_stat['conf_mean']}（<0.5 的 {jev_stat['low_conf']} 条）")
        print(f"一致率（关键词 vs Jev）: {jev_agree}/{len(jev_rows)} = {jev_stat['rate_kw']}%"
              f"　分歧 {len(jev_diffs)} 条：Jev 更高 {jev_higher} / 关键词更高 "
              f"{len(jev_diffs) - jev_higher}")
        if both:
            print(f"一致率（Pro vs Jev）    : {jp_agree}/{len(both)} = {jev_stat['rate_pro']}%")
        if sub_given:
            print(f"七细类一致率（关键词 vs Jev）: {sub_ok}/{sub_given} = {jev_stat['rate_sub']}%")
        if jev_diffs:
            print("\n=== Jev 分歧清单（细类 | 标题 | 关键词→Jev | conf）===")
            for r in jev_rows:
                if r[2] == r[4]["strength"]:
                    continue
                mark = "" if not r[5] or r[5] == r[0] else f"  ⚠️ Jev判细类={r[5]}"
                print(f"[{r[0]}] {r[1][:38]:<40} {r[2]:>2}→{r[4]['strength']:>2}"
                      f"  conf {r[4].get('conf_strength')}  {r[6]:.2f}s{mark}")

    # 累积历史（观察差距趋势）
    hist_path = ROOT / "data" / "score-diff-history.json"
    hist = []
    if hist_path.exists():
        try:
            hist = json.load(open(hist_path, encoding="utf-8"))
        except Exception:
            hist = []
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": requested_model,
        "fallback_to_flash": fell_back,
        # kind：区分冒烟与正式观察（复盘问题③）——只有 formal 记录才看趋势
        "kind": "formal" if llm_n >= 20 else "smoke",
        "snapshot": snapshot.name,
        "sample": llm_n,
        "llm_fail": llm_fail,
        "agree": agree,
        "rate": round(rate, 1),
        "diff": len(diff),
        "llm_higher": llm_higher,
        "kw_higher": kw_higher,
        "diff_items": [{"sub": s, "title": t, "kw": k, "llm": l} for s, t, k, l in diff],
    }
    if jev_stat:                      # 三轨时才写，旧记录形状不变
        rec["jev"] = jev_stat
    hist.append(rec)
    hist_path.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已追加到 data/score-diff-history.json（累计 {len(hist)} 次观察）")


if __name__ == "__main__":
    main()
