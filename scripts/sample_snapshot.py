#!/usr/bin/env python3.11
"""抽样快照：把"这一次抽样到底抽了哪几条"落盘，避免同 seed 复现不出同一批。

为什么需要（2026-09-23 复盘问题②）：
    `data/history.json` 每 30 分钟被服务器定时任务重写，条目会增删。
    只靠 `random.seed(N)` 抽样，语料一变，抽出来的就是另一批——
    A/B 对照若跨批就不可比，报告里也说不清"这批是哪份语料上的"。

约定：
    任何抽样脚本（探针/监控/标定）抽样后立刻 `save(tag, rows)`；
    快照落 `data/sample-snapshots/<tag>-<UTC时间戳>.json`，内含语料指纹 + 条目身份（id/title/细类）；
    报告/入档记录里写上快照文件名，事后可逐条核对。

用法：
    from sample_snapshot import save          # 与脚本同目录（scripts/ 已在 sys.path）
    snap = save("jev-probe-n30-seed7", sample, extra={"seed": 7})
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = ROOT / "data" / "sample-snapshots"


def corpus_fingerprint(items: list[dict]) -> dict:
    """语料指纹：条数 + 全部 id 排序后的 sha1 前 12 位（语料一变就变）。"""
    ids = sorted(str(i.get("id", "")) for i in items if isinstance(i, dict))
    h = hashlib.sha1("\n".join(ids).encode("utf-8")).hexdigest()[:12]
    return {"count": len(ids), "ids_sha1_12": h}


def save(tag: str, rows: list[dict], corpus: list[dict] | None = None,
         extra: dict | None = None) -> Path:
    """落盘一次抽样快照，返回文件路径。tag 用于人读（如 jev-probe-n30-seed7）。"""
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in tag)
    path = SNAP_DIR / f"{safe}-{ts}.json"
    payload = {
        "tag": tag,
        "ts": datetime.now(timezone.utc).isoformat(),
        "corpus": corpus_fingerprint(corpus) if corpus is not None else None,
        "sample": len(rows),
        "extra": extra or {},
        "items": [
            {
                "id": r.get("id"),
                "title": (r.get("title_zh") or r.get("title") or "")[:80],
                "sub_dimension": r.get("sub_dimension"),
                "score": r.get("score"),
            }
            for r in rows
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def latest(tag_prefix: str = "") -> Path | None:
    """取最近一次快照（可按 tag 前缀过滤）。"""
    if not SNAP_DIR.exists():
        return None
    cands = sorted(SNAP_DIR.glob("*.json"))
    if tag_prefix:
        cands = [p for p in cands if p.name.startswith(tag_prefix)]
    return cands[-1] if cands else None
