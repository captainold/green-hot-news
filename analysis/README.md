# analysis/ — 四维透视 Notebook

绿色低碳动态雷达 · 基于 `data/history.json`（62 天累积）的交互式数据分析 Notebook，专为 Positron 设计。

## 文件

| 文件 | 说明 |
|------|------|
| `四维透视.ipynb` | 主文件：8 大章节、16 个代码块，Positron 打开即用（已预跑，打开即可看到全部图表） |
| `四维透视-报告.html` | **纯结果展示版**（隐藏代码，只有图表/表格），浏览器直接打开即看，适合分享；由 nbconvert 从 ipynb 导出 |
| `build_radar_notebook.py` | Notebook 生成脚本（数据更新后重跑它可重新生成 + 重新预跑） |

## 展示 vs 编辑

- **想看得清爽**：双击 `四维透视-报告.html` 用浏览器打开（图表交互、无代码）
- **想改/重跑分析**：Positron 打开 `.ipynb`（代码和输出一体，逐格运行）
- **Positron 里临时隐藏代码**：鼠标移到代码块左侧点折叠图标

## 重新生成报告（数据更新后）

> 需要 `nbconvert`：`python3.11 -m pip install nbconvert`（Windows 侧用 `python -m pip install nbconvert`）

```bash
cd analysis
# 1. 重新生成 notebook（含预跑输出）
python3.11 ../analysis/build_radar_notebook.py
# 2. 转 HTML 报告（隐藏代码；plotly 特殊格式需先转 text/html）
python3.11 - <<'EOF'
import nbformat, json
import plotly.io as pio
nb = nbformat.read("四维透视.ipynb", as_version=4)
for c in nb.cells:
    if c.cell_type != "code": continue
    for o in c.get("outputs", []):
        d = o.get("data", {})
        if "application/vnd.plotly.v1+json" in d:
            fig = pio.from_json(json.dumps(d["application/vnd.plotly.v1+json"]))
            d["text/html"] = pio.to_html(fig, include_plotlyjs="cdn", full_html=False)
nbformat.write(nb, "/tmp/report.ipynb")
EOF
python3.11 -m nbconvert --to html --no-input --output 四维透视-报告 /tmp/report.ipynb
```

## 使用方法（Positron）

1. Positron 打开 `analysis/四维透视.ipynb`
2. 右下角选择内核：**Python 3.13**（Windows 已装 pandas/plotly/jieba）
3. 顶部工具栏点 **Run All（▶▶）** 一键跑完；或光标停在某个代码块内按 **Shift+Enter** 逐块运行
4. 表格输出点右上角「小格子」图标 → 打开 Data Explorer 交互翻表
5. 所有图表是 plotly 交互图：可悬停看详情、缩放、右上角工具栏导出 PNG

## 数据更新后重新生成

```bash
# WSL 侧（项目根目录）
python3.11 - <<'EOF'
import sys; sys.path.insert(0, 'analysis')
import nbformat, nbclient
EOF
python3.11 analysis/build_radar_notebook.py   # 重新生成 notebook（含预跑输出）
```

Windows 侧重新生成需先装生成依赖：`python -m pip install nbformat nbclient ipykernel`

## 依赖清单

- 运行 notebook：`pandas` `plotly` `jieba`（Windows Python 3.13 已装好）
- 生成脚本额外需要：`nbformat` `nbclient` `ipykernel`（WSL /tmp/radar_venv 已装好）

## 数据安全

Notebook **只读** `../data/history.json`，绝不写回数据文件，不影响打分/抓取管线。

## 已知数据坑（生成脚本已处理）

- `score_breakdown` 里的 `source`/`people` 与顶层字段撞名 → 展开时改名 `src_score`/`people_score`
- `published_at` 混合时区（`+08:00` 国内源 / `Z` 国外源）→ 统一 `to_datetime(utc=True)` 后转北京时间

## 章节一览

1. 数据加载（Data Explorer 翻表）
2. 总览仪表盘（四维/评分/区域）
3. 62 天时间序列（堆积面积图 + 星期节奏）
4. 来源贡献 TOP15 + 各维度头部来源
5. 打分体系透视 ★（五维得分率 / strength 分布 / 权威分 vs 综合分）
6. 四维关键词 TOP14（jieba 分词）
7. S/A 级高分回顾（62 天精华清单）
8. 结论自动汇总 + 策展笔记区
