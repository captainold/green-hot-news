#!/usr/bin/env python3.11
"""临时探测：直查本地 TokenHub（localhost:8080）管理 API，找出 typesafe 渠道 / 对外模型 / 可用 key。

只读（GET），不创建任何资源。admin token 从 tokenhub/deploy/.env 读取，不打印明文。
用法：python3.11 scripts/_probe_tokenhub_api.py
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

# 本机有 http_proxy/HTTPS_PROXY（mihomo）——localhost 绝不能走代理，否则每次请求超时/绕远
SESSION = requests.Session()
SESSION.trust_env = False


def load_admin_token() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("TOKENHUB_ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


def mask(v: str) -> str:
    v = str(v or "")
    return f"{v[:8]}…{v[-4:]}" if len(v) > 14 else v[:4] + "…"


def get(path: str, tok: str):
    try:
        r = requests.get(BASE + path, headers={"Authorization": f"Bearer {tok}"}, timeout=15)
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:200]}"
    try:
        return r.json(), ""
    except Exception as exc:
        return None, f"非 JSON: {exc}"


def rows(payload) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "items", "providers", "models", "keys", "projects", "results"):
            v = payload.get(k)
            if isinstance(v, list):
                return v
            if isinstance(v, dict) and isinstance(v.get("items"), list):
                return v["items"]
    return []


def main() -> int:
    tok = load_admin_token()
    if not tok:
        print("未找到 TOKENHUB_ADMIN_TOKEN")
        return 1
    print(f"admin token: {mask(tok)}（来自 {ENV.name}）\n")

    # 健康检查
    try:
        h = requests.get(BASE + "/healthz", timeout=8)
        print(f"GET /healthz → {h.status_code} {h.text[:120]}")
    except Exception as exc:
        print(f"/healthz 失败：{exc}")

    # 1) providers
    prov, err = get("/api/admin/providers", tok)
    if err:
        print(f"providers 失败：{err}")
        return 1
    plist = rows(prov)
    print(f"\n=== Providers {len(plist)} 个 ===")
    for p in plist:
        blob = json.dumps(p, ensure_ascii=False).lower()
        mark = "  <== typesafe/jev" if ("typesafe" in blob or "jev" in blob) else ""
        print(f"  id={p.get('id','')[:26]:<28} type={str(p.get('type') or p.get('provider_type') or ''):<18}"
              f"status={str(p.get('status') or ''):<9} name={str(p.get('name') or '')[:22]:<24}"
              f"base={str(p.get('base_url') or '')[:38]}{mark}")

    ts = [p for p in plist if "typesafe" in json.dumps(p, ensure_ascii=False).lower()
          or "jev" in json.dumps(p, ensure_ascii=False).lower()]
    print(f"\n=== 命中 typesafe 的 Provider {len(ts)} 个 ===")
    for p in ts:
        print(json.dumps(p, ensure_ascii=False, indent=1)[:1500])

    # 2) provider models（上游模型清单）
    pm, err = get("/api/admin/provider-models", tok)
    print("\n=== 上游模型（provider-models）中命中 typesafe/jev 的 ===")
    if err:
        print(f"  失败：{err}")
    else:
        pml = rows(pm)
        hits = [m for m in pml if "jev" in json.dumps(m, ensure_ascii=False).lower()
                or "typesafe" in json.dumps(m, ensure_ascii=False).lower()]
        print(f"  共 {len(pml)} 条，命中 {len(hits)} 条")
        for m in hits[:20]:
            print("  " + json.dumps(m, ensure_ascii=False)[:400])

    # 3) 对外模型目录
    for path in ("/api/admin/models", "/api/admin/model-directory", "/api/admin/routes",
                 "/api/admin/routing-policies"):
        data, err = get(path, tok)
        if err:
            print(f"\n{path} → {err}")
            continue
        lst = rows(data)
        hits = [m for m in lst if "jev" in json.dumps(m, ensure_ascii=False).lower()
                or "typesafe" in json.dumps(m, ensure_ascii=False).lower()]
        print(f"\n{path} → {len(lst)} 条，命中 typesafe/jev {len(hits)} 条")
        for m in hits[:20]:
            print("  " + json.dumps(m, ensure_ascii=False)[:500])

    # 4) 项目与 key
    prj, err = get("/api/admin/projects", tok)
    print("\n=== 项目与 API Key（key 掩码） ===")
    if err:
        print(f"  项目失败：{err}")
    else:
        for p in rows(prj):
            pid = p.get("id") or p.get("project_id") or ""
            print(f"  project {pid} name={p.get('name')}")
            ks, kerr = get(f"/api/admin/projects/{pid}/keys", tok)
            if kerr:
                print(f"    keys: {kerr}")
                continue
            for k in rows(ks):
                kk = dict(k)
                for f in ("api_key", "key", "token", "secret"):
                    if f in kk:
                        kk[f] = mask(kk[f])
                print("    " + json.dumps(kk, ensure_ascii=False)[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main())
