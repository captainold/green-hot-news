#!/usr/bin/env python3
"""_diag_cnenergy2.py — 服务器裸请求诊断：状态码/耗时/内容特征"""
import time
import requests

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
}

urls = [
    "https://www.cnenergynews.cn/",
    "https://www.cnenergynews.cn/article/4SrLqNFARAn",
    "http://www.cnenergynews.cn/article/4SrLqNFARAn",
]
for u in urls:
    t0 = time.time()
    try:
        r = requests.get(u, timeout=15, headers=HEADERS)
        dt = time.time() - t0
        print(f"{u}\n  status={r.status_code} len={len(r.text)} {dt:.1f}s")
        if r.status_code == 200:
            low = r.text[:2000].lower()
            for marker in ["waf", "验证", "captcha", "访问", "拦截", "403"]:
                if marker.lower() in low:
                    print(f"  特征: 含 '{marker}'")
                    break
    except Exception as e:
        print(f"{u}\n  ERROR {type(e).__name__}: {e} ({time.time()-t0:.1f}s)")
