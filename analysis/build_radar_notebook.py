#!/usr/bin/env python3
"""生成《绿色低碳动态雷达·四维透视》Notebook（Positron 用）"""
import nbformat as nbf
from pathlib import Path

nb = nbf.v4.new_notebook()
cells = []

def md(src):
    cells.append(nbf.v4.new_markdown_cell(src))

def code(src):
    cells.append(nbf.v4.new_code_cell(src))

# ---------- 0. 标题 ----------
md("""# 🌍 绿色低碳动态雷达 · 四维透视

> 数据源：`data/history.json`（62 天累积窗口） ｜ 生成：2026-08-19
> 环境：Python 3.13 + pandas + plotly + jieba
> 操作：逐格执行（Shift+Enter），或顶部 Run All 一次跑完
>
> **Positron 提示**：代码块输出表格后，点表格右上角的小格子图标，可打开 Data Explorer 交互式翻表~""")

# ---------- 1. 数据加载 ----------
md("""## 一、数据加载

从 `../data/history.json` 读取 62 天累积数据，转成 DataFrame。""")

code("""import json
from pathlib import Path
from collections import Counter

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import jieba

DATA_DIR = Path("../data")
with open(DATA_DIR / "history.json", encoding="utf-8") as f:
    hist = json.load(f)

df = pd.DataFrame(hist["items"])
print(f"共 {len(df)} 条 | 窗口 {hist['window_days']} 天 | 生成于 {hist['generated_at']}")""")

code("""# 混合时区（+08:00 / Z）统一转北京时间，再拆出日期
df["dt"] = pd.to_datetime(df["published_at"], utc=True, errors="coerce").dt.tz_convert("Asia/Shanghai")
df["date"] = df["dt"].dt.date

# score_breakdown 拆成独立列（source 是"来源权威分"→src_score；people 是"人物分"，防与顶层人物名单字段撞名 →people_score）
bd = df["score_breakdown"].apply(pd.Series).rename(columns={"source": "src_score", "people": "people_score"})
df = pd.concat([df.drop(columns=["score_breakdown"]), bd], axis=1)

df[["title", "dimension", "region", "score", "score_level",
    "src_score", "strength", "topic", "freshness", "date", "source"]].head()""")

# ---------- 2. 总览仪表盘 ----------
md("""## 二、总览仪表盘

四维分布 / 评分等级 / 区域版图，一眼看清 62 天数据全貌。""")

code("""# ⚠️ plotly 6.x 的 px.pie(names=...) 不再自动聚合（逐行 labels + 空 values），
# Positron 渲染时会把每行当独立扇区 → 必须先用 value_counts 显式聚合
dim_counts = df["dimension"].value_counts().reset_index()
dim_counts.columns = ["dimension", "count"]
fig1 = px.pie(dim_counts, names="dimension", values="count",
              title="四维分布（政府/行业/金融/AI）",
              hole=0.45, category_orders={"dimension": ["政府", "行业", "金融", "AI"]})
fig1.update_traces(textinfo="value+percent")
fig1.show()""")

code("""fig2 = px.histogram(df, x="score", color="score_level", nbins=20,
                   title="评分分布（S≥85 / A≥70 / B≥55 / C≥40 / D）")
fig2.show()""")

code("""# 同上：区域图也要显式聚合（空 region 显示为"未标注"）
region_counts = df["region"].replace("", "未标注").value_counts().reset_index()
region_counts.columns = ["region", "count"]
fig3 = px.pie(region_counts, names="region", values="count",
              title="区域版图（中国/国际/美国/印度/欧盟/日本）", hole=0.4)
fig3.show()""")

# ---------- 3. 时间序列 ----------
md("""## 三、62 天时间序列

每天入库多少条？哪个维度在升温？堆积面积图看四维热度演变。""")

code("""daily = df.groupby(["date", "dimension"]).size().reset_index(name="count")
fig4 = px.area(daily, x="date", y="count", color="dimension",
               line_group="dimension", title="每日入库量 · 四维堆积面积图")
fig4.show()""")

code("""# 周节奏：星期几最活跃？（0=周一）
df["weekday"] = df["dt"].dt.dayofweek
wd = df.groupby(["weekday", "dimension"]).size().reset_index(name="count")
fig5 = px.bar(wd, x="weekday", y="count", color="dimension",
              title="按星期几的入库节奏（政府源周末是否断更？）")
fig5.show()""")

# ---------- 4. 来源分析 ----------
md("""## 四、来源贡献分析

哪些源撑起了内容大盘？各维度的头部来源分别是谁？""")

code("""src_top = df["source"].value_counts().head(15).reset_index()
src_top.columns = ["source", "count"]
fig6 = px.bar(src_top, x="count", y="source", orientation="h",
              title="来源贡献 TOP15（2026-06-22 → 08-19）")
fig6.update_layout(yaxis={"categoryorder": "total ascending"})
fig6.show()""")

code("""dim_src = (df.groupby(["dimension", "source"]).size()
             .reset_index(name="count")
             .sort_values(["dimension", "count"], ascending=[True, False])
             .groupby("dimension").head(3))
fig7 = px.bar(dim_src, x="count", y="source", color="dimension",
              facet_col="dimension", facet_col_wrap=2, orientation="h",
              title="各维度头部来源 TOP3")
fig7.update_layout(yaxis={"categoryorder": "total ascending"}, showlegend=False)
fig7.show()""")

# ---------- 5. 打分体系透视 ----------
md("""## 五、打分体系透视 ★

v2.0 五维模型：内容强度 30 + 来源权威 25 + 主题相关 25 + 人物 10 + 时效 10。
按"得分率"（得分/满分）比较五维的松紧，验证打分是否偏科。""")

code("""MAXES = {"src_score": 25, "strength": 30, "topic": 25, "people_score": 10, "freshness": 10}
rate = pd.DataFrame({k: df[k] / v for k, v in MAXES.items()})
rate_mean = rate.mean().sort_values().reset_index()
rate_mean.columns = ["维度", "得分率"]
fig8 = px.bar(rate_mean, x="得分率", y="维度", orientation="h",
              title="五维得分率对比（越低 = 该维度越严苛）",
              text=rate_mean["得分率"].map(lambda x: f"{x:.0%}"))
fig8.update_layout(yaxis={"categoryorder": "total ascending"})
fig8.update_traces(textposition="outside")
fig8.show()""")

code("""# 内容强度（strength）按维度看分布 —— 各维度是否都吃满了自己的 30 分档？
fig9 = px.box(df, x="dimension", y="strength", color="dimension",
              title="内容强度分布（按维度，满分 30）")
fig9.show()""")

code("""# 来源权威分 vs 最终得分：权威性真的转化为高分了吗？
fig10 = px.scatter(df, x="src_score", y="score", color="dimension",
                   hover_data=["title"], opacity=0.65,
                   title="来源权威分 vs 综合得分（按维度着色）")
fig10.show()""")

code("""# ⚠️ 库里 freshness 是「首次收录时刻快照」，不随采集更新（老条目永不衰减）
# → 用 published_at 和当前时间重算"真实时效分"，对比出哪些条目虚高
from datetime import datetime, timezone

NOW = datetime.now(timezone.utc)

def real_freshness(published_at):
    dt = pd.to_datetime(published_at, utc=True, errors="coerce")
    if pd.isna(dt):
        return 0
    hours = (NOW - dt).total_seconds() / 3600
    if hours < 0:
        return 10
    if hours < 24:
        return 10
    if hours < 48:
        return 8
    if hours < 72:
        return 6
    if hours < 96:
        return 4
    return 2

df["freshness_real"] = df["published_at"].map(real_freshness)
df["freshness_diff"] = df["freshness"] - df["freshness_real"]  # >0 = 库里虚高

inflated = int((df["freshness_diff"] > 0).sum())
print(f"库里 freshness 虚高的条目: {inflated}/{len(df)}（占 {inflated/len(df):.0%}）")
print("示例（库里 10 分但真实时效已衰减）：")
for _, r in df[df["freshness_diff"] > 0].sort_values("freshness_diff", ascending=False).head(5).iterrows():
    print(f"  [{r['dimension']}] {str(r['title'])[:34]} | 快照{r['freshness']} → 实时{r['freshness_real']}")

fig10b = px.histogram(df, x="freshness_diff", nbins=12,
                      title="快照 freshness − 实时 freshness（>0 = 库里虚高）")
fig10b.show()""")

# ---------- 6. 关键词云 ----------
md("""## 六、关键词透视

jieba 分词，看四个维度各自在聊什么话题（标题+摘要前 200 字）。""")

code("""STOP = set(("的 了 是 在 和 与 及 等 中 为 将 对 并 由 通过 表示 称 指出 记者 报道 相关 进行 以及 我们 他们 其 该 这 那 有 也 就 都 而 但 或 一个 没有 不是 被 把 从 向 到 于 与 年 月 日 个 上 下 后 前 内 外 说 称 显示 据 据悉 目前 近日 今天 昨日 新 大 小 更 最 已 能 会 要 可 以 及 为 各 每 多 少 万 亿 元 人 公司 中国 美国 欧洲 日本 印度 政府 国际 全球 the a an and of to in for on with is are was were be by as at or from this that it its not have has had").split())

def top_words(texts, n=14):
    c = Counter()
    for t in texts:
        for w in jieba.lcut(str(t)[:200]):
            w = w.strip()
            if len(w) < 2 or w in STOP or w.isdigit():
                continue
            c[w] += 1
    return c.most_common(n)

rows = []
for dim, grp in df.groupby("dimension"):
    for w, n in top_words(grp["title"].tolist() + grp["summary"].fillna("").tolist()):
        rows.append({"dimension": dim, "word": w, "count": n})
kw = pd.DataFrame(rows)

fig11 = px.bar(kw, x="count", y="word", color="dimension",
               facet_row="dimension", orientation="h",
               title="四维关键词 TOP14")
fig11.update_layout(showlegend=False, height=1200)
fig11.for_each_annotation(lambda a: a.update(text=a.text.split("=")[-1]))
fig11.show()""")

# ---------- 7. 高分回顾 ----------
md("""## 七、高分回顾（S + A 级）

62 天里最重要的政策动态清单，可直接转发或写入 wiki。""")

code("""top = (df[df["score_level"].isin(["S", "A"])]
       .sort_values("score", ascending=False)
       .reset_index(drop=True))
print(f"S/A 级共 {len(top)} 条，最高分 {top['score'].max()}")

fig12 = go.Figure(go.Table(
    header=dict(values=["#", "标题", "维度", "来源", "分数", "链接"],
                fill_color="#0052ff", font=dict(color="white"), align="left"),
    cells=dict(
        values=[top.index + 1,
                top["title"].str[:38],
                top["dimension"],
                top["source"],
                top["score"],
                top["url"].str[:45]],
        align="left", height=28)))
fig12.update_layout(title="S/A 级条目清单（62 天精华）", height=60 + 30 * len(top))
fig12.show()""")

# ---------- 8. 结论 ----------
md("""## 八、结论与洞察

自动汇总关键数字，下面留了 markdown 区给你写策展心得~""")

code("""print("=" * 46)
print("📊 62 天数据速览")
print("=" * 46)
print(f"总条数          : {len(df)}")
print(f"四维分布        : {df['dimension'].value_counts().to_dict()}")
print(f"S/A 级占比      : {(df['score_level'].isin(['S','A'])).mean():.1%}")
print(f"平均分          : {df['score'].mean():.1f}  |  中位数 {df['score'].median():.0f}")
print(f"覆盖天数        : {df['date'].nunique()} 天，日均 {len(df)/df['date'].nunique():.1f} 条")
print(f"五维得分率(低=严): {dict(rate.mean().sort_values().round(2))}")
print(f"来源 TOP5       : {df['source'].value_counts().head(5).to_dict()}")""")

md("""### 📝 我的策展笔记

（在这里写下你的观察：哪个维度信号最强、哪些高分条目值得进 wiki、下周关注什么……）""")

nb.cells = cells
nb.metadata = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python", "version": "3.13"},
}

out = Path("analysis/四维透视.ipynb")
out.parent.mkdir(exist_ok=True)
nbf.write(nb, out)
print(f"✅ 已生成 {out}（{len(cells)} 个 cell）")
