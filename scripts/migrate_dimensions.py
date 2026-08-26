#!/usr/bin/env python3.11
"""三层分类迁移（2026-08-23 重构：四维「政策/产业/市场信号/AI」→
三层「绿色政策/绿色产业/科技创新」+ 六细类；2026-08-26 v5.0 二次复用：
三层中性命名「政策/创新/产业」+ 七细类「政策法规/国际动态/技术研发/基础研究/社会创新/企业经营/金融资本」，
AI 按技术阶段分流，碳普惠/碳账户归产业层）。

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

# 技术特征提取模块（2026-08-23 新增）
import tech_feature as tf  # noqa: E402

from datetime import datetime  # noqa: E402

NOW = datetime.now().astimezone()

# 技术特征缓存（url → tech_feature，避免重复调用 LLM）
_TF_CACHE_PATH = ROOT / "data" / "tech-feature-index.json"
tf_cache: dict[str, str] = {}
if _TF_CACHE_PATH.exists():
    try:
        tf_cache = json.loads(_TF_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        tf_cache = {}

# 韧性（2026-08-23 迁移被杀后补）：缓存定期落盘 + 进度输出，断点续跑
_SAVED = 0


def save_tf_cache(force: bool = False) -> None:
    """tf_cache 定期写盘：每 10 条新增自动保存；force=True 无条件保存。"""
    global _SAVED
    if not tf_cache:
        return
    if force or len(tf_cache) - _SAVED >= 10:
        _TF_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _TF_CACHE_PATH.write_text(json.dumps(tf_cache, ensure_ascii=False, indent=1), encoding="utf-8")
        _SAVED = len(tf_cache)
        print(f"  [cache] 已落盘 {len(tf_cache)} 条技术特征缓存", flush=True)


def _prefill_cache_from_history() -> int:
    """从 history.json 预填充技术特征缓存（url → tech_feature，空存"无"）。

    目的：latest-24h.json 等文件与 history.json 条目大量重叠，预填充后
    全部缓存命中，避免对同一 URL 重复调用 LLM（2026-08-23 实测教训：
    仅缓存"有特征"导致 24h 文件重复提取，白白浪费数百次调用）。
    """
    path = ROOT / "data" / "history.json"
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    items = data.get("items", data) if isinstance(data, dict) else data
    added = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        if it.get("dimension") == "政策":
            continue
        # 缓存 key 统一用规范化标题（2026-08-23：Google News 聚合 URL 每次抓取不同，
        # 按 URL 缓存永不命中；与 update_news.py 的 key 规则一致）
        _tk = _title_key(it.get("title", "")) or it.get("url", "")
        if not _tk or _tk in tf_cache:
            continue
        tf_cache[_tk] = it.get("tech_feature") or "无"
        added += 1
    return added


def _title_key(title: str) -> str:
    """与 update_news.py 的 _title_dedup_key 同规则（去空白/标点/小写，前 120 字符）。"""
    import re as _re
    t = _re.sub(r"[\s\u3000\-_—–()（）【】\[\]「」『』・,，.。:：;；/\\|]", "", (title or "").lower())
    return t[:120]


def migrate_file(path: Path) -> int:
    if not path.exists():
        print(f"  跳过（不存在）: {path.name}")
        return 0
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    changed = 0
    kept: list[dict] = []
    removed = 0
    n = len(items)
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            continue
        try:
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
            # 技术特征提取（2026-08-23 新增）：仅 Layer 2/3，用缓存避免重复调用 LLM
            if "tech_feature" not in it:
                it["tech_feature"] = ""
            if dim != "政策" and not it.get("tech_feature"):
                _tf_url = it.get("url", "")
                _tf_key = _title_key(it.get("title", "")) or _tf_url
                if _tf_key in tf_cache:
                    _tf = tf_cache[_tf_key]  # 命中（含"无"），不再调 LLM
                else:
                    _tf = tf.extract_tech_feature(it.get("title", ""), it.get("summary", ""))
                    tf_cache[_tf_key] = _tf or "无"  # 空串也缓存为"无"，避免重复调用
                    save_tf_cache()
                if _tf and _tf != "无":
                    it["tech_feature"] = _tf
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
        except Exception as e:  # 单条异常隔离：记录并跳过，不崩整个迁移
            print(f"  [skip] 第 {i}/{n} 条异常: {e} | {it.get('url', '')[:80]}", flush=True)
            kept.append(it)
        if i % 50 == 0:
            print(f"  {path.name}: 进度 {i}/{n}", flush=True)
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
    print("三层分类迁移（2026-08-26 v5.0：政策/创新/产业 + 七细类 + AI 分流 + 技术特征）", flush=True)
    _pre = _prefill_cache_from_history()
    print(f"  预填充技术特征缓存 {_pre} 条（从 history.json，含\"无\"）", flush=True)
    total = 0
    for fn in ("history.json", "latest-24h.json", "latest-24h-all.json"):
        try:
            total += migrate_file(ROOT / "data" / fn)
        except Exception as e:  # 文件级异常隔离：单文件失败不阻塞后续文件
            print(f"  [warn] {fn} 迁移中断: {e}", flush=True)
        save_tf_cache(force=True)  # 每文件处理完强制落盘缓存（断点续跑）
    print(f"完成，共 {total} 条维度变化，技术特征缓存 {len(tf_cache)} 条", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
