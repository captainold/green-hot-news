#!/usr/bin/env python3.11
"""发布时间回填修复（2026-08-20）：揪出「首抓当天冒充发布时间」的污染条目。

背景：update_news.py 写 Notes 时，详情页/RSS 都无时间会拿**抓取当天**兜底
（last resort），该日期被 published-index.json 永久固化——实测 chinanecc
（国家节能中心）4-23 的《碳达峰碳中和综合评价考核办法》答记者问被标成
8-19 首抓日。本脚本：

1. 读 published-index.json，对 archived 日期 == 该条 first_seen_at 日期
   （首抓日，强烈暗示兜底污染）的条目重新 fetch_article 提取真实发布时间
2. 命中 → 更新 published-index.json + history.json / latest-24h*.json 的
   published_at + time_source='published'
3. 未命中 → 语义修正为「收录时间」：time_source='scraped'（published_at 用
   first_seen_at，前端显示「收录 X」而非伪发布时间）

幂等：已修正条目 archived 日期 ≠ first_seen 日期，重跑自动跳过。

用法：python3.11 scripts/backfill_pubtimes.py
"""
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("un", str(ROOT / "scripts" / "update_news.py"))
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)

import article_content  # noqa: E402

DATA = ROOT / "data"
PUB_INDEX = DATA / "published-index.json"
JSON_FILES = ("history.json", "latest-24h.json", "latest-24h-all.json")


def load_items() -> dict[str, dict]:
    """url -> 条目（跨所有 JSON，后出现者覆盖——内容一致，取 latest-24h-all 最全）。"""
    merged: dict[str, dict] = {}
    for fn in JSON_FILES:
        p = DATA / fn
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        items = d.get("items", d) if isinstance(d, dict) else d
        for it in items:
            if isinstance(it, dict) and it.get("url"):
                merged[it["url"]] = it
    return merged


def suspicious(url: str, archived: str, rec: dict) -> bool:
    """archived 日期 == 首抓日 → 疑似兜底污染。"""
    first_seen = (rec.get("first_seen_at") or "")[:10]
    if not first_seen:
        return False
    return archived[:10] == first_seen


def main() -> int:
    items = load_items()
    pub_index = json.loads(PUB_INDEX.read_text(encoding="utf-8"))
    candidates = [
        (url, val) for url, val in pub_index.items()
        if url in items and suspicious(url, val, items[url])
    ]
    print(f"published-index 共 {len(pub_index)} 条，疑似首抓日兜底 {len(candidates)} 条")

    fixed_pub: dict[str, str] = {}
    scraped: set[str] = set()
    failed: list[tuple[str, str]] = []

    def probe(url: str):
        res = article_content.fetch_article(url)
        return url, (res or {}).get("published") or ""

    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(probe, url): url for url, _ in candidates}
        for fut in as_completed(futs):
            url = futs[fut]
            try:
                _, pub = fut.result()
            except Exception:
                pub = ""
            if pub:
                fixed_pub[url] = pub
            else:
                scraped.add(url)
            failed.append((url, pub or "(none)"))

    # 更新 published-index.json（修正值写回；未命中的从索引中剔除，避免再被回填）
    for url, pub in fixed_pub.items():
        pub_index[url] = pub
    for url in scraped:
        pub_index.pop(url, None)

    # 更新三个 JSON 的 published_at / time_source
    updated = 0
    for fn in JSON_FILES:
        p = DATA / fn
        if not p.exists():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        items_list = d.get("items", d) if isinstance(d, dict) else d
        n = 0
        for it in items_list:
            if not isinstance(it, dict) or not it.get("url"):
                continue
            url = it["url"]
            if url in fixed_pub:
                pub = fixed_pub[url]
                # date-only（'YYYY-MM-DD'）补 T00:00:00，带时分（'YYYY-MM-DD HH:MM'）
                # 换 T 分隔——必须输出标准 ISO（'2026-04-23+08:00' 会被 JS Date 判废）
                it["published_at"] = (
                    pub.replace(" ", "T") + "+08:00" if " " in pub
                    else pub + "T00:00:00+08:00"
                )
                it["time_source"] = "published"
                n += 1
            elif url in scraped and it.get("time_source") == "published":
                it["published_at"] = it.get("first_seen_at")
                it["time_source"] = "scraped"
                n += 1
        if isinstance(d, dict) and "items" in d:
            d["count"] = len(items_list)
            d["generated_at"] = un.iso(datetime.now(timezone.utc))
            p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        else:
            p.write_text(json.dumps(items_list, ensure_ascii=False), encoding="utf-8")
        updated += n
        print(f"  {fn}: 更新 {n} 条")

    PUB_INDEX.write_text(json.dumps(pub_index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完成：修正发布时间 {len(fixed_pub)} 条 / 改判收录时间 {len(scraped)} 条")
    if failed:
        print("未命中（改判收录时间）示例：")
        for url, pub in failed[:8]:
            print(f"  {pub[:40]:44s} {url[:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
