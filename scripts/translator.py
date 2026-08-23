"""腾讯云机器翻译（TMT）——非中文新闻标题翻译成中文。

复用 Rings 项目（同账号）的腾讯云 SecretId/Key（ASR/TTS 同款凭据）。
TMT 免费额度：每月 500 万字符（标准版），新闻标题每条几十字符，绰绰有余。

零新依赖：纯 stdlib 实现 TC3-HMAC-SHA256 签名 + requests 调用。

凭据读取顺序：
  1. 环境变量 TENCENT_SECRET_ID / TENCENT_SECRET_KEY
  2. 本机项目根 .env 的 TENCENT_SECRET_ID / TENCENT_SECRET_KEY
  3. 本机项目根 .env 的 ASR_SECRET_ID / ASR_SECRET_KEY（兼容旧命名）
  4. Rings 项目 backend/.env 的 ASR_SECRET_ID / ASR_SECRET_KEY（同账号复用）
未配置时 translate_title 返回 None（静默降级，不影响抓取主流程）。
"""

from __future__ import annotations

import datetime as dtm
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import requests

# ── 腾讯云 TMT 接口常量 ──────────────────────────────────────────────
_TMT_HOST = "tmt.tencentcloudapi.com"
_TMT_SERVICE = "tmt"
_TMT_ACTION = "TextTranslate"
_TMT_VERSION = "2018-03-21"
_TMT_REGION = "ap-guangzhou"

_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"

# 假名（日语特征）：出现即视为日语，需翻译
_KANA_RE = re.compile(r"[\u3040-\u30ff]")
# CJK 统一汉字（中文特征）
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 拉丁字母
_LATIN_RE = re.compile(r"[A-Za-z]")


def needs_translation(title: str) -> bool:
    """判断标题是否非中文（需要翻译成中文）。

    规则：含假名 → 日语需翻译；含汉字（无假名）→ 中文不翻译；
    其余（含拉丁字母的英文等）→ 需翻译。
    """
    t = (title or "").strip()
    if not t:
        return False
    if _KANA_RE.search(t):
        return True
    if _CJK_RE.search(t):
        return False
    return bool(_LATIN_RE.search(t))


def _load_credentials() -> tuple[str, str]:
    """按优先级读取腾讯云 SecretId/SecretKey，找不到返回 ("", "")。"""
    candidates: list[Path] = []
    # 本机项目根（green-hot-news）
    here = Path(__file__).resolve().parent.parent
    candidates.append(here / ".env")
    # Rings 项目 backend/.env（同账号复用）
    rings = here.parent / "Rings" / "backend" / ".env"
    candidates.append(rings)

    env_map: dict[str, str] = {}
    for p in candidates:
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                env_map.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except Exception:
            continue

    def get(*keys: str) -> str:
        for k in keys:
            if k in env_map and env_map[k]:
                return env_map[k]
            if k in os.environ and os.environ[k]:
                return os.environ[k]
        return ""

    sid = get("TENCENT_SECRET_ID", "ASR_SECRET_ID")
    skey = get("TENCENT_SECRET_KEY", "ASR_SECRET_KEY")
    return sid, skey


def _tc3_sign(secret_id: str, secret_key: str, action: str, version: str,
              region: str, host: str, service: str, payload: str,
              timestamp: int) -> dict[str, str]:
    """TC3-HMAC-SHA256 签名，返回请求头 dict（含 Authorization）。"""
    date = dtm.datetime.utcfromtimestamp(timestamp).strftime("%Y-%m-%d")
    credential_scope = f"{date}/{service}/tc3_request"

    # 1) 规范请求串
    http_method = "POST"
    canonical_uri = "/"
    canonical_querystring = ""
    ct = "application/json; charset=utf-8"
    canonical_headers = (
        f"content-type:{ct}\nhost:{host}\nx-tc-action:{action.lower()}\n"
    )
    signed_headers = "content-type;host;x-tc-action"
    hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    canonical_request = "\n".join([
        http_method, canonical_uri, canonical_querystring,
        canonical_headers, signed_headers, hashed_payload,
    ])

    # 2) 待签名字符串
    algorithm = "TC3-HMAC-SHA256"
    hashed_canonical_request = hashlib.sha256(
        canonical_request.encode("utf-8")).hexdigest()
    string_to_sign = "\n".join([
        algorithm, str(timestamp), credential_scope, hashed_canonical_request,
    ])

    # 3) 派生签名密钥 + 计算签名
    def _hmac(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    secret_date = _hmac(("TC3" + secret_key).encode("utf-8"), date)
    secret_service = _hmac(secret_date, service)
    secret_signing = _hmac(secret_service, "tc3_request")
    signature = hmac.new(
        secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    authorization = (
        f"{algorithm} Credential={secret_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    return {
        "Authorization": authorization,
        "Content-Type": ct,
        "Host": host,
        "X-TC-Action": action,
        "X-TC-Version": version,
        "X-TC-Timestamp": str(timestamp),
        "X-TC-Region": region,
    }


# 服务级短路标记：一旦检测到服务未开通/未授权/额度耗尽，后续调用直接返回
# None，避免每条标题都白打一次请求（2026-08-18）。
_SERVICE_DISABLED = False
_DISABLE_CODES = (
    "AuthFailure.UnauthorizedOperation",
    "AuthFailure.SignatureFailure",
    "AuthFailure.InvalidSecretId",
    "UnsupportedOperation.PkgExhausted",
)


def translate_text(text: str, source: str = "auto",
                   target: str = "zh", _retry: int = 0) -> Optional[str]:
    """调用腾讯云 TMT 翻译单段文本，失败返回 None。

    RequestLimitExceeded（QPS 限流）会自动退避重试（免费版默认 QPS=5，
    并发稍高就限流 — 2026-08-18 实测）。
    """
    global _SERVICE_DISABLED
    text = (text or "").strip()
    if not text:
        return None
    if _SERVICE_DISABLED:
        return None
    sid, skey = _load_credentials()
    if not sid or not skey:
        return None

    payload = json.dumps({
        "SourceText": text,
        "Source": source,
        "Target": target,
        "ProjectId": 0,
    })
    timestamp = int(dtm.datetime.now().timestamp())
    headers = _tc3_sign(sid, skey, _TMT_ACTION, _TMT_VERSION, _TMT_REGION,
                        _TMT_HOST, _TMT_SERVICE, payload, timestamp)
    try:
        r = requests.post(
            f"https://{_TMT_HOST}",
            headers=headers, data=payload, timeout=(10, 20),
        )
        r.raise_for_status()
        data = r.json()
        resp = data.get("Response", {})
        if "Error" in resp:
            code = resp["Error"].get("Code", "")
            if code in _DISABLE_CODES:
                _SERVICE_DISABLED = True  # 服务未开通/额度耗尽，短路
                return None
            # 限流/瞬时错误 → 退避重试（最多 2 次）
            if code in ("RequestLimitExceeded", "InternalError",
                        "FailedOperation.ServiceIsolate") and _retry < 2:
                time.sleep(0.5 * (_retry + 1))
                return translate_text(text, source, target, _retry + 1)
            return None
        out = resp.get("TargetText", "").strip()
        # 清理作者署名残留（X平台推文翻译后残留 "✍️ Written by @xxx" 等，2026-08-23）
        out = re.sub(r"\s*[✍️🖊️✒️]?\s*Written by\s+@?\S+.*$", "", out).strip()
        return out or None
    except Exception:
        if _retry < 1:
            time.sleep(0.5)
            return translate_text(text, source, target, _retry + 1)
        return None


# ── 标题翻译缓存（内存 + data/translation-cache.json）───────────────
_cache: dict[str, str] = {}
_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "translation-cache.json"


def _load_cache() -> dict[str, str]:
    global _cache
    if _cache:
        return _cache
    try:
        if _CACHE_PATH.exists():
            _cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        _cache = {}
    return _cache


def _save_cache() -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps(_cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:
        pass


def translate_title(title: str, use_cache: bool = True) -> Optional[str]:
    """翻译标题；非中文才翻译，失败/已中文返回 None。"""
    t = (title or "").strip()
    if not t or not needs_translation(t):
        return None
    if use_cache:
        cache = _load_cache()
        if t in cache:
            return cache[t]
    out = translate_text(t)
    if out:
        _cache[t] = out
        if use_cache:
            _save_cache()
    return out
