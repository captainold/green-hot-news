#!/usr/bin/env python3.11
"""gold set 三轨预测预登记（2026-09-28 实验，P0.5 的前置半步）。

为什么：84 条 gold set 等老温人工标注；在任何标注发生**之前**把 关键词/Jev/Pro 三轨
预测冻结到 data/gold-set-predictions.json——预登记性质，防"看着判定器结果标"的偏置，
也为"预测先于标注"留档。标注完成后 `gold_set.py evaluate` 会重新现跑三轨，
本文件是对照副本（另可核对两次运行的漂移）。

口径完全镜像 gold_set.py evaluate（保证冻结值 = 终审口径）：
  • kw   ：un.score_content_strength(sub_kw, title, summary) + level_of_score；细类=sub_kw
  • jev A：build_questions(True) 五问一次拿 sub_dim + 强度(A 形态) + topic + is_green/is_noise
  • jev C：judge_strength(form="C") 三问 noul 合成（P0 实测唯一有区分度的形态）
  • pro  ：score_diff_monitor.llm_score(sub_kw, title, summary, "pro")（4 并发）
上游 2026-09-28 不稳（503），jev 调用外围重试 ×2（与 _probe_jev_benchmark 同策略）。

输出：
  data/gold-set-predictions.json —— 冻结预测 + 汇总（分布/塌陷红线/七细类混淆/一致率）
  data/gold-set-predictions.md   —— 分歧初审材料（kw≠jev 细类逐条，附标题摘要）
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util

spec = importlib.util.spec_from_file_location("un", str(ROOT / "scripts" / "update_news.py"))
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)

import requests

import jev_client as jc
import score_diff_monitor as sdm
import gold_set as gs

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

OUT_JSON = ROOT / "data" / "gold-set-predictions.json"
OUT_MD = ROOT / "data" / "gold-set-predictions.md"
RETRYABLE = ("HTTP 5", "ConnectionError", "ConnectTimeout", "ReadTimeout",
             "Connection reset", "upstream", "service_disabled")


def _retry(fn):
    """外围重试 ×2（仅可重试错误；返回 fn 的原样三元组/二元组结果）。"""
    def wrapped(*a, **kw):
        last = None
        for attempt in range(3):
            if attempt:
                if not any(k in (last or "") for k in RETRYABLE):
                    break
                time.sleep(1.5)
                jc.reset()
            r = fn(*a, **kw)
            ok = r[0] if isinstance(r, tuple) else r
            if ok is not None:
                return r
            err = r[-1] if isinstance(r, tuple) and len(r) == 3 else ""
            last = err
        return r
    return wrapped


@_retry
def _jev_five(row: dict):
    return jc.evaluate(jc.state_from_item(row), jc.build_questions(True))


@_retry
def _jev_c(row: dict, fb: int):
    return jc.judge_strength(row, form="C", fallback=fb)


@_retry
def _pro_one(row: dict):
    return (sdm.llm_score(row.get("sub_kw", ""), row.get("title", ""),
                          row.get("summary", ""), "pro"),)


def main() -> None:
    rows = gs.load_gold()
    if not rows:
        print("gold-set.jsonl 为空")
        return
    labeled = [r for r in rows if r.get("label_strength") is not None]
    if labeled:
        print(f"⚠️ 已有 {len(labeled)} 条人工标注——预登记必须先于标注，中止"
              f"（防偏置完整性守卫）")
        return
    sha = hashlib.sha1(gs.GOLD_PATH.read_bytes()).hexdigest()[:12]
    print(f"gold set {len(rows)} 条（sha1_12={sha}，全部未标注）→ 开始冻结三轨预测\n")

    lock = threading.Lock()
    out_rows: list[dict] = []
    fails: Counter = Counter()
    jev_lat: list[float] = []

    def one(row: dict) -> dict:
        fb = un.DEFAULT_STRENGTH_BY_SUB.get(row.get("sub_kw", ""), un.DEFAULT_STRENGTH)
        kw_sc = gs.kw_strength(row)
        rec = {
            "id": row["id"],
            "sub_kw": row.get("sub_kw"),
            "kw": {"score": kw_sc, "level": gs.level_of_score(kw_sc)},
            "jev": {}, "pro": {},
        }
        ans, dt, err = _jev_five(row)
        if ans is None:
            fails["jev_A"] += 1
        else:
            with lock:
                jev_lat.append(dt)
            lvl = max(0, min(3, int(round(jc._num((ans.get("strength") or {}).get("score"), 0)))))
            rec["jev"] = {
                "sub": jc.sub_dimension(ans),
                "strength_A": {"level": lvl, "score": jc.level_to_score(lvl, row.get("sub_kw", ""), fb),
                               "conf": jc.confidence(ans, "strength")},
                "topic": jc.topic_score(ans),
                "is_green": jc.noul(ans, "is_green"),
                "is_noise": jc.noul(ans, "is_noise"),
            }
        res, dt2, err2 = _jev_c(row, fb)
        if res is None:
            fails["jev_C"] += 1
        else:
            rec["jev"]["strength_C"] = res
        (ps,) = _pro_one(row)
        if ps is None:
            fails["pro"] += 1
        else:
            rec["pro"] = {"score": ps, "level": gs.level_of_score(ps)}
        return rec

    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as ex:      # 4 并发：jev 上游今日不稳，保守
        futs = [ex.submit(one, r) for r in rows]
        for i, f in enumerate(as_completed(futs), 1):
            out_rows.append(f.result())
            if i % 12 == 0:
                print(f"  进度 {i}/{len(rows)}（失败计数 {dict(fails)}）")
    wall = time.monotonic() - t0

    out_rows.sort(key=lambda r: r["id"])

    # ── 汇总：分布 / 塌陷红线 / 混淆 / 一致率 ──────────────────────────────
    def dist(keypath):
        c = Counter()
        for r in out_rows:
            v = r
            for k in keypath:
                v = (v or {}).get(k) if isinstance(v, dict) else None
            if v is not None:
                c[v] += 1
        return {str(k): v for k, v in sorted(c.items(), reverse=True)}

    def collapse(d: dict) -> dict:
        tot = sum(d.values())
        if not tot:
            return {}
        tier, n = max(d.items(), key=lambda kv: kv[1])
        return {"max_tier": tier, "max_share": round(n / tot, 3),
                "collapse_flag": bool(n / tot >= 0.8)}

    dists = {"kw": dist(["kw", "level"]), "jev_A": dist(["jev", "strength_A", "level"]),
             "jev_C": dist(["jev", "strength_C", "level"]), "pro": dist(["pro", "level"])}
    collapse_chk = {k: collapse(v) for k, v in dists.items()}

    subs = ["政策法规", "国际动态", "技术研发", "基础研究", "社会创新", "企业经营", "金融资本"]
    conf = {a: {b: 0 for b in subs} for a in subs}
    sub_agree = 0
    dis_rows = []
    for r in out_rows:
        js = (r.get("jev") or {}).get("sub")
        if not js:
            continue
        conf.setdefault(r["sub_kw"], {b: 0 for b in subs})[js] = conf.get(r["sub_kw"], {}).get(js, 0) + 1
        if js == r["sub_kw"]:
            sub_agree += 1
        else:
            dis_rows.append(r)

    def agree(a, b):
        pr = []
        for r in out_rows:
            x, y = _dig(r, a), _dig(r, b)
            if x is not None and y is not None:
                pr.append((x, y))
        return {"n": len(pr), "agree": sum(1 for x, y in pr if x == y),
                "rate": round(sum(1 for x, y in pr if x == y) / len(pr), 3) if pr else None}

    summary = {
        "n": len(out_rows), "wall_s": round(wall, 1),
        "fails": dict(fails),
        "levels_dist": dists, "collapse_check": collapse_chk,
        "sub_confusion_kw_vs_jev": conf,
        "sub_agree": {"n": len([r for r in out_rows if (r.get('jev') or {}).get('sub')]),
                      "agree": sub_agree},
        "strength_agree": {
            "kw_vs_jevA": agree(["kw", "level"], ["jev", "strength_A", "level"]),
            "kw_vs_jevC": agree(["kw", "level"], ["jev", "strength_C", "level"]),
            "kw_vs_pro": agree(["kw", "level"], ["pro", "level"]),
            "jevA_vs_pro": agree(["jev", "strength_A", "level"], ["pro", "level"]),
        },
        "jev_lat_p50": round(sorted(jev_lat)[len(jev_lat) // 2], 2) if jev_lat else None,
    }

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "gold-set-predictions-freeze",
        "note": "预登记：84 条未标注 gold set 上的三轨预测，冻结于人工标注之前（防偏置）。"
                "终审用 gold_set.py evaluate（现跑），本文件为对照副本。",
        "gold_set": {"path": "data/gold-set.jsonl", "n": len(rows), "sha1_12": sha,
                     "labeled_before_freeze": False},
        "models": {"jev": jc._load_cfg("JEV_MODEL", "TypeSafe/jev-latest"),
                   "pro": sdm.MODELS["pro"]},
        "rows": out_rows, "summary": summary,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── 分歧初审材料（供 AI 初审/人工复核逐条研判）─────────────────────────
    by_id = {r["id"]: r for r in rows}
    lines = ["# gold set 分歧初审材料（kw ≠ Jev 七细类）", "",
             f"生成：{payload['ts']}｜分歧 {len(dis_rows)} 条｜"
             "判读依据：docs/标准文档/打分体系标准.md v5.1 七细类判据", ""]
    for r in dis_rows:
        g = by_id.get(r["id"], {})
        lines += [f"## {r['id'][:16]}", f"- 标题：{g.get('title_zh') or g.get('title', '')}",
                  f"- kw 细类：{r['sub_kw']}｜Jev 细类：{(r.get('jev') or {}).get('sub')}",
                  f"- 摘要：{(g.get('summary') or '')[:200]}", ""]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n=== 冻结完成（{len(out_rows)} 条，wall {wall:.0f}s，失败 {dict(fails)}）===")
    print("档位分布：")
    for k, v in dists.items():
        print(f"  {k:<7}{v}  塌陷红线：{collapse_chk.get(k)}")
    print(f"七细类一致率（kw vs jev）：{summary['sub_agree']}")
    print(f"强度一致率：{json.dumps(summary['strength_agree'], ensure_ascii=False)}")
    print(f"\n冻结 → {OUT_JSON.name}｜分歧材料 → {OUT_MD.name}（{len(dis_rows)} 条分歧）")


def _dig(r: dict, keypath: list[str]):
    v = r
    for k in keypath:
        if not isinstance(v, dict):
            return None
        v = v.get(k)
    return v


if __name__ == "__main__":
    main()
