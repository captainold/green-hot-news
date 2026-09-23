#!/usr/bin/env python3
"""_fix_polluted_titles.py v3 — 修复「站名/导航标题」污染（2026-08-19 全量）。

背景：Google News 把 EIA/DOE/NOAA/EPA/FERC 等美国部委站的站内导航/工具/栏目页
当文章收录（列表标题自带 " - 站点名 (.gov)" 后缀），且详情页 <title> 覆盖逻辑
（旧版无相似度门槛）把写死的站名覆盖到列表标题上。

动作：
  A. data/*.json（主页数据源，strict）：剥离 " - 站点名 (.gov)" 后缀；
     剥离后为空/导航页/科普静态页/栏目页 → 删除条目；mee 跳转提示 → 正确标题。
  B. Notes 素材（Obsidian 库，宽松）：同上剥离后缀 + 改名（无双链引用，安全）；
     仅明确导航/工具页 → 删除；科普/政策/报告页 → 保留改名。
"""
import os, re, json, sys

# ── 后缀剥离（循环） ────────────────────────────────────────────────
SUFFIX_RES = [
    r"\s*[-—–|｜_]\s*U\.S\. Energy Information Administration(?: \(EIA\))?(?: \(\.gov\))?\s*$",
    r"\s*[-—–|｜_]\s*U\.S\. Environmental Protection Agency(?: \(\.gov\))?\s*$",
    r"\s*[-—–|｜_]\s*Environmental Protection Agency(?: \(\.gov\))?\s*$",
    r"\s*[-—–|｜_]\s*Federal Energy Regulatory Commission(?: \(\.gov\))?\s*$",
    r"\s*[-—–|｜_]\s*Department of Energy(?: \(\.gov\))?\s*$",
    r"\s*[-—–|｜_]\s*California Air Resources Board(?: \(\.gov\))?\s*$",
    r"\s*[-—–|｜_]\s*NOAA Office for Coastal Management(?: \(\.gov\))?\s*$",
    r"\s*[-—–|｜_]\s*NOAA Tides and Currents(?: \(\.gov\))?\s*$",
    r"\s*[-—–|｜_]\s*NOAA(?: \(\.gov\))?\s*$",
    r"\s*[-—–|｜_]\s*NOAA\s+(?:National\w*|Office\w*|Tides\w*)[\w\s']*?(?:\([A-Z]+\))?\s*(?:\(\.gov\))?\s*\.{0,3}$",
    r"\s*[-—–|｜_]\s*National Hurricane Center\s*$",
    r"\s*[-—–|｜_]\s*NHC(?: \(\.gov\))?\s*$",
    r"\s*[-—–|｜_]\s*Climate Prediction Center\s*$",
    r"\s*[-—–|｜_]\s*EPA\s*$",
    r"\s*[-—–|｜_]\s*Southwestern Power Administration\s*$",
    r"\s*[-—–|｜_]\s*taiyangnews\.info\s*$",
    r"\s*-\s*上海环境能源交易所\s*$",
    r"\s*[-—–|｜_]\s*(News|Press|Releases?|Updates?|Staff|Report|Blog|Daily|Weekly|Monthly|Media)\s*$",
]
_SUFFIX_COMPILED = [re.compile(p) for p in SUFFIX_RES]

def strip_site_suffix(t: str) -> str:
    t = (t or "").strip()
    changed = True
    while changed and t:
        changed = False
        for rx in _SUFFIX_COMPILED:
            nt = rx.sub("", t).strip()
            if nt != t:
                t, changed = nt, True
                break
    return t

# ── 导航/工具/栏目垃圾（两个层都删） ────────────────────────────────
NAV_JUNK_EXACT = {
    "contact us", "about", "about us", "glossary", "opendata", "databases", "dashboard",
    "webinars", "tide predictions", "daily weather map", "data in the classroom", "education",
    "maps and data", "energy explained", "faqs", "learn more about energy sources",
    "map a career in energy", "renewable energy maps and tools", "data access viewer",
    "sea level analysis tool", "archived directives library", "women in energy",
    "from our blogs", "grid talk", "innovation", "energy workforce", "find careers in cmei",
    "find financing for energy-efficiency upgrades", "credit subsidy", "technical project officer",
    "collegiate wind competition 2023 judges", "international science & technology collaboration",
    "state energy advisory board", "shara mohtadi", "veronica jackson", "deploy 2024",
    "energy improvements in rural or remote areas", "getting to know lpo", "loan program office",
    "aes marahu", "critical minerals and materials", "short-term energy outlook",
    "weekly petroleum status report", "gasoline and diesel fuel update", "steo data browser",
    "hourly electric grid monitor", "real-time operating grid", "new england dashboard",
    "united states", "southwestern power administration", "national weather service marine forecast",
    "electric matters", "electric matters - m", "statements and speeches", "multi-state regions",
    "air quality system (aqs)", "public water system service areas", "clean school bus program",
    "does eia project energy production, consumption, or prices for individual states",
    "what can i expect to pay for heating this winter",
    "u.s. energy information administration", "california air resources board",
    "federal energy regulatory commission", "national hurricane center",
    "national hurricane center and central pacific hurricane center",
    "snow station information", "climate prediction center", "documentation",
    "what types of cmei funding exist", "transmission facility financing",
    "regional clean hydrogen hubs", "quarterly solar industry update",
    "u.s. energy & employment report", "marine energy basics", "cybersecurity",
    "solar workforce development", "critical minerals and materials",
}
NAV_JUNK_RES = [
    re.compile(r"^station\s+[\w\s\-,#'()]+$", re.I),      # 海洋/气象观测站数据页
    re.compile(r"^national weather service marine forecast", re.I),
    re.compile(r"^tropical storm \w+ forecast discussion", re.I),  # 飓风例行预报
    re.compile(r"^(climate prediction center|enso).*", re.I),
    re.compile(r"^latest commit", re.I),
    re.compile(r"^snow station information", re.I),
    re.compile(r"^u\.s\. energy information administration", re.I),   # 站名页（含截断版）
    re.compile(r"^southwestern power administration", re.I),
    re.compile(r"^(does eia project|what can i expect|what is general conformity)", re.I),  # FAQ
]

# ── 静态科普/政策/报告页（data 层删；Notes 层保留改名） ─────────────
CONTENT_PAGES_EXACT = {
    "3 reasons why nuclear is clean and sustainable", "5 fast facts about nuclear energy",
    "solar photovoltaic technology basics", "types of hydropower plants",
    "how distributed wind works", "hydrogen production_ electrolysis",
    "solar cybersecurity", "end-of-life management for solar photovoltaics",
    "solar rooftop potential", "solar workforce development",
    "updates to the section 1703 loan guarantee program", "30d new clean vehicle credit",
    "nepa schedule for pending infrastructure projects",
    "notice regarding dispute resolution procedures",
    "ferc issues notice for dispute resolution services proceedings for pjm governance",
    "july_august 2026 highlights", "public notice: final permit decision to issue a permit under the clean air act",
    "epa - office of agriculture and rural affairs", "weather and climate indicators",
    "clean trucks plan", "ethylene oxide", "u.s. energy & employment report",
    "climate prediction center: enso diagnostic discussion",
    "data in the classroom", "sea level analysis tool",
}

def is_nav_junk(t: str) -> bool:
    tl = t.strip().lower()
    if not tl or len(tl) < 4:
        return True
    if tl in NAV_JUNK_EXACT:
        return True
    for rx in NAV_JUNK_RES:
        if rx.search(tl):
            return True
    if len(tl) <= 3 or tl in {"u.s.", "eia", "noaa", "epa", "doe", "ferc", "nhc", "mee", "pib"}:
        return True
    return False

def is_static_content(t: str) -> bool:
    tl = t.strip().lower()
    return tl in {x.lower() for x in CONTENT_PAGES_EXACT}

# ── A. data JSON 修复（strict） ─────────────────────────────────────
def fix_data():
    total_fixed, total_deleted = 0, 0
    for f in ("data/history.json", "data/latest-24h.json", "data/latest-24h-all.json"):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception as e:
            print(f"  [skip] {f}: {e}")
            continue
        items = d if isinstance(d, list) else d.get("items", [])
        changed = False
        f_fixed, f_deleted = 0, 0
        for it in items:
            t = str(it.get("title", ""))
            if "您访问的链接即将离开" in t:
                it["title"] = "生态环境部发布8月下半月全国空气质量预报会商结果"
                changed, f_fixed = True, f_fixed + 1
                continue
            stripped = strip_site_suffix(t)
            if stripped == t:
                # 无后缀但标题本身就是站名/导航页（如 "Southwestern Power Administration"、
                # 截断的 "U.S. Energy Information Administration - EIA - Independent..."）
                if is_nav_junk(t):
                    it["_drop"] = True
                    changed, f_deleted = True, f_deleted + 1
                continue
            if is_nav_junk(stripped) or is_static_content(stripped):
                it["_drop"] = True
                changed, f_deleted = True, f_deleted + 1
            else:
                it["title"] = stripped
                changed, f_fixed = True, f_fixed + 1
        if changed:
            items = [i for i in items if not i.get("_drop")]
            for i in items:
                i.pop("_drop", None)
            if isinstance(d, list):
                d = items
            else:
                d["items"] = items
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False, indent=2)
            print(f"  [data] {f}: 修 {f_fixed} / 删 {f_deleted}")
        total_fixed += f_fixed
        total_deleted += f_deleted
    print(f"[data] 合计修 {total_fixed} 条，删 {total_deleted} 条")

# ── B. Notes 素材修复（宽松） ───────────────────────────────────────
def fix_notes(root="Notes"):
    fixed, deleted, renamed = 0, 0, 0
    for sub in ("政策库", "媒体库"):
        for dirpath, _d, files in os.walk(os.path.join(root, sub)):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                fp = os.path.join(dirpath, fn)
                base = os.path.basename(fp)[:-3]
                if base.startswith(("ai-index", "政策库", "媒体库")):
                    continue
                name_no_date = re.sub(r"^\d{4}-\d{2}-\d{2} ", "", base)
                stripped = strip_site_suffix(name_no_date)
                if stripped != name_no_date or is_nav_junk(name_no_date):
                    if is_nav_junk(stripped):
                        os.remove(fp)
                        print(f"  DEL {fp}")
                        deleted += 1
                        continue
                if stripped != name_no_date:
                    date_pre = base[:len(base) - len(name_no_date)]
                    new_base = (date_pre + stripped).strip()
                    new_base = re.sub(r'[<>:"/\\|?*]', "_", new_base)
                    if not new_base or new_base == base:
                        continue
                    new_fp = os.path.join(dirpath, new_base + ".md")
                    if os.path.exists(new_fp):
                        print(f"  SKIP-EXIST {new_fp}")
                        continue
                    os.rename(fp, new_fp)
                    fp = new_fp
                    renamed += 1
                    try:
                        c = open(fp, encoding="utf-8").read()
                    except Exception:
                        continue
                    m_h1 = re.search(r"^# .+$", c, re.M)
                    if m_h1:
                        new_h1 = (date_pre + stripped).strip()
                        c = c[:m_h1.start()] + f"# {new_h1}" + c[m_h1.end():]
                        open(fp, "w", encoding="utf-8").write(c)
                    print(f"  REN {fp}")
    print(f"[notes] 改名 {renamed}，删除 {deleted}")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("data", "all"):
        fix_data()
    if mode in ("notes", "all"):
        fix_notes()
