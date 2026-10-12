"""探针（临时）：新老 unescape 语义一致性回归。用完即删。"""
import itertools
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import repair_runaway_fields as rrf  # noqa: E402

BS = b"\\"
Q = b'"'


def ref_unescape(s: bytes) -> bytes:
    """参考实现：逐对扫描（= export_qmd.yaml_unscalar 的字节等价版，慢但语义明确）。"""
    out = bytearray()
    i = 0
    while i < len(s):
        if s[i:i + 1] == BS and i + 1 < len(s) and s[i + 1:i + 2] in (BS, Q):
            out += s[i + 1:i + 2]
            i += 2
            continue
        out += s[i:i + 1]
        i += 1
    return bytes(out)


# 穷举所有由 b\ , b" , bx 组成、长度 ≤ 5 的串，逐一比对
alpha = [BS, Q, b"x"]
bad = 0
n = 0
for L in range(0, 6):
    for combo in itertools.product(alpha, repeat=L):
        s = b"".join(combo)
        n += 1
        if rrf._unescape_bytes(s) != ref_unescape(s):
            bad += 1
            if bad <= 5:
                print("  ✗", s, "→", rrf._unescape_bytes(s), "| 参考", ref_unescape(s))
print(f"穷举 {n} 个串：语义不一致 {bad} 个")

# 幂等 + 折叠：两轮往返（unescape → escape）保持稳定
def escape(t: str) -> bytes:
    return t.replace("\\", "\\\\").replace('"', '\\"').encode("utf-8")


for t in ['REO="50"%', "back\\slash", '混"合\\', "纯中文", "a\\\\b"]:
    e1 = escape(t)
    back = rrf._unescape_bytes(e1).decode("utf-8")
    print(("  ✓" if back == t else "  ✗"), repr(t), "→ 往返", repr(back))
raise SystemExit(1 if bad else 0)
