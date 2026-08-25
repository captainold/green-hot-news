#!/usr/bin/env python3.11
"""临时脚本：修复英文短词子串误匹配后，重算 taxonomy + enabling_tech 字段。

只重算两个字段（2026-08-25 _kw_hit 词边界修复），不动 score/tech_feature/
people/dimension 等其他字段（避免触发 LLM 与重打分）。
用法：python3.11 scripts/_fix_taxonomy_wordboundary.py
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("un", str(ROOT / "scripts" / "update_news.py"))
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)


def recount(fn: str) -> None:
    path = ROOT / "data" / fn
    if not path.exists():
        print(f"  跳过（不存在）: {fn}")
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    changed_tax = changed_et = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        title = it.get("title", "")
        summ = it.get("summary", "")
        sid = it.get("site_id", "")
        new_tax = {
            "eu_taxonomy": un.classify_eu_taxonomy(title, summ),
            "isic": un.classify_isic(sid, title, summ),
            "gics": un.classify_gics(title, summ),
            "ipc": un.classify_ipc(title, summ),
        }
        old_tax = it.get("taxonomy") or {}
        if old_tax != new_tax:
            changed_tax += 1
        it["taxonomy"] = new_tax
        new_et = un.classify_enabling_tech(title, summ)
        if (it.get("enabling_tech") or []) != new_et:
            changed_et += 1
        it["enabling_tech"] = new_et
    if isinstance(data, dict) and "items" in data:
        data["items"] = items
    else:
        data = items
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"  {fn}: {len(items)} 条，taxonomy 变化 {changed_tax}，enabling_tech 变化 {changed_et}")


def main() -> None:
    # 备份
    for fn in ("history.json", "latest-24h.json", "latest-24h-all.json"):
        p = ROOT / "data" / fn
        if p.exists():
            shutil.copy2(p, Path("/tmp") / f"{fn}.bak")
    print("已备份到 /tmp/*.bak", flush=True)
    for fn in ("history.json", "latest-24h.json", "latest-24h-all.json"):
        recount(fn)
    print("完成")


if __name__ == "__main__":
    main()
