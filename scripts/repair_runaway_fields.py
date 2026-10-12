r"""修复 2026-10-10~12「字段膨胀事故」在存量数据里留下的超长字段。

背景（详见 docs/todo/2026-10-12 代理流量超额与字段膨胀事故复盘.md）：
- summary：写入侧 `export_qmd._yaml_scalar` 每轮把 `\` 转义成 `\\`，读取侧
  `update_news.load_archived_summaries` 原来不回反转义 → 主流程每轮回读+回写一次，
  含反斜杠的摘要就**翻一倍**。实测单条 md：201KB→…→25MB→48MB（每 30min 精确 ×2），
  `data/summary-index.json` 170MB、`data/latest-24h.json` 34.7MB。
- published_at：`_archived_to_iso` 对已是 ISO 的值再追加 `T00:00:00+08:00`，
  每轮追加一段（实测累积 24 段）。

代码侧修复（同批提交）：读侧 `yaml_unscalar` 反转义、`_archived_to_iso` ISO 短路、
三处摘要长度上限（8000，正常摘要最长 ~4600 字）。**磁盘上的存量值不会自己变短**，
本脚本做一次性还原：

1. 反斜杠长串还原：翻倍产物按逆变换折回。
   - 串后不是引号：长度 = m·2^k（偶数）→ 反复折半；
   - 串后是引号：长度 = m·2^k − 1（奇数，末位反斜杠与引号组成 `\"`）→ `(n+1)//2 − 1`。
   实测：千家网 33,554,431 = 2^25−1，中国能源报 2,097,151 = 2^21−1。
2. published_at 尾巴：剥掉重复追加的 `T00:00:00+08:00` 段（并去掉长串）。
3. 超长值截断：summary → 8000 字、published_at → 40 字。

⚠️ 内存约束（服务器 1.8G 内存、2 核）：**全程按行 + 字节级处理**，绝不 json.loads 大文件
（170MB summary-index.json 一次 loads 就把进程 OOM 掉 —— 2026-10-12 实测 exit 137）。
膨胀永远是单条超长行，逐行修即可，峰值内存 ≈ 最大单行（96MB 实测 24 秒跑完）。

派生文件：`summary-index.json / published-index.json / title-index.json /
latest-24h*.json` 都由主流程每轮从素材库重建；超过 `--max-json-mb`（默认 60）的
派生 JSON 直接**备份改名停用**，下轮自动重建，不做就地修复。

用法：
    python scripts/repair_runaway_fields.py                 # dry-run（只报告，默认）
    python scripts/repair_runaway_fields.py --apply         # 真正写盘（先自动备份）
    python scripts/repair_runaway_fields.py --apply --vault-only   # 只修素材库 md
    python scripts/repair_runaway_fields.py --apply --json-only    # 只修 data/*.json

幂等：修完再跑一次应报告 0 处改动。备份：改动的 md/JSON 存
`cache/repair-backup-<ts>/<相对路径>`（素材库 1.6 万文件只备份真改到的几条）。
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import export_qmd as eq  # noqa: E402  SUMMARY_MAX_CHARS / PUBLISHED_MAX_CHARS

DATA = ROOT / "data"
MATERIAL = ROOT / "Notes" / "素材库"
TS = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

SUMMARY_MAX = eq.SUMMARY_MAX_CHARS      # 8000 字
PUBLISHED_MAX = eq.PUBLISHED_MAX_CHARS  # 40 字

ITEM_JSONS = ("history.json", "latest-24h.json", "latest-24h-all.json")
MAP_JSONS = ("summary-index.json", "published-index.json", "title-index.json")

BS = b"\\"
_Q = b'"'
_TAIL_B = re.compile(rb"(?:T00:00:00\+08:00)+$")
# 值里含 `\\` `\"` 以外的转义序列（如 JSON 的 \n / \uXXXX）→ 不动它（避免张冠李戴改坏语义）
_FOREIGN_ESC = re.compile(rb'\\[^\\"]')
# 「异常长串」闸门：翻倍产物的最小可辨形态。正常内容的反斜杠串 ≤3 个（`\\` 转义 + `\"`），
# ≥8 只可能是事故产物 —— 只有命中它才动手还原，避免把正常长行/正常转义当膨胀值误伤
# （2026-10-12 实测：无此闸门会误改 20+ 个正常文件、并把合法长正文当膨胀值截断）。
_BIG_RUN = re.compile(rb"\\{8,}")


# ── 字节级原语（内存有界） ────────────────────────────────────────────────
def _collapse_run(n: int, next_is_quote: bool) -> int:
    """反斜杠长串还原（见模块 docstring §1）。"""
    while n > 1:
        if n % 2 == 0:
            n //= 2
        elif n >= 7 or next_is_quote:
            n = (n + 1) // 2 - 1
        else:
            break
    return 1 if n >= 4 else n


def _map_backslash_runs(s: bytes, fn) -> bytes:
    """按「反斜杠串」为单位的单遍重写：fn(串长, 串后一字节) → (新串, 额外消费字节数 0/1)。

    ⚠️ 不能用 `re.sub`：膨胀值里反斜杠串长达 3,300 万 —— 逐对匹配会产生上千万个小对象，
    实测 MemoryError / RSS 1.4G 被内核 OOM（服务器只有 1.8G 内存，2026-10-12 踩坑）。
    按串处理时回调次数 = 串数（实测单条只有 4 个串），非反斜杠段用 `bytes.find` 整段搬运（C 级），
    峰值内存 ≈ 输入 + 输出。
    """
    BS_BYTE = 0x5C
    out = bytearray()
    i, n = 0, len(s)
    while i < n:
        if s[i] == BS_BYTE:
            j = i
            while j < n and s[j] == BS_BYTE:
                j += 1
            new, eat = fn(j - i, s[j:j + 1])
            out += new
            i = j + eat
            continue
        k = s.find(BS, i)
        if k < 0:
            out += s[i:]
            break
        out += s[i:k]
        i = k
    return bytes(out)


def _collapse_bytes(s: bytes) -> bytes:
    """反斜杠长串还原（逐串折半，见 _collapse_run）。"""
    return _map_backslash_runs(
        s, lambda L, nxt: (BS * _collapse_run(L, nxt == _Q), 0))


def _unescape_bytes(s: bytes) -> bytes:
    r"""反转义 `\\`→`\`、`\"`→`"`（左起两两配对，与 export_qmd.yaml_unscalar 同语义）。

    按串处理：长度为 L 的反斜杠串 →
    - L 偶数：L/2 个反斜杠（两两配对）；
    - L 奇数且后随引号：`(L-1)/2` 个反斜杠 + 引号（末位反斜杠转义了该引号，消费掉原引号）；
    - L 奇数且后随其他：`(L+1)/2` 个反斜杠（末位是普通反斜杠）。
    """
    if BS not in s:
        return s

    def fn(length: int, nxt: bytes) -> tuple[bytes, int]:
        if length % 2 == 0:
            return BS * (length // 2), 0
        if nxt == _Q:
            return BS * ((length - 1) // 2) + _Q, 1     # 消费被转义的引号
        return BS * ((length + 1) // 2), 0

    return _map_backslash_runs(s, fn)


def _cap_chars(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _escape_bytes(text: str) -> bytes:
    r"""单行标量再转义：`\`→`\\`、`"`→`\"`（YAML 双引号 / JSON 字符串同款）。"""
    return text.replace("\\", "\\\\").replace('"', '\\"').encode("utf-8")


def _fix_summary_value(val_bytes: bytes) -> tuple[bytes, bool]:
    """修一个**转义态**的 summary 值（frontmatter 行 / JSON 字符串通用）。

    返回 (新的转义态字节, 是否改动)。
    """
    if not val_bytes or _FOREIGN_ESC.search(val_bytes):
        return val_bytes, False
    logical = _unescape_bytes(val_bytes)
    log_text = logical.decode("utf-8", "replace")
    if not _BIG_RUN.search(val_bytes) and len(log_text) <= SUMMARY_MAX:
        return val_bytes, False          # 无长串且不超长 → 正常值，不动
    logical = _collapse_bytes(logical)
    text = _cap_chars(logical.decode("utf-8", "replace"), SUMMARY_MAX)
    new = _escape_bytes(text)
    return new, new != val_bytes


def _fix_published_value(val_bytes: bytes, escaped: bool) -> tuple[bytes, bool]:
    """修 published_at 值（escaped=True 表示值处于转义态）。

    只在两种明确病征下动手：异常长串、或重复追加的 `T00:00:00+08:00` 尾巴。
    """
    if not val_bytes or (escaped and _FOREIGN_ESC.search(val_bytes)):
        return val_bytes, False
    s = _unescape_bytes(val_bytes) if escaped else val_bytes
    if not (_BIG_RUN.search(s) or _TAIL_B.search(s)):
        return val_bytes, False          # 正常时间戳 → 不动
    s = _collapse_bytes(s)
    s = _TAIL_B.sub(b"", s)
    text = _cap_chars(s.decode("utf-8", "replace"), PUBLISHED_MAX)
    new = _escape_bytes(text) if escaped else text.encode("utf-8")
    return new, new != val_bytes


def _backup(p: Path, root: Path) -> None:
    dst = ROOT / "cache" / f"repair-backup-{TS}" / p.relative_to(root)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dst)


# ── 素材库 md（按行流式） ─────────────────────────────────────────────────
FM_SUMMARY = b"summary: "
FM_PUB = (b"published_at: ", b"published: ")
META_PUB = re.compile("(^> 来源:.*?\\| 发布时间: )(\\S+)".encode("utf-8"))


def repair_vault(apply: bool) -> list[str]:
    """逐行修素材库笔记：frontmatter summary / published 行、meta 行发布时间、超长行。"""
    n_files = n_sum = n_pub = n_body = 0
    biggest: list[tuple[int, str]] = []
    for p in MATERIAL.rglob("*.md"):
        try:
            size = p.stat().st_size
        except OSError:
            continue
        lines: list[bytes] = []
        changed = False
        with open(p, "rb") as fh:
            for raw in fh:
                # 保留原行尾（CRLF 文件只改内容不换行尾 —— 2026-10-12 踩坑：
                # 首版用 read_text() 读（universal newlines 会把 CRLF 归一成 LF），
                # 写回后整库行尾漂移、git diff 变成整文件改动）
                eol = b"\r\n" if raw.endswith(b"\r\n") else b"\n"
                line = raw[:-len(eol)] if raw.endswith(eol) else raw
                if line.startswith(FM_SUMMARY):
                    val = line[len(FM_SUMMARY):].strip()
                    new, ch = _fix_summary_value(val)
                    if ch:
                        n_sum += 1
                        changed = True
                        line = FM_SUMMARY + new
                elif line.startswith(FM_PUB):
                    for key in FM_PUB:
                        if line.startswith(key):
                            val = line[len(key):].strip().strip(b'"')
                            new, ch = _fix_published_value(val, escaped=True)
                            if ch:
                                n_pub += 1
                                changed = True
                                line = key + b'"' + new + b'"'
                            break
                else:
                    mt = META_PUB.search(line)
                    if mt:
                        new, ch = _fix_published_value(mt.group(2), escaped=False)
                        if ch:
                            changed = True
                            line = line[:mt.start(2)] + new + line[mt.end(2):]
                    elif _BIG_RUN.search(line):
                        new = _collapse_bytes(line)
                        new = _cap_chars(new.decode("utf-8", "replace"), SUMMARY_MAX).encode("utf-8")
                        if new != line:
                            n_body += 1
                            changed = True
                            line = new
                lines.append(line + eol)
        if not changed:
            continue
        n_files += 1
        biggest.append((size, str(p.relative_to(MATERIAL))))
        if apply:
            _backup(p, MATERIAL)
            with open(p, "wb") as fh:
                fh.write(b"".join(lines))
    biggest.sort(reverse=True)
    out = [f"  素材库 md：改文件 {n_files}（frontmatter summary {n_sum}｜published {n_pub}｜正文超长行 {n_body}）"
           + ("" if apply else "（dry-run）")]
    for size, rel in biggest[:8]:
        out.append(f"    {size/1048576:8.2f}MB  {rel[:96]}")
    return out


# ── data/*.json：JSON 值级扫描（结构安全，绝不按行兜底） ────────────────────
# ⚠️ 不能按整行处理：latest-24h-all.json 是**单行 JSON**（无 indent），逐行兜底会把
#    整文件当一条超长行截断 → JSON 直接损坏（2026-10-12 实测踩坑，靠备份恢复）。
#    这里改为扫描 `"key": "值"` 的值区间（跳过 `\x` 转义找未转义结束引号），只替换值本身。
JSON_SUM = b'"summary"'
JSON_PUB = b'"published_at"'


def _repair_json_values(text: bytes, keys: tuple[bytes, bytes] = (JSON_SUM, JSON_PUB)) -> tuple[bytes, int, int]:
    """扫描 JSON 文本里 `"key" :? "值"` 的字符串值（JSON 转义态）就地修复。

    键匹配对空白容错（`json.dumps(indent=…)` 是 `"k": "v"`；`separators=(",", ":")` 是 `"k":"v"`）。
    """
    out = bytearray()
    i = 0
    n_sum = n_pub = 0
    n = len(text)
    while i < n:
        idx = -1
        key = keys[0]
        for k in keys:
            j = text.find(k, i)
            if j >= 0 and (idx < 0 or j < idx):
                idx, key = j, k
        if idx < 0:
            out += text[i:]
            break
        out += text[i:idx]
        p2 = idx + len(key)
        # 键后必须是 可选空白 + ':' + 可选空白 + '"'（否则不是我们要的键，跳过继续找）
        q = p2
        while q < n and text[q:q + 1] in (b" ", b"\t", b"\n", b"\r"):
            q += 1
        if text[q:q + 1] != b":":
            out += text[p2:q + 1]
            i = q + 1
            continue
        q += 1
        while q < n and text[q:q + 1] in (b" ", b"\t", b"\n", b"\r"):
            q += 1
        if text[q:q + 1] != b'"':
            out += text[p2:q]
            i = q
            continue
        vstart = q + 1
        j = vstart
        while j < n:
            if text[j] == 0x5C:          # 反斜杠 → 转义对，跳过下一字节
                j += 2
                continue
            if text[j] == 0x22:          # 未转义引号 → 值结束
                break
            j += 1
        val = text[vstart:j]
        if key == JSON_SUM:
            new, ch = _fix_summary_value(val)
            n_sum += 1 if ch else 0
        else:
            new, ch = _fix_published_value(val, escaped=True)
            n_pub += 1 if ch else 0
        out += text[idx:vstart] + new + b'"'
        i = min(j + 1, n)
    return bytes(out), n_sum, n_pub


def repair_json(apply: bool, max_json_mb: int = 60) -> list[str]:
    report: list[str] = []
    for name in ITEM_JSONS + MAP_JSONS:
        p = DATA / name
        if not p.exists():
            continue
        size = p.stat().st_size
        if size > max_json_mb * 1048576:
            if apply:
                bak = p.parent / f"{name}.bak-repair{TS}"
                if not bak.exists():
                    p.rename(bak)
            report.append(f"  {name}: {size/1048576:.1f}MB > {max_json_mb}MB → "
                          + (f"已备份停用（{name}.bak-repair{TS}），下轮从素材库重建"
                             if apply else "dry-run：将备份停用，下轮重建"))
            continue
        raw = p.read_bytes()
        new, n_sum, n_pub = _repair_json_values(raw)
        if n_sum or n_pub:
            if apply:
                _backup(p, DATA)
                with open(p, "wb") as fh:
                    fh.write(new)
            report.append(f"  {name}: summary 修 {n_sum}｜published_at 修 {n_pub}"
                          f"｜{len(raw)/1048576:.2f}MB → {(len(new) if apply else len(raw))/1048576:.2f}MB"
                          + ("" if apply else "（dry-run）"))
        else:
            report.append(f"  {name}: 无需修复（{size/1048576:.2f}MB）")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="真正写盘（默认 dry-run）")
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--vault-only", action="store_true")
    ap.add_argument("--max-json-mb", type=int, default=60,
                    help="超过该体积的派生 JSON 不做就地修复（备份停用，下轮重建）")
    args = ap.parse_args()
    print(f"=== 膨胀字段修复（{'APPLY' if args.apply else 'DRY-RUN'}）===")
    if not args.json_only:
        for line in repair_vault(args.apply):
            print(line)
    if not args.vault_only:
        for line in repair_json(args.apply, args.max_json_mb):
            print(line)
    if not args.apply:
        print("（dry-run 结束；加 --apply 写盘，备份在 cache/repair-backup-<ts>/）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
