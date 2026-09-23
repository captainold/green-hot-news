# scripts/archive/ — 一次性脚本归档

> 建立：2026-09-23（项目整理，Phase 2）。规则：本目录脚本为**已完成历史使命的一次性工具**，保留可检索、可复用（改名/适配后可复活），不保证在当前数据结构下可直接运行。

## 归档时的分类

| 前缀/类别 | 数量 | 用途 |
|-----------|------|------|
| `_probe_*` | 18 | 当时的源探测/接口调试 |
| `_diag_*` | 10 | 数据问题诊断 |
| `_fix_*` / `fix_*` | 14 | 存量数据批量修复 |
| `backfill_*` | 12 | 存量回填（一次性跑完） |
| `clean_*` / `dedup_notes*` / `strip_*` 等 | 10 | 素材库清理 |
| `tmp_*` | 3 | 临时统计 |
| 三库合并/实体骨架/迁移 | 8 | 2026-09-14 知识图谱重构 P1/P2（build_entity_skeleton / build_media_entities / merge_libraries / backfill_ontology / fix_paths / _verify_merge / _migrate_qmd_to_md / _dedup_qmd） |
| 其他 | 6 | align_filenames / finalize_notes / recompute_trl / _compare_or_split / _split_or_queries / _rebuild_title_index |

## 复用注意

- 2026-09-15 起素材库为 **.md**（原 .qmd）；本目录脚本多数 glob `*.qmd`，复活时需适配
- update_news.py 本地 import 依赖 `article_content.py` / `translator.py`（仍在 `scripts/` 根）
- 活跃脚本清单以 `AGENTS.md` 与 `docs/服务器部署与运维.md` 引用为准
