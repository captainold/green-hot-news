#!/usr/bin/env python3.11
"""P0 探测：Jev（TypeSafe 决策模型）三方对照 + 网关连通性自检。

—— 属于「Jev 接入方案（讨论稿 v0.2）」P0 阶段，只读 data/*.json，不改任何主流程产出。
   唯一写入：data/jev-probe-history.json（本探测自己的证据累积，与 score-diff-history.json 平行）。

用法：
  # ① 连通性自检（不需要 key 也能看出网关是否透传 /v1/systemone：404 = 没透传）
  python3.11 scripts/_probe_jev.py --check

  # ② 三方对照：随机抽 30 条（按七细类等量），关键词 / DeepSeek-Pro / Jev 并排比
  python3.11 scripts/_probe_jev.py --n 30 --seed 7

  # ③ 只比 Jev vs 关键词（省掉 Pro 的慢调用）
  python3.11 scripts/_probe_jev.py --n 30 --no-pro

配置（环境变量优先，其次 .env / /etc/green-policy.env）：
  JEV_DIALECT    tokenhub（默认）：走网关 OpenAI 兼容口 /v1/chat/completions + typesafe_questions / typesafe_state 扩展字段
                 native：直连 TypeSafe 原生 /v1/systemone
  JEV_BASE_URL   tokenhub 默认 http://localhost:8080 ｜ native 默认 https://api.typesafe.ai
  JEV_API_KEY    TokenHub 项目级 key（sk_…）或 TypeSafe 原生 key
  JEV_MODEL      tokenhub 默认 TypeSafe/jev-latest（上游 jev-latest）｜ native 默认 jev-1.13
  JEV_PATH       仅 native 用，默认 /v1/systemone（OpenRouter 走 /api/alpha/decisions）

背景（2026-09-23 实测）：TokenHub 内置 typesafe 适配器（provider_typesafe.go）——
把 Chat Completions 翻译成 System One 评估，并把类型化答案渲染回 message.content，
末行是 `answers: {...}`（本脚本据此取回原始 answers JSON，含 probabilities/confidence）。

老温的验收看点（P0 的产出就是这个）：
  1. 中文真实语料上，Jev 的强度档位与关键词的一致率 / 偏差方向（LLM 高还是关键词高）
  2. 七细类分类一致率（分类错了，强度判据也会跟着错）
  3. 失败率与真实延迟（含网关/代理开销）
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# Windows 控制台默认 GBK：避免 emoji 触发 UnicodeEncodeError（服务器 UTF-8 无此问题）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("un", str(ROOT / "scripts" / "update_news.py"))
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)

import requests  # noqa: E402
import jev_client as jc  # 五问定义/传输/解析的唯一来源（勿在本脚本里复制一份）
import sample_snapshot as snap  # 抽样快照：把"这次抽了哪几条"落盘（复盘问题②）

# localhost 网关绝不能走 mihomo 代理（否则每次请求绕远/超时）
SESSION = requests.Session()
SESSION.trust_env = False

try:  # Pro 对照复用双轨监控里的提示词（保持与既有观察口径一致）
    import score_diff_monitor as sdm
except Exception:  # pragma: no cover
    sdm = None

DEFAULT_BASE = "https://api.typesafe.ai"
DEFAULT_PATH = "/v1/systemone"
DEFAULT_MODEL = "jev-1.13"

# ── 五问定义 / 映射表 / 传输：唯一来源是 scripts/jev_client.py（勿在此复制，防口径漂移）──
SUB_CRITERIA = jc.SUB_CRITERIA
STRENGTH_LEVELS = jc.STRENGTH_LEVELS
STRENGTH_TO_SCORE = jc.STRENGTH_TO_SCORE
TOPIC_LEVELS = jc.TOPIC_LEVELS
TOPIC_TO_SCORE = jc.TOPIC_TO_SCORE
build_questions = jc.build_questions


def _load_env(name: str, default: str = "") -> str:
    return jc._load_cfg(name, default)


def jev_call(dialect: str, base: str, path: str, key: str, model: str, state: dict,
             questions: dict, timeout: int = 45) -> tuple[dict | None, float, str]:
    """薄封装：把 CLI 参数写进环境变量后交给 jev_client.evaluate（单一传输实现）。

    dialect=tokenhub：POST {base}/v1/chat/completions，typesafe_state/typesafe_questions 作请求级扩展字段；
    dialect=native  ：POST {base}{path}（/v1/systemone），body 为 {model,state,questions}。
    """
    if dialect:
        os.environ["JEV_DIALECT"] = dialect
    if base:
        os.environ["JEV_BASE_URL"] = base
    if path:
        os.environ["JEV_PATH"] = path
    if key:
        os.environ["JEV_API_KEY"] = key
    if model:
        os.environ["JEV_MODEL"] = model
    return jc.evaluate(state, questions, timeout=timeout)


def cmd_check(args: argparse.Namespace) -> int:
    """连通性自检：按 dialect 打一次真实评估请求，并列出可用模型。"""
    dialect = args.dialect or _load_env("JEV_DIALECT", "tokenhub")
    default_base = "http://localhost:8080" if dialect == "tokenhub" else DEFAULT_BASE
    base = args.base or _load_env("JEV_BASE_URL", default_base)
    model = args.model or _load_env("JEV_MODEL",
                                    "TypeSafe/jev-latest" if dialect == "tokenhub" else DEFAULT_MODEL)
    key = args.key or _load_env("JEV_API_KEY")
    print(f"dialect  = {dialect}")
    print(f"base_url = {base}")
    print(f"model    = {model}")
    print(f"api_key  = {'已配置（%d 字符）' % len(key) if key else '未配置'}\n")

    # 1) 模型列表
    if key:
        try:
            r = SESSION.get(base.rstrip("/") + "/v1/models",
                            headers={"Authorization": f"Bearer {key}"}, timeout=(10, 25))
            if r.status_code == 200:
                ids = [m.get("id") for m in (r.json().get("data") or [])]
                ts = [i for i in ids if i and ("jev" in i.lower() or "typesafe" in i.lower())]
                print(f"GET /v1/models → 200，可见 {len(ids)} 个模型；其中 Jev/TypeSafe 相关：{ts or '（无）'}")
            else:
                print(f"GET /v1/models → {r.status_code} {r.text[:160]}")
        except Exception as exc:
            print(f"GET /v1/models → 连接失败 {type(exc).__name__}: {exc}")

    # 2) 真实评估
    state = {"title": "测试：光伏装机突破 1 亿千瓦",
             "summary": "国家能源局发布数据，全国光伏累计装机突破 1 亿千瓦。"}
    questions = {"is_green": {"type": "noul",
                              "instructions": "这条内容是否与绿色低碳直接相关？"}}
    ans, dt, err = jev_call(dialect, base, args.path or _load_env("JEV_PATH", DEFAULT_PATH),
                            key, model, state, questions, timeout=30)
    if err:
        print(f"\nPOST 评估 → 失败（{dt:.2f}s）：{err}")
        if "404" in err:
            print("判读：路由不存在——网关没透传这个接口。")
        elif "401" in err or "403" in err:
            print("判读：路由存在，但 key 无效/无权限。")
        return 1
    print(f"\nPOST 评估 → 200（{dt:.2f}s）")
    print(f"  answers = {json.dumps(ans, ensure_ascii=False)[:400]}")
    print("\n判读：[OK] 可用。" if ans else "\n判读：返回为空，需人工看原始响应。")
    return 0


def random_sample(items: list[dict], n: int) -> list[dict]:
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


def main() -> int:
    ap = argparse.ArgumentParser(description="Jev P0 探测：连通性自检 + 三方对照")
    ap.add_argument("--check", action="store_true", help="只做连通性自检")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--base", default="")
    ap.add_argument("--key", default="")
    ap.add_argument("--model", default="")
    ap.add_argument("--path", default="")
    ap.add_argument("--dialect", default="", choices=["", "tokenhub", "native"],
                    help="tokenhub=走网关 OpenAI 口（默认）｜native=直连 /v1/systemone")
    ap.add_argument("--no-pro", action="store_true", help="跳过 DeepSeek-Pro 对照（省时间）")
    ap.add_argument("--no-sub", action="store_true", help="不测七细类（只测强度/主题）")
    args = ap.parse_args()

    if args.check:
        return cmd_check(args)

    dialect = args.dialect or _load_env("JEV_DIALECT", "tokenhub")
    base = args.base or _load_env("JEV_BASE_URL",
                                  "http://localhost:8080" if dialect == "tokenhub" else DEFAULT_BASE)
    path = args.path or _load_env("JEV_PATH", DEFAULT_PATH)
    model = args.model or _load_env("JEV_MODEL",
                                    "TypeSafe/jev-latest" if dialect == "tokenhub" else DEFAULT_MODEL)
    key = args.key or _load_env("JEV_API_KEY")
    if not key:
        print("❌ 未找到 JEV_API_KEY（环境变量 / .env / /etc/green-policy.env）。先跑 --check 看网关是否透传。")
        return 2
    if args.seed is not None:
        random.seed(args.seed)

    d = json.load(open(ROOT / "data" / "history.json", encoding="utf-8"))
    items = [i for i in d.get("items", []) if isinstance(i, dict) and i.get("sub_dimension")]
    sample = random_sample(items, args.n)
    snapshot = snap.save(f"jev-probe-n{len(sample)}-seed{args.seed}", sample, corpus=items,
                         extra={"seed": args.seed, "no_pro": args.no_pro, "no_sub": args.no_sub})
    print(f"抽取 {len(sample)} 条 ｜ dialect={dialect} ｜ {base}{'' if dialect == 'tokenhub' else path} "
          f"｜ model={model} ｜ Pro 对照={'关' if args.no_pro else '开'}")
    print(f"语料快照 {snapshot.name}（语料 {snap.corpus_fingerprint(items)}）\n")

    questions = build_questions(with_sub=not args.no_sub)
    rows = []
    lat = []
    fails = 0
    for i, it in enumerate(sample, 1):
        sub = it["sub_dimension"]
        title = it.get("title", "")
        summary = it.get("summary", "")
        kw = un.score_content_strength(sub, title, summary)
        kw_topic = un.score_topic(title, summary)
        kw_sub = sub
        state = {"title": title, "summary": summary[:600],
                 "source": it.get("site_name", ""), "library": it.get("library", "media")}
        ans, dt, err = jev_call(dialect, base, path, key, model, state, questions)
        if ans is None:
            fails += 1
            print(f"  [{i}/{len(sample)}] 失败：{err[:120]}")
            continue
        lat.append(dt)
        s = ans.get("strength", {}) or {}
        lvl = int(round(float(s.get("score", 0))))
        lvl = max(0, min(3, lvl))
        jev_strength = STRENGTH_TO_SCORE[lvl] or un.DEFAULT_STRENGTH_BY_SUB.get(sub, un.DEFAULT_STRENGTH)
        t = ans.get("topic", {}) or {}
        t_lvl = max(0, min(3, int(round(float(t.get("score", 3))))))
        jev_topic = TOPIC_TO_SCORE[t_lvl]
        c = ans.get("sub_dim", {}) or {}
        jev_sub = c.get("choice", "")
        pro = None
        if not args.no_pro and sdm is not None:
            pro = sdm.llm_score(sub, title, summary, "pro")
        rows.append({
            "sub_kw": kw_sub, "sub_jev": jev_sub, "sub_ok": (kw_sub == jev_sub),
            "title": title[:38], "kw": kw, "jev": jev_strength, "pro": pro,
            "kw_topic": kw_topic, "jev_topic": jev_topic,
            "strength_conf": round(float(s.get("confidence", 0)), 2),
            "topic_conf": round(float(t.get("confidence", 0)), 2),
            "is_green": round(float((ans.get("is_green", {}) or {}).get("noul", 0)), 2),
            "is_noise": round(float((ans.get("is_noise", {}) or {}).get("noul", 0)), 2),
            "lat": round(dt, 2),
        })
        if i % 5 == 0:
            print(f"  进度 {i}/{len(sample)}（失败 {fails}）")

    n = len(rows)
    if not n:
        print("\n❌ 全部失败，先跑 --check 判断网关是否透传。")
        return 1

    def rate(pairs: list[tuple[int, int]]) -> str:
        ok = sum(1 for a, b in pairs if a == b)
        return f"{ok}/{len(pairs)} = {ok / len(pairs) * 100:.1f}%"

    print("\n=== 结果 ===")
    print(f"有效样本 {n}（失败 {fails}）｜ 延迟 p50 {sorted(lat)[len(lat) // 2]:.2f}s / max {max(lat):.2f}s")
    print(f"内容强度一致率（关键词 vs Jev）: {rate([(r['kw'], r['jev']) for r in rows])}")
    if any(r["pro"] is not None for r in rows):
        pr = [(r["kw"], r["pro"]) for r in rows if r["pro"] is not None]
        print(f"内容强度一致率（关键词 vs Pro）: {rate(pr)}")
    print(f"主题相关一致率（关键词 vs Jev）: {rate([(r['kw_topic'], r['jev_topic']) for r in rows])}")
    if not args.no_sub:
        sub_ok = sum(1 for r in rows if r["sub_ok"])
        print(f"七细类一致率（关键词 vs Jev）  : {sub_ok}/{n} = {sub_ok / n * 100:.1f}%")
    print(f"is_green 均值 {sum(r['is_green'] for r in rows) / n:.2f} ｜ "
          f"is_noise 均值 {sum(r['is_noise'] for r in rows) / n:.2f} ｜ "
          f"强度 confidence 均值 {sum(r['strength_conf'] for r in rows) / n:.2f}")

    print("\n=== 明细（细类 | 标题 | 关键词→Jev[Pro] | 主题 关键词→Jev | conf | 延迟）===")
    for r in rows:
        miss = "" if r["sub_ok"] else f"  ⚠️ Jev判={r['sub_jev']}"
        print(f"[{r['sub_kw']}] {r['title']:<40} {r['kw']:>2}→{r['jev']:>2}"
              f"[{r['pro'] if r['pro'] is not None else '-'}]  主题 {r['kw_topic']:>2}→{r['jev_topic']:>2}"
              f"  conf {r['strength_conf']:.2f}  {r['lat']}s{miss}")

    hist_path = ROOT / "data" / "jev-probe-history.json"
    hist = []
    if hist_path.exists():
        try:
            hist = json.loads(hist_path.read_text(encoding="utf-8"))
        except Exception:
            hist = []
    hist.append({
        "ts": datetime.now(timezone.utc).isoformat(), "base": base, "model": model,
        "dialect": dialect, "sample": n, "fail": fails,
        "kind": "three-way",                          # 记录类型（与 anchor-experiment 区分）
        "scale": "smoke" if n < 20 else "formal",     # 冒烟/正式（只看 formal 的趋势，复盘问题③）
        "snapshot": snapshot.name,
        "agree_strength_kw_jev": sum(1 for r in rows if r["kw"] == r["jev"]),
        "agree_strength_kw_pro": sum(1 for r in rows if r["pro"] is not None and r["kw"] == r["pro"]),
        "agree_topic": sum(1 for r in rows if r["kw_topic"] == r["jev_topic"]),
        "agree_sub": sum(1 for r in rows if r["sub_ok"]),
        "sub_dist_jev": dict(Counter(r["sub_jev"] for r in rows)),
        "lat_p50": sorted(lat)[len(lat) // 2], "rows": rows,
    })
    hist_path.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已追加到 data/jev-probe-history.json（累计 {len(hist)} 次探测）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
