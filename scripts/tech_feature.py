"""技术特征提取（护城河字段）——调用 SiliconFlow 的 DeepSeek-V4-Pro。

从标题+摘要提取一句技术特征（数值参数/技术路线/工艺/标准/性能指标）。
评测集见 scripts/tech_feature_eval.json（pro 准确率 96.7%，2026-08-23 定稿）。

限流策略（服务器每 30 分钟抓取 70 源、每轮约 300-500 条）：
1. 仅对 Layer 2/3 条目提取（Layer 1 政策类跳过，减少 50%+ 请求）
2. 缓存去重（同 URL 已提取过跳过，tech-feature-cache 由调用方维护）
3. 串行 + 每请求间隔（QPS 控制）
4. 静默降级（LLM 不可用/超限时返回空串，不影响抓取主流程）
"""

from __future__ import annotations

import os
import time

import requests

_SF_BASE = "https://api.siliconflow.cn/v1"
_SF_MODEL = "deepseek-ai/DeepSeek-V4-Pro"

# 提示词模板（2026-08-23 与老温核定 + 评测集验证，勿擅改）
PROMPT_TEMPLATE = """你是绿色低碳科技领域的技术情报分析师。从下面新闻的标题和摘要中，提取该新闻涉及的"技术特征"——即具体的技术参数、技术路线、工艺方法或性能指标。

技术特征包括（但不限于）：
1. 降本曲线（成本下降，如"度电成本下降40%"）
2. 设备参数（功率/效率/容量/寿命，如"转换效率26.1%"）
3. 工艺包特点（技术路线/流程，如"闪速焦耳热热化学转化"）
4. 指标要求（政策/规划/项目中的具体技术指标，如"SAF掺混比例1%/2%/5%""绿电占比80%""储能时长4h"）
5. 性能提升（速度/精度/容量提升，如"启动速度提升3倍"）

规则：
- 只输出一句技术特征描述，不超过 50 字
- 新闻完全不涉及任何技术参数/指标/路线时，才输出「无」
- 直接给结论，不要解释、不要前缀

标题：{title}
摘要：{summary}

技术特征："""

# QPS 控制：全局上次调用时间戳，串行 + 最小间隔（SiliconFlow 免费/付费档 QPS 宽容）
_last_call_ts: float = 0.0
_MIN_INTERVAL: float = 0.2  # 200ms → QPS=5，与腾讯云 TMT 同级

_SERVICE_DISABLED: bool = False  # 连续失败后熔断，本轮不再调用


def _load_key() -> str:
    """从环境变量或项目根 .env / 服务器 /etc/green-policy.env 读 SiliconFlow key。"""
    key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if key:
        return key
    for path in (".env", "/etc/green-policy.env"):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.lower().startswith("siliconflow_api_key"):
                        return line.split("=", 1)[1].strip()
        except OSError:
            continue
    return ""


def extract_tech_feature(title: str, summary: str, _retry: int = 0) -> str:
    """提取技术特征，失败返回空串（静默降级，不抛异常）。

    返回：技术特征描述（一句 ≤50 字），或「无」，或空串（LLM 不可用）。
    """
    global _SERVICE_DISABLED, _last_call_ts
    if _SERVICE_DISABLED:
        return ""
    key = _load_key()
    if not key:
        _SERVICE_DISABLED = True
        return ""

    title = (title or "").strip()
    summary = (summary or "").strip()[:500]
    if not title:
        return ""

    # QPS 控制：距上次调用不足最小间隔则等待
    elapsed = time.monotonic() - _last_call_ts
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)

    prompt = PROMPT_TEMPLATE.format(title=title, summary=summary)
    try:
        _last_call_ts = time.monotonic()
        r = requests.post(
            f"{_SF_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={
                "model": _SF_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 800,   # reasoning 模型：给思考留足空间
                "temperature": 0,
            },
            timeout=(15, 60),
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"].get("content", "").strip()
        if content:
            return content
        # 空 content（reasoning 被截断）→ 退避重试一次
        if _retry < 1:
            time.sleep(1.0)
            return extract_tech_feature(title, summary, _retry + 1)
        return ""
    except Exception:
        # 静默降级：连续失败熔断，本轮不再调用
        if _retry >= 1:
            _SERVICE_DISABLED = True
        return ""
