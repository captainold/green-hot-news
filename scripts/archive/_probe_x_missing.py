#!/usr/bin/env python3
"""_probe_x_missing.py — 诊断未出现的 4 个 X 账号"""
import sys
import requests

sys.path.insert(0, "scripts")
import update_news as un

for h in ["EUClimateAction", "WBG_Climate", "EmberClimate", "ReutersEnergy"]:
    try:
        r = requests.get(f"https://x.com/{h}", timeout=20, headers=un.X_PAGE_HEADERS)
        tweets = un.parse_x_tweets(r.text, h)
        print(f"@{h}: status={r.status_code} len={len(r.text)} 推文={len(tweets)}")
        for t in tweets[:3]:
            hit = un.is_policy_relevant(t["text"], t["url"], "x", t["text"][:500])
            print(f"   [hit={hit}] {t['text'][:110]}")
    except Exception as e:
        print(f"@{h}: ERROR {type(e).__name__}: {e}")
