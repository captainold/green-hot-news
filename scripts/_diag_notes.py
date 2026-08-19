#!/usr/bin/env python3
"""_diag_notes.py — 服务器 Notes git 状态 + 中国能源报正文统计"""
import re
from pathlib import Path

print("=== Notes git status ===")
import subprocess
r = subprocess.run(
    ["git", "-C", "/opt/green-hot-news/Notes", "status", "--porcelain"],
    capture_output=True, text=True)
print(r.stdout[:1500] or "(clean)")
r2 = subprocess.run(
    ["git", "-C", "/opt/green-hot-news/Notes", "rev-parse", "--abbrev-ref", "HEAD"],
    capture_output=True, text=True)
print("branch:", r2.stdout.strip())
r3 = subprocess.run(
    ["git", "-C", "/opt/green-hot-news/Notes", "log", "--oneline", "-3"],
    capture_output=True, text=True)
print(r3.stdout)

print("\n=== 中国能源报 Notes 正文统计 ===")
notes_dir = Path("/opt/green-hot-news/Notes/媒体库/中国能源报")
files = list(notes_dir.glob("*.md")) if notes_dir.exists() else []
no_body = []
for f in files:
    c = f.read_text(encoding="utf-8", errors="ignore")
    if "## 正文" not in c:
        no_body.append(f.name)
print(f"笔记 {len(files)}, 缺正文 {len(no_body)}")
for n in no_body[:5]:
    print("  ", n)
