#!/usr/bin/env python3
"""_probe_title_audit.py — 全量审计素材 H1 与文件名不一致 / 疑似坏标题（v2 精化）。

三类：
  POLLUTED  : H1 与文件名共享内容极少（<50%），或 H1 是站名/栏目/导航 —— 严重污染，需修复
  SUFFIX    : H1 = 文件名 + 站点后缀（"-上海环境能源交易所" 等）—— 次等瑕疵，可剥离
  ENHANCED  : 文件名截断（...结尾），H1 是详情页完整标题 —— 正常增强逻辑，保留
"""
import os, re, json, glob, sys, difflib

BAD_PATTERNS = [
    r"公共服务网", r"门户网站", r"欢迎访问", r"欢迎来到", r"^首页",
    r"^#?\s*[^-—–|｜_]{2,25}[网中心部局署厅院站][^-—–|｜_]{0,8}[-—–|｜_]\s*(首页|官网|门户|简介|关于我们|新闻|资讯|动态|要闻|工作动态|最新公告|通知公告|政务公开|政策文件|信息公开|行业动态|节能研究)\s*$",
]

def norm(s):
    return re.sub(r"[\s\-—–|｜_【】\[\]（）()《》〈〉<>「」『』\"'“”‘’.,，。:：;；!！?？、…]", "", s)

def sim(a, b):
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()

def classify(fname, h1):
    # 坏标题模式直接判污染
    for p in BAD_PATTERNS:
        if re.search(p, h1):
            return "POLLUTED"
    r = sim(fname, h1)
    if r >= 0.9:
        # 高相似：再看是否有可剥离后缀（文件名是 H1 前缀）
        if h1.startswith(fname) and len(h1) > len(fname):
            return "SUFFIX"
        return "OK"
    if r >= 0.5:
        return "ENHANCED"  # 文件名截断/标点差异，H1 更完整
    return "POLLUTED"

def scan_notes(root="Notes"):
    counts = {"OK": 0, "ENHANCED": 0, "SUFFIX": 0, "POLLUTED": 0}
    out = {"POLLUTED": [], "SUFFIX": [], "ENHANCED": []}
    total = 0
    for sub in ("政策库", "媒体库"):
        for dirpath, _dirs, files in os.walk(os.path.join(root, sub)):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                fp = os.path.join(dirpath, fn)
                base = os.path.basename(fp)[:-3]
                if base.startswith(("ai-index", "政策库", "媒体库")):
                    continue
                total += 1
                try:
                    with open(fp, encoding="utf-8", errors="replace") as f:
                        head = f.read(2500)
                except Exception:
                    continue
                m_h1 = re.search(r"^# (.+)$", head, re.M)
                if not m_h1:
                    continue
                h1 = m_h1.group(1).strip()
                fname = re.sub(r"^\d{4}-\d{2}-\d{2} ", "", base)
                cat = classify(fname, h1)
                counts[cat] += 1
                if cat in out:
                    out[cat].append((fp, fname, h1))
    print(f"[Notes] total={total} OK={counts['OK']} ENHANCED={counts['ENHANCED']} "
          f"SUFFIX={counts['SUFFIX']} POLLUTED={counts['POLLUTED']}")
    return out

def scan_data():
    hits = []
    for f in sorted(glob.glob("data/*.json")):
        if f.endswith(("title-index.json", "summary-index.json", "published-index.json",
                       "translation-cache.json", "source-status.json", "daily-digest.md")):
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        items = d if isinstance(d, list) else d.get("items", [])
        for it in items:
            t = str(it.get("title", ""))
            sname = str(it.get("site_name", ""))
            if not t:
                continue
            if t == sname or (sname and t.startswith(sname)):
                hits.append((f, it.get("site_id", ""), t, str(it.get("url", "")), "title==sitename"))
            elif re.search(r"公共服务网|门户网站|欢迎访问|欢迎来到", t):
                hits.append((f, it.get("site_id", ""), t, str(it.get("url", "")), "nav-pattern"))
    print(f"[data] suspicious={len(hits)}")
    return hits

if __name__ == "__main__":
    notes_out = scan_notes(sys.argv[1] if len(args := sys.argv) > 1 else "Notes")
    data_out = scan_data()
    print("\n===== POLLUTED（严重污染，需修复）=====")
    for fp, fname, h1 in notes_out["POLLUTED"]:
        print(f"  {fp}\n    fname={fname!r}\n    H1   ={h1!r}")
    print("\n===== SUFFIX（可剥离后缀）=====")
    for fp, fname, h1 in notes_out["SUFFIX"]:
        print(f"  {fp}\n    fname={fname!r}\n    H1   ={h1!r}")
    print("\n===== ENHANCED 样例（前10）=====")
    for fp, fname, h1 in notes_out["ENHANCED"][:10]:
        print(f"  {fp}\n    fname={fname!r}\n    H1   ={h1!r}")
    print("\n===== DATA suspicious =====")
    for row in data_out:
        print(" ", row)
