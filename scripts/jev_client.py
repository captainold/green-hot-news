#!/usr/bin/env python3.11
"""Jev（TypeSafe System One）判定客户端 —— 复用范式照 `tech_feature.py`。

⚠️ 先明确概念：Jev 是**决策模型**，不是 LLM。它不生成文本、不解释理由，
只回答三件事（本模块只用前两种）：
  • noul   —— 是/否的概率（0~1）
  • score  —— 有序档位（2~10 档），返回概率加权位置 + 概率分布 + confidence
  • choice —— 从给定选项里选一个，返回选项 + 概率分布 + confidence
因此：**问法即全部**。选项写不清，答案就没意义；答案只能落在你给的选项里（不用解析文本）。

官方设计要点（决定了本模块的形态）：
  1. 一次请求里的多个问题**并行、互不可见** → 任何问题都不能依赖另一个问题的答案
     （所以我们把「内容强度」的档位描述写成与细类无关的四档，细类单独用 choice 问）；
  2. 权重与逻辑留在调用方（即本模块/主流程），Jev 只给判定；
  3. confidence 是给调用方做路由用的（低置信 → 回落关键词判定）。

接线（2026-09-23 打通）：本地 TokenHub 网关已内置 typesafe 适配器，
把 Chat Completions 翻译成 System One，因此默认走网关的 OpenAI 兼容口：

    POST {JEV_BASE_URL}/v1/chat/completions
    { "model": "TypeSafe/jev-latest",
      "messages": [{"role":"user","content":"..."}],   # 有 typesafe_state 时为占位
      "typesafe_state": {...},        # 要判定的内容（任意 JSON）
      "typesafe_questions": {...} }    # 问题定义（choice/score/noul）
响应是正常 chat completion，`choices[0].message.content` 末尾附 `answers: {...}` 原始 JSON。

配置（环境变量 → 项目根 .env → 服务器 /etc/green-policy.env）：
  JEV_DIALECT   tokenhub（默认，走网关 OpenAI 口）｜native（直连 /v1/systemone）
  JEV_BASE_URL  tokenhub 默认 http://localhost:8080 ｜ native 默认 https://api.typesafe.ai
  JEV_MODEL     tokenhub 默认 TypeSafe/jev-latest ｜ native 默认 jev-1.13
                ⚠️ 钉版本，勿用 jev-latest 之外的浮动名做阈值校准；native 下也别用 "latest"
  JEV_API_KEY   TokenHub 项目级 key（sk_…）
  JEV_PATH      仅 native 用，默认 /v1/systemone

设计纪律：
  • 失败一律**静默降级**（返回 None + 错误串），绝不抛异常打断抓取主流程；
  • 致命状态码（401/402/403/429）立即熔断，本轮不再尝试；
  • 串行 + 最小间隔（_MIN_INTERVAL）限流；快速失败类错误（连接拒绝/5xx 秒回）自动重试
    ≤2 次（0.8s 退避，2026-09-29 补——依据 09-28 实测上游 503 风暴，见实验报告 §3.3）。
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

try:  # Windows 控制台 GBK：避免中日文字符/emoji 让脚本中途崩掉
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent

# ── 限流与熔断（与 tech_feature.py 同范式）──────────────────────────────
_last_call_ts: float = 0.0
_MIN_INTERVAL: float = 0.1          # 100ms → QPS=10；Jev 单次 0.3~0.5s，实际远低于此
_SERVICE_DISABLED: bool = False     # 熔断后本轮不再调用
_fail_count: int = 0                # 连续失败计数，≥3 次熔断
_FATAL_STATUS = {401, 402, 403, 429}
_RETRY_MAX_FAST_S = 10.0   # 快于该值的失败才重试（503 秒回/连接拒绝）；慢超时不重试防主流程延迟翻倍
_RETRY_BACKOFF_S = 0.8

_SESSION = requests.Session()
_SESSION.trust_env = False          # localhost 网关绝不走 mihomo 代理

# ── 五问定义（P0 已验证被网关接受；改这里 = 改判定口径，需同步方案文档）──
SUB_CRITERIA = {
    "政策法规": "政府发文、法规、规划、部委通知等官方文件",
    "国际动态": "国际组织、国家之间的协议/峰会/谈判/国际倡议",
    "技术研发": "技术突破、样机、中试、应用开发、工程示范",
    "基础研究": "论文、理论研究、学术发现、研究报告",
    "社会创新": "制度机制/模式创新、绿色消费与生活方式、公众参与",
    "企业经营": "企业经营进展、投产签约、产品发布与落地、AI 产品化",
    "金融资本": "碳市场、碳价、绿色金融产品、融资并购、资本信号",
}
# 内容强度四档：描述必须与细类无关（同一请求内问题互不可见，不能引用 sub_dim 的答案）
STRENGTH_LEVELS = [
    "里程碑级：国家级/全球级的开创性、突破性、历史性事件",
    "重要级：高规格推进、关键节点、明确的政策/技术转向",
    "进展级：有实质内容的常规进展、报告、数据发布",
    "常规级：无强信号的普通条目",
]
# 0（常规级）→ None：由调用方按细类取兜底分（权威表在 update_news.py 的 DEFAULT_STRENGTH_BY_SUB）
STRENGTH_TO_SCORE = {3: 30, 2: 25, 1: 20, 0: None}
TOPIC_LEVELS = [
    "核心议题：碳市场/碳交易/碳价/双碳/碳中和/碳足迹等",
    "重要议题：新能源/储能/氢能/光伏/风电/绿电/CCUS/绿色金融/ESG/AI 等",
    "一般议题：节能/环保/气候/绿色/低碳/减排/能源/电力等",
    "弱相关：以上都不明显",
]
TOPIC_TO_SCORE = {0: 25, 1: 18, 2: 12, 3: 6}

# ── 内容强度的"形态 C"：不问绝对档位，改问三个可证的是非，档位在本仓库合成 ──
# 依据（2026-09-23 P0 实测，见 docs/2026-09-23 Jev（TypeSafe）接入方案-讨论稿.md §七）：
#   A 现状四档 / B 频率锚定四档 的输出 83~97% 挤在最高两档（无方差 → 无法排序）；
#   C 三问 noul 是唯一有区分度的形态（分布 0/5/13/12）。且官方设计本就要求"权重与逻辑留在调用方"。
NOUL_STRENGTH_QUESTIONS = {
    "is_milestone": {
        "type": "noul",
        "instructions": "这条内容是否为全球或国家级的历史性首次/开创性事件？"
                        "必须能在内容里指出「首次/首个/历史性/破纪录」之类，且层级是国家或全球；"
                        "一般的「重要进展」不算。",
    },
    "is_important": {
        "type": "noul",
        "instructions": "这条内容是否为明确的关键节点、高规格推进、或政策/技术转向？"
                        "（前提：它不是历史性首次。）",
    },
    "is_routine": {
        "type": "noul",
        "instructions": "这条内容是否缺少可验证的实质信息？"
                        "（可验证的实质信息 = 数字、政策条款、技术参数、协议/资金、明确的数据结论。）"
                        "例行会议、榜单、颁奖、仪式、宣传稿、报名或订阅通知、只有口号没有内容的，算缺少。",
    },
}


def build_noul_strength_questions() -> dict:
    """形态 C 的问题集（三个互相独立的是非题，同一请求内互不可见，不违反 Jev 的并行约束）。"""
    return {k: dict(v) for k, v in NOUL_STRENGTH_QUESTIONS.items()}


def compose_strength_level(answers: dict, threshold: float = 0.5) -> int:
    """三个 noul 概率 → 档位 3/2/1/0（合成逻辑在本仓库，不在 Jev 里）。"""
    def p(k: str) -> float:
        a = (answers or {}).get(k)
        return _num(a.get("noul") if isinstance(a, dict) else None)

    cands = [(p("is_milestone"), 3), (p("is_important"), 2), (p("is_routine"), 0)]
    cands = [(v, lvl) for v, lvl in cands if v >= threshold]
    if not cands:
        return 1                       # 三个都不明确 → 进展级（有实质内容但无强信号）
    return max(cands)[1]


def level_to_score(level: int, sub: str = "", fallback: int | None = None) -> int | None:
    """档位 → 分值；0（常规级）返回 fallback（调用方按细类的兜底分）。"""
    mapped = STRENGTH_TO_SCORE.get(level)
    return mapped if mapped is not None else fallback


def _load_cfg(name: str, default: str = "") -> str:
    """环境变量 → 项目根 .env → /etc/green-policy.env。"""
    v = os.environ.get(name, "").strip()
    if v:
        return v
    for path in (ROOT / ".env", Path("/etc/green-policy.env")):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.lower().startswith(name.lower() + "="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return default


def dialect() -> str:
    return (_load_cfg("JEV_DIALECT", "tokenhub") or "tokenhub").lower()


def is_enabled() -> bool:
    """是否具备调用条件（有 key 且未熔断）。主流程据此决定要不要走 Jev。"""
    if _SERVICE_DISABLED:
        return False
    return bool(_load_cfg("JEV_API_KEY"))


def shadow_enabled() -> bool:
    """P2 影子模式开关（JEV_SHADOW=1/true/yes/on）。

    关闭时主流程完全不碰 Jev（默认关闭，保证"关开关即回到现状"）。
    """
    return (_load_cfg("JEV_SHADOW", "") or "").strip().lower() in ("1", "true", "yes", "on")


def shadow_max() -> int:
    """P2 影子模式每轮判定条数上限（成本护栏，JEV_SHADOW_MAX，默认 600）。"""
    try:
        return max(0, int(_load_cfg("JEV_SHADOW_MAX", "600") or 600))
    except (TypeError, ValueError):
        return 600


def shadow_budget() -> float:
    """P2 影子模式墙钟预算秒数（JEV_SHADOW_BUDGET，默认 180s）。

    ⚠️ 为什么必须有：单次 timeout=45s，若上游变慢（2026-09-28 实测 503 风暴），
    600 条 × 45s / 4 并发 = 最坏 112 分钟，会把 30 分钟的 timer 拖爆。
    超预算即停止判定剩余条目（已判的照常入档），主流程不受影响。
    """
    try:
        return max(10.0, float(_load_cfg("JEV_SHADOW_BUDGET", "180") or 180))
    except (TypeError, ValueError):
        return 180.0


def shadow_interval_min() -> float:
    """影子模式最小运行间隔分钟（JEV_SHADOW_INTERVAL_MIN，默认 0=每轮都跑）。

    成本护栏③（2026-10-07 老温批可）：影子随主流程每 30 分钟触发一次，
    去重（护栏②，update_news._run_jev_shadow）后剩余判定量已很小，
    此间隔是防重复判定/窗口抖动的第二道护栏。
    """
    try:
        return max(0.0, float(_load_cfg("JEV_SHADOW_INTERVAL_MIN", "0") or 0))
    except (TypeError, ValueError):
        return 0.0


def score_level(answers: dict, key: str = "strength") -> int | None:
    """score 型问题的概率加权档位（四舍五入后截断到 0~3）；无答案返回 None。"""
    a = (answers or {}).get(key) or {}
    if not a:
        return None
    return max(0, min(3, int(round(_num(a.get("score"), 0)))))



def reset() -> None:
    """清空熔断状态（长驻进程每轮开始时调用）。"""
    global _SERVICE_DISABLED, _fail_count
    _SERVICE_DISABLED = False
    _fail_count = 0


def build_questions(with_sub: bool = True) -> dict:
    """组装 5 问（1 次请求并列回答）。with_sub=False 时省掉七细类 choice。"""
    q: dict = {
        "is_green": {
            "type": "noul",
            "instructions": "这条内容是否与绿色低碳、气候、能源转型直接相关？",
            "criteria": {"true": "主题本身就是绿色低碳/气候/能源",
                         "false": "只是泛泛提及，或与该主题无关"},
        },
        "is_noise": {
            "type": "noul",
            "instructions": "这条内容是否为无实质信息的仪式/揭牌/榜单/广告/导航/邮件订阅类内容？",
        },
        "strength": {
            "type": "score",
            "instructions": "这条新闻的内容强度处于哪一档？（看事件本身的分量，不看来源）",
            "criteria": STRENGTH_LEVELS,
        },
        "topic": {
            "type": "score",
            "instructions": "这条内容与本雷达核心议题的相关程度处于哪一档？",
            "criteria": TOPIC_LEVELS,
        },
    }
    if with_sub:
        q["sub_dim"] = {
            "type": "choice",
            "instructions": "这条内容属于哪一细类？",
            "criteria": SUB_CRITERIA,
        }
    return q


def state_from_item(item: dict) -> dict:
    """把一条新闻 item 转成 Jev 的 state（判定输入）。"""
    return {
        "title": item.get("title", ""),
        "summary": (item.get("summary", "") or "")[:600],
        "source": item.get("site_name", ""),
        "library": item.get("library", "media"),
    }


def _parse_answers(content: str) -> dict | None:
    """从网关渲染文本里取回原始 answers JSON（末段 `answers: {...}`）。"""
    marker = "answers: "
    idx = content.rfind(marker)
    if idx < 0:
        return None
    try:
        return json.loads(content[idx + len(marker):].strip())
    except Exception:
        return None


def evaluate(state: dict, questions: dict, timeout: int = 45) -> tuple[dict | None, float, str]:
    """执行一次判定。返回 (answers, 秒, 错误串)；失败时 answers=None 且静默（不抛）。

    一次请求回答全部问题；同一请求内各问题互不可见（不要写互相依赖的问题）。
    内置重试：快速失败类错误（单次尝试 ≤10s，如 503 秒回/连接拒绝）重试 ≤2 次（0.8s 退避）；
    慢超时（>10s）与致命状态码（401/402/403/429）不重试。熔断计数按一次逻辑调用计 1
    （不按尝试次数，避免一次抖动直接把本轮打熔断）。
    """
    global _SERVICE_DISABLED, _fail_count, _last_call_ts
    if _SERVICE_DISABLED:
        return None, 0.0, "service_disabled（本轮已熔断）"

    key = _load_cfg("JEV_API_KEY")
    if not key:
        _SERVICE_DISABLED = True
        return None, 0.0, "no_api_key"

    d = dialect()
    base = _load_cfg("JEV_BASE_URL", "http://localhost:8080" if d == "tokenhub"
                     else "https://api.typesafe.ai")
    model = _load_cfg("JEV_MODEL", "TypeSafe/jev-latest" if d == "tokenhub" else "jev-1.13")
    path = _load_cfg("JEV_PATH", "/v1/systemone")

    if d == "tokenhub":
        url = base.rstrip("/") + "/v1/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "绿色低碳动态判定"}],  # state 由扩展字段提供
            "typesafe_state": state,
            "typesafe_questions": questions,
        }
    else:
        url = base.rstrip("/") + path
        payload = {"model": model, "state": state, "questions": questions}

    # 限流 + 重试（2026-09-29 补）：失败语义与旧版一致（一次逻辑调用计 1 次失败），
    # 区别仅在"快速失败"类错误（秒回的 5xx/连接拒绝）自动多试 2 次。
    answers, dt, err = None, 0.0, ""
    for attempt in range(3):              # 首次 + 最多 2 次重试
        elapsed = time.monotonic() - _last_call_ts
        if elapsed < _MIN_INTERVAL:
            time.sleep(_MIN_INTERVAL - elapsed)

        t0 = time.monotonic()
        _last_call_ts = t0
        try:
            r = _SESSION.post(url, headers={"Authorization": f"Bearer {key}",
                                            "Content-Type": "application/json"},
                              json=payload, timeout=(10, timeout))
        except Exception as exc:
            answers, dt, err = None, time.monotonic() - t0, f"{type(exc).__name__}: {exc}"
        else:
            dt = time.monotonic() - t0
            if r.status_code in _FATAL_STATUS:
                _SERVICE_DISABLED = True      # 认证/余额/限流 → 立即熔断，不重试
                return None, dt, f"HTTP {r.status_code}: {r.text[:160]}"
            if r.status_code != 200:
                answers, err = None, f"HTTP {r.status_code}: {r.text[:160]}"
            else:
                try:
                    body = r.json()
                except Exception as exc:
                    answers, err = None, f"JSON 解析失败: {exc}"
                else:
                    if d == "tokenhub":
                        content = (((body.get("choices") or [{}])[0].get("message") or {})
                                   .get("content") or "")
                        answers = _parse_answers(content)
                        if answers is None:
                            err = f"未取到 answers（上游返回：{content[:180]}）"
                    else:
                        answers = body.get("answers") or {}
                        if not answers:
                            err = f"answers 为空（{json.dumps(body, ensure_ascii=False)[:160]}）"

        if answers is not None:
            _fail_count = 0
            return answers, dt, ""
        if dt > _RETRY_MAX_FAST_S or attempt >= 2:
            break                   # 慢超时重试会让主流程延迟翻倍，宁可直接降级
        time.sleep(_RETRY_BACKOFF_S)

    _fail_count += 1
    if _fail_count >= 3:
        _SERVICE_DISABLED = True
    return None, dt, err


# ── 答案 → 打分量（判定归 Jev，合成归本仓库：公式不变，只换判定器）────────
def _num(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def strength_score(sub: str, answers: dict, fallback: int | None = None) -> int | None:
    """内容强度：取 strength 档位 → 换算成六维模型的 0-30 分。

    档位由 score 的概率加权位置四舍五入得到；落到「常规级」时用 fallback
    （调用方传 update_news.DEFAULT_STRENGTH_BY_SUB[sub]，保持公式唯一权威）。
    """
    a = (answers.get("strength") or {})
    lvl = int(round(_num(a.get("score"), 0)))
    lvl = max(0, min(3, lvl))
    mapped = STRENGTH_TO_SCORE[lvl]
    return mapped if mapped is not None else fallback


def topic_score(answers: dict) -> int | None:
    a = (answers.get("topic") or {})
    if not a:
        return None
    lvl = max(0, min(3, int(round(_num(a.get("score"), 3)))))
    return TOPIC_TO_SCORE[lvl]


def sub_dimension(answers: dict) -> str:
    """七细类（choice）。返回 "" 表示未给出/不在选项内。"""
    c = (answers.get("sub_dim") or {})
    v = str(c.get("choice", "") or "").strip()
    return v if v in SUB_CRITERIA else ""


def noul(answers: dict, key: str) -> float | None:
    a = (answers.get(key) or {})
    return None if not a else round(_num(a.get("noul"), 0.0), 3)


def confidence(answers: dict, key: str) -> float | None:
    a = (answers.get(key) or {})
    if not a or "confidence" not in a:
        return None
    return round(_num(a.get("confidence"), 0.0), 3)


def judge_item(item: dict, with_sub: bool = True, fallback: int | None = None
               ) -> tuple[dict | None, float, str]:
    """一步到位：item → (判定结果字典, 秒, 错误串)。

    结果字典字段：sub / strength / topic / is_green / is_noise / conf_strength / conf_topic
    """
    answers, dt, err = evaluate(state_from_item(item), build_questions(with_sub))
    if answers is None:
        return None, dt, err
    return {
        "sub": sub_dimension(answers),
        "strength": strength_score(item.get("sub_dimension", ""), answers, fallback),
        "topic": topic_score(answers),
        "is_green": noul(answers, "is_green"),
        "is_noise": noul(answers, "is_noise"),
        "conf_strength": confidence(answers, "strength"),
        "conf_topic": confidence(answers, "topic"),
    }, dt, ""


# 内容强度的三种问法（供标定/对照用；切换前必须先在 gold set 上比过）
STRENGTH_FORMS = ("A", "B", "C")
_ANCHORED_LEVELS = [
    "里程碑级（全库约占 2~5%）：全球或国家级的历史性首次/开创性突破"
    "（如全国碳市场启动、全球首台套、国际条约达成）",
    "重要级（全库约占 15~25%）：明确的关键节点、高规格推进、政策或技术转向，但不是历史性首次",
    "进展级（全库约占 40~50%）：有实质信息的常规进展——报告发布、数据公布、企业正常经营动作、单篇论文",
    "常规级（全库约占 25~40%）：无强信号的普通条目——例行会议、榜单、仪式、宣传稿、只有口号没有信息的内容",
]


def judge_strength(item: dict, form: str = "A", fallback: int | None = None
                   ) -> tuple[dict | None, float, str]:
    """按指定问法判"内容强度"，返回 ({level, score, extra...}, 秒, 错误串)。

    form=A：现状四档（score，定性描述）
    form=B：频率锚定四档（score，给出各档应占比例）
    form=C：三个可证的是非（noul）+ 本仓库合成档位 —— P0 实测唯一有区分度的形态
    """
    form = (form or "A").upper()
    if form == "C":
        answers, dt, err = evaluate(state_from_item(item), build_noul_strength_questions())
        if answers is None:
            return None, dt, err
        lvl = compose_strength_level(answers)
        return {
            "level": lvl,
            "score": level_to_score(lvl, item.get("sub_dimension", ""), fallback),
            "is_milestone": noul(answers, "is_milestone"),
            "is_important": noul(answers, "is_important"),
            "is_routine": noul(answers, "is_routine"),
        }, dt, ""

    q = build_questions(with_sub=False)
    q["strength"]["criteria"] = _ANCHORED_LEVELS if form == "B" else STRENGTH_LEVELS
    answers, dt, err = evaluate(state_from_item(item), q)
    if answers is None:
        return None, dt, err
    a = answers.get("strength") or {}
    lvl = max(0, min(3, int(round(_num(a.get("score"), 0)))))
    return {
        "level": lvl,
        "score": level_to_score(lvl, item.get("sub_dimension", ""), fallback),
        "conf": confidence(answers, "strength"),
    }, dt, ""
