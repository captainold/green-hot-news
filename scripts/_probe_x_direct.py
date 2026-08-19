#!/usr/bin/env python3
"""_probe_x_direct.py — 探测 x.com 账号页能否被 requests 直接抓取（服务器/本地双视角）

目的：判断「零成本接入 X 源」是否可行：
  A. requests 直抓 x.com/<handle> 返回什么？（登录墙? 可解析 HTML?）
  B. 若可解析，推文数据在 HTML 哪里？（SSR JSON / meta / script 标签）
  C. nitter 镜像是否还有活口（fallback）

用法：python3.11 scripts/_probe_x_direct.py
"""
import sys
import json
import re
import requests

HANDLES = ["IEA", "IRENA", "UNFCCC"]

def probe_direct(handle: str) -> None:
    url = f"https://x.com/{handle}"
    print(f"\n=== A. requests 直抓 {url} ===")
    try:
        r = requests.get(url, timeout=20, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/126.0 Safari/537.36"),
            "Accept-Language": "en-US,en;q=0.9",
        })
        print(f"  status={r.status_code}  len={len(r.text)}  final_url={r.url}")
        text = r.text
        # 登录墙特征
        if "login" in r.url and r.status_code == 200:
            print("  → 被重定向到登录墙 (login redirect)")
        elif "Sign in to X" in text or "sign in" in text.lower() and len(text) < 200000:
            print("  → 页面含登录提示，疑似登录墙")
        # 推文数据特征：tweet JSON 在 <script data-testid> 或 __NEXT_DATA__ 或 meta
        meta_count = len(re.findall(r'<meta[^>]+property="og:description"', text))
        print(f"  og:description meta 数 = {meta_count}")
        # 找 tweet id 特征（/status/ 数字）
        status_ids = re.findall(r'/status/(\d{15,20})', text)
        print(f"  /status/ 推文链接数 = {len(set(status_ids))}  样例 = {list(set(status_ids))[:3]}")
        # 找 JSON 数据块
        for marker in ['__NEXT_DATA__', 'data-testid="tweet"', '"created_at"', 'timeline']:
            print(f"  '{marker}' 出现次数 = {text.count(marker)}")
        # 保存一份供分析
        with open(f"/tmp/x_probe_{handle}.html", "w", encoding="utf-8") as f:
            f.write(text)
        print(f"  → HTML 已存 /tmp/x_probe_{handle}.html")
    except Exception as e:
        print(f"  ✗ 异常: {e}")

def probe_nitter(handle: str) -> None:
    mirrors = [
        "https://nitter.net",
        "https://nitter.poast.org",
        "https://nitter.privacydev.net",
        "https://nitter.woodland.cafe",
        "https://nitter.tiekoetter.com",
    ]
    print(f"\n=== C. nitter 镜像 {handle} ===")
    for m in mirrors:
        try:
            r = requests.get(f"{m}/{handle}", timeout=12, headers={"User-Agent": "Mozilla/5.0"})
            ok = r.status_code == 200 and ("tweet" in r.text or handle in r.text)
            print(f"  {m:<35} status={r.status_code} len={len(r.text)} ok={ok}")
        except Exception as e:
            print(f"  {m:<35} ✗ {type(e).__name__}")

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "direct"
    if which == "nitter":
        for h in HANDLES[:1]:
            probe_nitter(h)
    else:
        for h in HANDLES:
            probe_direct(h)
