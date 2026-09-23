# -*- coding: utf-8 -*-
"""
生成《知识数据库构建与管理》分享用的 Excalidraw 图。
中文字宽按 1.0em、ASCII 按 0.55em 估算，生成时自检文字是否溢出框体。
运行：python build_diagrams.py
"""
import json
import os
import random

random.seed(20260914)
# 脚本放在 <项目>/生成脚本/ 下，图输出到同级 <项目>/图/
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE_DIR, "图")

BLUE = "#a5d8ff"    # 网站数据链
TEAL = "#c3fae8"    # 知识库素材
PURPLE = "#d0bfff"  # 知识层
GREEN = "#b2f2bb"   # 图谱实体
ORANGE = "#ffd8a8"  # 打分/加工
YELLOW = "#fff3bf"  # 说明/结论
RED = "#ffc9c9"     # 踩坑/警示
GRAY = "#f1f3f5"    # 泳道底
INK = "#1e1e1e"
MUTED = "#868e96"

WARNINGS = []


def _seed():
    return random.randint(1, 2 ** 31 - 1)


def est_width(text, fs):
    """估算一行文字宽度（px）。"""
    w = 0.0
    for ch in text:
        w += fs * (1.0 if ord(ch) > 0x2000 else 0.55)
    return w


def _base(el_type, el_id, x, y, w, h):
    return {
        "type": el_type,
        "id": el_id,
        "x": x, "y": y, "width": w, "height": h,
        "angle": 0,
        "strokeColor": INK,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "seed": _seed(),
        "version": 1,
        "versionNonce": _seed(),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
    }


def box(doc, el_id, x, y, w, h, label=None, fill=None, fs=16, dashed=False,
        stroke=INK, stroke_w=2, rounded=True, pad=8, color=INK, line_height=1.25):
    """矩形（可带居中容器文字）。"""
    el = _base("rectangle", el_id, x, y, w, h)
    el["backgroundColor"] = fill or "transparent"
    el["strokeColor"] = stroke
    el["strokeWidth"] = stroke_w
    el["strokeStyle"] = "dashed" if dashed else "solid"
    if rounded:
        el["roundness"] = {"type": 3}
    doc.append(el)

    if label:
        lines = label.split("\n")
        tw = max(est_width(l, fs) for l in lines)
        th = len(lines) * fs * line_height + 6
        if tw > w - 2 * pad:
            WARNINGS.append(f"[溢出-宽] {el_id}: 文字 {tw:.0f} > 框内 {w - 2 * pad:.0f}")
        if th > h - pad:
            WARNINGS.append(f"[溢出-高] {el_id}: 文字 {th:.0f} > 框内 {h - pad:.0f}")
        tid = "t_" + el_id
        el["boundElements"] = [{"id": tid, "type": "text"}]
        txt = _base("text", tid, x + (w - tw) / 2, y + (h - th) / 2, tw, th)
        txt.update({
            "text": label, "originalText": label,
            "fontSize": fs, "fontFamily": 1,
            "textAlign": "center", "verticalAlign": "middle",
            "strokeColor": color,
            "containerId": el_id, "autoResize": True, "lineHeight": line_height,
            "roundness": None,
        })
        doc.append(txt)
    return el


def text(doc, el_id, x, y, s, fs=16, color=INK, align="left", line_height=1.25):
    """独立文字。align=center 时 x 视为中心。"""
    lines = s.split("\n")
    tw = max(est_width(l, fs) for l in lines)
    th = len(lines) * fs * line_height + 4
    if align == "center":
        x = x - tw / 2
    el = _base("text", el_id, x, y, tw, th)
    el.update({
        "text": s, "originalText": s,
        "fontSize": fs, "fontFamily": 1,
        "textAlign": "left" if align == "left" else "center",
        "verticalAlign": "top",
        "strokeColor": color,
        "autoResize": True, "lineHeight": line_height,
        "roundness": None,
    })
    doc.append(el)
    return el


def arrow(doc, el_id, x, y, pts, end_arrow=True, dashed=False, color=INK,
          stroke_w=2, start_bind=None, end_bind=None):
    """箭头。x,y 为起点绝对坐标；pts 为相对位移点列，如 [[0,0],[100,0]]。"""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    el = _base("arrow", el_id, x, y, max(xs) - min(xs), max(ys) - min(ys))
    el.update({
        "points": [[float(px), float(py)] for px, py in pts],
        "lastCommittedPoint": None,
        "startBinding": {"elementId": start_bind, "focus": 0, "gap": 6} if start_bind else None,
        "endBinding": {"elementId": end_bind, "focus": 0, "gap": 6} if end_bind else None,
        "startArrowhead": None,
        "endArrowhead": "arrow" if end_arrow else None,
        "strokeColor": color,
        "strokeWidth": stroke_w,
        "strokeStyle": "dashed" if dashed else "solid",
        "elbowed": False,
    })
    doc.append(el)
    return el


def save(doc, filename, bg="#ffffff"):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, filename)
    payload = {
        "type": "excalidraw",
        "version": 2,
        "source": "hermes-agent",
        "elements": doc,
        "appState": {"viewBackgroundColor": bg, "gridSize": None},
        "files": {},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    return path


# ══════════════════════════════════════════════════════════════
# 图 01：网站 ⇄ Obsidian 知识库 关系结构图
# ══════════════════════════════════════════════════════════════
def diagram_01():
    d = []
    text(d, "title", 70, 40, "绿色低碳创新动态雷达 · 网站 ⇄ Obsidian 知识库 关系结构图", 28)
    text(d, "sub", 70, 92,
         "一套数据、两条消费链：机器即刻可读（排行榜／时间线／图谱）＋ 人可检索可关联（qmd 素材库／实体图谱）",
         16, MUTED)

    # ① 服务器流水线
    box(d, "laneA", 60, 150, 1740, 420, fill=GRAY, dashed=True, stroke="#adb5bd")
    text(d, "laneA_t", 95, 170, "① 服务器（新加坡）· systemd timer 每 30 分钟自动跑一轮", 20)

    box(d, "n1", 110, 250, 175, 110, "77 个信源\n部委·国际组织\n智库·学术·媒体\n技术趋势·热榜", fill=BLUE, fs=16)
    box(d, "n2", 330, 250, 185, 110, "update_news.py\n抓取 77 源\n标题规范化去重", fs=16)
    box(d, "n3", 560, 250, 180, 110, "三层分类\n政策／创新／产业\n＋ 七细类", fill=PURPLE, fs=16)
    box(d, "n4", 785, 250, 215, 110, "打分 v5.1 六维\n内容30 来源20 主题25\n人物10 时效10 TRL5", fill=ORANGE, fs=16)
    box(d, "n5", 1045, 250, 245, 110, "多维标注 21 字段\nLayer／TRL／EU-Taxonomy\nISIC／GICS／IPC\nEnabling／tech_feature", fill=TEAL, fs=15)

    arrow(d, "a12", 285, 305, [[0, 0], [45, 0]], start_bind="n1", end_bind="n2")
    arrow(d, "a23", 515, 305, [[0, 0], [45, 0]], start_bind="n2", end_bind="n3")
    arrow(d, "a34", 740, 305, [[0, 0], [45, 0]], start_bind="n3", end_bind="n4")
    arrow(d, "a45", 1000, 305, [[0, 0], [45, 0]], start_bind="n4", end_bind="n5")

    box(d, "o1", 1050, 420, 230, 100, "data/*.json\n网站数据 · 实时", fill=BLUE, fs=16)
    box(d, "o2", 1330, 420, 280, 100, "Notes/素材库/*.md\n知识库素材 · 12297 条", fill=TEAL, fs=16)
    arrow(d, "an5o1", 1167, 360, [[0, 0], [-2, 60]], start_bind="n5", end_bind="o1")
    arrow(d, "an5o2", 1167, 360, [[0, 0], [303, 0], [303, 60]], start_bind="n5")

    # ② 网站链
    box(d, "laneB", 60, 610, 840, 380, fill=GRAY, dashed=True, stroke="#adb5bd")
    text(d, "laneB_t", 95, 630, "② 网站链 · 机器即刻可读（无人干预）", 20)
    box(d, "w1", 140, 730, 250, 110, "nginx 静态直出\n（服务器静态目录）", fs=16)
    box(d, "w2", 470, 730, 340, 110, "https://ywm.life\n排行榜 · 时间线 · 关系图谱", fill=BLUE, fs=16)
    arrow(d, "aw12", 390, 785, [[0, 0], [80, 0]], start_bind="w1", end_bind="w2")
    text(d, "wb_note", 140, 878, "60s 轮询 · 新条目自动插入高亮\n当日 ≥70 分浓缩一键复制转发", 16, MUTED)
    arrow(d, "ao1w1", 1165, 520, [[0, 0], [-900, 210]], start_bind="o1", end_bind="w1")

    # ③ 知识库链
    box(d, "laneC", 960, 610, 840, 380, fill=GRAY, dashed=True, stroke="#adb5bd")
    text(d, "laneC_t", 995, 630, "③ 知识库链 · 人可检索可关联（人工策展）", 20)
    box(d, "k1", 1000, 745, 250, 110, "Obsidian Git 插件\n15min pull / 30min push", fs=16)
    box(d, "k2", 1300, 745, 170, 110, "人工策展\n（标准定稿）", fill=YELLOW, fs=16)
    box(d, "k3", 1520, 690, 230, 80, "Notes/政策wiki\n12 板块 · 知识层", fill=PURPLE, fs=16)
    box(d, "k4", 1520, 810, 230, 80, "Notes/实体 93 节点\norg／tec／reg／top", fill=GREEN, fs=16)
    arrow(d, "ao2k1", 1470, 520, [[0, 0], [-345, 225]], start_bind="o2", end_bind="k1")
    arrow(d, "ak12", 1250, 800, [[0, 0], [50, 0]], start_bind="k1", end_bind="k2")
    arrow(d, "ak2k3", 1470, 778, [[0, 0], [50, -48]])
    arrow(d, "ak2k4", 1470, 822, [[0, 0], [50, 28]])

    # ④ 双向同步闭环
    box(d, "laneD", 60, 1030, 1740, 160, fill=GRAY, dashed=True, stroke="#adb5bd")
    text(d, "laneD_t", 95, 1050, "④ 双向同步闭环", 20)
    box(d, "m1", 120, 1110, 760, 66, "本地 Obsidian 编辑 → git push（30min）\n→ 服务器 bare 物料仓库", fs=15)
    box(d, "m2", 1000, 1110, 760, 66, "服务器每轮抓取时合并 → 回写 Notes/素材库\n成为下一轮知识库素材", fill=TEAL, fs=15)
    arrow(d, "am12", 880, 1143, [[0, 0], [120, 0]], start_bind="m1", end_bind="m2")
    arrow(d, "ak2m2", 1385, 855, [[0, 0], [-5, 255]], dashed=True, start_bind="k2", end_bind="m2")
    arrow(d, "am2o2", 1760, 1143, [[0, 0], [70, 0], [70, -613], [-220, -50]], dashed=True, color="#1971c2")
    text(d, "loop_lbl", 1845, 790, "下一轮\n回写", 15, "#1971c2")

    # 图例与实测数据
    box(d, "legend", 60, 1220, 760, 100,
        "图例：蓝＝网站数据链　青＝知识库素材　紫＝知识层　绿＝图谱实体\n橙＝加工环节　黄＝人工决策　灰底虚线＝系统边界／泳道", fill=YELLOW, fs=15)
    box(d, "stats", 860, 1220, 940, 100,
        "2026-09 实测：77 信源 · 每 30 分钟一轮 · 单轮 1165 条原始 → 508 条入库\n"
        "history.json 62 天 3136 条（政策 813／创新 1183／产业 1140）\n"
        "素材库 12295 qmd · 政策 wiki 12 板块 · 实体 93 节点", fill=GRAY, fs=15)

    return save(d, "01-系统与知识库关系结构图.excalidraw")


# ══════════════════════════════════════════════════════════════
# 图 02：打分体系 v5.1 六维模型
# ══════════════════════════════════════════════════════════════
def diagram_02():
    d = []
    text(d, "title", 70, 40, "打分体系 v5.1 · 六维可解释评分模型（0-100）", 28)
    text(d, "sub", 70, 92,
         "内容强度按七细类自适应：政策看文件层级、技术看突破程度、金融看市场信号——各细类凭自身价值得高分，技术类不再被政策文件压分",
         16, MUTED)

    box(d, "sec1", 60, 150, 1740, 230, fill=GRAY, dashed=True, stroke="#adb5bd")
    text(d, "sec1_t", 95, 168, "六个维度与权重", 20)
    dims = [
        ("b1", "内容强度\n30 分\n按七细类自适应", ORANGE),
        ("b2", "来源权威\n20 分\n部委20 … 热榜6", None),
        ("b3", "主题相关\n25 分\n核心25 … 弱相关6", None),
        ("b4", "人物\n10 分\n部长10 … 分析师3", None),
        ("b5", "时效\n10 分\n24h 10 … 96h 4", None),
        ("b6", "TRL 技术成熟度\n5 分\n7-9档5／1-3档4", TEAL),
    ]
    x0, w, gap = 105, 255, 27
    for i, (bid, lbl, fill) in enumerate(dims):
        box(d, bid, x0 + i * (w + gap), 200, w, 150, lbl, fill=fill, fs=16)

    box(d, "sec2", 60, 405, 1740, 420, fill=GRAY, dashed=True, stroke="#adb5bd")
    text(d, "sec2_t", 95, 423, "内容强度 30 分 · 按七细类自适应（里程碑 30／重要 25／进展 20／一般 默认）", 20)
    rules = [
        ("r1", "政策法规（默认 10）\n判据：文件层级 × 发布主体\n30 法律/条例/国务院　25 解读　20 报告"),
        ("r2", "国际动态（默认 10）\n判据：协议层级 × 气候里程碑\n30 协议/COP/气候融资　25 谈判　20 报告"),
        ("r3", "技术研发（默认 8）\n判据：突破程度 × 首创性\n30 世界首个/颠覆　25 中试/样机　20 研发/专利"),
        ("r4", "基础研究（默认 8）\n判据：发现价值 × 发表层级\n30 诺奖/新发现　25 封面论文　20 论文/机理"),
        ("r5", "社会创新（默认 8，v5.0 新增）\n判据：机制层级 × 首创性\n30 国家级试点　25 绿色消费　20 垃圾分类"),
        ("r6", "企业经营（默认 10）\n判据：里程碑 × 规模\n30 首台套/超大规模　25 投产/签约　20 常规经营"),
        ("r7", "金融资本（默认 10）\n判据：市场信号强度\n30 全国碳市场机制　25 IPO/大额融资　20 碳价数据"),
    ]
    rw, rg = 390, 35
    for i, (rid, lbl) in enumerate(rules):
        if i < 4:
            box(d, rid, 105 + i * (rw + rg), 470, rw, 140, lbl, fs=15)
        else:
            box(d, rid, 105 + (i - 4) * (rw + rg), 640, rw, 140, lbl, fs=15)

    box(d, "sec3", 60, 845, 1740, 290, fill=GRAY, dashed=True, stroke="#adb5bd")
    text(d, "sec3_t", 95, 863, "两个工程化设计：让分数可解释、可迭代", 20)
    box(d, "g1", 105, 900, 840, 210,
        "双轨观察（2026-08-26 定）\n"
        "主流程：关键词判定——快、稳定、零成本、可审计\n"
        "旁路：LLM few-shot（DeepSeek-V4-Pro）随机抽样对比\n"
        "实验结论：Flash 系统性低估／Pro 延迟 >30min\n"
        "→ 两者都不接入主流程，只用于持续优化关键词\n"
        "（PROMPT_EXAMPLES few-shot 锚定是优化入口）", fill=YELLOW, fs=15)
    box(d, "g2", 985, 900, 790, 210,
        "可解释性：score_breakdown 六维分解\n"
        "{\"strength\":25, \"source\":14, \"topic\":18,\n"
        " \"people\":0, \"freshness\":10, \"trl\":3}\n"
        "→ 前端悬停评分徽章即展开六维明细\n"
        "→ 排序可信：分数异议可追溯到具体维度\n"
        "→ 改打分＝改标准文档＋改代码两处同步", fs=15)
    return save(d, "02-评分体系六维模型.excalidraw")


# ══════════════════════════════════════════════════════════════
# 图 03：知识图谱构建的七个基本步骤
# ══════════════════════════════════════════════════════════════
def diagram_03():
    d = []
    text(d, "title", 70, 40, "知识图谱构建的七个基本步骤 · 以绿色低碳雷达为例", 28)
    text(d, "sub", 70, 92,
         "原则：本体先行（不自造词典）→ 机器标注 → 人可追溯 → 稳定 id → 先量化再重构", 16, MUTED)

    steps1 = [
        ("s1", "1　定义本体与标签词典\n映射国际标准，不自造词典\nEU Taxonomy／ISIC／GICS\nWIPO IPC／TRL 九级", BLUE),
        ("s2", "2　采集与清洗\n多源抓取：部委／国际组织／智库\n学术／媒体／技术趋势／热榜\n规范化标题去重", None),
        ("s3", "3　多维标注\nLayer／TRL／Taxonomy\nEnabling Tech／topics／region\n21 字段正交，不做互斥分类", None),
        ("s4", "4　打分与排序\n六维 0-100、可解释\n三层 × 主题 × 周期 × 区域\n排行榜 ＋ 时间线", None),
    ]
    sw, sg = 395, 30
    for i, (sid, lbl, fill) in enumerate(steps1):
        box(d, sid, 105 + i * (sw + sg), 180, sw, 170, lbl, fill=fill, fs=15)

    steps2 = [
        ("s5", "5　入库存档（qmd）\nYAML frontmatter 多维标签\n＋ 正文（标题/摘要/技术特征）\n全量打标版 ≠ 策展精选版", TEAL),
        ("s6", "6　实体化与双链\n实体 6 类：pol／org／per／\ntec／top／reg；related 存稳定 id\n正文写 [[标题]] 才成图", None),
        ("s7", "7　图谱校验\n断链／孤立节点／重复 url\n幂等校验脚本断言\n（合并丢失必须为 0）", GREEN),
    ]
    xs2 = [1380, 955, 530]
    for (sid, lbl, fill), x in zip(steps2, xs2):
        box(d, sid, x, 430, sw, 170, lbl, fill=fill, fs=15)
    box(d, "loop", 105, 430, sw, 170,
        "闭环：校验结果回写\n本体词典与标签规范 → 回到第 1 步\n\n纪律：先量化再重构\n大重构前用只读脚本扫全量", fill=YELLOW, fs=15)

    arrow(d, "as12", 500, 265, [[0, 0], [30, 0]], start_bind="s1", end_bind="s2")
    arrow(d, "as23", 925, 265, [[0, 0], [30, 0]], start_bind="s2", end_bind="s3")
    arrow(d, "as34", 1350, 265, [[0, 0], [30, 0]], start_bind="s3", end_bind="s4")
    arrow(d, "as45", 1577, 350, [[0, 0], [0, 80]], start_bind="s4", end_bind="s5")
    arrow(d, "as56", 1380, 515, [[0, 0], [-30, 0]], start_bind="s5", end_bind="s6")
    arrow(d, "as67", 955, 515, [[0, 0], [-30, 0]], start_bind="s6", end_bind="s7")
    arrow(d, "as7loop", 530, 515, [[0, 0], [-30, 0]], start_bind="s7", end_bind="loop")
    arrow(d, "aloop1", 302, 430, [[0, 0], [0, -80]], dashed=True)
    text(d, "aloop1_t", 320, 385, "迭代", 15, "#1971c2")

    box(d, "p1", 105, 660, 540, 180,
        "三种组织范式（递进，不是替代）\n"
        "① 树状文件夹：来源清晰，交叉检索困难\n"
        "② 多维标签：交叉检索强，但无结构关系\n"
        "③ 实体-关系图谱：节点＋边，可推理可导航\n"
        "→ 本项目三层同用：素材层 ＋ qmd 标签 ＋ 实体页", fs=15)
    box(d, "p2", 675, 660, 540, 180,
        "五条硬原则\n"
        "① 不自造词典，映射国际权威标准\n"
        "② 维度正交，不做互斥分类\n"
        "③ 稳定 id，不靠文件名维系关系\n"
        "④ 机器标注 ＋ 人工策展，分工不越界\n"
        "⑤ 先量化再动手，只读脚本先扫全量", fs=15)
    box(d, "p3", 1245, 660, 530, 180,
        "踩坑实录（真实教训）\n"
        "· 通用兜底标签贴满条目 → 失去区分度\n"
        "· related 存文件名 → 改文件名即断链\n"
        "· 三库合并顺序错 → 静默覆盖 1000+ 条\n"
        "· 完整性按 url 去重数验证，不按文件名数", fill=RED, fs=15)

    return save(d, "03-知识图谱构建七步闭环.excalidraw")


# ══════════════════════════════════════════════════════════════
# 图 04：信息收集 · 77 个信源地图与两道过滤
# ══════════════════════════════════════════════════════════════
def diagram_04():
    d = []
    text(d, "title", 70, 40, "信息收集 · 77 个信源地图与两道过滤", 28)
    text(d, "sub", 70, 92,
         "白名单直通（信任源，不做绿色词过滤）＋ 关键词过滤（综合源，命中才入库）→ 单轮 1165 条原始 → 508 条入库", 16, MUTED)

    box(d, "map_zone", 60, 150, 1180, 920, fill=GRAY, dashed=True, stroke="#adb5bd")
    text(d, "map_t", 95, 168, "信源地图 · 77 个（8 类，分类计数来自 source-status.json）", 20)

    cards = [
        ("c1", "国内部委与机构 · 10 源\n发改委／生态环境部／能源局／工信部\n中央网信办／人民银行／国家气候中心\n环境规划院 CAEP／国家节能中心\n→ 政策层主干", BLUE),
        ("c2", "国际组织与主要国家官方 · 17 源\nIEA／IRENA／UNFCCC／世界银行／欧盟委员会\nUNEP／Euractiv\n＋ 美国 EPA·DOE·NOAA·EIA·FERC·CARB\n＋ 日本环境省·经产省·资源能源厅 ＋ 印度 PIB", None),
        ("c3", "国际智库 · 12 源\nE3G／Agora／TERI／Brookings／Bruegel\nPIIE／CSIS／Chatham House／Carnegie\nRAND／CAP／高盛 Insights\n→ 深度分析与政策评论", None),
        ("c4", "学术期刊 · 4 源\nNature Sustainability／Nature Climate Change\nNature Biotechnology／《经济管理学刊》\n→ 创新层·基础研究", PURPLE),
        ("c5", "碳市场与绿色金融 · 5 源\n上海环交所／中国碳交易网／碳道\nCarbon Brief／财新\n→ 产业层·金融资本", None),
        ("c6", "行业媒体 · 14 源\nReuters Energy／北极星／中国能源报／中国环境报\nCNESA／IEEE Spectrum／千家网／中国家电网\nGreen Builder／Mongabay／绿色和平\n＋ 澎湃／36氪／虎嗅（综合源走过滤）", None),
        ("c7", "科技·AI·技术趋势 · 13 源\nOpenAI／arXiv·AI／机器之心／量子位\nVentureBeat AI／AIHOT／Artificial Analysis\nClimate Change AI／中国科技网／CleanTechnica\nThe Robot Report／Hot or Cool／RadarAI·GitHub 趋势", TEAL),
        ("c8", "全网热点 · 2 源\nallnet.hot（微博／知乎／头条／澎湃／IT之家 5 榜单）\nX 平台快讯（账号白名单 + 页面 SSR 直抓）\n→ 靠绿色关键词过滤，只留相关热榜", None),
    ]
    cw, ch, cgx, cgy = 540, 180, 30, 30
    for i, (cid, lbl, fill) in enumerate(cards):
        col, row = i % 2, i // 2
        box(d, cid, 90 + col * (cw + cgx), 200 + row * (ch + cgy), cw, ch, lbl, fill=fill, fs=17)

    box(d, "flt_zone", 1270, 150, 590, 920, fill=GRAY, dashed=True, stroke="#adb5bd")
    text(d, "flt_t", 1300, 168, "两道过滤＋接入坑", 20)
    box(d, "f1", 1300, 220, 530, 180,
        "第一道：白名单直通\n信任源（部委／国际组织／学术／AI 官方）\n不做绿色关键词过滤，直接进分类与打分\n理由：权威源本身与主题先验相关，过滤只会漏信息", fill=ORANGE, fs=17)
    box(d, "f2", 1300, 450, 530, 200,
        "第二道：关键词过滤\n综合源（36氪／虎嗅／热榜／X 平台）\n命中绿色词或 AI 词才入库\n· Google News 源一律单主题词 + when:30d\n（括号 OR 语法会返回全站混合内容）\n· X 平台走账号白名单 + SSR 直抓，零 API 成本", fs=17)
    box(d, "f3", 1300, 700, 530, 180,
        "单轮实测\n1165 条原始信息\n→ 去重与过滤 → 508 条入库\n（保留率约 44%，77 源全部抓取成功）", fill=TEAL, fs=17)
    box(d, "f4", 1300, 930, 530, 120,
        "反爬与接入坑\n· 中央网信办 WAF 按 UA／出口挡 → 独立直连\n· Google News base64 链接每次不同 → 按规范化标题去重", fill=RED, fs=17)
    arrow(d, "af12", 1565, 400, [[0, 0], [0, 50]], start_bind="f1", end_bind="f2")
    arrow(d, "af23", 1565, 650, [[0, 0], [0, 50]], start_bind="f2", end_bind="f3")
    arrow(d, "af34", 1565, 880, [[0, 0], [0, 50]], start_bind="f3", end_bind="f4")

    box(d, "why", 60, 1090, 1800, 190,
        "为什么是 77 个，而不是越多越好？\n"
        "① 权威分层：部委／国际组织打底，智库与学术做深度，行业媒体做覆盖，热榜做预警——每类都有不可替代的位置\n"
        "② 每接一个源先回答三个问题：更新频率多少？会不会被 WAF 挡？内容是否与主题先验相关（决定走直通还是过滤）\n"
        "③ 源健康监控：admin 面板逐源统计成功／失败与产出条数，低产源定期复核（本轮 77 源全部成功）", fill=YELLOW, fs=17)

    return save(d, "04-信息收集77源地图.excalidraw")


if __name__ == "__main__":
    paths = [diagram_01(), diagram_02(), diagram_03(), diagram_04()]
    for p in paths:
        with open(p, encoding="utf-8") as f:
            doc = json.load(f)
        n_shapes = sum(1 for e in doc["elements"] if e["type"] != "text")
        n_texts = sum(1 for e in doc["elements"] if e["type"] == "text")
        ids = [e["id"] for e in doc["elements"]]
        print(f"OK  {os.path.basename(p)}  元素 {len(doc['elements'])}（图形 {n_shapes}／文字 {n_texts}）"
              f"  id 唯一={len(ids) == len(set(ids))}")
    if WARNINGS:
        print("\n⚠ 文字溢出告警：")
        for w in WARNINGS:
            print("  " + w)
    else:
        print("\n文字溢出检查：全部通过")
