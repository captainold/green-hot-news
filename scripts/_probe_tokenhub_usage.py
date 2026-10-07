#!/usr/bin/env python3.11
"""临时探测：TokenHub（localhost:8080）有没有"用量/计费"只读端点，用来校准成本推算。

背景（2026-09-23 复盘问题④）：方案里的 $0.0005/次判定、$20.5/月 都是**文档推算**，没有平台数据校准。
本脚本只读（GET），把一个候选端点清单挨个试，打印命中的端点与样例字段；不创建任何资源、不打印明文 key。

用法：python3.11 scripts/_probe_tokenhub_usage.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

ENV = Path("C:/Users/wenyu/Platform/net/tokenhub/deploy/.env")
BASE = "http://localhost:8080"
SESSION = requests.Session()
SESSION.trust_env = False           # localhost 绝不走 mihomo

CANDIDATES = [
    "/api/admin/usage/summary",
    "/api/admin/usage",
    "/api/admin/stats",
    "/api/admin/logs?limit=2",
    "/api/admin/request-logs?limit=2",
    "/api/admin/dashboard",
]


def load_admin_token() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("TOKENHUB_ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


def snippet(payload, limit: int = 220) -> str:
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except Exception:
        text = str(payload)
    return text[:limit]


def main() -> int:
    tok = load_admin_token()
    if not tok:
        print("未找到 TOKENHUB_ADMIN_TOKEN")
        return 2
    hdr = {"Authorization": f"Bearer {tok}"}
    print(f"探测 {len(CANDIDATES)} 个候选端点（{BASE}，只读 GET）\n")
    hits = []
    for path in CANDIDATES:
        try:
            r = SESSION.get(BASE + path, headers=hdr, timeout=20)
        except Exception as exc:
            print(f"  {path:<52} EXC {type(exc).__name__}: {exc}")
            continue
        if r.status_code == 200:
            try:
                body = r.json()
            except Exception:
                body = r.text
            print(f"  {path:<52} 200 ← 命中")
            print(f"      {snippet(body)}")
            hits.append(path)
        else:
            print(f"  {path:<52} {r.status_code}")

    # 本项目 key 的用量明细（这是校准成本的关键：真实 token 数 + 请求数）
    key_id = ""
    try:
        r = SESSION.get(BASE + "/api/admin/api-keys", headers=hdr, timeout=20)
        if r.status_code == 200:
            keys = r.json().get("data") or r.json().get("items") or []
            for k in keys:
                if str(k.get("name", "")).startswith("green-hot-news"):
                    key_id = k.get("id", "")
                    print(f"\n本项目 key：{k.get('name')} → {key_id}（创建 {str(k.get('created_at'))[:19]}）")
                    break
            if not key_id:
                print(f"\n未在 {len(keys)} 个 key 里找到 green-hot-news")
    except Exception as exc:
        print(f"\n列 key 失败：{type(exc).__name__}: {exc}")

    if key_id:
        path = f"/api/admin/api-keys/{key_id}/usage"
        try:
            r = SESSION.get(BASE + path, headers=hdr, timeout=30)
            print(f"\nGET {path} → {r.status_code}（默认近 30 天）")
            if r.status_code == 200:
                body = r.json()
                print("  summary :", snippet(body.get("summary"), 400))
                print("  models  :", snippet(body.get("models"), 400))
                print("  errors  :", snippet(body.get("errors"), 300))
                print("  time    :", snippet(body.get("range"), 200))
                hits.append(path)
        except Exception as exc:
            print(f"  用量查询异常：{type(exc).__name__}: {exc}")

    print(f"\n命中 {len(hits)} 个：{hits}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
