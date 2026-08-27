"""清理 Notes/数据库 重复 url qmd（2026-08-27）：同 url 多文件时保留最新 mtime。

背景：08-26 全量导出后 history.json 的 published_at 被后续 update_news 更新，
_date_of 生成新日期文件名 → 同 url 新旧文件并存（105 组）。旧文件正文是
表格格式（换行问题修复前导出），新文件是修复后格式。保留最新，删旧的。
git 可恢复（Notes 仓库），删除前打印清单。
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "Notes" / "数据库"


def main() -> int:
    dry = "--dry" in sys.argv
    by_url: dict[str, list[Path]] = defaultdict(list)
    for f in DB.glob("*.qmd"):
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'^url: "([^"]+)"', txt, re.MULTILINE)
            if m:
                by_url[m.group(1)].append(f)
        except Exception:
            continue
    dups = {u: fs for u, fs in by_url.items() if len(fs) > 1}
    to_delete: list[Path] = []
    for u, fs in dups.items():
        fs_sorted = sorted(fs, key=lambda x: x.stat().st_mtime)
        to_delete.extend(fs_sorted[:-1])  # 保留最新，删其余
    print(f"重复组 {len(dups)}，待删除 {len(to_delete)} 个文件")
    for f in to_delete:
        print("  DELETE:", f.name[:70])
    if dry:
        print("（dry 模式，未删除）")
        return 0
    for f in to_delete:
        f.unlink()
    print(f"已删除 {len(to_delete)} 个旧文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
