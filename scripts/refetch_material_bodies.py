#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""素材库正文补抓（2026-10-04 Track 2）：给"无正文/正文过短"的素材条目重新抓正文。

背景（实测）：
  素材库 15380 条中**有正文（≥50 字）仅 6690 条 = 43%**；缺的 8689 条里
  **3857 条（44%）是 Google News 聚合 URL**（`news.google.com/rss/articles/…`），
  解码器 `article_content._decode_google_news_url` 实测 14/14 成功、正文抓取 10/14 成功
  → 历史库存可批量补回。空摘要同时是"关键词打分只能看标题"的根因。

铁律（不可违反）：
  1. **绝不改写 frontmatter**：`url` 字段是 `mat/<sha1(url)[:12]>` 的唯一来源，改了 id 就漂移；
     文件名同理不动（只补正文节）
  2. **保留 KEEP_SECTIONS**（`相关条目` / `关联实体`）：这两节由 P3/P4 工具接线，
     重建时必须原样续接（2026-10-04 实测过一次被擦掉的坑）
  3. 只填空：`## 摘要` 仅在当前为空时写；`## 正文` 仅在 < `--min-body` 时写
  4. **垃圾页不许入库**：反爬/WAF 拦截页、浏览器墙、纯导航页（36氪/虎嗅/财新/高盛实测）
     用 `is_junk_body()` 拦掉 —— 否则"有正文率"指标会被垃圾骗上去

用法：
    # ① 先看缺口（不写文件）
    python3.11 scripts/refetch_material_bodies.py --dry-run --limit 200
    # ② 小批实跑（Google News 优先）
    python3.11 scripts/refetch_material_bodies.py --apply --gnews-only --limit 60 --workers 4
    # ③ 全量（后台跑，可断点续跑；缓存 data/refetch-bodies-cache.json）
    python3.11 scripts/refetch_material_bodies.py --apply --workers 4
    # ④ 定向站点
    python3.11 scripts/refetch_material_bodies.py --apply --site 36氪 --limit 50
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import article_content as ac  # noqa: E402

MAT_ROOT = ROOT / "Notes" / "素材库"
CACHE_PATH = ROOT / "cache" / "refetch-bodies-cache.json"   # cache/ 已 gitignore（派生缓存）
KEEP_SECTIONS = ("相关条目", "关联实体")
MIN_BODY_DEFAULT = 50
RETRY_DAYS_DEFAULT = 14

# ── 垃圾页判定（2026-10-04 实测踩坑）────────────────────────────
# 反爬/WAF 拦截页、浏览器墙、纯导航页会被当成"正文"写进库（实测 4/40）：
#   36氪「正在进行安全检测…」｜虎嗅 `appkey: "CF_APP_WAF"`｜高盛 nature.com 浏览器墙｜财新纯导航
# 这些不但是垃圾，还会把"有正文率"指标骗上去，必须在写回前拦掉。
_JUNK_PAT = re.compile(
    r"正在进行安全检测|为保障您的访问安全|安全验证|人机验证|请输入验证码|请耐心等待|访问过于频繁|"
    r"Just a moment|Checking your browser|Enable JavaScript|Verify you are human|Attention Required|"
    r"CF_APP_WAF|__tst_status|document\.cookie|window\.location\.href|"
    r"browser version with|请在浏览器中启用|您的浏览器版本过低|"
    r"登录后继续|请先登录|该内容已被删除|页面不存在|403 Forbidden|404 Not Found",
    re.I)
_NAV_WORDS = {"首页", "登录", "注册", "关于我们", "联系我们", "更多", "搜索", "导航", "菜单",
              "订阅", "分享", "评论", "返回", "上一页", "下一页", "English",
              "Home", "Login", "Sign in", "Menu", "Search", "Share", "News"}


def is_junk_body(text: str, min_content: int = 150) -> bool:
    """正文是否是反爬页/导航页（而非真文章）。"""
    t = (text or "").strip()
    if len(t) < 200:
        return True
    head = t[:3000]
    if _JUNK_PAT.search(head):
        return True
    lines = [ln.strip() for ln in t.split("\n") if ln.strip()]
    long_lines = [ln for ln in lines if len(ln) >= 25]
    content_chars = sum(len(ln) for ln in long_lines)
    if content_chars < min_content:      # 长句太少 → 纯导航/目录
        return True
    nav = sum(1 for ln in lines if ln in _NAV_WORDS)
    if lines and nav / len(lines) > 0.5 and content_chars < 400:
        return True
    return False

_tls = threading.local()


def _session():
    s = getattr(_tls, "sess", None)
    if s is None:
        s = ac.requests.Session()
        s.headers.update({"User-Agent": ac.BROWSER_UA,
                          "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
        _tls.sess = s
    return s


# ── 笔记读写（只动 摘要/正文 两节）────────────────────────────────
def _parse_fm(text: str) -> dict[str, str]:
    fm: dict[str, str] = {}
    if not text.startswith("---"):
        return fm
    for line in text.split("\n")[1:]:
        if line.strip() == "---":
            break
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm


def _section_span(text: str, name: str) -> tuple[int, int] | None:
    m = re.search(rf"^##\s*{re.escape(name)}\s*$", text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    nxt = re.search(r"^##\s", rest, re.M)
    end = m.end() + (nxt.start() if nxt else len(rest))
    return m.start(), end


def _get_section(text: str, name: str) -> str:
    span = _section_span(text, name)
    if not span:
        return ""
    seg = text[span[0]:span[1]]
    return seg.split("\n", 1)[1].strip() if "\n" in seg else ""


_SECTION_ORDER = ("摘要", "正文", "技术特征") + KEEP_SECTIONS


def _set_section(text: str, name: str, body: str) -> str:
    """替换已有小节；不存在时按规范顺序插入（摘要→正文→技术特征→相关条目→关联实体）。"""
    new = f"## {name}\n\n{body.strip()}\n\n"
    span = _section_span(text, name)
    if span:
        return text[:span[0]] + new + text[span[1]:]
    idx = _SECTION_ORDER.index(name) if name in _SECTION_ORDER else len(_SECTION_ORDER)
    for later in _SECTION_ORDER[idx + 1:]:
        sp = _section_span(text, later)
        if sp:
            return text[:sp[0]] + new + text[sp[0]:]
    return text.rstrip() + "\n\n" + new


def scan_candidates(min_body: int, site: str | None, gnews_only: bool,
                    sub: str | None) -> list[dict]:
    """列出缺正文的素材条目。"""
    out: list[dict] = []
    for p in sorted(MAT_ROOT.rglob("*.md")):
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        if not t.startswith("---"):
            continue
        fm = _parse_fm(t)
        url = fm.get("url", "")
        if not url:
            continue
        if site and fm.get("site", "") != site:
            continue
        if sub and fm.get("sub_dimension", "") != sub:
            continue
        if gnews_only and "news.google.com" not in url:
            continue
        body = _get_section(t, "正文")
        summary = _get_section(t, "摘要")
        if len(body) >= min_body:
            continue
        out.append({"path": p, "url": url, "site": fm.get("site", "?"),
                    "title": fm.get("title", ""), "body_len": len(body),
                    "summary_len": len(summary)})
    return out


# ── 抓取 + 写回 ───────────────────────────────────────────────────
def refetch_one(item: dict, min_body: int, min_content: int = 150) -> tuple[dict, str]:
    """抓一条并写回（只在有收获时写文件）。返回 (item, 结果描述)。"""
    p: Path = item["path"]
    try:
        res = ac.fetch_article(item["url"], session=_session(), rich=False)
    except Exception as e:  # 单条异常隔离
        return item, f"exc:{type(e).__name__}"
    if not res:
        return item, "fetch-none"
    new_body = (res.get("content") or "").strip()
    new_sum = (res.get("summary") or "").strip()
    if len(new_body) < min_body:
        return item, f"body-too-short({len(new_body)})"
    if is_junk_body(new_body, min_content):
        return item, f"junk-page({len(new_body)})"
    if new_sum and (len(new_sum) < 20 or _JUNK_PAT.search(new_sum[:400])):
        new_sum = ""      # 摘要也不许写垃圾

    try:
        t = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return item, f"read-exc:{type(e).__name__}"

    old_body = _get_section(t, "正文")
    old_sum = _get_section(t, "摘要")
    changed = False
    if len(old_body) < min_body:
        t = _set_section(t, "正文", new_body)
        changed = True
    # 摘要只填空（不覆盖既有摘要）
    if not old_sum and new_sum:
        t = _set_section(t, "摘要", new_sum)
        changed = True
    if not changed:
        return item, "no-change"
    # 兜底：确认 KEEP_SECTIONS 未被破坏
    for name in KEEP_SECTIONS:
        if f"## {name}" in p.read_text(encoding="utf-8", errors="replace") and \
           f"## {name}" not in t:
            return item, "ABORT:would-drop-keep-section"
    try:
        p.write_text(t, encoding="utf-8")
    except Exception as e:
        return item, f"write-exc:{type(e).__name__}"
    return item, f"ok({len(new_body)}字, 摘要+{len(new_sum)})"


def _spread(items: list[dict]) -> list[dict]:
    """按站点轮转排序：避免整批撞在同一个站点（36氪 92% 失败会把批次样本带偏）。"""
    by: dict[str, list[dict]] = {}
    for it in items:
        by.setdefault(it["site"], []).append(it)
    groups = sorted(by.items(), key=lambda kv: -len(kv[1]))
    out: list[dict] = []
    while True:
        added = False
        for _, lst in groups:
            if lst:
                out.append(lst.pop(0))
                added = True
        if not added:
            return out


def load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_cache(c: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CACHE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, ensure_ascii=False, indent=0), encoding="utf-8")
    tmp.replace(CACHE_PATH)


def main() -> int:
    ap = argparse.ArgumentParser(description="素材库正文补抓（Track 2）")
    ap.add_argument("--apply", action="store_true", help="真正写回（默认只扫描/试抓）")
    ap.add_argument("--dry-run", action="store_true", help="只列候选，不抓取")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 条（0=不限）")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--min-body", type=int, default=MIN_BODY_DEFAULT)
    ap.add_argument("--min-content", type=int, default=150,
                    help="正文里长句（≥25字）字符数下限，低于此判为导航/反爬页")
    ap.add_argument("--site", default=None, help="只处理指定 site 字段（精确匹配）")
    ap.add_argument("--sub", default=None, help="只处理指定 sub_dimension（细类）")
    ap.add_argument("--gnews-only", action="store_true", help="只处理 Google News 聚合条目")
    ap.add_argument("--spread", action="store_true",
                    help="按站点轮转取样（避免整批落在一个站点）")
    ap.add_argument("--retry-days", type=int, default=RETRY_DAYS_DEFAULT,
                    help="缓存里失败条目多少天后重试")
    ap.add_argument("--no-cache", action="store_true", help="忽略缓存（全量重试）")
    ap.add_argument("--report", default=None,
                    help="把本轮结果写成 JSON（站点级成功/垃圾/失败汇总，便于排产）")
    args = ap.parse_args()

    if not MAT_ROOT.exists():
        print(f"❌ 素材库不存在: {MAT_ROOT}")
        return 1

    cand = scan_candidates(args.min_body, args.site, args.gnews_only, args.sub)
    print(f"缺正文候选: {len(cand)} 条（min_body={args.min_body}"
          f"{', site=' + args.site if args.site else ''}"
          f"{', sub=' + args.sub if args.sub else ''}"
          f"{', gnews-only' if args.gnews_only else ''}）", flush=True)
    if args.dry_run:
        preview = _spread(cand) if args.spread else cand
        for it in preview[:args.limit or 40]:
            print(f"  {it['site'][:14]:<16} body={it['body_len']:<5} sum={it['summary_len']:<4} "
                  f"{it['title'][:44]}")
        return 0

    cache = {} if args.no_cache else load_cache()
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.retry_days)
    todo = []
    for it in cand:
        rec = cache.get(it["url"])
        if rec and rec.get("ok"):
            continue  # 已成功过（正文已在笔记里，理论上不会再进候选）
        if rec and not rec.get("ok"):
            try:
                if datetime.fromisoformat(rec.get("t", "")) > cutoff:
                    continue  # 近期失败过，先跳过
            except Exception:
                pass
        todo.append(it)
    if args.spread:
        todo = _spread(todo)
    if args.limit:
        todo = todo[:args.limit]
    print(f"本轮处理: {len(todo)} 条（缓存跳过 {len(cand) - len(todo)}）", flush=True)
    if not todo:
        return 0

    if not args.apply:
        print("（未加 --apply：只试抓不写回）", flush=True)

    ok = short = fail = junk = 0
    by_site: dict[str, dict[str, int]] = {}
    details: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(_fetch_only, it, args.min_body, args.apply,
                          args.min_content): it for it in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            it, msg = fut.result()
            if msg.startswith("ok"):
                ok += 1
                kind = "ok"
            elif msg.startswith("junk-page"):
                junk += 1
                kind = "junk"
            elif msg.startswith("body-too-short") or msg == "fetch-none":
                fail += 1
                kind = "fail"
            else:
                short += 1
                kind = "other"
            st = by_site.setdefault(it["site"], {"ok": 0, "junk": 0, "fail": 0, "other": 0,
                                                 "total": 0})
            st[kind] += 1
            st["total"] += 1
            details.append({"site": it["site"], "msg": msg, "kind": kind,
                            "title": it["title"][:70], "url": it["url"]})
            cache[it["url"]] = {
                "t": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "ok": msg.startswith("ok"), "msg": msg, "len": 0,
            }
            print(f"[{i}/{len(todo)}] {msg:<26} {it['site'][:12]:<14} {it['title'][:38]}", flush=True)
            if i % 20 == 0:
                save_cache(cache)
    save_cache(cache)
    dt = time.time() - t0
    print(f"\n完成：成功 {ok}｜抓不到/太短 {fail}｜垃圾页拦下 {junk}｜跳过 {short}｜耗时 {dt:.0f}s "
          f"（{dt / max(len(todo), 1):.1f}s/条）")
    if args.report:
        rp = Path(args.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "total": len(todo), "ok": ok, "fail": fail, "junk": junk, "other": short,
            "by_site": dict(sorted(by_site.items(), key=lambda kv: -kv[1]["total"])),
            "details": details,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"报告: {rp}")
    print(f"缓存: {CACHE_PATH.relative_to(ROOT)}")
    return 0


def _fetch_only(item: dict, min_body: int, apply: bool,
                min_content: int = 150) -> tuple[dict, str]:
    if apply:
        return refetch_one(item, min_body, min_content)
    try:
        res = ac.fetch_article(item["url"], session=_session(), rich=False)
    except Exception as e:
        return item, f"exc:{type(e).__name__}"
    if not res:
        return item, "fetch-none"
    body = (res.get("content") or "").strip()
    n = len(body)
    if n < min_body:
        return item, f"body-too-short({n})"
    if is_junk_body(body, min_content):
        return item, f"junk-page({n})"
    return item, f"ok({n}字)"


if __name__ == "__main__":
    raise SystemExit(main())
