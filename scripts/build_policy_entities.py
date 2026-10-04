#!/usr/bin/env python3
r"""政策条目实体页生成（2026-09-23，P4 wiki 深化首批）。

按 `docs/标准文档/知识图谱实体与双链规范.md`：
- 类型 `pol`，目录 `Notes/实体/政策/`，id `pol/<cc>-<site_id>-<年>-<短名>`
- frontmatter：id/type/name/aliases/region/topics/related/tags/created
- 正文：发布机构与主题双链、素材来源回链（`mat/<id>`）、要点摘自 summary

选材：`data/history.json` 中 `dimension=政策`、含政策文件词（通知/办法/方案/意见/条例/规划…）、
排除会议活动噪声，按 score 降序去重取前 N（默认 15）。

幂等：已存在页面默认跳过（`--force` 重建）；📚 导航页条目列表用标记块整体刷新。

用法：
    python scripts/build_policy_entities.py [--dry-run|--apply] [--limit 15] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "Notes"
POL_DIR = NOTES / "实体" / "政策"
ORG_DIR = NOTES / "实体" / "机构"
WIKI_ROOT = NOTES / "政策wiki" / "📚 绿色政策 Wiki.md"
HISTORY = ROOT / "data" / "history.json"
MAT_INDEX = ROOT / "cache" / "mat-index.json"   # 由 build_material_index.py 生成的派生缓存

DOC_WORDS = ("通知", "办法", "方案", "意见", "条例", "规划", "公告", "规定", "决定",
             "法案", "战略", "计划", "指南", "标准", "细则", "目录", "批复", "令",
             "Act", "Strategy", "Plan", "Rule", "Directive", "Regulation")
ISSUER = ("中共中央", "国务院", "全国人大", "国家发展改革委", "国家发改委", "生态环境部",
          "工业和信息化部", "工信部", "国家能源局", "财政部", "科技部", "住房城乡建设部",
          "交通运输部", "商务部", "人民银行", "中国人民银行", "金融监管总局", "国家标准",
          "省人民政府", "市人民政府", "生态环境厅", "发展改革委", "欧盟委员会", "欧委会",
          "Commission", "Government", "Ministry", "Agency", "Parliament")
NOISE = ("研讨会", "座谈", "交流", "会议", "发布会", "活动", "培训", "招聘", "党日",
         "学习", "调研", "来访", "到访", "举办", "签署仪式", "开幕", "致辞", "论坛",
         "休市", "假期", "节假日", "会见", "一图读懂", "图解", "公示", "名单", "周报",
         "月报", "指数", "解读", "专访", "观察", "评论", "速递", "快报", "首款", "宣布",
         "专业委员会", "专委会", "协会", "学会",
         # 2026-10-04 vault 池新增噪声（交易所日常业务公告 / 媒体栏目稿 / 摘要蹭词）
         "竞价", "挂牌", "交割", "划转", "信托", "发放公告", "风险提示", "招聘公告",
         "【关注】", "之十五", "系列", "答记者问")
GREEN = ("碳", "绿色", "低碳", "节能", "减排", "新能源", "可再生", "光伏", "风电", "储能",
         "氢", "电网", "环保", "生态环境", "气候", "资源循环", "ESG", "清洁能源", "双碳",
         "能效", "循环经济", "电动车", "充电", "绿色金融", "碳排放", "污染")
CC = {"中国": "cn", "美国": "us", "欧盟": "eu", "日本": "jp", "印度": "in", "国际": "int"}


def _org_id(path: Path) -> str:
    m = re.search(r'^id:\s*"?(.+?)"?\s*$', path.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip() if m else ""


def _org_aliases(path: Path) -> list[str]:
    t = path.read_text(encoding="utf-8")
    m = re.search(r'^aliases:\s*\[(.*?)\]\s*$', t, re.M)
    if not m:
        return []
    return [x.strip().strip('"\'') for x in m.group(1).split(",") if x.strip()]


def slug(title: str) -> str:
    m = re.search(r"《([^》]{2,20})》", title)
    base = m.group(1) if m else title
    base = re.sub(r"^(关于|关于印发|印发|发布)", "", base)
    base = re.sub(r"(的通知|的公告|的意见|的办法|的实施方案|实施方案|工作方案)$", "", base)
    base = re.sub(r"[^\w\u4e00-\u9fff]+", "", base)
    return base[:14] or "政策"


def _unescape(s: str) -> str:
    """还原 YAML 双引号标量里的转义（`\\"` / `\\\\`）。

    2026-10-04 踩坑：素材库 frontmatter 里 `title: "…《…\\"十五五\\"规划》…"` 带转义引号，
    不还原就会把 `\\"` 当成标题内容 → 生成含 `"` `\\` 的**非法文件名**，写盘直接炸。
    """
    return s.replace('\\"', '"').replace("\\\\", "\\")


def safe_filename(title: str) -> str:
    """去文件系统非法字符 + 按字节控长（与 export_qmd._safe_filename 同口径）。"""
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", title or "").strip().rstrip(".")
    b = s.encode("utf-8")[:200]
    return b.decode("utf-8", "ignore") or "政策"


def yaml_str(s: str) -> str:
    """写 frontmatter 用：转义反斜杠与双引号（否则标题里的引号会撑破 YAML）。"""
    return '"' + (s or "").replace("\\", "\\\\").replace('"', '\\"') + '"'


def load_vault_items() -> list[dict]:
    """把素材库政策条目读成与 history.json 同构的 item（供 --source vault 用）。

    history.json 只覆盖 62 天（实测命中判据 9 条），素材库全量能给出 119 条候选，
    这是「政策实体页扩量」的真实瓶颈所在（2026-10-04 实测）。
    """
    fm_re = re.compile(r"^---\s*\n(.*?)\n---", re.S)
    out: list[dict] = []
    for p in (NOTES / "素材库" / "政策").rglob("*.md"):
        text = p.read_text(encoding="utf-8", errors="replace")
        m = fm_re.match(text)
        if not m:
            continue
        fm: dict[str, str] = {}
        for line in m.group(1).split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = _unescape(v.strip().strip('"'))
        sm = re.search(r"^##\s*摘要\s*$", text, re.M)
        summary = ""
        if sm:
            rest = text[sm.end():]
            nx = re.search(r"^##\s", rest, re.M)
            summary = re.sub(r"\s+", " ", (rest[:nx.start()] if nx else rest)).strip()
        score_raw = fm.get("score", "0")
        try:
            score = int(float(score_raw))
        except ValueError:
            score = 0
        out.append({
            "dimension": fm.get("dimension", ""),
            "sub_dimension": fm.get("sub_dimension", ""),
            "title": fm.get("title", "") or p.stem,
            "summary": summary,
            "site_id": fm.get("site", ""),
            "site_name": fm.get("site", ""),
            "source": fm.get("site", ""),
            "region": fm.get("region", "中国"),
            "score": score,
            "published_at": fm.get("published_at", "") or fm.get("date", ""),
            "url": fm.get("url", ""),
            "topics": [x.strip() for x in re.findall(r"[^\[\],]+",
                                                     fm.get("topics", "")) if x.strip()],
            "_note_stem": p.stem,
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="不传则只预览（dry-run）")
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--per-site", type=int, default=4, help="同一来源最多入选几条")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--source", choices=["history", "vault"], default="history",
                    help="候选池：history=62 天 data/history.json（默认）；vault=素材库全量")
    ap.add_argument("--from-year", type=int, default=0, help="只要 >= 该年（0=不限）")
    ap.add_argument("--min-score", type=int, default=0, help="只要评分 >= 该值")
    ap.add_argument("--green-in-summary", action="store_true",
                    help="绿色词允许只出现在摘要（默认只认标题，防交易所日常公告蹭词）")
    args = ap.parse_args()

    if args.source == "vault":
        items = load_vault_items()
        print(f"[info] 素材库候选池 {len(items)} 条政策条目")
    else:
        data = json.loads(HISTORY.read_text(encoding="utf-8"))
        items = data["items"] if isinstance(data, dict) and "items" in data else data
    mat = json.loads(MAT_INDEX.read_text(encoding="utf-8")) if MAT_INDEX.exists() else {}
    orgs = {p.stem: p for p in ORG_DIR.rglob("*.md")} if ORG_DIR.exists() else {}
    # 官方发布主体：机构实体里非「媒体」的 org id（org/cn|eu|jp|us|in|int）
    official_ids: set[str] = set()
    for p in orgs.values():
        oid = _org_id(p)
        if oid and not oid.startswith("org/media"):
            official_ids.add(oid)
    official_sites = {i.rsplit("/", 1)[-1] for i in official_ids}
    topics = {p.stem for p in (NOTES / "政策wiki").rglob("*.md")}

    picked: list[dict] = []
    seen: set[str] = set()
    existing_names: set[str] = set()
    # 已有页面先入 seen：同一政策被两个来源转载时（标题尾多一个「-站点」）不再重复建页。
    # existing_names 用于放行"就是同一份文件"的情形（--force 重建时不该被自己的 seen 挡住）
    if POL_DIR.exists():
        for q in POL_DIR.rglob("*.md"):
            nm = re.search(r"^name:\s*(.+?)\s*$", q.read_text(encoding="utf-8",
                                                             errors="replace"), re.M)
            if nm:
                v = nm.group(1).strip().strip('"').replace('\\"', '"')
                existing_names.add(v)
                seen.add(re.sub(r"[-–—]\s*[^-–—]{0,20}$", "", v).strip())
    cands: list[tuple[int, int, dict]] = []
    for it in items:
        if it.get("dimension") != "政策":
            continue
        if it.get("sub_dimension") not in ("政策法规", "国际动态"):
            continue
        title = (it.get("title_zh") or it.get("title") or "").strip()
        if not title or any(n in title for n in NOISE):
            continue
        if not any(w in title for w in DOC_WORDS):
            continue
        year = int(((it.get("published_at") or "")[:4] or "0")) if \
            (it.get("published_at") or "")[:4].isdigit() else 0
        if args.from_year and year < args.from_year:
            continue
        if args.min_score and (it.get("score") or 0) < args.min_score:
            continue
        is_official = ((it.get("site_id") or "").lower() in official_sites
                       or (it.get("source") or "") in official_ids)
        if not is_official and not any(w in title for w in ISSUER):
            continue
        blob = title + (" " + (it.get("summary") or "") if args.green_in_summary else "")
        if not any(g in blob for g in GREEN):
            continue
        cands.append((2 if is_official else 1, it.get("score") or 0, it))
    per_site: dict[str, int] = {}
    for _auth, _score, it in sorted(cands, key=lambda x: (-x[0], -x[1])):
        title = (it.get("title_zh") or it.get("title") or "").strip()
        key = re.sub(r"[-–—]\s*[^-–—]{0,20}$", "", title).strip()
        if key in seen and title not in existing_names:
            continue
        sid = it.get("site_id") or ""
        if per_site.get(sid, 0) >= args.per_site:
            continue
        seen.add(key)
        per_site[sid] = per_site.get(sid, 0) + 1
        picked.append(it)
        if len(picked) >= args.limit:
            break

    print(f"选中政策条目 {len(picked)} 条")
    if args.apply:
        POL_DIR.mkdir(parents=True, exist_ok=True)

    written: list[tuple[str, str]] = []
    entries: list[tuple[str, str, str]] = []   # (pid, title, short) —— 导航表用全量，不随跳过而变
    # pid 去重：现有页面的 id 先入集合，防止同短名不同文件写出重复 id（verify_graph 会报 id 重复）；
    # 存成 {pid: 文件} 才能放行"重建自己"（--force 时 pid 属于本文件，不算冲突）
    known_pids: dict[str, Path] = {}
    if POL_DIR.exists():
        for q in POL_DIR.rglob("*.md"):
            oid = _org_id(q)
            if oid:
                known_pids[oid] = q.resolve()
    for it in picked:
        title = (it.get("title_zh") or it.get("title") or "").strip()
        region = it.get("region") or "中国"
        cc = CC.get(region, "int")
        year = (it.get("published_at") or "")[:4] or "2026"
        sid = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (it.get("site_id") or "src").lower()) or "src"
        pid = f"pol/{cc}-{sid}-{year}-{slug(title)}"
        target_path = POL_DIR / f"{safe_filename(title)[:80]}.md"
        owner = known_pids.get(pid)
        if owner is not None and owner != target_path.resolve():
            # 同一发文机关的两份文件前 14 字可能相同（如「工业和信息化部办公厅关于印发…」）
            # → 用标题哈希补尾，别丢页
            alt = f"{pid}-{hashlib.sha1(title.encode('utf-8')).hexdigest()[:4]}"
            if alt in known_pids:
                print(f"  ⏭ id 已占用且补尾仍冲突，跳过：{title[:44]}")
                continue
            pid = alt
        known_pids[pid] = target_path.resolve()
        short = slug(title)
        date = (it.get("published_at") or "")[:10]
        url = it.get("url") or ""
        summary = re.sub(r"\s+", " ", (it.get("summary") or "")).strip()
        # 发布机构实体：优先标题中出现的非媒体机构（真正发文主体），其次来源站点
        site = it.get("site_name") or it.get("source") or ""
        m_iss = re.match(
            r"^(中共中央办公厅|国务院办公厅|国务院|全国人大常委会|"
            r"[\u4e00-\u9fff]{2,10}?(?:发展改革委|生态环境部|工业和信息化部|能源局|财政部|"
            r"科技部|住房城乡建设部|交通运输部|商务部|人民银行|市场监管总局|金融监管总局|"
            r"部|委|局|厅|署|省人民政府|市人民政府))", title)
        issuer_text = m_iss.group(1) if m_iss else ""
        alias_map: dict[str, str] = {}
        for stem, p in orgs.items():
            if _org_id(p).startswith("org/media"):
                continue
            alias_map[stem] = stem
            for a in _org_aliases(p):
                if len(a) >= 3:
                    alias_map[a] = stem
        issuer_stem = next((alias_map[a] for a in
                            sorted(alias_map, key=len, reverse=True)
                            if issuer_text and a in issuer_text), "")
        src_stem = next((s for s in sorted(orgs, key=len, reverse=True)
                         if s and (s in site or site in s)), "")
        org_id = _org_id(orgs[issuer_stem]) if issuer_stem else ""
        src_id = _org_id(orgs[src_stem]) if src_stem else ""
        # 主题
        tp = [t for t in (it.get("topics") or []) if t in topics]
        # 素材来源
        mrow = mat.get(url) or next((v for v in mat.values() if v.get("url") == url), None)
        note = it.get("_note_stem") or (Path(mrow["path"]).stem if mrow else "")
        mat_id = next((k for k, v in mat.items() if v.get("url") == url), "")

        lines = [
            "---",
            f'id: "{pid}"',
            'type: "pol"',
            f'name: {yaml_str(title)}',
            f'aliases: [{yaml_str(short)}, {yaml_str(pid)}]',
            f'region: "{region}"',
            f"topics: {json.dumps(tp, ensure_ascii=False)}",
            f'related: {json.dumps([org_id] if org_id else [], ensure_ascii=False)}',
            f'tags: ["type/pol", "region/{region}"]',
            "created: 2026-09-23",
            "status: skeleton",
            f'issued: "{date}"',
            f'source_url: "{url}"',
            f"score: {it.get('score')}",
            "---",
            "",
            f"# {title}",
            "",
            f"> **发文主体**：{('[[%s]]' % issuer_stem) if issuer_stem else (issuer_text or '待核（素材来源为媒体转述）')}"
            f" ｜ **素材日期**：{date or '—'}"
            f" ｜ **评分**：{it.get('score')}（v5.0 六维）",
            f"> **原文**：{url}",
            "",
            "## 要点",
            "",
            summary[:600] or "_（素材无摘要，待人工补充）_",
            "",
            "## 关联",
            "",
        ]
        if issuer_stem:
            lines.append(f"- 发文主体：[[{issuer_stem}]]（`{org_id}`）")
        elif issuer_text:
            lines.append(f"- 发文主体：{issuer_text}（_实体页待建_）")
        if src_stem and src_stem != issuer_stem:
            lines.append(f"- 来源站点：[[{src_stem}]]（`{src_id}`）")
        for t in tp:
            lines.append(f"- 主题：[[{t}|{t}]]")
        if note:
            lines.append(f"- 素材来源：[[{note}]]（`{mat_id}`）")
        lines += [
            "",
            "## 说明",
            "",
            "- 本页由 `scripts/build_policy_entities.py` 生成（P4 首批，2026-09-23）；"
            "要点摘自素材摘要，**待人工深化**（文号/效力/关联政策）。",
            "",
        ]
        path = target_path
        entries.append((pid, title, short))
        exists = path.exists()
        if exists and not args.force:
            continue
        written.append((pid, title))
        if args.apply:
            path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  {'重建' if exists else '新建'} {pid}")

    # 导航页条目列表（标记块整体刷新）
    if args.apply and entries:
        text = WIKI_ROOT.read_text(encoding="utf-8")
        block = ["<!-- pol-entities:start -->", "", "### 重要政策条目（P4 首批，自动生成）", "",
                 "| 政策 | 地区 | 实体 id |", "|------|------|--------|"]
        for pid, title, short in entries:
            block.append(f"| [[{title[:80]}|{short}]] | {pid.split('/')[1][:2]} | `{pid}` |")
        block += ["", "<!-- pol-entities:end -->", ""]
        new_block = "\n".join(block)
        if "<!-- pol-entities:start -->" in text:
            text = re.sub(r"<!-- pol-entities:start -->.*?<!-- pol-entities:end -->\n?",
                          new_block, text, flags=re.S)
        else:
            anchor = "## 板块结构（六段模板）"
            text = text.replace(anchor, new_block + "\n" + anchor)
        WIKI_ROOT.write_text(text, encoding="utf-8")
        print(f"📚 导航页条目列表已刷新（{len(entries)} 条）")

    print(f"\n{'写入' if args.apply else '待写入'} {len(written)} 个政策实体页 → {POL_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
