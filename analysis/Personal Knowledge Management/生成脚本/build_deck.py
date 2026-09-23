# -*- coding: utf-8 -*-
"""
生成 Excalidraw 演示文稿（配 Obsidian Excalidraw 的 Slideshow 脚本用）。

关键约定（读脚本源码确认）：
- 一个 frame = 一页；frame 名按字母序为默认顺序（另写显式 order 元数据锁定）
- 讲稿存 frame.customData.slideshow.notes → presenter notes 窗口，投屏看不到
- 画幅默认 1920x1080；镜头 zoom = 1080 / 帧高 → 一页内容越少字越大
- 键位：↓/→/Space 下页，↑/← 上页，F 全屏，Esc 结束

本脚本「保留用户手改的封面」：读现有 演示文稿.excalidraw 里 name=="01 封面"
的 frame 及其子元素，原样搬入；其余页按下方 PAGES 重建。改封面请在 Excalidraw
里改完再重跑本脚本（封面会原样保留）。

运行：python build_deck.py
输出：<项目>/演示文稿.excalidraw  ＋  <项目>/讲稿.md
"""
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG_DIR = os.path.join(BASE_DIR, "图")
DECK_PATH = os.path.join(BASE_DIR, "演示文稿.excalidraw")
NOTES_PATH = os.path.join(BASE_DIR, "讲稿.md")
DECK_NAME = "知识数据库构建与管理"
PAD = 40
GAP = 700
INK = "#1e1e1e"
GRAY = "#495057"
SUB = "#343a40"      # 缩进行：比正文略浅但仍足够深，抗投影亮度衰减
BLUE = "#1971c2"
LIGHT_BLUE = "#a5d8ff"
LIGHT_ORANGE = "#ffd8a8"
LIGHT_GREEN = "#b2f2bb"

D01 = "01-系统与知识库关系结构图.excalidraw"
D02 = "02-评分体系六维模型.excalidraw"

# ══════════════════════ 讲稿（每页一份，投屏看不到） ══════════════════════
N_COVER = """### 开场（约 1.5 分钟）

- 一句话开场：今天不讲宏大理论，讲一个我实际在用的、把「信息」变成「独特判断」的体系。
- 交代结构：先花一页讲「为什么值得做」（不展开），然后 90% 的时间讲一个真实产品怎么设计、每个环节的取舍——每个环节都配一个真实例子。
- 最后留讨论。"""

N_HOOK = """### 引子：一个刚刚发生的信号（约 2 分钟）

- 先抛事实，不解释、不评论：**Anthropic CEO Dario Amodei 公开表示，Anthropic 内部已经实现「自举」（bootstrapping）——AI 开始自己改进自己。**
- 现场动作：念完这句，**停顿 2 秒，向观众提问**：「那么，现在算不算已经实现 AGI 了？」
- 让观众先想、先回答，不要急着给结论；不管答什么都不直接反驳。
- 衔接下一页：这个问题本身，恰恰说明我们缺一个**自己的判断基准**——这正是下面要讲的「独立数据源 → 独立理解 → 独特判断」。
- 备注：这句是 Dario 公开表述的概括，不是逐字引语；若被追问出处，说明来自其近期关于 AI 递归自我改进的公开表态即可。"""

N_WHY = """### 为什么建知识数据库（约 1 分钟，刻意压短、不说教）

- AGI 时代，通用知识已经不值钱（模型都会）；真正值钱的是**独特性**。
- 独特性 = 三个台阶：**独立数据源 → 独立理解 → 独特判断**。
- 独立数据源：自己的政策／技术／市场信源体系（不靠别人喂）
- 独立理解：自己的本体、标签、打分标准（不套用通用口径）
- 独特判断：数据 ＋ 理解沉淀出的、属于自己的结论
- 收口一句（轻）：**这套体系不是给 AI 用的，是给我自己的判断兜底的。**
- 语气提醒：这页 30 秒带过，不要展开，避免说教感。"""

N_OVERVIEW = """### 雷达总览（约 2 分钟）

- 一句话定义：**绿色低碳创新动态雷达 = 一条每 30 分钟自动跑一轮、把 77 个信源变成「可检索、可打分、可关联」知识资产的流水线。**
- 这条流水线（看图从左到右）：采集 77 源 → 去重 → 三层分类（政策/创新/产业 + 七细类）→ 六维打分 → 21 字段标注 → **两个出口**（网站 ＋ 知识库）。
- 后面逐环节拆开讲，每个环节都给一个真实例子；先记住这个「一个分叉、两个出口」的结构。"""

N_COLLECT_DESIGN = """### 信息收集：设计逻辑（约 4 分钟）

- 77 个信源，八类各有不可替代的位置：部委与机构 10／国际组织与官方 17／智库 12／学术期刊 4／碳市场金融 5／行业媒体 14／AI 与技术 13／全网热点 2。
- **核心设计决策——两种接入策略**：
  - 白名单直通：部委／国际组织／学术期刊／AI 官方源——不做绿色词过滤，直接进分类打分。理由：权威源本身与主题先验相关，过滤只会漏信息。
  - 关键词过滤：36氪／虎嗅／热榜／X 平台等综合源——命中绿色词或 AI 词才入库。
- 每接一个源先回答三问：更新频率多少？会不会被 WAF 挡？内容与主题是否先验相关？
- 工程细节（被追问时）：中央网信办 WAF 独立直连；Google News 一律单主题词 + when:30d。"""

N_COLLECT_EX = """### 信息收集：一个真实例子（约 2 分钟）

- 同一天抓到的两条，来源不同 → 待遇不同：
  - **白名单直通**：中央网信办《中国新电商发展报告(2026)》→ 政策法规，权威直通入库。即使主题相关度不高，权威源本身值得持续跟踪。
  - **关键词过滤**：热榜《新能源汽车普及了，汽油会回到三两元吗？》→ 命中绿色词才留下，但来源只有 6 分（热榜），定位是「舆情预警」而不是「知识」。
- 讲这个例子的目的：**「来源」是一等设计要素**——它决定一条信息的待遇和定位，不是抓完就完。
- 这也是为什么不能「一个爬虫抓一切」：不同来源要用不同的对待方式。"""

N_SCORE_DESIGN = """### 打分：六维与七细类自适应（约 4 分钟）—— 核心卖点

- 公式：**内容强度 30 ＋ 来源权威 20 ＋ 主题相关 25 ＋ 人物 10 ＋ 时效 10 ＋ TRL 5 ＝ 100**。
- **内容强度按七细类自适应**：政策看文件层级、国际动态看协议层级、技术研发看突破程度、基础研究看发表层级、金融资本看市场信号、社会创新看机制首创性、企业经营看里程碑与规模——每类都有各自的满分路径。
- 教训（务必讲）：早期版本「内容强度」只认政策文件，技术类被系统性压分（技术均分 47 vs 政策 56）。**用一把尺子量所有内容，是打分体系最常见的错。**
- 为什么要六维而不是一个总分：多维才能解释、才能调——某一维给分不合理，改一维不影响其他。"""

N_SCORE_EX = """### 打分：两条真实信息的分数分解（约 2 分钟）

- 政策：环境规划院《石化行业全国碳市场扩围专题研讨会》→ **90 分(S)**：强度 30 ＋ 来源 20 ＋ 主题 25 ＋ 人物 0 ＋ 时效 10 ＋ TRL 5。
- 技术：OpenAI《支持加州青少年 AI 安全法案》→ **77 分(A)**：强度 30 ＋ 来源 16 ＋ 主题 18 ＋ 人物 0 ＋ 时效 10 ＋ TRL 3。
- 解读：两条「内容强度」都拿满 30——政策靠文件层级、技术靠治理/安全信号；拉开差距的是**来源权威（20 vs 16）**和**主题相关（25 vs 18）**。
- 一句话：**内容强度解决「公平」，来源和主题解决「取舍」。** 每个分数都能拆开解释，异议可追溯到具体维度——评估类工作，这一点比分数本身更重要。"""

N_DISPLAY = """### 排序与展示（约 3 分钟）

- 三区布局：
  - 顶部**主题排行榜**：三层（政策/创新/产业）× 周期（日/周/月）× 区域（国内/国际）× 分数段，四组切换器组合筛选。
  - 中部**实时时间线**：跟随筛选，60 秒轮询，新条目自动插入并高亮。
  - 底部**关系图谱**：主题／Layer／国际分类／交叉技术四维切换。
- 当日 ≥70 分（A 级）浓缩版 `daily-digest.md`：一键复制即可转发——**给领导看的就是这一条**。
- 特点：不是「信息流」，是「已打分、可筛选、可追溯」的看板。

> 讲完这一页切到网站做现场 Demo：https://ywm.life。"""

N_INGEST = """### 入库与知识图谱（约 4 分钟）

- 一条信息被 **21 个字段**描述（Layer／TRL／EU-Taxonomy／ISIC／GICS／IPC／Enabling／topics／region／score…），qmd = YAML frontmatter ＋ 正文。
- **护城河字段 `tech_feature`**（真实例子）：蚂蚁百灵一条，提取出「用 GSPO 算法训练 400 步后，rollout/rewards_mean 从 -0.5 升至 0.4，response_len 降至…」——普通新闻聚合不做这件事，而这恰是咨询场景最需要的。
- 三层结构（从文件夹到图谱）：
  - 素材层：全量机器打标 12295 条 qmd（政策 4926 ＋ 媒体 7371）
  - 知识层：政策 wiki 12 板块，人工策展
  - 实体层：93 个图谱节点（机构 77／技术 10／地区 6）
- 一句话：**目录解决「存在哪」，图谱解决「和什么有关」。**"""

N_ARCH = """### 网站 ⇄ Obsidian：两个出口（约 4 分钟）

- **同一套抓取结果，两条消费链**（看图）：
  - 网站链（机器即刻可读）：JSON → nginx 静态直出 → ywm.life 三区界面，无人干预。
  - 知识库链（人可检索可关联）：qmd 素材库 → git 同步到本地 Obsidian → 人工策展 → 知识层＋实体层。
- 同步机制：服务器每 30 分钟抓取提交 → 本地 Obsidian Git 每 15 分钟 pull；本地策展成果每 30 分钟 push 回服务器。
- **关键纪律**：笔记随便改、插件自动同步；但代码和标准文档必须手动 commit ＋ push。
- 为什么必须两个出口：网站解决「今天看什么」（时效、可转发）；知识库解决「三年后还查不查得到」（沉淀、可检索）。**数据同源**，避免「看板一套、资料另一套」的分裂。"""

N_CLOSE = """### 收尾与讨论（约 4 分钟 ＋ 10 分钟）

- 三点可迁移建议：
  1. **先定本体，再动手收集**——哪怕只有 8 个字段；先想清楚按什么维度检索，再决定收集什么。
  2. **素材层与知识层分开**——全量机器打标（素材）与人工策展精选（知识）混在一起，两边都会烂。
  3. **评估类工作必须可解释**——打分、排序、评级都要留 score_breakdown 式分解，否则结论无法辩护。
- 回扣开场：这套体系给我的是什么？不是更多信息，是**独特性——自己的数据源、自己的理解、自己的判断**。
- 讨论：部门还有哪些专题值得建库？可行性三问：**数据从哪来／谁维护／多久更新一次**。"""

# ══════════════════════ 页面定义 ══════════════════════
# kind: cover(保留用户改的) / quote(引子页) / cards(卡片页) / lines(要点页) / image(图页)

T_HOOK = {
    "frame": "02 一个信号：自举已实现", "note": N_HOOK,
    "kicker": "一个刚刚发生的信号",
    "quote": "Dario Amodei（Anthropic CEO）：\n「Anthropic 已经实现自举（bootstrapping）——\nAI 开始自己改进自己。」",
    "question": "那么…… AGI 实现了吗？",
}

T_WHY = {
    "frame": "03 为什么建知识数据库", "note": N_WHY, "title": "AGI 时代，为什么建知识数据库",
    "cards": [
        {"head": "① 独立数据源", "fill": LIGHT_BLUE,
         "lines": ["自己的政策·技术·\n市场信源体系", "不靠别人喂"]},
        {"head": "② 独立理解", "fill": LIGHT_ORANGE,
         "lines": ["自己的本体·标签·\n打分标准", "不套通用口径"]},
        {"head": "③ 独特判断", "fill": LIGHT_GREEN,
         "lines": ["数据＋理解沉淀出\n自己的结论", "最终价值所在"]},
    ],
    "caption": "通用知识不值钱，值钱的是独特性——这套体系，是给我自己的判断兜底。",
}

T_COLLECT = {
    "frame": "05 信息收集·设计", "note": N_COLLECT_DESIGN, "title": "信息收集：77 个信源",
    "lines": [
        "· 八类信源共 77 个：部委 10 ／ 国际组织与官方 17 ／ 智库 12 ／ 学术期刊 4",
        "　　碳市场金融 5 ／ 行业媒体 14 ／ AI 与技术 13 ／ 全网热点 2",
        "· 两种接入策略（设计核心）",
        "　　白名单直通：部委 / 国际组织 / 学术 / AI 官方 —— 不做绿色词过滤",
        "　　关键词过滤：36氪 / 虎嗅 / 热榜 / X 平台 —— 命中绿色词才入库",
        "· 每接一个源先回答三问：更新频率？会不会被 WAF 挡？是否与主题先验相关？",
    ],
}

T_COLLECT_EX = {
    "frame": "06 信息收集·举例", "note": N_COLLECT_EX, "title": "信息收集：一个真实例子",
    "cards": [
        {"head": "白名单直通｜中央网信办", "fill": LIGHT_BLUE,
         "lines": ["《中国新电商发展报告\n（2026）》", "→ 政策法规·权威直通入库", "主题相关度不高，但权威源\n本身值得持续跟踪"]},
        {"head": "关键词过滤｜全网热点", "fill": LIGHT_ORANGE,
         "lines": ["《新能源汽车普及了，\n汽油会回到三两元吗？》", "→ 命中绿色词才留下，\n来源仅 6 分（热榜）", "定位是「舆情预警」\n而非「知识」"]},
    ],
    "caption": "「来源」是一等设计要素——它决定一条信息的待遇和定位，不是抓完就完。",
}

T_SCORE_EX = {
    "frame": "08 打分·举例", "note": N_SCORE_EX, "title": "打分：两条真实信息的分数分解",
    "cards": [
        {"head": "政策｜环境规划院 · 90 分(S)", "fill": LIGHT_BLUE,
         "lines": ["《石化行业全国碳市场\n扩围专题研讨会》", "强度 30　来源 20　主题 25", "人物 0　时效 10　TRL 5"]},
        {"head": "技术｜OpenAI · 77 分(A)", "fill": LIGHT_ORANGE,
         "lines": ["《支持加州青少年\nAI 安全法案》", "强度 30　来源 16　主题 18", "人物 0　时效 10　TRL 3"]},
    ],
    "caption": "内容强度都拿满 30（政策靠文件层级、技术靠治理信号）；差距来自来源权威与主题相关——每个分数都能拆开解释。",
}

T_DISPLAY = {
    "frame": "09 排序与展示", "note": N_DISPLAY, "title": "排序与展示",
    "lines": [
        "· 三区布局：主题排行榜（三层 × 周期 × 区域 × 分数段）",
        "　　实时时间线（60s 轮询）＋ 关系图谱（四维切换）",
        "· 当日 ≥70 分（A 级）浓缩版 daily-digest.md：一键复制即可转发",
        "· 特点：不是「信息流」，是「已打分、可筛选、可追溯」的看板",
    ],
    "footer": "现场演示：https://ywm.life（排行榜 → 时间线 → 关系图谱 → 当日浓缩）",
}

T_INGEST = {
    "frame": "10 入库与知识图谱", "note": N_INGEST, "title": "入库与知识图谱",
    "lines": [
        "· 一条信息被 21 个字段描述：Layer / TRL / EU-Taxonomy / ISIC / GICS / IPC",
        "　　Enabling / topics / region / score 等",
        "· 护城河字段 tech_feature（真实例子）：",
        "　　「用 GSPO 算法训练 400 步后，rollout/rewards_mean 从 -0.5 升至 0.4…」",
        "· 三层结构：素材层（全量打标 12295 条 qmd）",
        "　　→ 知识层（政策 wiki 12 板块，人工策展）",
        "　　→ 实体层（93 个图谱节点）",
        "· 目录解决「存在哪」，图谱解决「和什么有关」",
    ],
}

T_CLOSE = {
    "frame": "12 收尾·可迁移", "note": N_CLOSE, "title": "三点可迁移建议",
    "lines": [
        "1　先定本体，再动手收集 ——",
        "　　先想清楚按什么维度检索，再决定收集什么（哪怕只有 8 个字段）",
        "2　素材层与知识层分开 ——",
        "　　全量机器打标 与 人工策展精选，混在一起两边都会烂",
        "3　评估类工作必须可解释 ——",
        "　　留 score_breakdown 式分解，否则结论无法辩护",
        "小结：这套体系给我的是独特性 —— 自己的数据源、自己的理解、自己的判断",
    ],
}

I_PAGES = [
    {"frame": "04 雷达总览·流水线", "src": D01, "note": N_OVERVIEW, "crop": (60, 140, 1880, 570)},
    {"frame": "07 打分·六维与七细类", "src": D02, "note": N_SCORE_DESIGN, "crop": (60, 130, 1840, 835)},
    {"frame": "11 网站与知识库", "src": D01, "note": N_ARCH, "crop": (60, 580, 1830, 1210),
     # 裁切后排除了跨出裁剪区的回写虚线，这里在页内补一条，让「双向同步闭环」在页内闭合
     "extra": [
         {"kind": "arrow", "dashed": True, "color": BLUE,
          "pts": [[1380, 1110], [1380, 900], [1125, 900], [1125, 862]]},
         {"kind": "text", "x": 1150, "y": 908, "text": "下一轮回写", "fs": 15, "color": BLUE},
     ]},
]

_seq = [500000]  # 高位起步，避免与「用户手改封面」的元素 id 冲突


def nid(pfx="e"):
    _seq[0] += 1
    return f"{pfx}{_seq[0]:04d}"


def est_w(s, fs):
    return sum(fs * (1.0 if ord(c) > 0x2000 else 0.55) for c in s)


def _tokens(s):
    """把连续 ASCII（数字/字母/标点）聚成整体，避免折行把数字或单词切断。"""
    out, buf = [], ""
    for ch in s:
        if ord(ch) < 0x2000:
            buf += ch
        else:
            if buf:
                out.append(buf)
                buf = ""
            out.append(ch)
    if buf:
        out.append(buf)
    return out


def wrap_line(s, fs, max_w, indent="　"):
    """折行：按 token 切分；续行缩进 1 个全角空格（≈ 对齐首行「· 」之后的正文）。"""
    if est_w(s, fs) <= max_w:
        return [s]
    out, cur = [], ""
    for tk in _tokens(s):
        if est_w(cur + tk, fs) > max_w and cur.strip():
            out.append(cur.rstrip())
            cur = indent + tk
        else:
            cur += tk
    if cur.strip():
        out.append(cur.rstrip())
    return out


def e_bounds(e):
    if e["type"] == "arrow":
        xs = [e["x"] + p[0] for p in e["points"]]
        ys = [e["y"] + p[1] for p in e["points"]]
        return min(xs), min(ys), max(xs), max(ys)
    return e["x"], e["y"], e["x"] + e.get("width", 0), e["y"] + e.get("height", 0)


def make_frame(name, x, y, w, h, order, note):
    return {
        "type": "frame", "id": nid("frame"), "x": round(x), "y": round(y),
        "width": round(w), "height": round(h),
        "angle": 0, "strokeColor": INK, "backgroundColor": "transparent",
        "fillStyle": "solid", "strokeWidth": 2, "strokeStyle": "solid",
        "roughness": 1, "opacity": 100, "groupIds": [], "frameId": None,
        "roundness": None, "seed": 100000 + order, "version": 1,
        "versionNonce": 200000 + order, "isDeleted": False, "boundElements": None,
        "updated": 1, "link": None, "locked": False, "name": name,
        "customData": {"slideshow": {"schemaVersion": 2, "kind": "frame",
                                     "order": order, "deckName": DECK_NAME, "notes": note}},
    }


def _text(tid, x, y, s, fs, color=INK, lh=1.35, align="left"):
    lines = s.split("\n")
    w = max(est_w(ln, fs) for ln in lines)
    h = len(lines) * fs * lh
    return {
        "type": "text", "id": tid, "x": round(x, 1), "y": round(y, 1),
        "width": round(w, 1), "height": round(h, 1), "angle": 0, "strokeColor": color,
        "backgroundColor": "transparent", "fillStyle": "solid", "strokeWidth": 2,
        "strokeStyle": "solid", "roughness": 1, "opacity": 100, "groupIds": [],
        "frameId": None, "roundness": None, "seed": _seq[0] + 5000, "version": 1,
        "versionNonce": _seq[0] + 6000, "isDeleted": False, "boundElements": [],
        "updated": 1, "link": None, "locked": False, "text": s, "originalText": s,
        "fontSize": fs, "fontFamily": 1, "textAlign": align, "verticalAlign": "top",
        "containerId": None, "autoResize": True, "lineHeight": lh,
    }


def _box(rid, x, y, w, h, fill):
    return {
        "type": "rectangle", "id": rid, "x": round(x), "y": round(y), "width": round(w),
        "height": round(h), "angle": 0, "strokeColor": INK, "backgroundColor": fill,
        "fillStyle": "solid", "strokeWidth": 2, "strokeStyle": "solid", "roughness": 1,
        "opacity": 100, "groupIds": [], "frameId": None,
        "roundness": {"type": 3}, "seed": _seq[0] + 8000, "version": 1,
        "versionNonce": _seq[0] + 9000, "isDeleted": False, "boundElements": [],
        "updated": 1, "link": None, "locked": False,
    }


def _arrow(aid, x, y, dx, color=INK):
    return {
        "type": "arrow", "id": aid, "x": round(x), "y": round(y), "width": abs(dx),
        "height": 0, "angle": 0, "strokeColor": color, "backgroundColor": "transparent",
        "fillStyle": "solid", "strokeWidth": 3, "strokeStyle": "solid", "roughness": 1,
        "opacity": 100, "groupIds": [], "frameId": None, "roundness": None,
        "seed": _seq[0] + 7000, "version": 1, "versionNonce": _seq[0] + 7100,
        "isDeleted": False, "boundElements": [], "updated": 1, "link": None,
        "locked": False, "points": [[0, 0], [dx, 0]], "lastCommittedPoint": None,
        "startBinding": None, "endBinding": None, "startArrowhead": None,
        "endArrowhead": "arrow", "elbowed": False,
    }


def build_quote(spec, order, frame_xy):
    """引子页：一句 kicker ＋ 一句居中引言 ＋ 一个大问句。制造悬念，不展开。"""
    fx, fy = frame_xy
    W = 1180
    els = []
    kicker = _text(nid("t"), 0, 0, spec["kicker"], 22, GRAY, align="center")
    kicker["x"] = fx + (W - kicker["width"]) / 2
    kicker["y"] = fy + 70
    els.append(kicker)
    quote = _text(nid("t"), 0, 0, spec["quote"], 30, INK, 1.5, align="center")
    quote["x"] = fx + (W - quote["width"]) / 2
    quote["y"] = fy + 165
    els.append(quote)
    q = _text(nid("t"), 0, 0, spec["question"], 46, BLUE, align="center")
    q["x"] = fx + (W - q["width"]) / 2
    q["y"] = fy + 430
    els.append(q)
    H = 560
    frame = make_frame(spec["frame"], fx, fy, W, H, order, spec["note"])
    for e in els:
        e["frameId"] = frame["id"]
    return frame, els, (W, H)


def build_cards(spec, order, frame_xy):
    """卡片页：标题 + N 张横向卡片（带箭头）+ 底部一句。"""
    fx, fy = frame_xy
    W = 1180
    els = []
    title = _text(nid("t"), fx + 46, fy + 40, spec["title"], 38, INK)
    els.append(title)

    cards = spec["cards"]
    n = len(cards)
    gap = 48
    cw = (W - 92 - (n - 1) * gap) // n
    ch = 360
    cy = fy + 150
    for i, c in enumerate(cards):
        cx = fx + 46 + i * (cw + gap)
        els.append(_box(nid("b"), cx, cy, cw, ch, c["fill"]))
        head = _text(nid("t"), 0, 0, c["head"], 27, INK, align="center")
        body = _text(nid("t"), 0, 0, "\n".join(c["lines"]), 21, INK, 1.5, align="center")
        # 卡内文字块整体垂直居中（head ＋ 24 间距 ＋ body）
        block = head["height"] + 24 + body["height"]
        ty = cy + (ch - block) / 2
        head["x"] = round(cx + (cw - head["width"]) / 2, 1)
        head["y"] = round(ty, 1)
        body["x"] = round(cx + (cw - body["width"]) / 2, 1)
        body["y"] = round(ty + head["height"] + 24, 1)
        els.append(head)
        els.append(body)
        if i < n - 1:
            els.append(_arrow(nid("a"), cx + cw + 10, cy + ch / 2, gap - 20, GRAY))

    if spec.get("caption"):
        cap = _text(nid("t"), 0, 0, spec["caption"], 21, BLUE, 1.4, align="center")
        cap["x"] = fx + 46                      # 用帧内可用宽度做居中容器
        cap["width"] = W - 92
        cap["y"] = round(cy + ch + 60, 1)
        els.append(cap)

    H = round(cy + ch + 120) - fy if spec.get("caption") else round(cy + ch + 40) - fy
    frame = make_frame(spec["frame"], fx, fy, W, H, order, spec["note"])
    for e in els:
        e["frameId"] = frame["id"]
    return frame, els, (W, H)


def build_lines(spec, order, frame_xy):
    fx, fy = frame_xy
    W, H = 1180, 700
    els = [_text(nid("t"), fx + 46, fy + 44, spec["title"], 38, INK)]
    y = fy + 150
    lines = spec["lines"]
    for idx, ln in enumerate(lines):
        if not ln.strip():
            y += 26                      # 段落之间的空行
            continue
        is_sub = ln.startswith("　")
        pre = "　　" if is_sub else "　"
        sub = []
        for part in ln.split("\n"):      # 支持文案里的人工断行
            sub.extend(wrap_line(part, 27, W - 92, indent=pre))
        # 缩进行用略浅的深灰＋缩进：投影页只能靠缩进＋颜色拉开层级
        t = _text(nid("t"), fx + 46, y, "\n".join(sub), 27, SUB if is_sub else INK, 1.4)
        els.append(t)
        # 间距由**下一行**决定：下一行是缩进行 → 紧贴（10）；否则项间距（38）
        nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
        y += t["height"] + (10 if nxt.startswith("　") else 38)
    if spec.get("footer"):               # 页脚（如现场演示入口）：小一号 + 缩进，与正文分层
        y += 10
        t = _text(nid("t"), fx + 46 + 32, y, spec["footer"], 22, GRAY, 1.4)
        els.append(t)
        y += t["height"]
    H = max(H, int(y - fy) + 30)
    frame = make_frame(spec["frame"], fx, fy, W, H, order, spec["note"])
    for e in els:
        e["frameId"] = frame["id"]
    return frame, els, (W, H)


def _poly_arrow(aid, x, y, pts, dashed=False, color=INK, width=3):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return {
        "type": "arrow", "id": aid, "x": round(x), "y": round(y),
        "width": round(max(xs) - min(xs)), "height": round(max(ys) - min(ys)),
        "angle": 0, "strokeColor": color, "backgroundColor": "transparent",
        "fillStyle": "solid", "strokeWidth": width,
        "strokeStyle": "dashed" if dashed else "solid", "roughness": 1,
        "opacity": 100, "groupIds": [], "frameId": None, "roundness": None,
        "seed": _seq[0] + 7200, "version": 1, "versionNonce": _seq[0] + 7300,
        "isDeleted": False, "boundElements": [], "updated": 1, "link": None,
        "locked": False, "points": [[float(px), float(py)] for px, py in pts],
        "lastCommittedPoint": None, "startBinding": None, "endBinding": None,
        "startArrowhead": None, "endArrowhead": "arrow", "elbowed": False,
    }


def build_image(spec, order, frame_xy):
    with open(os.path.join(IMG_DIR, spec["src"]), encoding="utf-8") as f:
        src = json.load(f)
    all_els = src["elements"]
    x1, y1, x2, y2 = spec["crop"]
    cw, ch = x2 - x1, y2 - y1
    picked = []
    for e in all_els:
        eb = e_bounds(e)
        ex1, ey1, ex2, ey2 = eb
        if e["type"] == "arrow":
            # 箭头必须**整条**落在 crop 内，否则会留下起点悬空的断箭头
            if not (ex1 >= x1 - 1 and ey1 >= y1 - 1 and ex2 <= x2 + 1 and ey2 <= y2 + 1):
                continue
            picked.append(e)
            continue
        cx, cy = (ex1 + ex2) / 2, (ey1 + ey2) / 2
        if not (x1 <= cx <= x2 and y1 <= cy <= y2):
            continue
        if e["type"] == "rectangle" and e["width"] * e["height"] > 0.9 * cw * ch:
            continue
        picked.append(e)
    bx1 = min(e_bounds(e)[0] for e in picked)
    by1 = min(e_bounds(e)[1] for e in picked)
    bx2 = max(e_bounds(e)[2] for e in picked)
    by2 = max(e_bounds(e)[3] for e in picked)
    W, H = round(bx2 - bx1) + PAD * 2, round(by2 - by1) + PAD * 2
    fx, fy = frame_xy
    frame = make_frame(spec["frame"], fx, fy, W, H, order, spec["note"])
    mapping, out = {}, []
    for e in picked:
        new = json.loads(json.dumps(e))
        old = new["id"]
        new["id"] = f"s{order}-{old}"
        new["x"] = round(new["x"] + fx + PAD - bx1, 2)
        new["y"] = round(new["y"] + fy + PAD - by1, 2)
        new["frameId"] = frame["id"]
        mapping[old] = new["id"]
        out.append(new)
    for e in out:
        if isinstance(e.get("boundElements"), list):
            for it in e["boundElements"]:
                if "id" in it:
                    it["id"] = mapping.get(it["id"], it["id"])
        if e.get("containerId"):
            e["containerId"] = mapping.get(e["containerId"], e["containerId"])
        for key in ("startBinding", "endBinding"):
            if isinstance(e.get(key), dict) and "elementId" in e[key]:
                e[key]["elementId"] = mapping.get(e[key]["elementId"], e[key]["elementId"])

    # extra：裁切后在页内补画的元素（用源图坐标书写，这里统一换算到页内）
    def to_page(px, py):
        return (px - bx1 + PAD, py - by1 + PAD)

    for ex in spec.get("extra", []):
        if ex["kind"] == "arrow":
            pts = [to_page(px, py) for px, py in ex["pts"]]
            a = _poly_arrow(nid("a"), fx + pts[0][0], fy + pts[0][1],
                            [[p[0] - pts[0][0], p[1] - pts[0][1]] for p in pts],
                            dashed=ex.get("dashed", False), color=ex.get("color", INK))
            a["frameId"] = frame["id"]
            out.append(a)
        elif ex["kind"] == "text":
            px, py = to_page(ex["x"], ex["y"])
            t = _text(nid("t"), fx + px, fy + py, ex["text"], ex.get("fs", 15),
                      ex.get("color", INK), 1.3)
            t["frameId"] = frame["id"]
            out.append(t)
            # 补画后 frame 可能变大，重新贴合
            W = max(W, int(px + t["width"]) + PAD)
            H = max(H, int(py + t["height"]) + PAD)
            frame["width"], frame["height"] = W, H
    return frame, out, (W, H)


def load_cover():
    """读取现有文件的封面 frame ＋ 子元素（原样，保留用户手改），返回 (frame, children)。"""
    if not os.path.exists(DECK_PATH):
        return None, None
    with open(DECK_PATH, encoding="utf-8") as f:
        deck = json.load(f)
    els = deck["elements"]
    frame = next((e for e in els if e["type"] == "frame" and e.get("name", "").startswith("01")), None)
    if frame is None:
        return None, None
    kids = [e for e in els if e.get("frameId") == frame["id"]]
    # 更新讲稿，但视觉元素原样保留
    frame["customData"] = {"slideshow": {"schemaVersion": 2, "kind": "frame",
                                         "order": 0, "deckName": DECK_NAME, "notes": N_COVER}}
    return frame, kids


def main():
    cover_frame, cover_kids = load_cover()

    elements = []
    order = 0
    if cover_frame is not None:
        elements.append(cover_frame)
        elements.extend(cover_kids)
        y_cursor = cover_frame["y"] + cover_frame["height"] + GAP
        order = 1
    else:
        y_cursor = 0

    # 02 引子(自举信号) → 03 意义 → 04 总览(图) → 05 收集设计 → 06 收集举例 → 07 打分图 → 08 打分举例 → 09 展示 → 10 入库 → 11 网站图 → 12 收尾
    for spec in [T_HOOK, T_WHY, I_PAGES[0], T_COLLECT, T_COLLECT_EX, I_PAGES[1], T_SCORE_EX,
                 T_DISPLAY, T_INGEST, I_PAGES[2], T_CLOSE]:
        if "quote" in spec:
            frame, els, (_w, h) = build_quote(spec, order, (0, y_cursor))
        elif spec in (T_WHY, T_COLLECT, T_COLLECT_EX, T_SCORE_EX, T_DISPLAY, T_INGEST, T_CLOSE):
            if "cards" in spec:
                frame, els, (_w, h) = build_cards(spec, order, (0, y_cursor))
            else:
                frame, els, (_w, h) = build_lines(spec, order, (0, y_cursor))
        else:
            frame, els, (_w, h) = build_image(spec, order, (0, y_cursor))
        elements.append(frame)
        elements.extend(els)
        y_cursor += h + GAP
        order += 1

    deck = {
        "type": "excalidraw", "version": 2, "source": "hermes-agent",
        "elements": elements,
        "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None,
                     "frameRendering": {"enabled": True, "name": True, "outline": True, "clip": True}},
        "files": {},
    }
    with open(DECK_PATH, "w", encoding="utf-8") as f:
        json.dump(deck, f, ensure_ascii=False, indent=1)

    notes = [f"# 讲稿 · {DECK_NAME}\n",
             "> 配合 `演示文稿.excalidraw`。**放映时讲稿在 presenter notes 窗口，投屏看不到。**\n"
             "> 启动：点 Slideshow 脚本图标＝全屏放映；Alt+点击＝窗口；Ctrl+点击＝放映编辑器。\n"
             "> 键位：↓/→/Space 下页，↑/← 上页，Home/End 首末页，F 全屏，Esc 结束。\n"]
    frames = sorted([e for e in elements if e["type"] == "frame"],
                    key=lambda f: f["customData"]["slideshow"]["order"])
    for f in frames:
        md = f["customData"]["slideshow"]
        notes.append(f"\n---\n\n## 第 {md['order'] + 1} 页 · {f['name']}\n\n{md['notes']}\n")
    with open(NOTES_PATH, "w", encoding="utf-8") as f:
        f.write("".join(notes))

    verify(elements)


def verify(elements):
    frames = [e for e in elements if e["type"] == "frame"]
    others = [e for e in elements if e["type"] != "frame"]
    ids = [e["id"] for e in elements]
    assert len(ids) == len(set(ids)), "元素 id 重复"
    fids = {f["id"] for f in frames}
    for e in others:
        assert e.get("frameId") in fids, f"{e['id']} 未挂到 frame"
        fr = next(f for f in frames if f["id"] == e["frameId"])
        ex1, ey1, ex2, ey2 = e_bounds(e)
        assert ex1 >= fr["x"] - 1 and ey1 >= fr["y"] - 1, f"{e['id']} 超出 frame 左上"
        assert ex2 <= fr["x"] + fr["width"] + 1, f"{e['id']} 超出 frame 右"
        assert ey2 <= fr["y"] + fr["height"] + 1, f"{e['id']} 超出 frame 下"
    for i, a in enumerate(frames):
        for b in frames[i + 1:]:
            assert not (a["x"] < b["x"] + b["width"] and a["x"] + a["width"] > b["x"]
                        and a["y"] < b["y"] + b["height"] and a["y"] + a["height"] > b["y"]), \
                f"frame 重叠: {a['name']} / {b['name']}"
    by_name = sorted(frames, key=lambda f: f["name"])
    by_order = sorted(frames, key=lambda f: f["customData"]["slideshow"]["order"])
    assert by_name == by_order, "字母序与 order 不一致"
    print(f"OK  演示文稿.excalidraw  {len(frames)} 页 / {len(elements)} 个元素")
    for f in by_order:
        zoom = 1080 / f["height"]
        print(f"    {f['name']:<20} {int(f['width'])}x{int(f['height']):<8} zoom {zoom:4.2f}"
              f"  讲稿 {len(f['customData']['slideshow']['notes'])} 字")
    print(f"OK  讲稿.md  {os.path.getsize(NOTES_PATH)} bytes")


if __name__ == "__main__":
    main()
