"""qmd 导出器——把 data/*.json 的条目导出为 .md 数据库记录（护城河：本地 Obsidian 多维检索）。

架构（2026-08-24 老温定稿）：**qmd 为主格式，md 为副本**。
- 主：Notes/数据库/*.md —— 多维标签 frontmatter + 富文本全文（图片/表格/结构）+ 技术特征
- 副本：Notes/数据库/*.md —— 内容相同，兼容 Obsidian 原生生态（插件/工具只认 .md 的场景）
- 图片附件：Notes/数据库/attachments/（md5 命名，qmd/md 内相对路径引用）

用法：
    python3.11 scripts/export_qmd.py                     # 默认 latest-24h.json → Notes/数据库/
    python3.11 scripts/export_qmd.py --input data/history.json --output Notes/数据库
    python3.11 scripts/export_qmd.py --limit 10          # 小批验证（先看质量再全量）
    python3.11 scripts/export_qmd.py --force             # 重新抓取正文（覆盖已有）
    python3.11 scripts/export_qmd.py --refresh-frontmatter  # 只重建 YAML 多维标签（正文保留，不重抓——分类规则/打分规则改后的历史刷新）

幂等：已有正文的 qmd 跳过（除非 --force）；图片附件 md5 命名天然去重。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import article_content  # noqa: E402

# 正文抓取并发（qmd 全量 984 条 × 2-5s 抓取 + 图片下载，串行太久）
_FETCH_WORKERS = 4
# 正文有效长度阈值（低于视为抓取失败/导航垃圾页）
_MIN_BODY_CHARS = 200
# 文件名标题段字节预算：11(日期+空格) + 200 + 14(〔mat-xxxxxx〕) + 10( 【dupN】) + 3(.md) < 255
_NAME_TITLE_BYTES = 200
# 解码 gnews url 的进程内缓存（同一 b64 一轮内可能重复出现；跨轮由 mat-index 天然记忆）
_GNEWS_DECODE_CACHE: dict[str, Optional[str]] = {}


def _resolve_gnews_dup(url: str, url_index: dict[str, Path], session) -> Optional[str]:
    """gnews 聚合 url → 解码后的真实 url（仅在它撞上既有直连笔记时有意义）。

    2026-10-05 dup 根治（批准项）：1039 组「同文两条 url」的根因是 `export()` 的 url
    索引只认原始 url——Google News 聚合 url 与站点直连 url 永不相等 → 同文落两个文件
    （`〔mat-xxx〕` 后缀 / 【dupN】由此而来）。这里把新 gnews url 解码成真实 url 再查
    一次索引：命中直连笔记 → 返回真实 url（调用方按直连路径 upsert，不再新建文件）。
    解码 ~1.6s/条（Google batchexecute 两步协议），所以**只对索引查不到的 gnews url
    解码**（已在索引的原样返回，等下面正常路径处理）。失败返回 None（按真新文章建文件，
    与旧行为一致）。
    """
    if url in _GNEWS_DECODE_CACHE:
        return _GNEWS_DECODE_CACHE[url]
    real = None
    try:
        real = article_content._decode_google_news_url(url, session=session)
    except Exception:
        real = None
    _GNEWS_DECODE_CACHE[url] = real if real else None
    return _GNEWS_DECODE_CACHE[url]


def _has_body(fpath: Path) -> bool:
    """文件是否已有正文节（有内容，不是「正文暂缺」占位）。"""
    try:
        txt = fpath.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    i = txt.find("## 正文")
    if i < 0:
        return len(txt) > _MIN_BODY_CHARS + 400      # 老格式无正文节：按总长判断
    return len(txt[i:]) > 260 and "正文暂缺" not in txt[i:i + 120]


def _clip_bytes(s: str, limit: int) -> str:
    """按 UTF-8 **字节**截断（ext4/xfs 文件名上限 255 字节）。

    2026-10-04 实测：按字符截断（80 字）对 CJK 会到 240 字节，加日期前缀与
    ` 【dupN】` 后缀后 263 字节 → 服务器 `git reset --hard` 报
    `unable to create file …: File name too long`，整个 vault 落不了盘。
    """
    b = s.encode("utf-8")
    if len(b) <= limit:
        return s
    return b[:limit].decode("utf-8", "ignore")


def _safe_filename(title: str) -> str:
    """去文件系统非法字符 + 按字节控长（预算见 _NAME_TITLE_BYTES）。

    2026-10-04 补：截断点正好落在空格上时会留下**结尾空格**（实测 122 个），
    NTFS 无法正常创建/打开这种名字，且 verify_graph.resolve() 会对目标 strip()
    → 引用它的链接永远解析不到。故截断后再去一次首尾空格与结尾点。
    """
    s = re.sub(r'[\\/:*?"<>|\r\n\t]', "", title or "").strip()
    return _clip_bytes(s[:80], _NAME_TITLE_BYTES).strip().rstrip(".") or "untitled"


def _date_of(item: dict) -> str:
    """取发布日期（YYYY-MM-DD），无则取首次抓取。"""
    for key in ("published_at", "first_seen_at"):
        v = (item.get(key) or "")[:10]
        if v:
            return v
    return "undated"


# ── 素材库（2026-09-23 切库：唯一写手） ──────────────────────────────────────
def mat_id(url: str) -> str:
    """素材稳定 id：`mat/<sha1(url)[:12]>`（规范 §2.2，url 不变则 id 不变）。"""
    return "mat/" + hashlib.sha1((url or "").encode("utf-8")).hexdigest()[:12]


def _safe_dirname(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", name or "").strip()


def material_dir(item: dict, mat_root: Path) -> Path:
    """素材库内目标目录：`素材库/政策/<分组>/<站点>/` 或 `素材库/媒体/<站点>/`。

    与 P2 合并快照的既有布局保持一致（政策/中国/国家发改委、媒体/36氪…）。
    站点分库规则复用 update_news.site_library/site_policy_group（延迟导入避免循环依赖）。
    """
    site_id = item.get("site_id", "")
    site_name = item.get("site_name") or site_id or "unknown"
    lib, group = "媒体", ""
    try:
        import update_news as _un  # 延迟导入：update_news 反向依赖本模块
        if _un.site_library(site_id) != "media":
            lib, group = "政策", (_un.site_policy_group(site_id) or "其他")
    except Exception:
        pass
    parts = [mat_root, lib] + ([group] if group else []) + [_safe_dirname(site_name)]
    return Path(*parts)


def _ci_existing(path: Path) -> Path | None:
    """大小写不敏感地找同目录同名文件（Windows/macOS 无法共存大小写重名）。

    ext4 上 `Hurricane POLO.md` 与 `Hurricane Polo.md` 可并存，落到 Windows 只能留一个
    → 本地 git 永远显示 modified。2026-10-04 服务器切库实测 1 例。
    """
    if path.exists():
        return path
    if not path.parent.is_dir():
        return None
    low = path.name.casefold()
    try:
        for f in path.parent.iterdir():
            if f.name.casefold() == low:
                return f
    except OSError:
        pass
    return None


def target_path(item: dict, output_dir: Path, material: bool) -> Path:
    """条目落盘路径（material=True → 素材库分层布局；否则旧扁平数据库布局）。

    同名不同 url（同日同站点同标题，如「Ideacarbon 盘前资讯」系列）不能互相覆盖：
    已有文件 url 不同时给新文件加 id 后缀 `〔mat-<6位>〕`（方括号是不可链接字符，故用全角）。
    大小写不敏感查重：跨平台（Windows/macOS）同目录大小写重名会互相覆盖。
    """
    fname = f"{_date_of(item)} {_safe_filename(item.get('title', ''))}.md"
    path = (material_dir(item, output_dir) if material else Path(output_dir)) / fname
    existing = _ci_existing(path)
    if existing is not None:
        url = (item.get("url") or "").strip()
        try:
            m = re.search(r'^url:\s*"?([^"\n]+)"?\s*$',
                          existing.read_text(encoding="utf-8", errors="replace"), re.M)
            cur = m.group(1).strip() if m else ""
        except Exception:
            cur = ""
        if url and cur != url:
            path = path.with_name(f"{path.stem} 〔mat-{mat_id(url)[4:10]}〕.md")
    return path


def build_frontmatter(item: dict) -> dict:
    """从 JSON 条目提取多维标签，构建 YAML frontmatter 字段（taxonomy 展平为独立字段，便于 Obsidian 检索）。

    2026-09-23 切库：首字段补素材稳定 id `mat/<sha1(url)[:12]>`，补 `related`（空列表，
    由 P4/P5 工具后续接线）与 `summary`（供 update_news.load_archived_summaries 回读）。
    """
    tax = item.get("taxonomy") or {}
    return {
        "id": mat_id(item.get("url", "")),
        "title": item.get("title", ""),
        "title_zh": item.get("title_zh", ""),
        "url": item.get("url", ""),
        "site": item.get("site_name", ""),
        "site_id": item.get("site_id", ""),
        "dimension": item.get("dimension", ""),
        "layer": item.get("layer", ""),
        "sub_dimension": item.get("sub_dimension", ""),
        "trl": item.get("trl", ""),
        "eu_taxonomy": tax.get("eu_taxonomy", ""),
        "isic": tax.get("isic", ""),
        "gics": tax.get("gics", ""),
        "ipc": tax.get("ipc", ""),
        "enabling_tech": item.get("enabling_tech") or [],
        "tech_feature": item.get("tech_feature", ""),
        "topics": item.get("topics") or [],
        "region": item.get("region", ""),
        "people": item.get("people") or [],
        "score": item.get("score", 0),
        "score_level": item.get("score_level", ""),
        "published_at": item.get("published_at", ""),
        "summary": (item.get("summary") or "").replace("\n", " ").strip(),
        "author": item.get("author") or "",
        "related": item.get("related") or [],
    }


def _yaml_scalar(v) -> str:
    """标量转 YAML（字符串加引号，列表转 [a, b]，空转 ""）。"""
    if isinstance(v, str):
        s = v.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[" + ", ".join(_yaml_scalar(x) for x in v) + "]"
    return '""'


def build_qmd(item: dict, content: str = "") -> str:
    """构建完整 qmd 内容：YAML frontmatter + 元信息 + 摘要 + 正文（富文本）+ 技术特征。"""
    fm = build_frontmatter(item)
    lines = ["---"]
    for k, v in fm.items():
        lines.append(f"{k}: {_yaml_scalar(v)}")
    lines.append("---")
    lines.append("")

    title = item.get("title", "")
    url = item.get("url", "")
    site = item.get("site_name", "")
    published = item.get("published_at", "")
    score = item.get("score", 0)
    level = item.get("score_level", "")
    summary = (item.get("summary") or "").strip()
    tech_feature = (item.get("tech_feature") or "").strip()
    title_zh = (item.get("title_zh") or "").strip()

    lines.append(f"# {title}")
    lines.append("")
    if title_zh and title_zh != title:
        lines.append(f"*{title_zh}*")
        lines.append("")
    if url:
        lines.append(f"[原文链接]({url})")
        lines.append("")
    meta = f"> 来源: {site} | 发布时间: {published} | 评分: {score} ({level})"
    lines.append(meta)
    lines.append("")
    if summary:
        lines.append("## 摘要")
        lines.append("")
        lines.append(summary)
        lines.append("")
    if content:
        lines.append("## 正文")
        lines.append("")
        lines.append(content)
        lines.append("")
    if tech_feature:
        lines.append("## 技术特征")
        lines.append("")
        lines.append(tech_feature)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# 重写时需原样保留的小节：build_qmd 只产出 摘要/正文/技术特征，这几节由 P3/P4 工具接线
# （link_entities / wire_wiki_links）。不保留的话，任何一次正文回填都会把图谱接线擦掉
# —— 2026-10-04 实测（us_epa Clean Trucks Plan 丢 `## 关联实体`）。
KEEP_SECTIONS = ("相关条目", "关联实体")


def extra_sections(text: str) -> str:
    """取出既有笔记里 KEEP_SECTIONS 各节正文（用于重写时续接）。"""
    parts: list[str] = []
    for name in KEEP_SECTIONS:
        m = re.search(rf"^##\s*{name}\s*$", text, re.M)
        if not m:
            continue
        rest = text[m.end():]
        nxt = re.search(r"^##\s", rest, re.M)
        body = (rest[:nxt.start()] if nxt else rest).rstrip()
        parts.append(f"## {name}\n{body}" if body else f"## {name}")
    return "\n\n".join(parts)


def fetch_rich_body(item: dict, att_dir: Path, session) -> tuple[str, int]:
    """抓取富文本正文 + 下载图片附件。

    返回 (markdown_content, 图片数)。失败返回 ("", 0)。
    """
    url = item.get("url", "")
    if not url:
        return "", 0
    # arxiv 高分论文（score >= 55）抓 PDF 全文替代 abs 页摘要（2026-08-24 老温定）
    if "arxiv.org/abs" in url and (item.get("score") or 0) >= 55:
        pdf_text = article_content.fetch_arxiv_pdf(url, session=session)
        if pdf_text:
            return pdf_text, 0  # PDF 全文纯文本，无图片附件
    res = article_content.fetch_article(url, session=session, rich=True)
    if not res or not res.get("content"):
        return "", 0
    content: str = res["content"] or ""
    if len(content) < _MIN_BODY_CHARS:
        return "", 0
    # 下载正文图片 → attachments/（相对路径引用；referer=原页面 URL 解决防盗链）
    content, n_img = article_content.download_images(content, att_dir, session=session, referer=url)
    return content, n_img


def _load_url_index(output_dir: Path, material: bool) -> dict[str, Path]:
    """url → 已落盘文件路径（增量幂等判断用）。

    material 模式优先读 `cache/mat-index.json`（build_material_index 生成，10k 条一次读盘，
    免去每轮 rglob 全库）；缓存缺失/过期时回退 rglob（兼容嵌套布局）。
    """
    if material:
        cache = ROOT / "cache" / "mat-index.json"
        try:
            meta = json.loads(cache.read_text(encoding="utf-8"))
            idx = {v["url"]: output_dir / v["path"]
                   for v in meta.values() if v.get("url") and v.get("path")}
            if idx:
                return idx
        except Exception:
            pass
    idx = {}
    for f in output_dir.rglob("*.md"):
        try:
            # 只读文件头（frontmatter 在最前）：10k+ 文件的全库扫描省掉大量 IO
            with f.open("r", encoding="utf-8", errors="ignore") as fh:
                head = fh.read(800)
            m = re.search(r'^url:\s*"?([^"\n]+)"?\s*$', head, re.MULTILINE)
            if m:
                idx[m.group(1).strip()] = f
        except Exception:
            continue
    return idx


def export(input_path: Path, output_dir: Path, force: bool = False,
           limit: int = 0,
           only_sites: Optional[set] = None,
           material: bool = False) -> int:
    """导出条目为 .md（2026-09-15 起统一 .md，原 .qmd），返回写入的文件数。

    material=True（2026-09-23 切库）：写入 `Notes/素材库/政策/<分组>/<站点>/` 或
    `Notes/素材库/媒体/<站点>/`，frontmatter 带素材稳定 id；否则沿用旧的扁平
    `Notes/数据库/` 布局（保留以便回滚）。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import requests as _req

    if not input_path.exists():
        print(f"  输入不存在: {input_path}")
        return 0
    data = json.loads(input_path.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    output_dir.mkdir(parents=True, exist_ok=True)
    att_dir = output_dir / "attachments"

    # 已落盘文件 → 按 url 去重；已有正文的跳过（幂等）
    url_index = _load_url_index(output_dir, material)

    # 待处理：新 url + （force 或 旧文件无正文）
    pending: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # 只导出指定站点（2026-08-27：us_doe/openai 服务器 403 无正文，
        # 本地 Clash 出口可抓 → --only-sites 定向重导出回填正文）
        if only_sites and item.get("site_id") not in only_sites:
            continue
        url = item.get("url", "")
        if url and url in url_index:
            # 已存在同一 url：按**原落盘路径**判断/回写（published_at 后续被修正会让文件名
            # 的日期段变化，重算路径会生成重复文件 —— 2026-10-04 实测 us_epa 一条）
            fpath = url_index[url]
            if not force and fpath.exists() and _has_body(fpath):
                continue  # 已有正文，跳过
            pending.append(item)
            continue
        # dup 根治（2026-10-05）：gnews 聚合 url 不在索引时，先解码成真实 url 再查一次。
        # 命中既有直连笔记 → 记住映射，落盘时按直连路径 upsert（不再新建 〔mat-〕孪生文件）。
        # 只在这一分支解码（索引已命中的 gnews 条目无需解码），控制 batchexecute 调用量。
        _dup_real: Optional[str] = None
        if url and "news.google.com" in url and url not in url_index:
            _dup_real = _resolve_gnews_dup(url, url_index, _req.Session())
            if _dup_real and _dup_real in url_index:
                it_path = url_index[_dup_real]
                if not force and it_path.exists() and _has_body(it_path):
                    continue  # 直连笔记已有正文：同文已在库，直接跳过
                item["_dup_of"] = _dup_real
                pending.append(item)
                continue
        pending.append(item)
    if limit:
        pending = pending[:limit]

    if not pending:
        print(f"  {input_path.name}: 无待导出条目（全部已有正文）→ {output_dir}")
        return 0

    print(f"  {input_path.name}: {len(pending)} 条待导出（含正文抓取+图片下载）→ {output_dir}")
    session = _req.Session()
    session.headers.update({"User-Agent": article_content.BROWSER_UA,
                            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})

    written = 0
    no_body = 0
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as ex:
        futs = {ex.submit(fetch_rich_body, it, att_dir, session): it for it in pending}
        for fut in as_completed(futs):
            it = futs[fut]
            try:
                content, n_img = fut.result()
            except Exception:
                content, n_img = "", 0
            if not content:
                no_body += 1
            url = it.get("url", "")
            # dup 归并：本条是某直连笔记的 gnews 孪生 → 写进直连笔记的路径（正文互补，
            # 保留它原有的图谱接线小节），url/id 仍是 gnews 自己的（id 不能漂移）
            if it.pop("_dup_of", None):
                real = _resolve_gnews_dup(url, url_index, session) if url else None
                fpath = url_index.get(real) if real else None
                fpath = fpath if fpath else target_path(it, output_dir, material)
            else:
                fpath = (url_index.get(url) if url else None) or target_path(it, output_dir, material)
            new_text = build_qmd(it, content)
            if fpath.exists():
                old = fpath.read_text(encoding="utf-8", errors="ignore")
                keep = extra_sections(old)
                # 互补原则：新抓为空而旧文有正文 → 保留旧正文（只更新元信息/接线）
                if not content and _has_body(fpath):
                    i_body = old.find("## 正文")
                    if i_body >= 0:
                        old_body = old[i_body:].split("## 关联实体")[0].rstrip()
                        new_text = new_text.rstrip() + "\n\n" + old_body + "\n"
                if keep:
                    new_text = new_text.rstrip() + "\n\n" + keep + "\n"
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(new_text, encoding="utf-8")
            if url:
                url_index[url] = fpath
            written += 1
            if written % 20 == 0:
                print(f"    进度 {written}/{len(pending)}（无正文 {no_body}）", flush=True)

    print(f"  {input_path.name}: 写入 {written} 条（{no_body} 条无正文）→ {output_dir}，图片附件 → {att_dir}")
    return written


def backfill_images(output_dir: Path) -> int:
    """补图模式（2026-08-24）：对已有正文的 qmd 只做图片下载补全。

    首次全量导出时部分源站图 404/超时失败（保留原 URL）——重跑正文浪费，
    此模式只提取正文中的 http 图片 → 下载到 attachments/ → 重写 qmd+md。
    404 死链自动保留原 URL（Obsidian 点击可打开）。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import requests as _req

    output_dir = Path(output_dir)
    att_dir = output_dir / "attachments"
    files = [f for f in output_dir.glob("*.md")
             if re.search(r"!\[[^\]]*\]\(https?://", f.read_text(encoding="utf-8", errors="ignore"))]
    if not files:
        print("  无待补图 qmd（正文无 http 图片引用）")
        return 0
    print(f"  {len(files)} 个 qmd 待补图 → {att_dir}")

    session = _req.Session()
    session.headers.update({"User-Agent": article_content.BROWSER_UA})

    def _work(f: Path) -> int:
        text = f.read_text(encoding="utf-8", errors="ignore")
        m = re.search(r"^## 正文\s*$", text, re.M)
        if not m:
            return 0
        # 从 frontmatter 读 url 作为 Referer（防盗链）
        m_url = re.search(r'^url:\s*"?([^"\n]+)"?\s*$', text, re.M)
        referer = m_url.group(1).strip() if m_url else ""
        body = text[m.end():]
        new_body, n = article_content.download_images(body, att_dir, session=session, referer=referer)
        if n == 0:
            return 0
        new_text = text[:m.end()] + new_body
        f.write_text(new_text, encoding="utf-8")
        return n

    total = 0
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as ex:
        futs = {ex.submit(_work, f): f for f in files}
        for fut in as_completed(futs):
            total += fut.result()
    print(f"  补图完成：{total} 张（404 死链自动保留原 URL）")
    return total


def refresh_frontmatter(input_path: Path, output_dir: Path) -> int:
    """仅刷新 frontmatter 模式（2026-08-25）：不重抓正文，只重建 YAML 头部多维标签。

    用途：分类规则/打分规则改进后，历史 qmd 的 frontmatter 标签过时——
    全量重导会重抓正文（浪费 + 服务器禁 --force），此模式按 url 匹配
    已存在的 qmd，用最新 JSON 重建 frontmatter，正文部分原样保留。

    返回刷新的文件数；新条目（JSON 有、磁盘无）跳过，留待主流程增量导出。
    """
    if not input_path.exists():
        print(f"  输入不存在: {input_path}")
        return 0
    data = json.loads(input_path.read_text(encoding="utf-8"))
    items = data.get("items", data) if isinstance(data, dict) else data
    # url → item（同 url 取最后一条）
    by_url: dict[str, dict] = {}
    for it in items:
        if isinstance(it, dict) and it.get("url"):
            by_url[it["url"]] = it

    refreshed = 0
    skipped_no_fm = 0
    fm_re = re.compile(r"^---\n.*?\n---\n", re.DOTALL | re.MULTILINE)
    for f in sorted(output_dir.glob("*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        m_url = re.search(r'^url:\s*"([^"]+)"', text, re.MULTILINE)
        if not m_url:
            skipped_no_fm += 1
            continue
        item = by_url.get(m_url.group(1))
        if not item:
            continue  # 该 url 不在本次输入 JSON（可能是其他输入文件导出的），跳过
        new_fm = build_frontmatter(item)
        lines = ["---"]
        for k, v in new_fm.items():
            lines.append(f"{k}: {_yaml_scalar(v)}")
        lines.append("---")
        new_head = "\n".join(lines) + "\n"
        m = fm_re.match(text)
        if not m:
            skipped_no_fm += 1
            continue
        if m.group(0) == new_head:
            continue  # frontmatter 未变化，跳过写盘
        f.write_text(new_head + text[m.end():], encoding="utf-8")
        refreshed += 1
    print(f"  {input_path.name}: 刷新 {refreshed} 个 qmd frontmatter"
          f"（无 frontmatter/格式异常 {skipped_no_fm}，新条目待主流程增量导出）")
    return refreshed


def main() -> int:
    ap = argparse.ArgumentParser(description="数据库导出器（.md + 富文本全文）")
    ap.add_argument("--input", default=str(ROOT / "data" / "latest-24h.json"))
    ap.add_argument("--output", default=str(ROOT / "Notes" / "素材库"),
                    help="输出目录；默认 Notes/素材库（2026-10-04 切库）。旧扁平布局请显式传 Notes/数据库")
    ap.add_argument("--force", action="store_true", help="重新抓取正文（覆盖已有）")
    ap.add_argument("--limit", type=int, default=0, help="只导出前 N 条（小批验证用）")
    ap.add_argument("--backfill-images", action="store_true",
                    help="补图模式：只对已有正文的 qmd 下载图片（不重抓正文）")
    ap.add_argument("--refresh-frontmatter", action="store_true",
                    help="仅刷新 frontmatter：按 url 重建 YAML 多维标签，正文保留（不重抓）")
    ap.add_argument("--only-sites", default="",
                    help="只导出指定 site_id（逗号分隔，如 us_doe,openai）——定向重导出/回填用")
    ap.add_argument("--material", action="store_true",
                    help="素材库模式（2026-09-23 切库）：写入 素材库/政策/<分组>/<站点>/ 或 素材库/媒体/<站点>/，"
                         "frontmatter 带 mat id；默认输出目录相应改为 Notes/素材库")
    args = ap.parse_args()

    out = Path(args.output)
    if args.material and args.output == str(ROOT / "Notes" / "数据库"):
        out = ROOT / "Notes" / "素材库"
    elif not args.material and out == ROOT / "Notes" / "素材库":
        # 2026-10-04：默认输出已是素材库，不自动开分层会把扁平文件写进素材库根目录
        args.material = True
        print("ℹ️ 输出为 Notes/素材库 → 自动启用 --material 分层布局")
    if args.backfill_images:
        total = backfill_images(out)
        print(f"完成，共补图 {total} 张")
        return 0
    if args.refresh_frontmatter:
        total = refresh_frontmatter(Path(args.input), out)
        print(f"完成，共刷新 {total} 个 qmd frontmatter")
        return 0
    only = {s.strip() for s in args.only_sites.split(",") if s.strip()}
    total = export(Path(args.input), out, args.force, args.limit,
                   only_sites=only or None, material=args.material)
    print(f"完成，共写入 {total} 条 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
