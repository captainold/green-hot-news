#!/usr/bin/env python3
"""P3 双链迁移：素材库发稳定 id + related 存 id（2026-09-23，老确定稿口径 A）。

规则（写入 docs/标准文档/知识图谱实体与双链规范.md §2.2）：
- 素材记录 id = `mat/<sha1(url)[:12]>`：url 是素材的天然身份，url 不变 → id 不变，
  改标题/改名不断链。
- `related` 字段存 mat id（替代原先存文件名）。

脚本行为（幂等）：
1. 全库扫描 素材库/**/*.md，按 url 计算 id
2. frontmatter 补 `id:`（缺则插在 `---` 后首行；已有且正确则跳过）
3. `related: [...]` 内文件名 → 目标 id；处理 dedup manifest（被去重删掉的文件名 → 保留文件的 id）
4. 备份：迁移前把每个文件的 frontmatter 原文存 cache/p3-backup/frontmatter.json，
   并生成 cache/p3-backup/rollback.py 可一键还原
5. 失败/未解析项写入报告，不静默丢弃

用法：
    python scripts/migrate_related_to_id.py [--dry-run|--apply] [--limit N]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SC = ROOT / "Notes" / "素材库"
CACHE = ROOT / "cache"
BACKUP = CACHE / "p3-backup"
DEDUP_MANIFEST = CACHE / "dedup-manifest.json"
FM_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
REL_FLOW_RE = re.compile(r"^related:\s*(\[.*\])\s*$", re.M)


def mat_id(url: str) -> str:
    return "mat/" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def fm_url(fm: str) -> str:
    m = re.search(r'^url:\s*["\']?([^"\'\n]+)', fm, re.M)
    return m.group(1).strip() if m else ""


def fm_id(fm: str) -> str:
    m = re.search(r'^id:\s*["\']?([^"\'\n]+)', fm, re.M)
    return m.group(1).strip() if m else ""


def rel_entries(fm: str) -> list[str]:
    """取 related 列表内的条目（支持 flow 与 block 两种写法）。"""
    m = REL_FLOW_RE.search(fm)
    if m:
        return re.findall(r'"((?:[^"\\]|\\.)*)"', m.group(1)) or \
               [x.strip().strip("'") for x in m.group(1).strip("[]").split(",") if x.strip()]
    # block 形式
    bm = re.search(r"^related:\s*\n((?:[ \t]+-[^\n]*\n?)+)", fm, re.M)
    if bm:
        return [ln.strip()[1:].strip().strip('"').strip("'") for ln in bm.group(1).splitlines() if ln.strip()]
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际写入（默认 dry-run）")
    ap.add_argument("--limit", type=int, default=0, help="仅处理前 N 个文件（小批验证用）")
    args = ap.parse_args()
    apply = args.apply

    files = sorted(SC.rglob("*.md"))
    if args.limit:
        files = files[: args.limit]
    print(f"mode={'apply' if apply else 'dry-run'} | files={len(files)}")

    # ---- 第一遍：stem -> id 映射（当前库） ----
    stem2id: dict[str, str] = {}
    path_id: dict[Path, str] = {}
    no_url: list[str] = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        m = FM_RE.match(text)
        if not m:
            no_url.append(f"{f.relative_to(SC)} (无 frontmatter)")
            continue
        url = fm_url(m.group(1))
        if not url:
            no_url.append(str(f.relative_to(SC)))
            continue
        i = mat_id(url)
        stem2id[f.stem] = i
        path_id[f] = i

    # ---- 补充：dedup manifest 中被移除的文件名 → 保留文件 id ----
    if DEDUP_MANIFEST.exists():
        man = json.loads(DEDUP_MANIFEST.read_text(encoding="utf-8"))
        for d in man.get("decisions", []):
            keep_stem = Path(d["keep"]).stem
            if keep_stem in stem2id:
                for rm in d.get("removed", []):
                    stem2id.setdefault(Path(rm).stem, stem2id[keep_stem])
        print(f"dedup manifest 已并入：{len(man.get('decisions', []))} 组")

    unresolved: list[tuple[str, str]] = []
    stats = {"id_added": 0, "id_ok": 0, "related_rewritten": 0, "related_kept_id": 0,
             "related_fuzzy": 0}
    backup: dict[str, str] = {}
    BACKUP.mkdir(parents=True, exist_ok=True)

    # 前缀索引：AI 互链当年按 ~100 字符截断了文件名，需要模糊回指
    sorted_stems = sorted(stem2id)

    def fuzzy_lookup(trunc: str) -> str | None:
        """按前缀匹配真实 stem（截断名是真实名的前缀）；唯一命中才返回。"""
        t = trunc.rstrip()
        if len(t) < 20:
            return None
        import bisect
        i = bisect.bisect_left(sorted_stems, t)
        hits = []
        while i < len(sorted_stems) and sorted_stems[i].startswith(t):
            hits.append(sorted_stems[i])
            i += 1
            if len(hits) > 1:
                return None
        return hits[0] if len(hits) == 1 else None

    for f in files:
        if f not in path_id:
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        m = FM_RE.match(text)
        if not m:
            continue
        fm, rest = m.group(1), text[m.end():]
        want_id = path_id[f]
        new_fm = fm

        # 1) 补 id
        cur_id = fm_id(fm)
        if cur_id == want_id:
            stats["id_ok"] += 1
        elif not cur_id:
            new_fm = f'id: "{want_id}"\n' + new_fm
            stats["id_added"] += 1
        else:
            unresolved.append((str(f.relative_to(SC)), f"id 冲突: 现有 {cur_id} != {want_id}"))

        # 2) related → id
        entries = rel_entries(new_fm)
        if entries:
            new_entries = []
            changed = False
            for e in entries:
                e_clean = re.sub(r"\.(md|qmd)$", "", e).strip()
                if e_clean.startswith("mat/"):
                    new_entries.append(e_clean)
                    stats["related_kept_id"] += 1
                    continue
                tid = stem2id.get(e_clean)
                if tid is None:
                    fz = fuzzy_lookup(e_clean)
                    if fz:
                        tid = stem2id[fz]
                        stats["related_fuzzy"] += 1
                if tid:
                    if tid != e:
                        changed = True
                    new_entries.append(tid)
                else:
                    unresolved.append((str(f.relative_to(SC)), f"related 目标未解析: {e}"))
                    new_entries.append(e)
            if changed:
                payload = json.dumps(new_entries, ensure_ascii=False)
                if REL_FLOW_RE.search(new_fm):
                    new_fm = REL_FLOW_RE.sub(f"related: {payload}", new_fm, count=1)
                else:
                    new_fm = re.sub(r"^related:\s*\n((?:[ \t]+-[^\n]*\n?)+)",
                                    f"related: {payload}\n", new_fm, count=1, flags=re.M)
                stats["related_rewritten"] += 1

        if new_fm != fm:
            backup[str(f.relative_to(SC))] = fm
            if apply:
                f.write_text(f"---\n{new_fm}\n---\n{rest}", encoding="utf-8")

    print("stats:", json.dumps(stats, ensure_ascii=False))
    print("unresolved:", len(unresolved), "| no_url:", len(no_url))
    for p, why in unresolved[:10]:
        print("  -", p, "|", why)
    for p in no_url[:5]:
        print("  ! 无 url:", p)

    if apply:
        (BACKUP / "frontmatter.json").write_text(
            json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8")
        rollback_src = (
            '#!/usr/bin/env python3\n'
            '"""还原 P3 迁移前的 frontmatter（数据源 cache/p3-backup/frontmatter.json）。"""\n'
            'import json\n'
            'import re\n'
            'from pathlib import Path\n'
            '\n'
            f'SC = Path(r"{SC}")\n'
            f'BK = Path(r"{BACKUP}") / "frontmatter.json"\n'
            "FM = re.compile(r'^---\\r?\\n(.*?)\\r?\\n---\\r?\\n', re.DOTALL)\n"
            '\n'
            "def main() -> None:\n"
            "    data = json.loads(BK.read_text(encoding='utf-8'))\n"
            "    n = 0\n"
            "    for rel, fm in data.items():\n"
            "        p = SC / rel\n"
            "        t = p.read_text(encoding='utf-8')\n"
            "        m = FM.match(t)\n"
            "        if not m:\n"
            "            continue\n"
            "        p.write_text('---\\n' + fm + '\\n---\\n' + t[m.end():], encoding='utf-8')\n"
            "        n += 1\n"
            "    print('restored', n)\n"
            '\n'
            '\n'
            "if __name__ == '__main__':\n"
            '    main()\n'
        )
        (BACKUP / "rollback.py").write_text(rollback_src, encoding="utf-8")
        print(f"备份 {len(backup)} 个 frontmatter → {BACKUP}（rollback.py 可还原）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
