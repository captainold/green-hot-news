#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发布工作流公共工具（2026-09-23）。

路径约定 / 清洗函数 / 配置读取。清洗逻辑参考 daily_digest.py（独立实现，避免跨区改动）。
本目录（scripts/publish/）为「每日发布工作流」专属区域，与 update_news.py 主流程解耦：
只读 data/latest-24h.json，不回写任何主流程数据文件。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 项目根 = scripts/publish/ 的上两级
ROOT = Path(__file__).resolve().parents[2]
PUBLISH_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUT_BASE = DATA_DIR / "publish"          # 每日产物根目录 data/publish/
STATE_FILE = OUT_BASE / "state.json"     # 跨天已发布 URL 指纹，防止重复推送
CONFIG_FILE = PUBLISH_DIR / "config.json"
LOCAL_CONFIG_FILE = PUBLISH_DIR / "config.local.json"  # 密钥（gitignore）

DIM_META = {
    # 三层体系（打分体系标准 v5.0）：徽标 / 一句话定位 / 配色
    "政策": {"icon": "🏛️", "tagline": "为什么——政府发文·国际动态", "color": "#166534", "bg": "#ecfdf5"},
    "创新": {"icon": "🔬", "tagline": "可能吗——技术研发·基础研究·社会创新", "color": "#0e7490", "bg": "#ecfeff"},
    "产业": {"icon": "💼", "tagline": "成了吗——企业经营·金融资本", "color": "#b45309", "bg": "#fffbeb"},
}
DIM_ORDER = ["政策", "创新", "产业"]


def today_str() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")


def out_dir(date: str | None = None) -> Path:
    d = OUT_BASE / (date or today_str())
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_config() -> dict:
    """config.json + config.local.json（后者优先，存密钥）。"""
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if LOCAL_CONFIG_FILE.exists():
        local = json.loads(LOCAL_CONFIG_FILE.read_text(encoding="utf-8"))
        for k, v in local.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"published_urls": []}


def save_state(state: dict) -> None:
    OUT_BASE.mkdir(parents=True, exist_ok=True)
    urls = state.get("published_urls", [])
    state["published_urls"] = urls[-3000:]  # 有界，防无限膨胀
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- 清洗（参考 daily_digest.py 同名逻辑，独立维护） ----------

def clean_title(title: str) -> str:
    t = re.sub(r"\s+", " ", title or "").strip()
    if "摘要：" in t:
        t = t.split("摘要：", 1)[0].strip()
    t = re.sub(r"[\u4e00-\u9fff]{0,6}(小编|编辑)\s*[^\u4e00-\u9fff]*\d*[天小时分]?前\s*$", "", t)
    t = re.sub(r"\s*[-–—]\s*[^，。；！？、\s]{2,24}$", "", t).strip()
    return t


def clean_summary(title: str, summary: str, limit: int = 120) -> str:
    s = re.sub(r"\s+", " ", summary or "").strip()
    if not s:
        return ""
    if "摘要：" in s:
        s = s.split("摘要：", 1)[1].strip()
    s = re.sub(r"发布时间：\d{4}-\d{2}-\d{2}\s*", "", s)
    # arXiv 摘要样板头（"arXiv:2609.01852v1 Announce Type: new Abstract: ..."）
    s = re.sub(r"^arXiv:\d{4}\.\d{4,5}v?\d*\s+Announce Type:\s*\w+\s+Abstract:\s*", "", s)
    s = re.sub(r"[\u4e00-\u9fff]{0,6}(小编|编辑)\s*[^\u4e00-\u9fff]*\d*[天小时分]?前", "", s)
    s = re.sub(r"^文章来源[:：]\s*[^\s，。；]{1,24}\s*\d{4}[-/]\d{2}[-/]\d{2}\s*\d{2}:\d{2}\s*", "", s)
    # 摘要开头重复标题 → 截掉公共前缀
    t_flat = re.sub(r"\s+", "", title)
    s_flat = re.sub(r"\s+", "", s)
    if len(t_flat) > 4 and s_flat.startswith(t_flat[:12]):
        common = 0
        while common < min(len(t_flat), len(s_flat)) and s_flat[common] == t_flat[common]:
            common += 1
        if common >= 12:
            s = s[common:].strip(" ，。、：;；:,.·-—")
    # 只取第一段（首句优先），限长
    first_cut = re.split(r"[。！？]", s)
    lead = first_cut[0] if first_cut and len(first_cut[0]) >= 18 else s
    lead = lead[:limit]
    return lead.rstrip("，、；：,.;: ") + ("…" if len(s) > limit else "。")


def fmt_date_cn(iso_str: str) -> str:
    """2026-09-03T15:00+08:00 → 09-03"""
    if not iso_str:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso_str)
    return f"{m.group(2)}-{m.group(3)}" if m else ""


def domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url or "")
    return m.group(1).replace("www.", "") if m else ""


def utf8_console() -> None:
    """Windows 控制台中文安全输出。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
