#!/usr/bin/env python3
"""修复 3 篇被跳转页标题污染的生态环境部笔记（2026-08-11）。

backfill_full_titles 抓取时 mee.gov.cn 返回跳转提示页，h1 被提取为
"您访问的链接即将离开生态环境部门户网站，是否继续？"。正确标题
从网页 h2（正文标题）确认。本脚本用正确标题替换并重命名。
"""
import re
from pathlib import Path

FIXES = {
    "https://www.mee.gov.cn/ywdt/xwfb/202607/t20260728_1163004.shtml": "7月例行新闻发布会最新情况通报",
    "https://www.mee.gov.cn/ywdt/xwfb/202607/t20260729_1163032.shtml": "7月例行新闻发布会答问实录",
    "https://www.mee.gov.cn/ywdt/xwfb/202607/t20260731_1163302.shtml": "生态环境部发布8月上半月全国空气质量预报会商结果",
}

DIR = Path("Notes/政策库/中国/生态环境部")


def main() -> None:
    fixed = 0
    for fp in DIR.glob("*.md"):
        txt = fp.read_text(encoding="utf-8")
        m = re.search(r"^url:\s*(\S+)", txt, re.M)
        if not m or m.group(1) not in FIXES:
            continue
        correct = FIXES[m.group(1)]
        # 替换正文标题
        new_txt = re.sub(r"^# .+$", f"# {correct}", txt, count=1, flags=re.M)
        # 清掉跳转提示残留（正文里若有）
        new_txt = new_txt.replace("您访问的链接即将离开生态环境部门户网站，是否继续？", "")
        fp.write_text(new_txt, encoding="utf-8")
        # 重命名
        date_pref = re.match(r"^(\d{4}-\d{2}-\d{2} )", fp.name)
        new_name = (date_pref.group(1) if date_pref else "") + correct + ".md"
        new_fp = fp.with_name(new_name)
        if new_name != fp.name and not new_fp.exists():
            fp.rename(new_fp)
        fixed += 1
        print(f"修复: {fp.name[:45]} → {correct[:35]}")
    print(f"\n修复 {fixed} 篇")


if __name__ == "__main__":
    main()
