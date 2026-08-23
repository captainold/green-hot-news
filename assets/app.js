// ── Green Hot News · 绿色低碳动态雷达 — App（2026-08-19 v22 主页重构）─────────
// 三段式布局：
//   ① 顶部控制：主题（主题标签）· 时间段 · 区域 · 一键复制概要（含网站宣传）
//   ② 中部列表：重要性 / 新到旧 两种排序 + 每页条数可选（紧凑分页，避免过长）
//   ③ 底部趋势：关系图谱——主题标签共现（只显示主题标签，地域/政策类型等
//      数据库管理标签不显示）
// 数据源：data/history.json（62 天累积，含 topics 主题标签字段）
(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────────────────────────
  let historyItems = [];        // history.json（62 天累积，主数据源）
    let currentDim = "全部";      // 四大主题（四维）：全部 | 政府 | 行业 | 金融 | AI
    let currentPeriod = "周";     // 日 | 周 | 月
    let currentRegion = "国际";   // 国内 | 国际（互斥：国内=region 中国，国际=非中国，2026-08-19）
    let sortMode = "重要性";      // 重要性 | 新到旧
    let pageSize = 20;
    let page = 1;
    let lastFiltered = [];        // 最近一次筛选结果（供日/夜主题切换时重绘图谱）
    let graphChart = null;        // ECharts 关系图谱实例（须在 initTheme 前声明，避免 TDZ）
    let graphResizeBound = false; // resize 监听只挂一次（dispose/re-init 不重复挂）
    let searchQuery = "";         // Obsidian 语法搜索 query（2026-08-23 新增）

  // 四大主题 = 四维（政策/产业/市场信号/AI，四个观察窗口而非互斥分类：
  // 政策=部委发文动向、产业=企业进展兜底、市场信号=碳市场/绿色资本、AI=AI×绿色落地）；
  // 关系图谱节点用的是「主题标签」（碳市场/新能源…），见 TOPIC_COLORS
  const DIMS = ["全部", "政策", "产业", "市场信号", "AI"];
  // 四维 tab 副标题（2026-08-20）：消除「金融⊂行业」式层级误解
  const DIM_SUBS = {
    "政策": "部委文件·官方信号",
    "产业": "企业进展·行业动态",
    "市场信号": "碳市场·绿色资本",
    "AI": "AI×绿色落地",
  };
  const PERIODS = ["日", "周", "月"];
  const REGIONS = ["国内", "国际"];
  const SORTS = ["重要性", "新到旧"];
  const HOUR = 3600 * 1000;
  const POLL_MS = 60 * 1000;

  // 主题标签稳定配色（关系图谱节点颜色）
  const TOPIC_COLORS = {
    "碳市场": "#16a34a", "新能源": "#eab308", "储能": "#0ea5e9", "电力": "#6366f1",
    "化石能源": "#f97316", "节能降碳": "#10b981", "气候变化": "#14b8a6",
    "绿色金融": "#22c55e", "环境保护": "#3b82f6", "循环经济": "#84cc16",
    "电动车": "#06b6d4", "政策法规": "#64748b", "AI科技": "#a855f7",
  };

  // ── Dom refs ───────────────────────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const topicSwitch = $("#topicSwitch");
  const periodSwitch = $("#periodSwitch");
  const regionSwitch = $("#regionSwitch");
  const sortSwitch = $("#sortSwitch");
  const copyBtn = $("#copyBtn");
  const pageSizeSelect = $("#pageSizeSelect");
  const listSub = $("#listSub");
  const listBody = $("#listBody");
  const pager = $("#pager");
  const pagerInfo = $("#pagerInfo");
  const prevPage = $("#prevPage");
  const nextPage = $("#nextPage");
  const graphSub = $("#graphSub");
  const graphCount = $("#graphCount");
  const updatedAt = $("#updatedAt");
  const itemTpl = $("#itemTpl");
  const themeToggle = $("#themeToggle");
  // 搜索框（2026-08-23 新增）
  const searchInput = $("#searchInput");
  const searchClear = $("#searchClear");
  const searchBtn = $("#searchBtn");

  // ── 日/夜主题切换（2026-08-19）：整页联动 + localStorage 记忆，默认白天 ──
  function applyTheme(dark) {
    const root = document.documentElement;
    if (dark) {
      root.setAttribute("data-theme", "dark");
      if (themeToggle) themeToggle.textContent = "☀️";
    } else {
      root.removeAttribute("data-theme");
      if (themeToggle) themeToggle.textContent = "🌙";
    }
    try { localStorage.setItem("ghn-theme", dark ? "dark" : "light"); } catch (e) { /* ignore */ }
    if (graphChart) renderGraph(lastFiltered);
  }
  function initTheme() {
    let saved = null;
    try { saved = localStorage.getItem("ghn-theme"); } catch (e) { /* ignore */ }
    applyTheme(saved === "dark");
    if (themeToggle) {
      themeToggle.addEventListener("click", () => {
        applyTheme(document.documentElement.getAttribute("data-theme") !== "dark");
      });
    }
  }
  initTheme();

  // ── 切换器构建 ────────────────────────────────────────────────────────────
  function buildSwitch(container, opts, current, onPick) {
    container.innerHTML = "";
    opts.forEach((label) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "mode-btn" + (label === current ? " active" : "");
      b.textContent = label;
      b.addEventListener("click", () => {
        container.querySelectorAll(".mode-btn").forEach((e) => e.classList.remove("active"));
        b.classList.add("active");
        onPick(label);
      });
      container.appendChild(b);
    });
  }

  // 四大主题选择器（四维：政策/产业/市场信号/AI + 全部，tab 带观察窗口副标题）
  function buildDimSwitch() {
    buildSwitch(topicSwitch, DIMS, currentDim, (v) => { currentDim = v; page = 1; render(); });
    topicSwitch.querySelectorAll(".mode-btn").forEach((b) => {
      const sub = DIM_SUBS[b.textContent];
      if (sub) {
        b.classList.add("mode-btn-sub");
        const span = document.createElement("span");
        span.className = "mode-sub";
        span.textContent = sub;
        b.appendChild(span);
      }
    });
  }

  // ── Load data ──────────────────────────────────────────────────────────────
  const cb = `?t=${Date.now()}`;
  async function loadData() {
    try {
      let d = null;
      try {
        const r = await fetch(`./data/history.json${cb}`);
        if (r.ok) d = await r.json();
      } catch (e) { /* fallthrough */ }
      if (!d || !Array.isArray(d.items)) {
        const r = await fetch(`./data/latest-24h.json${cb}`);
        d = await r.json();
      }
      historyItems = d.items || [];
      if (d.generated_at) updatedAt.textContent = formatTime(d.generated_at);
      render();
    } catch (err) {
      console.error("Failed to load data:", err);
      listBody.innerHTML = '<p style="color:var(--text-dim);padding:2rem;text-align:center;">数据加载中，请稍候...</p>';
    }
  }

  // ── Filtering ──────────────────────────────────────────────────────────────
  function itemTime(i) { return i.published_at || i.first_seen_at || ""; }
  function timeMs(i) {
    const t = Date.parse(itemTime(i));
    return isNaN(t) ? 0 : t;
  }
  function periodStart() {
    const h = currentPeriod === "日" ? 24 : currentPeriod === "周" ? 24 * 7 : 24 * 30;
    return Date.now() - h * HOUR;
  }

  // ── Obsidian 语法解析（2026-08-23 新增）────────────────────────────────────
  // 支持：tag:储能 path:产业 source:虎嗅 "精确匹配" 空格=AND OR -排除
  function parseObsidianQuery(query) {
    if (!query || !query.trim()) return { active: false, terms: [] };

    const terms = [];
    let currentOp = "AND"; // 默认 AND
    const text = query.trim();

    // 分割 OR（先处理 OR，再处理每个组内的 AND/NOT）
    const orGroups = text.split(/\s+OR\s+/i);
    
    orGroups.forEach((group, groupIdx) => {
      const groupOp = groupIdx > 0 ? "OR" : currentOp;
      // 在组内处理 - 前缀（NOT）和tag:/path:等
      const tokens = group.trim().split(/\s+/).filter(t => t.length > 0);
      
      tokens.forEach(token => {
        if (token.startsWith("-")) {
          // NOT 排除
          const value = token.slice(1);
          if (value.startsWith("tag:")) {
            terms.push({ op: "NOT", type: "tag", value: value.slice(4) });
          } else if (value.startsWith("path:")) {
            terms.push({ op: "NOT", type: "path", value: value.slice(5) });
          } else if (value.startsWith("source:")) {
            terms.push({ op: "NOT", type: "source", value: value.slice(7) });
          } else {
            terms.push({ op: "NOT", type: "text", value });
          }
        } else if (token.startsWith("tag:")) {
          terms.push({ op: groupOp, type: "tag", value: token.slice(4) });
        } else if (token.startsWith("path:")) {
          terms.push({ op: groupOp, type: "path", value: token.slice(5) });
        } else if (token.startsWith("source:")) {
          terms.push({ op: groupOp, type: "source", value: token.slice(7) });
        } else if (token.startsWith('"') && token.endsWith('"')) {
          // 精确匹配（去引号）
          terms.push({ op: groupOp, type: "text", value: token.slice(1, -1), exact: true });
        } else {
          // 普通全文搜索
          terms.push({ op: groupOp, type: "text", value: token });
        }
      });
    });

    return { active: terms.length > 0, terms };
  }

  function matchItem(item, term) {
    // 根据术语类型匹配条目
    if (term.type === "tag") {
      return (item.topics || []).some(t => t.includes(term.value));
    } else if (term.type === "path") {
      // path 匹配 dimension 或 library
      const dim = item.dimension || "";
      const lib = item.library || "";
      return dim.includes(term.value) || lib.includes(term.value);
    } else if (term.type === "source") {
      const site = item.site_name || item.site_id || "";
      return site.includes(term.value);
    } else if (term.type === "text") {
      // 全文搜索：标题 + 摘要
      const title = item.title_zh || item.title || "";
      const summary = item.summary || "";
      const searchTarget = (title + " " + summary).toLowerCase();
      if (term.exact) {
        return searchTarget.includes(term.value.toLowerCase());
      }
      // 分词匹配（支持部分匹配）
      return term.value.split("").every(char => searchTarget.includes(char.toLowerCase()));
    }
    return false;
  }

  function filterBySearch(items) {
    if (!searchState.active || searchState.terms.length === 0) return items;

    const { terms } = searchState;
    
    // 分组处理：OR 组之间是或的关系，组内是 AND + NOT
    const orGroups = [];
    let currentGroup = [];
    
    terms.forEach(term => {
      if (term.op === "OR") {
        if (currentGroup.length > 0) orGroups.push(currentGroup);
        currentGroup = [term];
      } else {
        currentGroup.push(term);
      }
    });
    if (currentGroup.length > 0) orGroups.push(currentGroup);

    // 过滤：匹配任意 OR 组
    return items.filter(item => {
      return orGroups.some(group => {
        let andResult = true;
        
        for (const term of group) {
          const matches = matchItem(item, term);
          if (term.op === "NOT") {
            if (matches) {
              andResult = false;
              break;
            }
          } else { // AND
            if (!matches) {
              andResult = false;
              break;
            }
          }
        }
        
        return andResult;
      });
    });
  }

  function filterItems() {
    let items = [...historyItems];
    if (currentDim !== "全部") {
      items = items.filter(i => (i.dimension || "政策") === currentDim);
    }
    if (currentRegion === "国内") {
      items = items.filter(i => (i.region || "") === "中国");
    } else if (currentRegion === "国际") {
      // 2026-08-19：国际=排除中国（原「全部含国内」被老温否掉——\n      // 选国际却出现工信部/国家节能中心等国内新闻）
      items = items.filter(i => (i.region || "") !== "中国");
    }
    const start = periodStart();
    items = items.filter(i => {
      const t = Date.parse(itemTime(i));
      return isNaN(t) || t >= start; // 无时间的条目保留
    });
    // 应用搜索过滤（2026-08-23 新增）
    items = filterBySearch(items);
    return items;
  }

  function sortItems(items) {
    const arr = [...items];
    if (sortMode === "重要性") {
      arr.sort((a, b) => {
        const sa = a.score || 0, sb = b.score || 0;
        if (sa !== sb) return sb - sa;
        return timeMs(b) - timeMs(a);
      });
    } else {
      arr.sort((a, b) => timeMs(b) - timeMs(a));
    }
    return arr;
  }

  // ── Render ─────────────────────────────────────────────────────────────────
    function render() {
      const filtered = sortItems(filterItems());
      lastFiltered = filtered;
      const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
      if (page > totalPages) page = totalPages;

      // 副标题（2026-08-23 新增搜索时显示搜索结果计数）
      const periodLabel = currentPeriod === "日" ? "近 24 小时" : currentPeriod === "周" ? "近一周" : "近一月";
      let subText = `${currentDim} · ${currentRegion} · ${periodLabel} · ${filtered.length} 条`;
      if (searchState.active && searchQuery) {
        subText += ` · 搜索"${searchQuery}"`;
      }
      listSub.textContent = subText;

    // 列表（分页切片）
    const start = (page - 1) * pageSize;
    renderList(listBody, filtered.slice(start, start + pageSize));

    // 分页控件
    if (filtered.length > pageSize) {
      pager.hidden = false;
      pagerInfo.textContent = `第 ${page} / ${totalPages} 页 · 共 ${filtered.length} 条`;
      prevPage.disabled = page <= 1;
      nextPage.disabled = page >= totalPages;
    } else {
      pager.hidden = true;
    }

    renderGraph(filtered);
  }

  function renderList(container, items) {
    if (items.length === 0) {
      container.innerHTML = '<p style="color:var(--text-dim);padding:1rem;text-align:center;font-size:.8rem;">暂无动态</p>';
      return;
    }
    container.innerHTML = "";
    const frag = document.createDocumentFragment();
    items.forEach((item, idx) => {
      const card = itemTpl.content.cloneNode(true);
      const score = item.score || 0;
      const level = item.score_level || "";

      // 排名序号：仅「重要性」排序显示 1. 2. 3.（前三名金/银/铜）
      const rankNum = card.querySelector(".rank-num");
      if (sortMode === "重要性") {
        rankNum.textContent = `${(page - 1) * pageSize + idx + 1}`;
        rankNum.hidden = false;
        if (idx < 3 && page === 1) rankNum.classList.add(`rank-${idx + 1}`);
      }

      // 评分圆点（颜色=级别）+ 悬停五维分解
      const badge = card.querySelector(".score-badge");
      badge.classList.add(`lv-${level || "none"}`);
      const bd = item.score_breakdown || {};
      badge.title = score
        ? `综合 ${score} 分\n来源权威 ${bd.source} + 内容强度 ${bd.strength} + 主题相关 ${bd.topic} + 人物 ${bd.people} + 时效 ${bd.freshness}`
        : "暂无评分";

      // 四维标签（政策/产业/市场信号/AI）
      const dimTag = card.querySelector(".dim-tag");
      const dim = item.dimension || "政策";
      dimTag.textContent = dim;
      dimTag.classList.add(`dim-${dim}`);

      // 站点 + 时间
      card.querySelector(".site").textContent = item.site_name || item.site_id;
      const timeEl = card.querySelector(".time");
      const timeTxt = formatTime(itemTime(item));
      timeEl.textContent = item.time_source === "scraped" ? `收录 ${timeTxt}` : timeTxt;
      timeEl.title = item.time_source === "scraped"
        ? "源站未提供发布时间，此时间为收录（抓取）时间" : "发布时间";

      // 标题（非中文显示中文翻译 + 原文小字）
      const titleLink = card.querySelector(".title");
      const titleOrig = card.querySelector(".title-orig");
      titleLink.href = item.url;
      const zh = item.title_zh || "";
      if (zh && zh !== item.title) {
        titleLink.textContent = zh;
        titleLink.title = item.title;
        titleOrig.textContent = item.title;
        titleOrig.hidden = false;
      } else {
        titleLink.textContent = item.title;
        titleLink.title = item.title;
        titleOrig.hidden = true;
      }

      // 主题标签 chips（仅主题标签；地域/政策类型管理标签不显示）
      const chips = card.querySelector(".topic-chips");
      (item.topics || []).forEach(t => {
        const c = document.createElement("span");
        c.className = "topic-chip";
        c.textContent = t;
        c.title = "主题标签";
        chips.appendChild(c);
      });

      // 摘要（含评分，点开展开）
      const summary = item.summary || "";
      const sumEl = card.querySelector(".summary");
      const toggleBtn = card.querySelector(".summary-toggle");
      const scoreLine = score ? `综合评分 ${score} 分` : "";
      const fullSummary = [scoreLine, summary].filter(Boolean).join("　");
      if (fullSummary && fullSummary.length > 8) {
        sumEl.textContent = fullSummary;
        toggleBtn.hidden = false;
        toggleBtn.addEventListener("click", () => {
          const expanded = sumEl.hidden === false;
          sumEl.hidden = expanded;
          toggleBtn.textContent = expanded ? "展开摘要" : "收起";
          sumEl.classList.toggle("expanded", !expanded);
        });
      }

      frag.appendChild(card);
    });
    container.appendChild(frag);
  }

  // ── 关系图谱（2026-08-19）：主题标签共现 ──────────────────────────────────
  function renderGraph(filtered) {
    const el = document.getElementById("graphChart");
    if (!el || typeof echarts === "undefined") return;

    // 聚合：主题标签节点（按出现次数）+ 共现边（同一篇新闻内两个标签）
    const nodeCount = {};
    const edgeWeight = {};
    let taggedItems = 0;
    for (const it of filtered) {
      const topics = it.topics || [];
      if (topics.length === 0) continue;
      taggedItems += 1;
      const uniq = [...new Set(topics)];
      uniq.forEach(t => { nodeCount[t] = (nodeCount[t] || 0) + 1; });
      for (let a = 0; a < uniq.length; a++) {
        for (let b = a + 1; b < uniq.length; b++) {
          const key = [uniq[a], uniq[b]].sort().join("||");
          edgeWeight[key] = (edgeWeight[key] || 0) + 1;
        }
      }
    }

    const tags = Object.keys(nodeCount).sort((a, b) => nodeCount[b] - nodeCount[a]);
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    const labelColor = dark ? "#f2f4f7" : "#0a0b0d";
    const subColor = dark ? "#8a93a0" : "#5b616e";
    const edgeColor = dark ? "rgba(245,246,247,.28)" : "rgba(91,97,110,.32)";

    graphSub.textContent =
      `${currentDim === "全部" ? "全部维度" : currentDim} · ${tags.length} 个相关主题标签 · ${taggedItems} 条带标签动态`;
    graphCount.textContent = `${tags.length} 个标签`;

    if (tags.length === 0) {
      // 空态：销毁实例并显示提示文字（避免 el.innerHTML 清空却保留旧实例导致
      // 后续 setOption 画不出图）；实例销毁后下次有数据时在下方 if(!graphChart) 重新 init。
      if (graphChart) { graphChart.dispose(); graphChart = null; }
      el.innerHTML = '<p style="color:var(--text-dim);padding:3rem;text-align:center;font-size:.8rem;">该维度 × 时间段内暂无主题标签数据</p>';
      return;
    }

    const maxCount = Math.max(...tags.map(t => nodeCount[t]));
    const nodes = tags.map(t => {
      const count = nodeCount[t];
      const size = 22 + Math.round((count / maxCount) * 38);
      const color = TOPIC_COLORS[t] || "#0052ff";
      return {
        name: t,
        value: count,
        count,
        symbolSize: size,
        itemStyle: {
          color,
          borderColor: "transparent",
          borderWidth: 0,
          shadowBlur: 6,
          shadowColor: color,
          opacity: 0.9,
        },
        label: {
          show: true,
          color: labelColor,
          fontSize: 12,
          fontWeight: 500,
          formatter: `{b}\n{c|${count} 条}`,
          rich: { c: { color: subColor, fontSize: 10, lineHeight: 14 } },
        },
      };
    });

    const links = Object.entries(edgeWeight).map(([key, w]) => {
      const [s, t] = key.split("||");
      return { source: s, target: t, value: w };
    });

    if (!graphChart) {
      el.innerHTML = ""; // 清除空态提示文字（仅首次 init 前安全）
      graphChart = echarts.init(el);
      if (!graphResizeBound) {
        graphResizeBound = true;
        window.addEventListener("resize", () => graphChart && graphChart.resize());
      }
    }

    graphChart.setOption({
      backgroundColor: "transparent",
      tooltip: {
        trigger: "item",
        formatter: (p) => {
          if (p.dataType === "node") {
            return `<b>${p.data.name}</b><br/>出现 ${p.data.count} 条动态`;
          }
          return `${p.data.source} ↔ ${p.data.target}<br/>共现 ${p.data.value} 条`;
        },
        backgroundColor: dark ? "rgba(20,22,27,.95)" : "rgba(255,255,255,.97)",
        borderColor: dark ? "rgba(245,246,247,.15)" : "rgba(91,97,110,.2)",
        textStyle: { color: labelColor, fontSize: 12 },
      },
      series: [{
        type: "graph",
        layout: "force",
        data: nodes,
        links,
        roam: true,
        draggable: true,
        label: { show: true, position: "right" },
        edgeSymbol: ["none", "none"],
        lineStyle: { color: edgeColor, width: 1.2, curveness: 0.15, opacity: 0.7 },
        emphasis: { focus: "adjacency", lineStyle: { width: 2.5 } },
        force: {
          repulsion: 280,
          edgeLength: [60, 150],
          gravity: 0.15,
          layoutAnimation: true,
        },
      }],
    }, true);
  }

  // ── 一键复制概要（含网站宣传）──────────────────────────────────────────────
  // 摘要清洗：去「摘要：」前缀/发布时间/小编水印/阅读量（与 daily_digest.clean_summary 对齐）
  function cleanSummary(s) {
    if (!s) return "";
    let t = s.replace(/\s+/g, " ").trim();
    if (t.includes("摘要：")) t = t.split("摘要：", 2)[1].trim();
    t = t.replace(/发布时间：\d{4}-\d{2}-\d{2}\s*/g, "");
    t = t.replace(/[\u4e00-\u9fff]{0,6}(小编|编辑)\s*[^\u4e00-\u9fff]*\d*[天小时分]?前/g, "");
    t = t.replace(/阅读量\s*[：:·]?\s*\d+/g, "");
    return t.slice(0, 90).replace(/[，。、；：,.;:·\s]+$/, "");
  }

  function buildDigestText(items) {
      const periodLabel = currentPeriod === "日" ? "近 24 小时" : currentPeriod === "周" ? "近一周" : "近一月";
      const head = [
        "🌿 绿色低碳动态雷达 · 精选概要",
        `主题：${currentDim}  ｜  时间段：${periodLabel}  ｜  区域：${currentRegion}`,
        `更新时间：${updatedAt.textContent}`,
        "━━━━━━━━━━━━━━━━━━━━",
        "",
      ].join("\n");

      const body = items.slice(0, 20).map((it, idx) => {
        const title = it.title_zh || it.title || "";
        const site = it.site_name || "";
        const dim = it.dimension || "";
        return `${idx + 1}. ${title}（${site} · ${dim}）`;
      }).join("\n");

      const promo = [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "📡 绿色低碳动态雷达 · ywm.life",
        " 四维覆盖：政策 · 产业 · 市场信号 · AI",
        " 聚合 60+ 权威源，每日自动更新",
        " 👉 https://ywm.life",
      ].join("\n");

      return head + "\n" + (body || "（该范围内暂无动态）") + promo;
    }

  async function copyDigest() {
    const filtered = sortItems(filterItems()); // 重要性排序取前 20
    const text = buildDigestText(filtered);
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      ok = document.execCommand("copy");
      ta.remove();
    }
    copyBtn.textContent = ok ? "✅ 已复制" : "⚠️ 复制失败";
    copyBtn.classList.toggle("copied", ok);
    setTimeout(() => {
      copyBtn.textContent = "📋 一键复制概要";
      copyBtn.classList.remove("copied");
    }, 2000);
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  function formatAbsolute(d) {
    const h = d.getHours();
    const ap = h < 12 ? "上午" : "下午";
    const h12 = h % 12 === 0 ? 12 : h % 12;
    const min = String(d.getMinutes()).padStart(2, "0");
    return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日 ${ap}${h12}:${min}`;
  }
  function formatTime(isoStr) {
    if (!isoStr) return "时间未知";
    let d;
    try { d = new Date(isoStr); } catch { return "时间未知"; }
    if (isNaN(d.getTime())) return "时间未知";
    const abs = formatAbsolute(d);
    const diffMin = (new Date() - d) / 60000;
    if (diffMin < 0) return abs;
    if (diffMin < 60) return `${Math.floor(diffMin)}分钟前 · ${abs}`;
    if (diffMin < 24 * 60) return `${Math.floor(diffMin / 60)}小时前 · ${abs}`;
    return abs;
  }

  // ── 实时轮询：新条目并入（2026-08-19，保持实时感）─────────────────────────
  async function pollNew() {
    try {
      const r = await fetch(`./data/latest-24h.json${cb}`);
      if (!r.ok) return;
      const d = await r.json();
      const latest = d.items || [];
      const known = new Set(historyItems.map(i => (i.title || "").trim()));
      const fresh = latest.filter(i => !known.has((i.title || "").trim()));
      if (fresh.length === 0) return;
      historyItems = fresh.concat(historyItems);
      if (d.generated_at) updatedAt.textContent = formatTime(d.generated_at);
      render();
    } catch (e) { /* ignore */ }
  }

  // ── Event listeners ────────────────────────────────────────────────────────
  buildDimSwitch();
  buildSwitch(periodSwitch, PERIODS, currentPeriod, (v) => { currentPeriod = v; page = 1; render(); });
  buildSwitch(regionSwitch, REGIONS, currentRegion, (v) => { currentRegion = v; page = 1; render(); });
  buildSwitch(sortSwitch, SORTS, sortMode, (v) => { sortMode = v; page = 1; render(); });
  pageSizeSelect.addEventListener("change", () => { pageSize = Number(pageSizeSelect.value); page = 1; render(); });
  prevPage.addEventListener("click", () => { if (page > 1) { page--; render(); window.scrollTo({ top: 0, behavior: "smooth" }); } });
  nextPage.addEventListener("click", () => { page++; render(); window.scrollTo({ top: 0, behavior: "smooth" }); });
  copyBtn.addEventListener("click", copyDigest);
  
  // 搜索框事件（2026-08-23 新增）
  function handleSearch() {
    const query = searchInput.value.trim();
    searchQuery = query;
    const parsed = parseObsidianQuery(query);
    searchState.active = parsed.active;
    searchState.terms = parsed.terms;
    page = 1; // 重置页码
    
    // 清除按钮显示逻辑
    if (searchClear) {
      searchClear.hidden = query.length === 0;
    }
    
    render();
  }
  
  if (searchInput) {
    searchInput.addEventListener("input", handleSearch);
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Escape") {
        searchInput.value = "";
        handleSearch();
        searchInput.blur();
      }
    });
    // 支持回车键触发搜索
    searchInput.addEventListener("keypress", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        handleSearch();
        searchInput.blur();
      }
    });
  }
  
  if (searchClear) {
    searchClear.addEventListener("click", () => {
      searchInput.value = "";
      handleSearch();
      searchInput.focus();
    });
  }
  
  if (searchBtn) {
    searchBtn.addEventListener("click", () => {
      handleSearch();
      searchInput.blur();
    });
  }

  // ── Init ───────────────────────────────────────────────────────────────────
  loadData();
  setInterval(loadData, 10 * 60 * 1000);  // 全量刷新（含 history 重新拉取）
  setInterval(pollNew, POLL_MS);          // 新条目轮询（60s）
})();
