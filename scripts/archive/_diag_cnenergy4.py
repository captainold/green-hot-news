#!/usr/bin/env python3
"""_diag_cnenergy4.py — __tst_status 挑战 cookie 解码绕过验证"""
import re
import requests

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
}
URL = "https://www.cnenergynews.cn/article/4SrLqNFARAn"


def solve_challenge(html: str) -> str | None:
    """解析 __tst_status 挑战脚本 → 返回 cookie 串（失败 None）"""
    # e={WTKkN:<n1>,bOYDu:<n2>,...,wyeCN:<n3>,...}
    m1 = re.search(r"WTKkN:(\d+),bOYDu:(\d+).*?wyeCN:(\d+)", html)
    # EO_Bot_Ssid 值：case"3":t=a[...](t,<n4>)
    m2 = re.search(r'\(t,(\d+)\)', html)
    if not m1 or not m2:
        return None
    n1, n2, n3 = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
    n4 = int(m2.group(1))
    t = n1 + n2 + n3
    return f"__tst_status={t}#; EO_Bot_Ssid={n4};"


# 第一步：拿挑战页
r1 = requests.get(URL, timeout=15, headers=HEADERS)
print(f"第一次: status={r1.status_code} len={len(r1.text)}")
with open("/tmp/challenge.html", "w", encoding="utf-8") as f:
    f.write(r1.text)
print("挑战页已存 /tmp/challenge.html")
cookie = solve_challenge(r1.text)
print(f"解出 cookie: {cookie}")
if not cookie:
    print("!! 解码失败，正则没匹配")
    print(r1.text[:500])
else:
    # 第二步：带 cookie 重请求
    h2 = dict(HEADERS)
    h2["Cookie"] = cookie
    r2 = requests.get(URL, timeout=15, headers=h2)
    print(f"带 cookie: status={r2.status_code} len={len(r2.text)}")
    if len(r2.text) > 5000:
        # 检查是否正文页
        for marker in ["碳排放", "计量", "article", "正文", "content"]:
            if marker in r2.text:
                print(f"  ✓ 含正文特征 '{marker}'")
                break
        # 尝试提取标题
        import re as _re
        m = _re.search(r"<title>([^<]{5,80})</title>", r2.text)
        if m:
            print(f"  title: {m.group(1)}")
    else:
        print("  仍是被拦页面，解码不对或需更多处理")
        print(r2.text[:300])
