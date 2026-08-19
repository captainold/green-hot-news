#!/usr/bin/env python3
"""_diag_cnenergy3.py — 挑战页内容 + 绕过测试"""
import time
import requests

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
}

# 1. 挑战页内容
r = requests.get("https://www.cnenergynews.cn/article/4SrLqNFARAn", timeout=15, headers=HEADERS)
print("=== 挑战页内容 (986B) ===")
print(r.text)

# 2. 绕过测试
tests = [
    ("带 Referer", {"Referer": "https://www.cnenergynews.cn/"}),
    ("移动版", None, "https://m.cnenergynews.cn/article/4SrLqNFARAn"),
    ("无www", None, "http://cnenergynews.cn/article/4SrLqNFARAn"),
]
for t in tests:
    name = t[0]
    h = dict(HEADERS)
    url = t[2] if len(t) > 2 and t[2] else "https://www.cnenergynews.cn/article/4SrLqNFARAn"
    if len(t) > 1 and t[1]:
        h.update(t[1])
    try:
        rr = requests.get(url, timeout=15, headers=h)
        print(f"{name}: status={rr.status_code} len={len(rr.text)}")
    except Exception as e:
        print(f"{name}: ERROR {type(e).__name__}: {e}")

# 3. requests.Session 带 cookie jar（先访问首页拿 cookie 再抓详情页）
s = requests.Session()
s.headers.update(HEADERS)
try:
    s.get("https://www.cnenergynews.cn/", timeout=15)
    rr = s.get("https://www.cnenergynews.cn/article/4SrLqNFARAn", timeout=15)
    print(f"Session(先首页): status={rr.status_code} len={len(rr.text)}")
except Exception as e:
    print(f"Session: ERROR {type(e).__name__}: {e}")
