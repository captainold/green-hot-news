#!/usr/bin/env python3
"""把 update_news.py 里所有含 OR 的 Google News query 拆成单主题词 query（2026-08-19）。

背景：实测 Google News 括号 OR 语法（site:x (a OR b) when:7d）返回该站全站混合内容，
绿色命中率 <10%；单主题词 query（site:x a when:7d）返回 70-90% 相关内容。
本脚本把每个 OR query 拆成 N 条单主题词 query，保留原 when 窗口。

用法：python3.11 scripts/_split_or_queries.py
（修改前自动备份 update_news.py 到 /tmp/）
"""
import re
import shutil
from pathlib import Path

P = Path('scripts/update_news.py')
bak = Path('/tmp/update_news_pre_or_split.py')
shutil.copy2(P, bak)

src = P.read_text(encoding='utf-8')

QUERY_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def split_query(q: str) -> list[str]:
    """把一个 OR query 拆成单主题词 query 列表。非 OR 原样返回。"""
    if ' OR ' not in q:
        return [q]
    # 提取 when 后缀
    when_m = re.search(r'\s+when:\d+d\s*$', q)
    when = when_m.group(0).strip() if when_m else ''
    body = q[:when_m.start()].strip() if when_m else q.strip()
    # 提取 site: 前缀
    site = ''
    m = re.match(r'^(site:[^\s]+)\s+(.*)$', body)
    if m:
        site, body = m.group(1), m.group(2)
    # 去掉整段括号（若有）
    body = body.strip()
    if body.startswith('(') and body.endswith(')'):
        body = body[1:-1].strip()
    # 拆 OR；引号短语（"goldman sachs"）保持整体
    parts = [p.strip() for p in re.split(r'\s+OR\s+', body) if p.strip()]
    out = []
    for part in parts:
        newq = site
        if newq:
            newq += ' '
        newq += part
        if when:
            newq += f' {when}'
        out.append(newq)
    return out


count = 0


def repl(m):
    global count
    q = m.group(1)
    if ' OR ' not in q:
        return m.group(0)
    splits = split_query(q)
    count += 1
    if len(splits) == 1:
        return m.group(0)
    return '"' + '",\n        "'.join(splits) + '"'


new_src = QUERY_RE.sub(repl, src)
P.write_text(new_src, encoding='utf-8')
print(f'备份: {bak}')
print(f'转换 OR query 数: {count}')
print('完成。请运行 py_compile 验证语法。')
