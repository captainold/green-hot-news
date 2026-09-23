#!/usr/bin/env python3
"""移除政策库笔记中的碳交易网反爬水印。

水印特征：以 本`文/本文/夲呅/禸嫆/内/容 开头，中间含"碳"和"网/網"，
以域名尾巴 (c...o...m 各种变体) 结尾，如 "tan pai fang . com"。

用法:
  python3 scripts/strip_watermark.py --dry-run   # 预览匹配
  python3 scripts/strip_watermark.py             # 实际清理
"""
import argparse
import os
import re
import sys

ROOT = 'Notes/政策库'

# 水印正则：匹配 本文开头变体 → 碳 → 网/網 → 域名尾巴(c...o...m 变体)
# 变体示例:
#   本`文@内-容-来-自；中^国_碳0排0放^交-易=网 ta n pa i fa ng . co m
#   夲呅內傛莱源亍：ф啯碳*排*放^鲛*易-網 τā ńｐāīｆāńɡ.ｃōｍ
#   内/容/来/自:中-国-碳-排-放*交…易-网-tan pai fang . com
#   本`文内.容.来.自：中`国`碳`排*放*交*易^网 t a npai fan g.c om
_COM = r'(?:c[\s\.]*o[\s\.]*m|ｃ[\s\.]*ｏ[\s\.]*ｍ|ｃ[\s\.]*ō[\s\.]*ｍ)'
WM = re.compile(
    r'(?:本[\`\+%@$#\/\*]*文|本文|夲呅|禸嫆|内|內|容)'
    r'[^\n]{0,150}?'
    r'碳'
    r'[^\n]{0,150}?'
    r'(?:网|網)'
    r'[^\n]{0,150}?'
    + _COM
)
# 异体字水印：禸嫆@唻洎：狆國湠棑倣茭昜蛧 τāńｐāīｆāńɡ.ｃōｍ（无"碳"字，全角伪域名结尾）
WM_ALT = re.compile(
    r'禸\*?嫆[^\n]{0,120}?'
    r'(?:ｃ[\s\.]*ｏ[\s\.]*ｍ|ｃ[\s\.]*ō[\s\.]*ｍ)'
)
# 截断水印（summary 被截断 / YAML 修复截断，无 com 结尾）：
#   本`文-内.容.来.'   | 本/文-...网-tan pai fang .'  | 本%文$...网^t an pa i fang .'
# 匹配从水印开头到行尾/引号前（不吃后面正常正文）
WM_TRUNC = re.compile(
    r'(?:本[\`\+%@$#\/\*]*文|本文|夲呅|禸\*?嫆)'
    r'[^\n]{0,150}?'
    r'(?:来|來|唻)'
    r'[^\n]{0,100}?'
    r'(?:自|洎|亍)?'
    r'[^\n]{0,150}?'
    r'(?:碳)?[^\n]{0,100}?'
    r'(?:网|網)?[^\n]{0,100}?'
    r'(?=$|[\'\"])'
)


def collect_files(root):
    files = []
    for dp, _, fs in os.walk(root):
        for f in fs:
            if f.endswith('.md'):
                files.append(os.path.join(dp, f))
    return sorted(files)


def strip_line(line: str) -> tuple[str, int]:
    """删除一行内所有水印，返回 (新行, 删除个数)。"""
    new, n = WM.subn('', line)
    new, n2 = WM_ALT.subn('', new)
    new, n3 = WM_TRUNC.subn('', new)
    n += n2 + n3
    if n:
        # 清理残留：双空格、行首空白
        new = re.sub(r' {2,}', ' ', new)
        new = new.rstrip()
    return new, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--dir', default=ROOT)
    args = ap.parse_args()
    root = args.dir

    total = 0
    touched = 0
    for fp in collect_files(root):
        try:
            with open(fp, encoding='utf-8') as fh:
                lines = fh.readlines()
        except (UnicodeDecodeError, OSError) as e:
            print(f'!! 跳过 {fp}: {e}', file=sys.stderr)
            continue
        changed = []
        for i, ln in enumerate(lines):
            new, n = strip_line(ln.rstrip('\n'))
            if n:
                changed.append((i + 1, n, ln.rstrip('\n'), new))
                lines[i] = new + '\n'
                total += n
        if changed:
            touched += 1
            print(f'== {fp} ({len(changed)} 行, {sum(c[1] for c in changed)} 处)')
            for lineno, n, old, new in changed:
                print(f'  L{lineno}: {old[:130]}')
                print(f'    -> {new[:130]}')
            if not args.dry_run:
                with open(fp, 'w', encoding='utf-8') as fh:
                    fh.writelines(lines)
    print(f'\n总计: {touched} 文件, {total} 处水印' + (' [DRY-RUN]' if args.dry_run else ' [已清理]'))


if __name__ == '__main__':
    main()
