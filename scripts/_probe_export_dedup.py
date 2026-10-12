"""探针（临时）：export 判重兜底 / 字段上限 / YAML 往返 的无网络验证。用完即删。"""
import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import export_qmd as eq  # noqa: E402

FAIL = []


def check(name, cond, extra=""):
    print(("  ✓ " if cond else "  ✗ ") + name + (f"  {extra}" if extra else ""))
    if not cond:
        FAIL.append(name)


# ── 1. YAML 往返（写→读）─────────────────────────────────────────────
print("1) _yaml_scalar ↔ yaml_unscalar 往返")
for v in [
    'REO="50"%',
    "back\\slash",
    '混合\\与"引号"',
    '尾反斜杠\\',
    "普通中文摘要，无特殊字符",
    '多反斜杠\\\\\
结束',
]:
    line = f"summary: {eq._yaml_scalar(v)}"
    raw = line[len("summary: "):]
    back = eq.yaml_unscalar(raw)
    check(f"往返 {v[:18]!r}", back == v, f"→ {back[:24]!r}")

# ── 2. 字段上限 ────────────────────────────────────────────────────
print("2) build_frontmatter 字段上限")
fm = eq.build_frontmatter({"summary": "字" * (eq.SUMMARY_MAX_CHARS + 1000),
                            "published_at": "2026-01-01T00:00:00+08:00" * 5})
check(f"summary 截断到 {eq.SUMMARY_MAX_CHARS}+…", len(fm["summary"]) == eq.SUMMARY_MAX_CHARS + 1 and fm["summary"].endswith("…"),
      f"len={len(fm['summary'])}")
check("published_at 截断到 40+…", len(fm["published_at"]) == eq.PUBLISHED_MAX_CHARS + 1)

# ── 3. 判重兜底（索引过期时按落盘路径判重）─────────────────────────
print("3) export 判重兜底（索引冻结场景，桩掉抓取、不联网）")
tmp = pathlib.Path(tempfile.mkdtemp(prefix="eqprobe-"))
try:
    out, src = tmp / "vault", tmp / "in"
    out.mkdir()
    src.mkdir()
    # 从素材库取 3 条已有正文的真实条目 + 伪造 1 条全新的
    items = json.loads((ROOT / "data" / "latest-24h.json").read_text(encoding="utf-8"))["items"]
    picked = []
    for it in items:
        if it.get("site_id") in ("cac", "36kr") and it.get("url") and len(picked) < 3:
            p = eq.target_path(it, ROOT / "Notes" / "素材库", True)
            if p.exists() and eq._has_body(p):
                picked.append(it)
    for it in picked:   # 复制到临时 vault（保持相对路径）
        rel = eq.target_path(it, ROOT / "Notes" / "素材库", True).relative_to(ROOT / "Notes" / "素材库")
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "Notes" / "素材库" / rel, dst)
    fake = {"url": "https://example.com/brand-new-article", "site_id": "cac", "site_name": "国家网信办",
            "title": "全新条目", "published_at": "2026-10-12T00:00:00+08:00", "summary": "s"}
    inp = src / "in.json"
    inp.write_text(json.dumps({"items": picked + [fake]}, ensure_ascii=False), encoding="utf-8")
    calls = {"n": 0}

    def fake_fetch(item, att_dir, session):
        calls["n"] += 1
        return "正文" * 200, 0

    orig = eq.fetch_rich_body
    eq.fetch_rich_body = fake_fetch
    try:
        # 索引为空（模拟 cache/mat-index.json 冻结/缺失）→ 只能靠落盘路径兜底
        eq.ROOT = tmp
        written = eq.export(inp, out, material=True)
    finally:
        eq.fetch_rich_body = orig
        eq.ROOT = ROOT
    check("已有正文的 3 条未重抓（pending 只剩新条目）", calls["n"] == 1, f"抓取调用={calls['n']}, 写入={written}")
    check("写入数 == 1", written == 1)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
print("FAILED:", FAIL if FAIL else "无（全部通过）")
raise SystemExit(1 if FAIL else 0)
