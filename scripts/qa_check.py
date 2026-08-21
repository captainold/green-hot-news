#!/usr/bin/env python3
"""qa_check.py — 数据质量自动检查（只报告，不修复）

服务器每次抓取后由 green-policy-sync.sh 调用（步骤 1.7）。
读 data/latest-24h.json + history.json + source-status.json，输出：
  data/qa-report.json  — 结构化结果（agent/程序消费）
  data/qa-report.md    — 人类可读报告（老温/会话开始汇报用）

检查项（对应历史踩坑，见 AGENTS.md / docs/todo.md）：
  A 标题：空/导航站名污染/过短过长/HTML残留/纯数字
  B 摘要：空/污染词/过短/截断异常/HTML残留
  C 翻译：非中文标题缺 title_zh/机翻残留英文/中文误翻/失败占位
  D 时间：未来时间/发布时间缺失比例/scraped 比例过高
  E 链接：空/Google News base64 假链/http 明文/可选 HEAD 404
  F 数据：重复标题/空源/关键字段缺失/打分越界/条目数波动

评分：100 起，error -2（封顶 -50），warn -0.5（封顶 -25），info 不扣。
等级：A≥90  B≥80  C≥70  D<70

用法：
  python3 qa_check.py                # 默认纯数据检查（不联网）
  python3 qa_check.py --check-links  # 额外 HEAD 探测 url 有效性（慢）
纯 stdlib，服务器 .venv 或系统 python3 均可运行。
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# ---------- 复用 update_news.py 的标题去重键（2026-08-19，来源注释） ----------
def title_dedup_key(title: str) -> str:
    t = re.sub(r"[\s\u3000\-_—–()（）【】\[\]「」『』・,，.。:：;；/\\|]", "", (title or "").lower())
    return t[:120]

# ---------- 导航/站名污染标题（对齐 update_news.py _NAV_JUNK_TITLE_RE，2026-08-19/20） ----------
_NAV_JUNK_RE = re.compile(
    r"^(english releases|photo album|blogdescription|pib backgrounder|reports archives|.* archives|"
    r"archives|glossary|education|data in the classroom|station home page|tide predictions|"
    r"daily weather map|pib|eia webinars|short-term energy outlook|contact us|about us|opendata|"
    r"databases|dashboard|webinars|maps and data|energy explained|faqs|hourly electric grid monitor|"
    r"real-time operating grid|new england dashboard|weekly petroleum status report|"
    r"gasoline and diesel fuel update|steo data browser|learn more about|map a career|"
    r"renewable energy maps|data access viewer|sea level analysis tool|archived directives|"
    r"women in energy|from our blogs|grid talk|innovation|energy workforce|find careers|"
    r"find financing|credit subsidy|technical project officer|collegiate wind competition|"
    r"state energy advisory board|deploy 2024|energy improvements in rural|getting to know lpo|"
    r"loan program office|u\.s\. energy & employment report|marine energy basics|"
    r"regional clean hydrogen hubs|quarterly solar industry update|critical minerals and materials|"
    r"solar workforce|solar photovoltaic|types of hydropower|how distributed wind|"
    r"hydrogen production|solar cybersecurity|end-of-life management for solar|"
    r"3 reasons why nuclear|5 fast facts about nuclear|does eia project|"
    r"what can i expect to pay for heating|national weather service marine forecast\b.*|"
    r"tropical storm \w+ forecast discussion\b.*|station \d+\b.*|station [a-z0-9]{3,6} \b.*|"
    r"snow station information\b.*|multi-state regions|electric matters|statements and speeches|"
    r"data tool|air quality system|public water system service areas|clean school bus program|"
    r"transmission facility financing|what types of cmei funding exist|30d new clean vehicle credit|"
    r"u\.s\. energy information administration\b.*|southwestern power administration\b.*|"
    r"california air resources board\b.*|federal energy regulatory commission\b.*|"
    r"national hurricane center\b.*|climate prediction center\b.*)\s*$",
    re.IGNORECASE,
)

# 中文导航/站名/垃圾标题与摘要词（历史踩坑：8-19「文章来源」+「我的位置」导航垃圾、8-20 站名当标题）
_ZH_JUNK_WORDS = [
    "文章来源", "我的位置", "首页", "网站首页", "导航", "网站地图", "sitemap",
    "登录", "注册", "关于我们", "联系我们", "隐私政策", "版权声明",
    "免责声明", "页面不存在", "无法访问", "访问异常", "系统繁忙", "确认跳转",
    "正在跳转", "跳转提示", "您正在访问", "敬请期待", "开通会员", "阅读全文",
    "查看原文", "扫码下载", "加入收藏", "打印本页", "关闭窗口", "返回顶端",
]
_ZH_JUNK_TITLE_RE = re.compile(r"(^(%s)(\s*[-|—·:：])?)|(([-|—·:：]\s*)?(%s)$)" % (
    "|".join(_ZH_JUNK_WORDS), "|".join(_ZH_JUNK_WORDS)), re.IGNORECASE)

_HTML_ENTITY_RE = re.compile(r"&[a-z]+;|&#\d+;|<\s*[a-zA-Z/][^>]*>")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_EN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
_GOOGLE_BASE64_RE = re.compile(r"news\.google\.com/.+/articles/")

ERR, WARN, INFO = "error", "warn", "info"


def parse_ts(s: str):
    """解析 ISO 时间戳，失败返回 None。"""
    if not s:
        return None
    s = str(s).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


class QaReport:
    def __init__(self):
        self.issues = []          # {level, item, source, url, msg}
        self.stats = {"items": 0, "no_title_zh": 0, "scraped_time": 0}
        self.source_counts = {}

    def add(self, level, item, msg, source="", url=""):
        self.issues.append({"level": level, "item": item, "source": source, "url": url, "msg": msg})

    # ---------- A 标题 ----------
    def check_title(self, it):
        t = (it.get("title") or "").strip()
        if not t:
            self.add(ERR, "A1", "标题为空", it.get("site_name", ""), it.get("url", ""))
            return
        if _ZH_JUNK_TITLE_RE.search(t) or _NAV_JUNK_RE.match(t):
            self.add(ERR, "A2", f"标题疑似导航/站名/垃圾页: {t[:60]}", it.get("site_name", ""), it.get("url", ""))
        if len(t) < 4:
            self.add(WARN, "A3", f"标题过短({len(t)}字): {t}", it.get("site_name", ""), it.get("url", ""))
        if len(t) > 120:
            self.add(INFO, "A3", f"标题超长({len(t)}字): {t[:80]}…", it.get("site_name", ""), it.get("url", ""))
        if _HTML_ENTITY_RE.search(t):
            self.add(ERR, "A4", f"标题含 HTML 实体/标签残留: {t[:60]}", it.get("site_name", ""), it.get("url", ""))
        if re.fullmatch(r"[\d\s\W_]+", t):
            self.add(WARN, "A5", f"标题无有效文字: {t[:60]}", it.get("site_name", ""), it.get("url", ""))

    # ---------- B 摘要 ----------
    def check_summary(self, it):
        s = (it.get("summary") or "").strip()
        if not s:
            self.stats["empty_summary"] = self.stats.get("empty_summary", 0) + 1
            return  # 逐条 info 会刷屏，改由 build_report 按占比汇总告警
        hit = [w for w in _ZH_JUNK_WORDS if w in s]
        if hit:
            self.add(ERR, "B2", f"摘要含垃圾词{hit}: {s[:60]}…", it.get("site_name", ""), it.get("url", ""))
        if len(s) < 10:
            self.add(WARN, "B3", f"摘要过短({len(s)}字): {s}", it.get("site_name", ""), it.get("url", ""))
        if s[-1] in "，、；：,—-":
            self.add(WARN, "B4", f"摘要截断在非终止标点: …{s[-40:]}", it.get("site_name", ""), it.get("url", ""))
        if _HTML_ENTITY_RE.search(s):
            self.add(ERR, "B5", f"摘要含 HTML 残留: {s[:60]}…", it.get("site_name", ""), it.get("url", ""))

    # ---------- C 翻译 ----------
    def check_translation(self, it):
        t = (it.get("title") or "").strip()
        zh = (it.get("title_zh") or "").strip()
        cjk_chars = len(_CJK_RE.findall(t))
        has_cjk = cjk_chars >= 2  # 2 个以上汉字 = 中文标题（允许夹杂英文专有名词：AI/DeepMind/CORSIA…）
        en_words = _EN_WORD_RE.findall(t)
        is_foreign = not has_cjk  # 无中文 = 外文标题，需要 title_zh
        if is_foreign:
            if not zh:
                self.stats["no_title_zh"] += 1
                self.add(ERR, "C1", f"非中文标题缺 title_zh: {t[:60]}", it.get("site_name", ""), it.get("url", ""))
            elif zh == t:
                # GitHub 项目名/专有名词翻译后原样返回是正常行为（everything-claude-code、llama.cpp…）
                if "github.com" not in (it.get("url") or ""):
                    self.add(ERR, "C1", "title_zh 与原文完全相同（翻译失败回退）", it.get("site_name", ""), it.get("url", ""))
            elif _EN_WORD_RE.findall(zh):
                # 过滤社交元素（@mention / #hashtag / URL / emoji）后再数英文单词
                zh_clean = re.sub(r"@\S+|#\S+|https?://\S+|✍️|📢|🥵|🌡️|📉|🌿|💎|🔸|…|—|\|", "", zh)
                en_left = [w for w in _EN_WORD_RE.findall(zh_clean) if w.lower() not in
                           {"qa", "ai", "ccs", "gxp", "rl", "vc", "iea", "epa", "vcf", "sc"}]  # 常见缩写不算残留
                if len(en_left) > 3:
                    self.add(WARN, "C2", f"title_zh 机翻残留英文: {zh[:60]}", it.get("site_name", ""), it.get("url", ""))
            if zh and any(k in zh.lower() for k in ("翻译失败", "error", "failed", "原文")):
                self.add(ERR, "C4", f"title_zh 是失败占位: {zh[:60]}", it.get("site_name", ""), it.get("url", ""))
        elif has_cjk and zh and zh != t:
            self.add(INFO, "C3", f"中文标题却有不同 title_zh（疑似误翻/回译）: {t[:40]} → {zh[:40]}", it.get("site_name", ""), it.get("url", ""))

    # ---------- D 时间 ----------
    def check_time(self, it, now):
        pub = parse_ts(it.get("published_at"))
        if pub is None:
            self.stats["scraped_time"] += 1
            ts = it.get("time_source") or ""
            if ts == "scraped":
                self.add(INFO, "D2", "发布时间缺失（收录时间兜底，正常降级）", it.get("site_name", ""), it.get("url", ""))
            else:
                self.add(WARN, "D2", f"published_at 为空且 time_source={ts!r}", it.get("site_name", ""), it.get("url", ""))
            return
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if pub > now + __import__("datetime").timedelta(hours=48):
            self.add(ERR, "D1", f"发布时间在未来: {pub.isoformat()} (> now+48h)", it.get("site_name", ""), it.get("url", ""))
    # ---------- E 链接 ----------
    def check_url(self, it):
        u = (it.get("url") or "").strip()
        if not u:
            self.add(ERR, "E1", "url 为空", it.get("site_name", ""))
            return
        if _GOOGLE_BASE64_RE.search(u):
            self.add(INFO, "E2", "Google News base64 聚合链接（未抓详情页覆盖，属正常状态）", it.get("site_name", ""), u)
        if u.startswith("http://"):
            self.add(INFO, "E3", f"http 明文链接（源特性，部分老站无 https）: {u[:60]}", it.get("site_name", ""), u)

    # ---------- F 数据 ----------
    def check_duplicates(self, items):
        seen = {}
        for it in items:
            key = title_dedup_key(it.get("title", ""))
            if not key:
                continue
            seen.setdefault(key, []).append(it)
        for key, grp in seen.items():
            if len(grp) > 1:
                urls = {g.get("url", "") for g in grp}
                if len(urls) > 1:
                    srcs = sorted({g.get("site_name", "") for g in grp})
                    self.add(ERR, "F1", f"标题重复 x{len(grp)}（跨源）: {grp[0].get('title','')[:50]} [{', '.join(srcs)}]", "", list(urls)[0])

    def check_fields(self, it):
        for f in ("score", "dimension", "region", "url", "title"):
            if f not in it or it[f] in (None, ""):
                self.add(ERR, "F3", f"关键字段缺失: {f}", it.get("site_name", ""), it.get("url", ""))
        sc = it.get("score")
        if isinstance(sc, (int, float)) and not (0 <= sc <= 100):
            self.add(ERR, "F4", f"打分越界: score={sc}", it.get("site_name", ""), it.get("url", ""))
        if "score_breakdown" not in it:
            self.add(WARN, "F4", "缺 score_breakdown", it.get("site_name", ""), it.get("url", ""))

    def check_empty_sources(self, items, source_status):
        active = {s.get("site_id") for s in source_status.get("sites", []) if s.get("ok")}
        present = {it.get("site_id") for it in items}
        empty = active - present
        if empty:
            self.add(WARN, "F2", f"最新24h无条目（可能正常低更新）: {sorted(empty)[:8]}", "", "")

    def check_volume(self, items):
        for it in items:
            sid = it.get("site_id", "?")
            self.source_counts[sid] = self.source_counts.get(sid, 0) + 1
        state_path = DATA / "qa-state.json"
        if state_path.exists():
            try:
                prev = json.loads(state_path.read_text(encoding="utf-8")).get("source_counts", {})
                for sid, cnt in self.source_counts.items():
                    pcnt = prev.get(sid)
                    if pcnt and pcnt >= 5 and (cnt > pcnt * 3 or cnt < pcnt * 0.2):
                        self.add(WARN, "F5", f"条目数波动: {sid} {pcnt}→{cnt}", sid, "")
            except Exception:
                pass
        state_path.write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                                          "source_counts": self.source_counts}, ensure_ascii=False, indent=1),
                              encoding="utf-8")


def build_report(items, now, source_status):
    rep = QaReport()
    rep.stats["items"] = len(items)
    for it in items:
        rep.check_title(it)
        rep.check_summary(it)
        rep.check_translation(it)
        rep.check_time(it, now)
        rep.check_url(it)
        rep.check_fields(it)
    rep.check_duplicates(items)
    rep.check_empty_sources(items, source_status)
    rep.check_volume(items)

    # 汇总类告警（逐条报会刷屏，按占比只报一条）
    n = len(items)
    empty_ratio = rep.stats.get("empty_summary", 0) / n if n else 0
    if empty_ratio > 0.5:
        rep.add(ERR, "B1", f"摘要为空占比过高: {rep.stats['empty_summary']}/{n} ({empty_ratio:.0%})，抓取链路可能整体缺摘要")
    elif empty_ratio > 0.25:
        rep.add(WARN, "B1", f"摘要为空占比偏高: {rep.stats['empty_summary']}/{n} ({empty_ratio:.0%})")
    if rep.stats.get("no_title_zh", 0) > 10:
        rep.add(WARN, "C1", f"非中文标题缺 title_zh 达 {rep.stats['no_title_zh']} 条，翻译链路可能故障（检查 QPS/密钥）")

    n_err = sum(1 for i in rep.issues if i["level"] == ERR)
    n_warn = sum(1 for i in rep.issues if i["level"] == WARN)
    n_info = sum(1 for i in rep.issues if i["level"] == INFO)
    score = 100 - min(n_err * 2, 50) - min(n_warn * 0.5, 25)
    score = max(0, round(score, 1))
    level = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D"

    by_cat = {}
    for i in rep.issues:
        by_cat.setdefault(i["item"], []).append(i)

    return {
        "generated_at": now.isoformat(),
        "data_file": "latest-24h.json",
        "score": score,
        "score_level": level,
        "totals": {"items": len(items), "error": n_err, "warn": n_warn, "info": n_info},
        "stats": rep.stats,
        "issues": rep.issues,
        "by_category": {k: len(v) for k, v in by_cat.items()},
        "source_counts": dict(sorted(rep.source_counts.items(), key=lambda x: -x[1])),
    }, rep


def write_md(report, rep, out_path):
    lines = []
    lines.append(f"# 数据质量检查报告（QA）")
    lines.append(f"生成时间：{report['generated_at']}")
    lines.append(f"数据源：{report['data_file']}（{report['totals']['items']} 条）")
    lines.append("")
    lines.append(f"## 总评分：**{report['score']}**（{report['score_level']} 级）")
    lines.append(f"- 🔴 error：{report['totals']['error']} 条  🟡 warn：{report['totals']['warn']} 条  🔵 info：{report['totals']['info']} 条")
    if report["stats"].get("no_title_zh"):
        lines.append(f"- ⚠️ 非中文标题缺翻译：{report['stats']['no_title_zh']} 条")
    if report["stats"].get("scraped_time"):
        lines.append(f"- ℹ️ 发布时间缺失（收录时间兜底）：{report['stats']['scraped_time']} 条 / {report['totals']['items']} 条")
    lines.append("")

    if not rep.issues:
        lines.append("🎉 无问题，一切正常！")
    else:
        lines.append("## 问题清单（按严重级）")
        for lv, icon in ((ERR, "🔴"), (WARN, "🟡"), (INFO, "🔵")):
            sub = [i for i in rep.issues if i["level"] == lv]
            if not sub:
                continue
            lines.append(f"\n### {icon} {lv.upper()}（{len(sub)}）")
            for i in sub[:40]:
                src = f"[{i['source']}] " if i["source"] else ""
                lines.append(f"- {src}{i['msg']}")
                if i["url"]:
                    lines.append(f"  → {i['url']}")
            if len(sub) > 40:
                lines.append(f"- …共 {len(sub)} 条，详见 JSON")
    lines.append("")
    lines.append("## 各源条目数（Top 20）")
    for sid, cnt in list(report["source_counts"].items())[:20]:
        lines.append(f"- {sid}: {cnt}")
    lines.append("")
    lines.append("> 本报告由 qa_check.py 自动生成，只报告不修复。问题处置由人工/agent 决定。")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def check_links(items, rep):
    import urllib.request
    for it in items[:80]:
        u = it.get("url", "")
        if not u or _GOOGLE_BASE64_RE.search(u):
            continue
        try:
            req = urllib.request.Request(u, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                if r.status >= 400:
                    rep.add(ERR, "E4", f"链接 HTTP {r.status}", it.get("site_name", ""), u)
        except Exception as e:
            rep.add(WARN, "E4", f"链接探测失败: {type(e).__name__}", it.get("site_name", ""), u)


def main():
    ap = argparse.ArgumentParser(description="green-hot-news 数据质量检查（只报告不修复）")
    ap.add_argument("--check-links", action="store_true", help="额外 HEAD 探测链接有效性（慢，默认关）")
    ap.add_argument("--data", default=str(DATA), help="数据目录（默认 data/）")
    args = ap.parse_args()

    data_dir = Path(args.data)
    now = datetime.now(timezone.utc)

    latest = json.loads((data_dir / "latest-24h.json").read_text(encoding="utf-8"))
    items = latest if isinstance(latest, list) else latest.get("items", latest.get("news", []))
    try:
        source_status = json.loads((data_dir / "source-status.json").read_text(encoding="utf-8"))
    except Exception:
        source_status = {"sites": []}

    report, rep = build_report(items, now, source_status)
    if args.check_links:
        check_links(items, rep)
        report["totals"]["error"] = sum(1 for i in rep.issues if i["level"] == ERR)
        report["totals"]["warn"] = sum(1 for i in rep.issues if i["level"] == WARN)
        report["totals"]["info"] = sum(1 for i in rep.issues if i["level"] == INFO)

    (data_dir / "qa-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    write_md(report, rep, data_dir / "qa-report.md")
    print(f"QA done: score={report['score']} ({report['score_level']}) "
          f"err={report['totals']['error']} warn={report['totals']['warn']} info={report['totals']['info']} "
          f"items={report['totals']['items']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
