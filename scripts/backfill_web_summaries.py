#!/usr/bin/env python3
"""网站数据摘要补抓（S0-A1，2026-10-09 老温批可）。

背景（S0 实测定量）：全库 9,952 条中空摘要 3,940 条（40%）——76%（3,013 条）是
Google News 中转 URL 未解码，其余是直接源系统性空（us_doe 98%/us_epa 99%/jp_meti 99%/
cac 100%…）。根因：网站 summary 只取 RSS 描述、主流程从不抓正文；解码+抓正文引擎
（article_content.fetch_article，含 gnews 解码/WAF 处理/代理）仅在素材库路径接线。

设计三要点：
  1. **抓取**：复用 article_content.fetch_article（gnews 解码 + 反爬重试 + trust_env 走代理）；
     复用 refetch_material_bodies 的 _JUNK_PAT/is_junk_body 拦 WAF/导航垃圾页
     （2026-10-09 实测：huxiu 会返回 CF_APP_WAF 页被当正文，不拦必污染）
  2. **写回三层**：
     ① data/*.json（history + latest-24h + latest-24h-all）——立即生效；
        成功条目加 `summary_source: "body"`（缺省= RSS 自带，透明可统计）
     ② Notes/**/*.md frontmatter `summary:` 行——**持久层**（load_archived_summaries
        每轮从笔记重建回填层，主流程 update_news.py L4716 "摘要回填"自动消费）
     ③ 不加 --skip-vault 时自动做②；md 由 url 匹配定位，序列化复用 export_qmd._yaml_scalar
  3. **幂等/断点**：成功的 url 记入 done（重跑自动跳过已填 summary 的条目）；失败进
     cache/web-summary-cache.json（7 天冷却防反复重试）；每 N 条成功 checkpoint 落盘，
     落盘前**重读 JSON**（与服务器 30 分钟 timer 的整轮重写并发安全）

用法：
    python scripts/backfill_web_summaries.py --dry-run                 # 只统计候选
    python scripts/backfill_web_summaries.py --apply --gnews-only --limit 200
    python scripts/backfill_web_summaries.py --apply --workers 6 --report cache/web-summary-report.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load_env_file() -> None:
    """自动加载 /etc/green-policy.env（服务器代理 HTTPS_PROXY 等）。

    2026-10-09 踩坑：手动 ssh 运行不带 systemd 的 EnvironmentFile → 无代理直连，
    大量 fetch-none/junk-waf 全是数据中心 IP 触发的假失败（带代理重试 5/8 恢复）。
    """
    import os
    if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
        return
    for path in (Path("/etc/green-policy.env"), ROOT / ".env"):
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
            return
        except OSError:
            continue


_load_env_file()

import article_content as ac            # noqa: E402  gnews 解码 + 正文抓取引擎
import refetch_material_bodies as rmb   # noqa: E402  垃圾页拦截（_JUNK_PAT / is_junk_body）
import export_qmd as eq                 # noqa: E402  _yaml_scalar（vault frontmatter 序列化）

DATA = ROOT / "data"
JSON_FILES = ("history.json", "latest-24h.json", "latest-24h-all.json")
CACHE_PATH = ROOT / "cache" / "web-summary-cache.json"
NOTES_ROOT = ROOT / "Notes"
COOLDOWN_DAYS = 7
CHECKPOINT_EVERY = 150
MIN_SUMMARY_LEN = 15
_SHELL_PAT = re.compile(
    r"skip to main|打开.{0,8}app|下载.{0,8}app|click here|main content|sign in|log in|"
    r"subscribe|newsletter|cookie|订阅|登录|下载客户端", re.I)
FM_RE = re.compile(r"^(---\n)(.*?)(\n---\n)", re.DOTALL)


def _load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _save_json(p: Path, data) -> None:
    """按主流程同款格式写回（history=indent1 / latest-24h=indent2 / all=紧凑），
    写临时文件再替换（原子）。"""
    if p.name == "latest-24h-all.json":
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    elif p.name == "history.json":
        text = json.dumps(data, ensure_ascii=False, indent=1)
    else:
        text = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(p)


def load_memo() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_memo(memo: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(memo, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(CACHE_PATH)


def scan_candidates() -> dict[str, dict]:
    """扫三份 JSON：空摘要条目（按 url 去重）。返回 {url: {site, title, gnews, files}}"""
    cand: dict[str, dict] = {}
    for name in JSON_FILES:
        p = DATA / name
        if not p.exists():
            continue
        data = _load_json(p)
        items = data.get("items", data) if isinstance(data, dict) else data
        for it in items:
            if not isinstance(it, dict):
                continue
            url = it.get("url") or ""
            if not url or (it.get("summary") or "").strip():
                continue
            if url not in cand:
                cand[url] = {
                    "site": it.get("site_id", ""),
                    "title": (it.get("title_zh") or it.get("title") or "")[:60],
                    "gnews": "news.google.com" in url,
                    "files": [],
                }
            cand[url]["files"].append(name)
    return cand


def _fetch_summary(url: str) -> tuple[str | None, str]:
    """抓一条并返回 (summary|None, msg)。任何异常不抛出。"""
    try:
        res = ac.fetch_article(url)
    except Exception as exc:  # 网络类异常：静默失败
        return None, f"exc:{type(exc).__name__}"
    if not res:
        return None, "fetch-none"
    content = (res.get("content") or "").strip()
    summary = (res.get("summary") or "").strip().replace("\r", " ").replace("\n", " ")
    probe = (content or summary)[:3000]
    if rmb._JUNK_PAT.search(probe):
        return None, "junk-waf"
    if len(content) >= 200 and rmb.is_junk_body(content):
        return None, "junk-nav"
    if len(summary) < MIN_SUMMARY_LEN:
        return None, "too-short"
    # 导航壳页防漏（2026-10-09 实测）：如 "Skip to main content …"、"- The Robot Report"、
    # "打开虎嗅APP" 等短样板文本会通过长度检查——短文本 + 导航标记即判垃圾
    if len(summary) < 80 and _SHELL_PAT.search(summary):
        return None, "junk-shell"
    return summary, "ok"


def build_vault_index() -> dict[str, Path]:
    """Notes/**/*.md 全量扫 url → 文件路径（供 frontmatter 回写）。"""
    idx: dict[str, Path] = {}
    for p in NOTES_ROOT.rglob("*.md"):
        if p.name.startswith("ai-index"):
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="ignore")[:600]
        except Exception:
            continue
        m = re.search(r'^url:\s*"?([^"\n]+)"?\s*$', head, re.MULTILINE)
        if m:
            idx.setdefault(m.group(1).strip(), p)
    return idx


def patch_vault(path: Path, summary: str) -> bool:
    """只改 frontmatter 块内的 summary 行，正文原样。写入成功返回 True。"""
    if not summary or len(summary.strip()) < MIN_SUMMARY_LEN:
        return False          # 护栏：绝不用空/超短值覆盖已有摘要（2026-10-09 事故教训）
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    m = FM_RE.match(text)
    if not m:
        return False
    fm_body = m.group(2)
    line = f"summary: {eq._yaml_scalar(summary)}"
    if re.search(r"^summary:.*$", fm_body, re.MULTILINE):
        new_fm = re.sub(r"^summary:.*$", lambda _m: line, fm_body, count=1, flags=re.MULTILINE)
    else:
        new_fm = fm_body + "\n" + line
    if new_fm == fm_body:
        return False
    try:
        path.write_text(m.group(1) + new_fm + m.group(3) + text[m.end():], encoding="utf-8")
    except Exception:
        return False
    return True


def flush_json(done: dict[str, str], stats: dict) -> None:
    """把 done(url→summary) 应用回三份 JSON（重读保并发安全），统计汇总。"""
    for name in JSON_FILES:
        p = DATA / name
        if not p.exists():
            continue
        data = _load_json(p)
        items = data.get("items", data) if isinstance(data, dict) else data
        n = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            s = done.get(it.get("url") or "")
            if s and not (it.get("summary") or "").strip():
                it["summary"] = s
                it["summary_source"] = "body"
                n += 1
        if n:
            _save_json(p, data)
        stats.setdefault("json_written", {})[name] = n


def main() -> int:
    ap = argparse.ArgumentParser(description="网站数据摘要补抓（S0-A1）")
    ap.add_argument("--apply", action="store_true", help="真正抓取并写回（默认只扫不抓）")
    ap.add_argument("--dry-run", action="store_true", help="只统计候选分布")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 条（0=不限）")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--site", default="", help="只处理指定 site_id")
    ap.add_argument("--gnews-only", action="store_true", help="只处理 Google News 中转条目")
    ap.add_argument("--skip-vault", action="store_true", help="不写 Notes frontmatter（只改 JSON）")
    ap.add_argument("--report", default="", help="汇总报告 JSON 路径")
    ap.add_argument("--ignore-cooldown", action="store_true",
                    help="忽略失败冷却（代理修复后的重跑用）")
    args = ap.parse_args()

    cand = scan_candidates()
    pool = cand
    if args.site:
        pool = {u: v for u, v in pool.items() if v["site"] == args.site}
    if args.gnews_only:
        pool = {u: v for u, v in pool.items() if v["gnews"]}
    memo = load_memo()
    cutoff = datetime.now(timezone.utc) - timedelta(days=COOLDOWN_DAYS)
    todo_urls = []
    cooled = 0
    for u, v in pool.items():
        rec = memo.get(u)
        if rec and not rec.get("ok") and not args.ignore_cooldown:
            try:
                if datetime.fromisoformat(rec.get("t", "")) > cutoff:
                    cooled += 1
                    continue
            except Exception:
                pass
        todo_urls.append(u)
    gnews_n = sum(1 for u in todo_urls if pool[u]["gnews"])
    print(f"候选（空摘要）: {len(pool)} 条｜本轮处理 {len(todo_urls)}"
          f"（gnews {gnews_n} / 直接源 {len(todo_urls) - gnews_n}）｜失败冷却跳过 {cooled}")
    if args.dry_run or not args.apply:
        from collections import Counter
        top = Counter(pool[u]["site"] for u in todo_urls).most_common(15)
        print("按来源 Top15:", dict(top))
        if not args.apply:
            print("（未加 --apply：只统计不抓取）")
        return 0
    if args.limit:
        todo_urls = todo_urls[: args.limit]


    done: dict[str, str] = {}
    ok = fail = 0
    by_msg: dict[str, int] = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(_fetch_summary, u): u for u in todo_urls}
        for i, fut in enumerate(as_completed(futs), 1):
            url = futs[fut]
            try:
                summary, msg = fut.result()
            except Exception as exc:
                summary, msg = None, f"exc:{type(exc).__name__}"
            by_msg[msg] = by_msg.get(msg, 0) + 1
            if summary:
                ok += 1
                done[url] = summary
                memo[url] = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "ok": True, "msg": "ok"}
            else:
                fail += 1
                memo[url] = {"t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             "ok": False, "msg": msg}
            if i % 20 == 0 or i == len(todo_urls):
                el = time.time() - t0
                print(f"[{i}/{len(todo_urls)}] ok={ok} fail={fail} "
                      f"（{el:.0f}s，{el / i:.1f}s/条）", flush=True)
            if i % CHECKPOINT_EVERY == 0:
                flush_json(done, {})
                save_memo(memo)
    stats: dict = {}
    flush_json(done, stats)
    save_memo(memo)
    # ── vault 持久层补写（收尾阶段重建索引：素材库在 fetch 期间仍被 timer 持续导出，
    #    开跑时冻结的索引会漏掉新导出的 md——2026-10-09 实测 1/5 命中率教训）──
    vault_idx: dict[str, Path] = {}
    patched = miss = 0
    if not args.skip_vault and done:
        vault_idx = build_vault_index()
        for u, s in done.items():
            pth = vault_idx.get(u)
            if not pth:
                miss += 1
                continue
            if patch_vault(pth, s):
                patched += 1
        print(f"vault frontmatter 补写: 成功 {patched}｜url 不在素材库 {miss}（索引 {len(vault_idx)}）")
    dt = time.time() - t0
    print(f"\n完成：成功 {ok}｜失败 {fail}｜耗时 {dt:.0f}s（{dt / max(len(todo_urls), 1):.2f}s/条）")
    print("失败分布:", dict(sorted(by_msg.items(), key=lambda kv: -kv[1])))
    print("JSON 写回:", stats.get("json_written", {}))
    if args.report:
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "candidates": len(pool), "processed": len(todo_urls),
            "ok": ok, "fail": fail, "by_msg": by_msg, "json_written": stats.get("json_written", {}),
            "vault_indexed": len(vault_idx), "vault_patched": patched, "vault_miss": miss,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
