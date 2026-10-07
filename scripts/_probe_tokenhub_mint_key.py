#!/usr/bin/env python3.11
"""一次性配给：在本地 TokenHub 里为 green-hot-news 签发一把项目级 API Key，并写入项目 .env。

• 只走管理 API（POST /api/admin/projects/prj_default/keys），admin token 从 tokenhub/deploy/.env 读，不打印
• 明文 key 只在创建响应里出现一次：本脚本直接落 C:\\Users\\wenyu\\Documents\\Obsidian_wen\\green-hot-news\\.env
  （.env 已确认在 .gitignore 中），终端只打印掩码
• 幂等：.env 里已有 JEV_API_KEY 则直接退出，不重复签发

用法：python3.11 scripts/_probe_tokenhub_mint_key.py [--name green-hot-news] [--force]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

TH_ENV = Path("C:/Users/wenyu/Platform/net/tokenhub/deploy/.env")
BASE = "http://localhost:8080"
PROJECT = "prj_default"
OWNER = "usr_admin"
TARGET_ENV = Path(__file__).resolve().parent.parent / ".env"

SESSION = requests.Session()
SESSION.trust_env = False  # localhost 不走 mihomo 代理


def admin_token() -> str:
    for line in TH_ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("TOKENHUB_ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("未找到 TOKENHUB_ADMIN_TOKEN")


def mask(v: str) -> str:
    return f"{v[:8]}…{v[-4:]}（长度 {len(v)}）" if len(v) > 14 else "…"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="green-hot-news")
    ap.add_argument("--force", action="store_true", help="即使 .env 已有 JEV_API_KEY 也重新签发")
    args = ap.parse_args()

    env_text = TARGET_ENV.read_text(encoding="utf-8") if TARGET_ENV.exists() else ""
    if "JEV_API_KEY=" in env_text and not args.force:
        print(".env 已有 JEV_API_KEY，跳过签发（要重签加 --force）")
        return 0

    tok = admin_token()
    h = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

    # 已有同名 key 就不重复建（明文拿不回来，需要时用 --force 建新的）
    r = SESSION.get(f"{BASE}/api/admin/projects/{PROJECT}/keys", headers=h, timeout=20)
    existing = []
    if r.status_code == 200:
        payload = r.json()
        items = payload.get("items") if isinstance(payload, dict) else payload
        existing = [k for k in (items or []) if k.get("name") == args.name]
    if existing and not args.force:
        print(f"已存在同名 key（{existing[0].get('key_prefix')}…{existing[0].get('key_suffix')}），"
              f"但明文不可回读；如需新 key 请加 --force")
        return 0

    body = {
        "name": args.name,
        "owner_user_id": OWNER,
        "allowed_models": ["TypeSafe/jev-latest", "TypeSafe/jev-preview"],
        "model_access_mode": "allowlist",
    }
    r = SESSION.post(f"{BASE}/api/admin/projects/{PROJECT}/keys", headers=h,
                     data=json.dumps(body), timeout=30)
    if r.status_code >= 300:
        # 回退：不带模型白名单（部分版本字段名/取值不同）
        print(f"带白名单签发失败（HTTP {r.status_code}）：{r.text[:200]}\n回退为默认设置重试…")
        body.pop("allowed_models", None)
        body.pop("model_access_mode", None)
        r = SESSION.post(f"{BASE}/api/admin/projects/{PROJECT}/keys", headers=h,
                         data=json.dumps(body), timeout=30)
    if r.status_code >= 300:
        print(f"签发失败 HTTP {r.status_code}: {r.text[:400]}")
        return 1

    payload = r.json()
    key = ""
    for field in ("api_key", "key", "token", "plaintext_key"):
        if isinstance(payload, dict) and payload.get(field):
            key = str(payload[field])
            break
    if not key:
        for field in ("data", "key_info", "result"):
            sub = payload.get(field) if isinstance(payload, dict) else None
            if isinstance(sub, dict):
                for f2 in ("api_key", "key", "token"):
                    if sub.get(f2):
                        key = str(sub[f2])
                        break
            if key:
                break
    if not key:
        print("响应里没找到明文 key，原始响应（已截断）：")
        print(json.dumps(payload, ensure_ascii=False)[:800])
        return 1

    lines = [
        "",
        "# TokenHub（localhost:8080）TypeSafe/Jev 决策模型——2026-09-23 签发，key 名 green-hot-news",
        "# 走 TokenHub 的 OpenAI 兼容口 /v1/chat/completions，用 typesafe_questions/typesafe_state 扩展字段",
        f"JEV_API_KEY={key}",
        "JEV_BASE_URL=http://localhost:8080",
        "JEV_MODEL=TypeSafe/jev-latest",
        "JEV_DIALECT=tokenhub",
    ]
    with TARGET_ENV.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"已签发并写入 {TARGET_ENV}")
    print(f"  name      = {args.name}")
    print(f"  key       = {mask(key)}")
    print(f"  model     = TypeSafe/jev-latest（上游 jev-latest）")
    print(f"  撤销方式  = TokenHub 控制台 http://localhost:3001 → 项目 → 密钥 → 停用/删除 {args.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
