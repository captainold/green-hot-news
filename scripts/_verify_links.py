"""双链接结果验证（2026-08-27）：分布统计 + 链接目标存在性抽查。"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "Notes" / "数据库"
CACHE = ROOT / "data" / "qmd-links-cache.json"


def main() -> int:
    c = json.loads(CACHE.read_text(encoding="utf-8"))
    has = sum(1 for v in c.values() if v)
    print(f"缓存 {len(c)} 条，有链接 {has} 条")

    n_rel = 0
    n_dup = 0
    dist = {}
    empty = []
    targets_checked = 0
    targets_missing = 0
    samples = []
    for f in DB.glob("*.qmd"):
        txt = f.read_text(encoding="utf-8", errors="ignore")
        if not txt.startswith("---"):
            continue
        fm = txt.split("---", 2)[1]
        rel_lines = re.findall(r"^related:.*$", fm, re.MULTILINE)
        if not rel_lines:
            continue
        n_rel += 1
        if len(rel_lines) > 1:
            n_dup += 1
        m = re.search(r"related: \[(.*?)\]", fm, re.S)
        if not m:
            continue
        items = re.findall(r'"([^"]+)"', m.group(1))
        dist[len(items)] = dist.get(len(items), 0) + 1
        if not items:
            empty.append(f.name)
        # 抽查链接目标存在性（前 60 个文件）
        if targets_checked < 60:
            tg = re.findall(r"\[\[([^\]]+)\]\]", txt)
            for t in tg:
                targets_checked += 1
                if not (DB / (t + ".qmd")).exists():
                    targets_missing += 1
        if len(samples) < 3 and items:
            samples.append((f.name[:30], items[:4]))
    print(f"qmd 含 related: {n_rel} 个，重复 related 行: {n_dup} 个")
    print(f"每 qmd 链接数分布: {dict(sorted(dist.items()))}")
    print(f"空 related 异常: {len(empty)} 个", empty[:3] if empty else "")
    print(f"抽查链接目标: {targets_checked} 个，缺失 {targets_missing} 个")
    for name, rel in samples:
        print(f"  样例 {name}: {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
