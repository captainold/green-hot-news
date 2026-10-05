#!/usr/bin/env python3.11
"""P0.5 标尺标定工具：gold set 抽样 → 标注工作台 → 导入 → 三个判定器对 gold set 打分。

为什么需要（2026-09-23 P0 结论）：
    P0 实测发现关键词 / DeepSeek-Pro / Jev 三个判定器在同一批语料上给出三种塌陷分布
    （关键词 62.3% 落兜底、Pro 87% 落最低两档、Jev 97% 落最高两档），彼此一致率 10~13%。
    **在没有人工 gold set 之前，任何"一致率"都是两把未标定尺子之差，不是准确率。**
    所以先用人工标注 84 条（七细类各 12 条）当基准，再让三个判定器各自对它打分。

子命令：
    sample      七细类均衡抽样，写入 data/gold-set.jsonl（已有标注不覆盖）
    workbench   生成自包含标注工作台 HTML（拷到任何浏览器打开，不联网、不需要服务器）
    import      把工作台导出的 JSON 合并回 data/gold-set.jsonl
    evaluate    对已标注条目评估 关键词 / Jev（A|B|C 问法）/ Pro，输出准确率+混淆矩阵+序相关
    status      当前标注进度

用法：
    python3.11 scripts/gold_set.py sample --per-sub 12 --seed 7
    python3.11 scripts/gold_set.py workbench
    python3.11 scripts/gold_set.py import --file ~/Downloads/gold-set-labels.json
    python3.11 scripts/gold_set.py evaluate --judges kw,jev --form C
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

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

import jev_client as jc          # noqa: E402
import sample_snapshot as snap    # noqa: E402

GOLD_PATH = ROOT / "data" / "gold-set.jsonl"
EVAL_PATH = ROOT / "data" / "gold-set-eval.json"
WORKBENCH_HTML = ROOT / "docs" / "todo" / "gold-set-workbench.html"

LEVEL_NAME = {3: "里程碑级(30)", 2: "重要级(25)", 1: "进展级(20)", 0: "常规级(兜底)"}
LEVEL_ORDER = [3, 2, 1, 0]
SUB_ORDER = list(jc.SUB_CRITERIA.keys())          # 政策法规/国际动态/技术研发/基础研究/社会创新/企业经营/金融资本


# ────────────────────────────── 公共读写 ──────────────────────────────

def load_gold() -> list[dict]:
    if not GOLD_PATH.exists():
        return []
    rows = []
    for line in GOLD_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def save_gold(rows: list[dict]) -> None:
    GOLD_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLD_PATH.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


_HIST_META_CACHE: dict | None = None


def history_meta() -> dict:
    """url → (site_id, library)，按 url 从 history.json 反查（缓存一次）。

    ⚠️ 为什么需要：gold-set.jsonl 只存 source 名，**没有 site_id/library**；
    而 `categorize_dimension` 的判定依赖两者（外源政府 policy → 国际动态、
    library=policy 默认政策法规）。缺了它们会让 kw 轨基线失真——2026-09-30
    实测：细类命中 45.2%（缺 library）vs **53.0%（补 library）**，
    足以颠倒 P3 切换的结论，故必须反查。
    """
    global _HIST_META_CACHE
    if _HIST_META_CACHE is None:
        meta: dict[str, tuple[str, str]] = {}
        by_src: dict[str, tuple[str, str]] = {}
        try:
            items = json.loads((ROOT / "data" / "history.json").read_text(encoding="utf-8")).get("items", [])
        except Exception:
            items = []
        for it in items:
            pair = (it.get("site_id", ""), it.get("library", "media"))
            if it.get("url"):
                meta[it["url"]] = pair
            if it.get("site_name"):
                by_src.setdefault(it["site_name"], pair)
        _HIST_META_CACHE = {"by_url": meta, "by_src": by_src}
    return _HIST_META_CACHE


def live_sub(row: dict) -> str:
    """用**当前**分类代码 + 真实 site_id/library 重算细类（kw 轨基线用）。"""
    m = history_meta()
    sid, lib = m["by_url"].get(row.get("url") or "", ("", ""))
    if not sid:
        sid, lib = m["by_src"].get(row.get("source", ""), ("", "media"))
    return un.categorize_dimension(sid, row.get("title", ""), row.get("summary", ""), lib)[1]


def kw_strength(row: dict, sub: str | None = None) -> int:
    """kw 轨强度：默认用**实况细类**（而非抽样时冻结的 sub_kw）套当前词表。"""
    return un.score_content_strength(sub if sub is not None else live_sub(row),
                                     row.get("title", ""), row.get("summary", ""))


def level_of_score(score: int | None) -> int | None:
    if score is None:
        return None
    return {30: 3, 25: 2, 20: 1}.get(score, 0)


# ────────────────────────────── sample ──────────────────────────────

def cmd_sample(args: argparse.Namespace) -> int:
    old = {r["id"]: r for r in load_gold()}
    d = json.load(open(ROOT / "data" / "history.json", encoding="utf-8"))
    items = [i for i in d.get("items", []) if isinstance(i, dict)
             and i.get("sub_dimension") and (i.get("title") or "").strip()]
    by_sub: dict[str, list[dict]] = {}
    for it in items:
        by_sub.setdefault(it["sub_dimension"], []).append(it)

    random.seed(args.seed)
    picked: list[dict] = []
    for sub in SUB_ORDER:
        pool = [i for i in by_sub.get(sub, []) if i["id"] not in old]
        random.shuffle(pool)
        picked.extend(pool[:args.per_sub])
    if len(picked) < args.per_sub * len(SUB_ORDER):        # 某细类不足则用其他细类补
        rest = [i for i in items if i["id"] not in old and i not in picked]
        random.shuffle(rest)
        picked.extend(rest[:args.per_sub * len(SUB_ORDER) - len(picked)])

    rows = []
    for it in picked:
        sub = it["sub_dimension"]
        rows.append({
            "id": it["id"],
            "title": it.get("title") or "",
            "title_zh": it.get("title_zh") or "",
            "summary": (it.get("summary") or "")[:400],
            "url": it.get("url") or "",
            "source": it.get("source") or it.get("site_name") or "",
            "published_at": it.get("published_at") or "",
            "dimension": it.get("dimension") or "",
            "region": it.get("region") or "",
            "sub_kw": sub,
            "score_kw": it.get("score"),
            "strength_kw": None,           # 抽样时不算，避免提前把答案写在候选里
            "label_strength": None,        # ← 人工标注：3/2/1/0
            "label_sub": None,             # ← 人工标注：七细类之一
            "label_note": "",
            "labeled_at": None,
        })
    merged = list(old.values()) + rows
    save_gold(merged)
    snapshot = snap.save(f"gold-set-n{len(rows)}-seed{args.seed}", picked, corpus=items,
                         extra={"per_sub": args.per_sub, "seed": args.seed})
    print(f"gold set 候选：新增 {len(rows)} 条，累计 {len(merged)} 条 → {GOLD_PATH.relative_to(ROOT)}")
    print(f"抽样快照：{snapshot.name}（语料 {snap.corpus_fingerprint(items)}）")
    for sub in SUB_ORDER:
        n_new = sum(1 for r in rows if r["sub_kw"] == sub)
        n_all = sum(1 for r in merged if r["sub_kw"] == sub)
        print(f"  {sub}：新增 {n_new:>2}｜累计 {n_all:>2}")
    print("\n下一步：python3.11 scripts/gold_set.py workbench")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    rows = load_gold()
    if not rows:
        print("还没有 gold set，先跑 sample")
        return 1
    lab_s = [r for r in rows if r.get("label_strength") is not None]
    lab_b = [r for r in rows if r.get("label_strength") is not None and r.get("label_sub")]
    print(f"gold set 共 {len(rows)} 条｜已标强度 {len(lab_s)}｜强度+细类都标 {len(lab_b)}")
    for sub in SUB_ORDER:
        tot = sum(1 for r in rows if r["sub_kw"] == sub)
        done = sum(1 for r in rows if r["sub_kw"] == sub and r.get("label_strength") is not None)
        print(f"  {sub}：{done}/{tot}")
    if lab_s:
        from collections import Counter
        print("标注档位分布：", dict(sorted(Counter(r["label_strength"] for r in lab_s).items(),
                                          reverse=True)))
    return 0


# ────────────────────────────── workbench ──────────────────────────────

def cmd_workbench(args: argparse.Namespace) -> int:
    rows = load_gold()
    if not rows:
        print("还没有 gold set，先跑 sample")
        return 1
    data = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sub_order": SUB_ORDER,
        "level_name": {str(k): v for k, v in LEVEL_NAME.items()},
        "level_order": LEVEL_ORDER,
        "items": rows,
    }
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = _WORKBENCH_TEMPLATE.replace("__DATA__", payload)
    WORKBENCH_HTML.write_text(html, encoding="utf-8")
    print(f"标注工作台已生成：{WORKBENCH_HTML}")
    print("用浏览器打开（file:// 即可，不需要服务器）；标完点『导出 JSON』，"
          "再用 gold_set.py import --file <导出的文件> 合并。")
    return 0


_WORKBENCH_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>gold set 标注工作台 · 绿色低碳雷达</title>
<style>
  :root{--bg:#12161c;--card:#1b2129;--line:#2b333d;--fg:#e8edf3;--dim:#8b98a8;
        --ok:#3fb950;--warn:#d29922;--accent:#58a6ff;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font:15px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
  .wrap{max-width:920px;margin:0 auto;padding:22px 20px 60px}
  header{position:sticky;top:0;background:var(--bg);padding:10px 0 12px;z-index:5;
         border-bottom:1px solid var(--line)}
  h1{font-size:17px;margin:0 0 8px;font-weight:600}
  .bar{height:7px;background:#242c36;border-radius:4px;overflow:hidden}
  .bar > i{display:block;height:100%;background:var(--ok);width:0}
  .meta{display:flex;justify-content:space-between;color:var(--dim);font-size:13px;margin-top:6px}
  .buttons{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
  button{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:7px;
         padding:7px 12px;font-size:13px;cursor:pointer}
  button:hover{border-color:var(--accent)}
  button.primary{background:#1f6feb;border-color:#1f6feb}
  .card{background:var(--card);border:1px solid var(--line);border-radius:11px;padding:18px 20px;
        margin-top:18px}
  .tags{color:var(--dim);font-size:13px;display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px}
  .title{font-size:19px;font-weight:600;line-height:1.45;margin:2px 0 10px}
  .sum{color:#c3ccd8;font-size:14px;white-space:pre-wrap}
  details{margin-top:12px;color:var(--dim);font-size:13px}
  summary{cursor:pointer}
  .q{margin-top:16px}
  .q h2{font-size:14px;color:var(--dim);font-weight:600;margin:0 0 8px;letter-spacing:.02em}
  .opts{display:flex;gap:8px;flex-wrap:wrap}
  .opt{position:relative}
  .opt kbd{position:absolute;top:-7px;right:-5px;background:#0d1117;border:1px solid var(--line);
           border-radius:4px;font-size:11px;padding:0 5px;color:var(--dim)}
  .opt.on{border-color:var(--ok);box-shadow:inset 0 0 0 1px var(--ok)}
  input[type=text]{width:100%;margin-top:14px;background:#0d1117;border:1px solid var(--line);
        border-radius:7px;color:var(--fg);padding:8px 10px;font-size:14px}
  .strip{display:flex;flex-wrap:wrap;gap:4px;margin-top:18px}
  .cell{width:16px;height:16px;border-radius:3px;background:#242c36;cursor:pointer;
        border:1px solid transparent}
  .cell.done{background:var(--ok)}
  .cell.cur{border-color:var(--accent)}
  .hint{color:var(--dim);font-size:12.5px;margin-top:14px}
  .flash{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:#1f6feb;
         padding:8px 14px;border-radius:8px;font-size:13px;opacity:0;transition:opacity .18s}
  .flash.on{opacity:1}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>gold set 标注工作台 · 内容强度 + 七细类</h1>
    <div class="bar"><i id="pbar"></i></div>
    <div class="meta"><span id="pnum">0 / 0</span><span id="pidx"></span></div>
    <div class="buttons">
      <button onclick="jumpUnlabeled()">跳到未标注</button>
      <button onclick="exportJSON()" class="primary">导出 JSON</button>
      <button onclick="exportMD()">导出 Markdown</button>
      <button onclick="clearLocal()">清空本机进度</button>
    </div>
  </header>

  <div class="card">
    <div class="tags"><span id="t_sub"></span><span id="t_src"></span><span id="t_time"></span>
      <span id="t_region"></span></div>
    <div class="title" id="t_title"></div>
    <div class="sum" id="t_sum"></div>
    <details><summary>看关键词判定现值（建议先盲标，再对照）</summary>
      <div style="margin-top:6px">关键词细类：<b id="k_sub"></b>｜关键词内容强度分：<b id="k_score"></b>
        <span id="k_str"></span></div>
    </details>

    <div class="q">
      <h2>① 内容强度档位（这事件本身的分量，不看来源）</h2>
      <div class="opts" id="opts_level"></div>
    </div>
    <div class="q">
      <h2>② 七细类（这条内容属于哪一类）</h2>
      <div class="opts" id="opts_sub"></div>
    </div>
    <input type="text" id="note" placeholder="备注（可选）：为什么这么判 / 边界情况说明">
    <div class="strip" id="strip"></div>
    <div class="hint">热键：<b>3 2 1 0</b> 选档位｜<b>1~7</b> 选细类｜<b>← →</b> 翻页｜<b>N</b> 跳到未标注。
      标注自动存在浏览器本地，随时可关。</div>
  </div>
</div>
<div class="flash" id="flash"></div>

<script>
const DATA = __DATA__;
const LS_KEY = 'ghn-gold-labels-v1';
let labels = {};                                  // id -> {strength, sub, note, at}
try { labels = JSON.parse(localStorage.getItem(LS_KEY) || '{}') || {}; } catch(e) { labels = {}; }
DATA.items.forEach(it => {                        // 服务端已有标注优先
  if (it.label_strength !== null && it.label_strength !== undefined) {
    labels[it.id] = {strength: it.label_strength, sub: it.label_sub || '',
                     note: it.label_note || '', at: it.labeled_at || ''};
  } else if (!labels[it.id]) {
    labels[it.id] = {strength: null, sub: '', note: '', at: ''};
  }
});
let cur = 0;
const $ = id => document.getElementById(id);

function lvlKeys(){ return DATA.level_order; }              // [3,2,1,0]
function subKeys(){ return DATA.sub_order; }                // 7 类

function render(){
  const it = DATA.items[cur], L = labels[it.id] || {strength:null, sub:'', note:''};
  $('t_sub').textContent = it.dimension + ' · ' + it.sub_kw;
  $('t_src').textContent = it.source;
  $('t_time').textContent = (it.published_at || '').slice(0,10);
  $('t_region').textContent = it.region;
  $('t_title').textContent = it.title_zh || it.title;
  $('t_sum').textContent = it.summary || '（无摘要）';
  $('k_sub').textContent = it.sub_kw;
  $('k_score').textContent = it.score_kw;
  $('note').value = L.note || '';

  const ol = $('opts_level'); ol.innerHTML = '';
  lvlKeys().forEach((lv, i) => {
    const b = document.createElement('button');
    b.className = 'opt' + (L.strength === lv ? ' on' : '');
    b.innerHTML = DATA.level_name[String(lv)] + '<kbd>' + lv + '</kbd>';
    b.onclick = () => setLevel(lv);
    ol.appendChild(b);
  });
  const os = $('opts_sub'); os.innerHTML = '';
  subKeys().forEach((s, i) => {
    const b = document.createElement('button');
    b.className = 'opt' + (L.sub === s ? ' on' : '');
    b.innerHTML = s + '<kbd>' + (i+1) + '</kbd>';
    b.onclick = () => setSub(s);
    os.appendChild(b);
  });

  const strip = $('strip'); strip.innerHTML = '';
  DATA.items.forEach((x, i) => {
    const d = document.createElement('div');
    const done = labels[x.id] && labels[x.id].strength !== null;
    d.className = 'cell' + (done ? ' done' : '') + (i === cur ? ' cur' : '');
    d.title = x.title;
    d.onclick = () => { cur = i; render(); };
    strip.appendChild(d);
  });

  const done = DATA.items.filter(x => labels[x.id] && labels[x.id].strength !== null).length;
  $('pbar').style.width = (100 * done / DATA.items.length) + '%';
  $('pnum').textContent = done + ' / ' + DATA.items.length + ' 已标强度';
  $('pidx').textContent = '第 ' + (cur+1) + ' 条';
}

function persist(){ localStorage.setItem(LS_KEY, JSON.stringify(labels)); }

function setLevel(lv){
  const id = DATA.items[cur].id;
  labels[id] = Object.assign({}, labels[id], {strength: lv, at: new Date().toISOString()});
  persist(); render(); next();
}
function setSub(s){
  const id = DATA.items[cur].id;
  labels[id] = Object.assign({}, labels[id], {sub: s, at: new Date().toISOString()});
  persist(); render(); flash('细类：' + s);
}
function next(){ if (cur < DATA.items.length - 1) { cur++; render(); } }
function prev(){ if (cur > 0) { cur--; render(); } }
function jumpUnlabeled(){
  const i = DATA.items.findIndex(x => !labels[x.id] || labels[x.id].strength === null);
  if (i >= 0) { cur = i; render(); } else { flash('全部标完了 🎉'); }
}
function flash(msg){
  const f = $('flash'); f.textContent = msg; f.classList.add('on');
  setTimeout(() => f.classList.remove('on'), 900);
}
function clearLocal(){
  if (!confirm('清空浏览器里的标注进度？（服务端已导入的标注不受影响，但本机未导出的会丢）')) return;
  localStorage.removeItem(LS_KEY); location.reload();
}
$('note').addEventListener('change', () => {
  const id = DATA.items[cur].id;
  labels[id] = Object.assign({}, labels[id], {note: $('note').value});
  persist(); flash('备注已存');
});
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
  const k = e.key;
  if (k === 'ArrowRight') { next(); return; }
  if (k === 'ArrowLeft') { prev(); return; }
  if (k === 'n' || k === 'N') { jumpUnlabeled(); return; }
  if ('3210'.includes(k) && k.length === 1) { setLevel(parseInt(k, 10)); return; }
  const n = parseInt(k, 10);
  if (n >= 1 && n <= 7) { setSub(subKeys()[n-1]); return; }
});

function download(name, text, type){
  const blob = new Blob([text], {type: type || 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a'); a.href = url; a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}
function exportJSON(){
  const done = DATA.items.filter(x => labels[x.id] && labels[x.id].strength !== null);
  const payload = {version: 1, exported_at: new Date().toISOString(),
                   total: DATA.items.length, labeled: done.length, labels: {}};
  DATA.items.forEach(x => {
    const L = labels[x.id];
    if (L && L.strength !== null) payload.labels[x.id] = {strength: L.strength, sub: L.sub || '',
                                                          note: L.note || ''};
  });
  download('gold-set-labels.json', JSON.stringify(payload, null, 1));
  flash('已导出 ' + done.length + ' 条到 gold-set-labels.json');
}
function exportMD(){
  let md = '| id | 强度 | 细类 | 标题 | 备注 |\n|---|---|---|---|---|\n';
  DATA.items.forEach(x => {
    const L = labels[x.id] || {};
    if (L.strength === null || L.strength === undefined) return;
    md += '| ' + x.id.slice(0,8) + ' | ' + L.strength + ' | ' + (L.sub||'') + ' | ' +
          (x.title_zh || x.title).replace(/\|/g,'/') + ' | ' + (L.note||'').replace(/\|/g,'/') + ' |\n';
  });
  download('gold-set-labels.md', md, 'text/markdown');
}
render();
</script>
</body>
</html>
"""


def cmd_import(args: argparse.Namespace) -> int:
    src = Path(args.file).expanduser()
    raw = json.loads(src.read_text(encoding="utf-8"))
    labels = raw.get("labels", raw) if isinstance(raw, dict) else raw
    rows = load_gold()
    by_id = {r["id"]: r for r in rows}
    n = 0
    for iid, lab in labels.items():
        if iid not in by_id or not isinstance(lab, dict):
            continue
        if lab.get("strength") is None:
            continue
        r = by_id[iid]
        r["label_strength"] = int(lab["strength"])
        r["label_sub"] = lab.get("sub") or r.get("label_sub")
        r["label_note"] = lab.get("note") or r.get("label_note") or ""
        r["labeled_at"] = datetime.now(timezone.utc).isoformat()
        n += 1
    save_gold(rows)
    done = sum(1 for r in rows if r.get("label_strength") is not None)
    print(f"已从 {src.name} 合并 {n} 条标注｜gold set 共 {len(rows)} 条，已标 {done} 条")
    return 0


# ────────────────────────────── evaluate ──────────────────────────────

def _spearman(xs: list[int], ys: list[int]) -> float | None:
    if len(xs) < 3:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return round(num / (dx * dy), 3) if dx and dy else None


def _confusion(pairs: list[tuple], labels: list) -> dict:
    m = {str(a): {str(b): 0 for b in labels} for a in labels}
    for g, p in pairs:
        if str(g) in m and str(p) in m[str(g)]:
            m[str(g)][str(p)] += 1
    return m


def cmd_evaluate(args: argparse.Namespace) -> int:
    rows = [r for r in load_gold() if r.get("label_strength") is not None]
    if not rows:
        print("还没有标注（label_strength），先用 workbench 标注再 import")
        return 1
    # 细类缺失的条目：只进强度评估、不进细类评估（并提示，不静默丢）
    no_sub = [r["id"][:8] for r in rows if not r.get("label_sub")]
    if no_sub:
        print(f"ℹ️ {len(no_sub)} 条缺细类标注（{', '.join(no_sub)}）→ 只计入强度，不计入细类命中率")
    rows_sub = [r for r in rows if r.get("label_sub")]
    judges = [j.strip() for j in args.judges.split(",") if j.strip()]
    use_jev = "jev" in judges
    if use_jev and not jc.is_enabled():
        print("⚠️  Jev 不可用（缺 JEV_API_KEY 或已熔断）→ 跳过 jev 轨")
        use_jev = False
    use_pro = "pro" in judges
    if use_pro:
        import score_diff_monitor as sdm

    print(f"gold set 评估：{len(rows)} 条已标强度（{len(rows_sub)} 条含细类）｜Jev 问法 {args.form}"
          f"｜轨：{', '.join(j for j in judges if j != 'jev' or use_jev)}\n")
    preds: dict[str, dict] = {}
    errs: list[str] = []
    for name in ["kw"] + (["jev"] if use_jev else []) + (["pro"] if use_pro else []):
        s_pred, sub_pred, lat = [], [], []
        for r in rows:
            if name == "kw":
                _sub = live_sub(r)          # 实况细类（真实 site_id/library），非冻结 sub_kw
                sc = kw_strength(r, _sub)
                s_pred.append(level_of_score(sc))
                sub_pred.append(_sub)
            elif name == "jev":
                fb = un.DEFAULT_STRENGTH_BY_SUB.get(r.get("sub_kw", ""), un.DEFAULT_STRENGTH)
                res, dt, err = jc.judge_strength(r, form=args.form, fallback=fb)
                lat.append(dt)
                if res is None:
                    errs.append(f"[{r.get('sub_kw')}] {err[:120]}")
                s_pred.append(res["level"] if res else None)
                if res is None:
                    sub_pred.append(None)
                else:
                    ans, _, err2 = jc.evaluate(jc.state_from_item(r), jc.build_questions(True))
                    if ans is None:
                        errs.append(f"[细类] {err2[:120]}")
                    sub_pred.append(jc.sub_dimension(ans) if ans else None)
            else:
                sc = sdm.llm_score(r.get("sub_kw", ""), r.get("title", ""), r.get("summary", ""),
                                   args.model)
                s_pred.append(level_of_score(sc))
                sub_pred.append(None)      # Pro 轨只给强度，不给细类
        preds[name] = {"strength": s_pred, "sub": sub_pred, "lat": lat}

    gold_s = [r["label_strength"] for r in rows]
    gold_b = [r.get("label_sub") for r in rows]

    print("=== 内容强度（四档：3 里程碑 / 2 重要 / 1 进展 / 0 常规）===")
    print(f"{'判定器':<8}{'有效':>5}{'档位完全命中':>13}{'±1 命中':>10}{'平均偏差':>10}{'序相关':>9}")
    eval_out = {"ts": datetime.now(timezone.utc).isoformat(), "n": len(rows),
                "jev_form": args.form, "strength": {}, "sub": {}}
    for name, p in preds.items():
        pairs = [(g, q) for g, q in zip(gold_s, p["strength"]) if q is not None]
        if not pairs:
            continue
        exact = sum(1 for g, q in pairs if g == q) / len(pairs)
        near = sum(1 for g, q in pairs if abs(g - q) <= 1) / len(pairs)
        bias = sum(q - g for g, q in pairs) / len(pairs)
        rho = _spearman([g for g, _ in pairs], [q for _, q in pairs])
        print(f"{name:<8}{len(pairs):>5}{exact*100:>12.1f}%{near*100:>9.1f}%{bias:>+10.2f}"
              f"{('' if rho is None else f'{rho:>9}')}")
        eval_out["strength"][name] = {
            "n": len(pairs), "exact": round(exact, 3), "near1": round(near, 3),
            "bias": round(bias, 2), "spearman": rho,
            "confusion": _confusion(pairs, LEVEL_ORDER),
            "fail": sum(1 for q in p["strength"] if q is None),
            "lat_p50": (round(sorted(p["lat"])[len(p["lat"]) // 2], 2) if p["lat"] else None),
        }

    print("\n=== 七细类 ===")
    for name, p in preds.items():
        pairs = [(g, q) for g, q in zip(gold_b, p["sub"]) if q]
        if not pairs:
            print(f"{name:<8}  （该轨不产出细类）")
            continue
        acc = sum(1 for g, q in pairs if g == q) / len(pairs)
        print(f"{name:<8}  {len(pairs):>3} 条｜命中 {acc*100:.1f}%")
        eval_out["sub"][name] = {"n": len(pairs), "acc": round(acc, 3),
                                 "confusion": _confusion(pairs, SUB_ORDER)}
    EVAL_PATH.write_text(json.dumps(eval_out, ensure_ascii=False, indent=1), encoding="utf-8")
    if errs:
        print(f"\n⚠️ 调用失败 {len(errs)} 次（前 5 条）：")
        for e in errs[:5]:
            print("   " + e)
        eval_out["errors"] = errs[:20]
        EVAL_PATH.write_text(json.dumps(eval_out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n明细已写入 {EVAL_PATH.relative_to(ROOT)}")
    print("\n判读提醒：**先看分布与偏差方向，再看命中率**——"
          "命中率高但分布塌陷的判定器，不能用于排序（P0 的教训）。")
    return 0


# ────────────────────────────── CLI ──────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="P0.5 gold set 标尺标定工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sample", help="七细类均衡抽样，写入 data/gold-set.jsonl")
    p.add_argument("--per-sub", type=int, default=12)
    p.add_argument("--seed", type=int, default=7)
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("workbench", help="生成自包含标注工作台 HTML")
    p.set_defaults(func=cmd_workbench)

    p = sub.add_parser("import", help="合并工作台导出的 labels JSON")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("evaluate", help="对已标注条目评估各判定器")
    p.add_argument("--judges", default="kw,jev", help="kw,jev,pro（默认 kw,jev）")
    p.add_argument("--form", choices=list(jc.STRENGTH_FORMS), default="C")
    p.add_argument("--model", default="pro", choices=["pro", "flash"])
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("status", help="标注进度")
    p.set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
