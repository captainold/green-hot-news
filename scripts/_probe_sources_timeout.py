#!/usr/bin/env python3.11
"""探针：逐个测试 BUILTIN_SOURCES 每个源抓取是否超时（找 update_news.py 卡死根因）。

2026-08-23：update_news.py 从 17:32 起每次运行卡死（280s 无输出），
怀疑某个源 requests 无超时/无限挂起。本脚本逐个测（每源 25s 硬超时）。
"""
import importlib.util
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout
from datetime import datetime, timezone

sys.path.insert(0, "scripts")
spec = importlib.util.spec_from_file_location("un", "scripts/update_news.py")
un = importlib.util.module_from_spec(spec)
sys.modules["un"] = un
spec.loader.exec_module(un)

now = datetime.now(timezone.utc)
s = un.create_session()

slow = []
for func, site_id, site_name in un.BUILTIN_SOURCES:
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(func, s, now)
        try:
            items = fut.result(timeout=25)
            dt = time.monotonic() - t0
            mark = "⚠️慢" if dt > 10 else ""
            print(f"{site_id:16s} {len(items):3d} 条  {dt:5.1f}s {mark}")
        except FutTimeout:
            print(f"{site_id:16s}  *** 超时>25s（卡死源！）***")
            slow.append(site_id)
        except Exception as e:
            print(f"{site_id:16s}  异常 {type(e).__name__}: {str(e)[:60]}")
        ex.shutdown(wait=False, cancel_futures=True)
print()
print("卡死源:", slow if slow else "无（都能 25s 内返回）")
