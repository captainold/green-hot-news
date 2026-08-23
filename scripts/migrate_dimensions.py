#!/usr/bin/env python3.11
"""三层分类迁移（2026-08-23 重构：四维「政策/产业/市场信号/AI」→
三层「绿色政策/绿色产业/科技创新」+ 六细类「政策法规/国际动态/企业经营/金融资本/技术研发/基础研究」）。

- 重算 history.json 所有条目的 dimension + sub_dimension（用新 categorize_dimension）
- 重打分（score_item 内容强度按细类 key 计算——CONTENT_STRENGTH_RULES 的 key 变了）
- 同时迁移 latest-24h.json / latest-24h-all.json 的 dimension/sub_dimension 字段
- 幂等：可重复运行；不改 url/标题等原始字段

用法：python3.11 scripts/migrate_dimensions.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("un", str(ROOT / "scripts" / "update_news.py"))
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)

from datetime import datetime  # noqa: E402

NOW = datetime.now().astimezone()


def migrate_file(path: Path) -> int:
    if not path.exists():
        print(f"  跳过（不存在）: {path.name}")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    changed = 0
    kept: list[dict] = []
    removed = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        # radarai 清理（2026-08-19）：GitHub 开源项目趋势仅保留绿色主题或 AI 项目，
        # 与 is_policy_relevant 新规则对齐——vitejs/vite 等无关项目从历史数据移除
        if it.get("site_id") == "radarai":
            if not un.is_policy_relevant(it.get("title", ""), it.get("url", ""), "radarai", it.get("summary", "")):
                removed += 1
                continue
        old = it.get("dimension")
        dim, sub = un.categorize_dimension(
            it.get("site_id", ""),
            it.get("title", ""),
            it.get("summary", ""),
            it.get("library", "media"),
        )
        it["dimension"] = dim
        it["sub_dimension"] = sub
        # layer 国际化字段（2026-08-23 新增）
        it["layer"] = un.DIM_TO_LAYER.get(dim, "Layer 2")
        # 国际标准分类法（2026-08-23 新增）：EU Taxonomy / ISIC / GICS / IPC
        it["taxonomy"] = {
            "eu_taxonomy": un.classify_eu_taxonomy(it.get("title", ""), it.get("summary", "")),
            "isic": un.classify_isic(it.get("site_id", ""), it.get("title", ""), it.get("summary", "")),
            "gics": un.classify_gics(it.get("title", ""), it.get("summary", "")),
            "ipc": un.classify_ipc(it.get("title", ""), it.get("summary", "")),
        }
        # 交叉技术标签 + TRL（2026-08-23 新增）
        it["enabling_tech"] = un.classify_enabling_tech(it.get("title", ""), it.get("summary", ""))
        it["trl"] = un.classify_trl(it.get("title", ""), it.get("summary", ""))
        # 重打分：内容强度按细类 key + TRL 第 6 维度；people 重提取（打分依赖）
        people = it.get("people") or un.extract_people(it.get("title", ""), it.get("summary", ""), "")
        scoring = un.score_item(
            it.get("site_id", ""),
            it.get("title", ""),
            it.get("summary", ""),
            people,
            it.get("published_at", ""),
            NOW,
            sub,
            it["trl"],
        )
        it.update(scoring)
        if people:
            it["people"] = people
        if old != dim:
            changed += 1
        kept.append(it)
    if isinstance(data, dict) and "items" in data:
        data["count"] = len(kept)
        data["generated_at"] = un.iso(NOW)
        data["items"] = kept
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_text(json.dumps(kept, ensure_ascii=False), encoding="utf-8")
    print(f"  {path.name}: {len(kept)} 条（移除 {removed} 条 radarai 无关项目），维度变化 {changed} 条")
    return changed


def main() -> int:
    print("三层分类迁移（2026-08-23：绿色政策/绿色产业/科技创新 + 六细类）")
    total = 0
    for fn in ("history.json", "latest-24h.json", "latest-24h-all.json"):
        total += migrate_file(ROOT / "data" / fn)
    print(f"完成，共 {total} 条维度变化")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
