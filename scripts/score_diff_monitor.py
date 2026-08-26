#!/usr/bin/env python3.11
"""打分双轨对比监控（系统重要升级点，2026-08-26 老温定）。

长期观察「关键词判定」与「LLM 判定」的内容强度打分差距，持续优化 LLM 提示词。

用法：
  python3.11 scripts/score_diff_monitor.py            # 随机抽 40 条，Pro 打分，对比 + 累积
  python3.11 scripts/score_diff_monitor.py --n 60     # 自定义样本量
  python3.11 scripts/score_diff_monitor.py --model flash   # 用 Flash（便宜，用于提示词快迭代）

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
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    d = json.load(open(ROOT / "data" / "history.json"))
    items = [i for i in d.get("items", d) if isinstance(i, dict) and i.get("sub_dimension")]
    sample = random_sample(items, args.n)
    model_name = MODELS[args.model]
    print(f"随机提取 {len(sample)} 条，模型 {args.model}（{model_name}），双轨对比...\n")

    agree = 0
    diff = []
    llm_fail = 0
    results = []
    for i, it in enumerate(sample, 1):
        sub = it["sub_dimension"]
        title = it.get("title_zh") or it.get("title", "")
        summary = it.get("summary", "")
        kw = un.score_content_strength(sub, it.get("title", ""), it.get("summary", ""))
        lm = llm_score(sub, title, summary, args.model)
        if lm is None:
            llm_fail += 1
            continue
        results.append((sub, title, kw, lm))
        if kw == lm:
            agree += 1
        else:
            diff.append((sub, title, kw, lm))
        if i % 10 == 0:
            print(f"  进度 {i}/{len(sample)}（LLM 失败 {llm_fail}）")

    n = len(results)
    rate = agree / n * 100 if n else 0
    llm_higher = sum(1 for _, _, k, l in diff if l > k)
    kw_higher = len(diff) - llm_higher
    print(f"\n=== 对比结果 ===")
    print(f"有效样本 {n} 条（LLM 失败 {llm_fail}）")
    print(f"一致率: {agree}/{n} = {rate:.1f}%")
    print(f"分歧 {len(diff)} 条：LLM 更高 {llm_higher} / 关键词更高 {kw_higher}\n")
    if diff:
        print("=== 分歧清单（标题 | 关键词→LLM）===")
        for sub, title, kw, lm in diff:
            print(f"[{sub}] {title[:40]:<42} {kw}→{lm}")

    # 累积历史（观察差距趋势）
    hist_path = ROOT / "data" / "score-diff-history.json"
    hist = []
    if hist_path.exists():
        try:
            hist = json.load(open(hist_path, encoding="utf-8"))
        except Exception:
            hist = []
    hist.append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "sample": n,
        "llm_fail": llm_fail,
        "agree": agree,
        "rate": round(rate, 1),
        "diff": len(diff),
        "llm_higher": llm_higher,
        "kw_higher": kw_higher,
        "diff_items": [{"sub": s, "title": t, "kw": k, "llm": l} for s, t, k, l in diff],
    })
    hist_path.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已追加到 data/score-diff-history.json（累计 {len(hist)} 次观察）")


if __name__ == "__main__":
    main()
