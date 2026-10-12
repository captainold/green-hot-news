#!/usr/bin/env python3
"""title_zh 翻译质量抽检（S0-C，2026-10-12 老温批可）。

对 data/*.json 全量 title_zh 做质量分层扫描，输出各类命中数与样例：
  · 回显：译文与预处理输入完全相同（TMT 对文件名/纯专名/日语公文原样返回）——在线守卫已拦新条目，此处查存量
  · 串残：尾部来源名/栏目名残留（"… | 企业欧洲网络"、"- Prothom Alo English"）、乱符、嵌套括号
  · 拉丁连续词：多为专有名词合理保留（人名/公司/产品），仅计数不报警
  · 缺失：非中文标题但没有 title_zh（翻译失败/未译）

用法：
    python scripts/audit_zh_titles.py            # 默认扫服务器 data/ 三件套
    python scripts/audit_zh_titles.py --json out.json   # 附带机器可读输出
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import translator as tr  # noqa: E402

FILES = ("latest-24h.json", "latest-24h-all.json", "history.json")
_LATIN_RUN = re.compile(r"[A-Za-z]{2,}(?:\s+[A-Za-z]{2,}){2,}")
_ARTIFACT = re.compile(r"\|\s*\S+$|\ufffd|（[^）]{0,20}（|['\"]\s*[a-z]\b|[\u200b\u200e\u200f]")
_SEVERE_TAIL = re.compile(r"[_|｜]\s*\S{1,20}$|[-–—]\s*[A-Za-z][A-Za-z0-9 .,&'’()\-]{3,50}$")


def main() -> int:
    ap = argparse.ArgumentParser(description="title_zh 质量抽检")
    ap.add_argument("--json", default="", help="同时输出机器可读结果到该路径")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    args = ap.parse_args()

    seen: dict[str, dict] = {}
    for f in FILES:
        p = Path(args.data_dir) / f
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        for i in d.get("items", []) if isinstance(d, dict) else d:
            if isinstance(i, dict) and i.get("url"):
                seen.setdefault(i["url"], i)
    items = list(seen.values())
    z_items = [i for i in items if (i.get("title_zh") or "").strip()]
    need = [i for i in items if tr.needs_translation(i.get("title", ""))]
    miss = [i for i in need if not (i.get("title_zh") or "").strip()]

    classes = {"回显": [], "串残": [], "拉丁连续词": [], "缺失": []}
    for i in items:
        z = (i.get("title_zh") or "").strip()
        if not z:
            if tr.needs_translation(i.get("title", "")):
                classes["缺失"].append((i.get("site_id", ""), (i.get("title") or "")[:60]))
            continue
        if z == tr.preprocess_title(i.get("title", "")).strip():
            classes["回显"].append((i.get("site_id", ""), z[:60]))
        elif _ARTIFACT.search(z) or _SEVERE_TAIL.search(z):
            classes["串残"].append((i.get("site_id", ""), z[:60]))
        elif _LATIN_RUN.search(z):
            classes["拉丁连续词"].append((i.get("site_id", ""), z[:60]))

    print(f"条目 {len(items)}｜有 title_zh {len(z_items)}｜非中文需译 {len(need)}")
    for k in ("回显", "串残", "缺失"):
        v = classes[k]
        print(f"  {k}: {len(v)} 条")
        for s, z in v[:5]:
            print(f"    [{s[:10]}] {z}")
    print(f"  拉丁连续词: {len(classes['拉丁连续词'])} 条（专有名词合理保留，仅计数）")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {k: [{"site": s, "text": z} for s, z in v] for k, v in classes.items()},
            ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
