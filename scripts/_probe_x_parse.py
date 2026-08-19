#!/usr/bin/env python3
"""_probe_x_parse.py — 验证 x.com 账号页 SSR HTML → 结构化推文解析

用 bs4 按 schema.org 结构解析：identifier(推文ID)/datePublished/url/text/author。
输出每条推文的 {id, handle, name, url, published_at, text, likes, retweets}。

用法：python3.11 scripts/_probe_x_parse.py [handle ...]
"""
import sys
import re
import requests
from bs4 import BeautifulSoup

HANDLES = ["IEA", "IRENA", "UNFCCC", "KHayhoe", "fbirol"]

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}


def parse_tweets(html: str, handle: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    posts = soup.find_all(attrs={"itemtype": "https://schema.org/SocialMediaPosting"})
    out = []
    for p in posts:
        def meta(prop: str) -> str:
            m = p.find(attrs={"itemprop": prop})
            if m and m.get("content"):
                return m["content"]
            return ""
        author_block = p.find(attrs={"itemprop": "author"})
        a_handle = ""
        a_name = ""
        if author_block:
            hm = author_block.find(attrs={"itemprop": "alternateName"})
            nm = author_block.find(attrs={"itemprop": "name"})
            a_handle = hm.get("content", "") if hm else ""
            a_name = nm.get("content", "") if nm else ""
        likes = retweets = 0
        for stat in p.find_all(attrs={"itemprop": "interactionStatistic"}):
            it = stat.find(attrs={"itemprop": "interactionType"})
            cnt = stat.find(attrs={"itemprop": "userInteractionCount"})
            if not it or not cnt or not cnt.get("content"):
                continue
            t = it.get("content", "").rsplit("/", 1)[-1]
            try:
                n = int(cnt["content"])
            except (TypeError, ValueError):
                continue
            if "Like" in t:
                likes = n
            elif "Share" in t or "Repost" in t:
                retweets = n
        tid = meta("identifier")
        text = meta("text") or ""
        text = re.sub(r"\s+", " ", text).strip()
        out.append({
            "id": tid,
            "handle": a_handle or handle,
            "name": a_name,
            "url": f"https://x.com/{a_handle or handle}/status/{tid}" if tid else "",
            "published_at": meta("datePublished") or meta("dateCreated"),
            "text": text,
            "likes": likes,
            "retweets": retweets,
        })
    return out


def main() -> None:
    handles = sys.argv[1:] or HANDLES
    total = 0
    for h in handles:
        try:
            r = requests.get(f"https://x.com/{h}", timeout=20, headers=HEADERS)
            r.raise_for_status()
            tweets = parse_tweets(r.text, h)
            total += len(tweets)
            print(f"\n=== @{h}  ({r.status_code}, {len(r.text)} bytes, {len(tweets)} 条推文) ===")
            for t in tweets:
                likes = t["likes"] or "-"
                rt = t["retweets"] or "-"
                print(f"  [{t['published_at']}] {t['url']}  ♥{likes} ↻{rt}")
                print(f"    {t['text'][:150]}")
        except Exception as e:
            print(f"\n=== @{h}  ✗ {type(e).__name__}: {e} ===")
    print(f"\n共解析 {total} 条推文")


if __name__ == "__main__":
    main()
