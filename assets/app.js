// ── Green Hot News · 绿色低碳动态雷达 — App ──────────────────────────────────
// 布局（2026-08-14）：顶部综合评分排行榜 + 下面四维排行榜（政策/技术/金融/AI科技）
// 学 News Minimalist：分数徽章 + 相对时间 + 可展开摘要
(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────────────────────────
  let allItems = [];
  let greenItems = [];
  let allItemsRaw = [];
  let searchQuery = "";
  let selectedSite = "";
  let currentMode = "green"; // "green" | "all"
  let currentSort = "score"; // "score" | "time"

  const DIMS = [
    { key: "政策", id: "policyList", countId: "policyCount", limit: 8 },
    { key: "技术", id: "techList", countId: "techCount", limit: 8 },
    { key: "金融", id: "finList", countId: "finCount", limit: 8 },
    { key: "AI科技", id: "aiList", countId: "aiCount", limit: 8 },
  ];
  const OVERALL_LIMIT = 10;

  // ── Dom refs ───────────────────────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const overallList = $("#overallList");
  const overallCount = $("#overallCount");
  const searchInput = $("#searchInput");
  const siteSelect = $("#siteSelect");
  const updatedAt = $("#updatedAt");
  const stats = $("#stats");
  const modeGreenBtn = $("#modeGreenBtn");
  const modeAllBtn = $("#modeAllBtn");
  const modeHint = $("#modeHint");
  const sortScoreBtn = $("#sortScoreBtn");
  const sortTimeBtn = $("#sortTimeBtn");
  const advancedSummary = $("#advancedSummary");
  const sourceHealth = $("#sourceHealth");
  const sitePills = $("#sitePills");
  const itemTpl = $("#itemTpl");

  // ── Load data ──────────────────────────────────────────────────────────────
  const cb = `?t=${Date.now()}`;
  async function loadData() {
    try {
      const [greenResp, allResp, statusResp] = await Promise.all([
        fetch(`./data/latest-24h.json${cb}`),
        fetch(`./data/latest-24h-all.json${cb}`),
        fetch(`./data/source-status.json${cb}`),
      ]);

      const greenData = await greenResp.json();
      const allData = await allResp.json();
      const statusData = await statusResp.json();

      greenItems = greenData.items || [];
      allItemsRaw = allData.items || [];

      const greenIds = new Set(greenItems.map(i => i.id));
      allItems = allItemsRaw.map(i => ({ ...i, _green: greenIds.has(i.id) }));

      renderStats(greenData, statusData);
      renderSourcePills(statusData);
      renderSourceHealth(statusData);

      if (greenData.generated_at) {
        updatedAt.textContent = formatTime(greenData.generated_at);
      }

      render();
    } catch (err) {
      console.error("Failed to load data:", err);
      overallList.innerHTML = '<p style="color:var(--text-dim);padding:2rem;">数据加载中，请稍候...</p>';
    }
  }

  // ── Stats ──────────────────────────────────────────────────────────────────
  function renderStats(greenData, statusData) {
    const siteCount = greenData.site_count || 0;
    const totalGreen = greenData.total_items || 0;
    const success = statusData.successful || 0;
    const failed = statusData.failed || 0;

    stats.innerHTML = [
      `<span class="stat-item">📡 <strong>${siteCount}</strong> 个源</span>`,
      `<span class="stat-item">🟢 <strong>${totalGreen}</strong> 条动态</span>`,
      `<span class="stat-item">✅ ${success} 正常</span>`,
      failed > 0 ? `<span class="stat-item" style="color:#f87171">⚠️ ${failed} 异常</span>` : "",
    ].join("");
  }

  function renderSourceHealth(statusData) {
    const sites = statusData.sites || [];
    const ok = sites.filter(s => s.ok).length;
    const fail = sites.filter(s => !s.ok).length;
    const total = ok + fail || 1;
    const pct = Math.round((ok / total) * 100);
    sourceHealth.textContent = `源健康: ${ok}/${total} 正常 (${pct}%)`;
  }

  function renderSourcePills(statusData) {
    const sites = statusData.sites || [];
    const counts = {};
    greenItems.forEach(i => { counts[i.site_id] = (counts[i.site_id] || 0) + 1; });

    const pills = sites.map(s => {
      const count = counts[s.site_id] || 0;
      const cls = s.ok ? "" : "err";
      return `<span class="site-pill ${cls}" data-site="${s.site_id}" title="${s.site_name}: ${count} 条">${s.site_name}<span class="count">${count}</span></span>`;
    });

    sitePills.innerHTML = pills.join("");

    sitePills.querySelectorAll(".site-pill").forEach(el => {
      el.addEventListener("click", () => {
        const sid = el.dataset.site;
        if (selectedSite === sid) {
          selectedSite = "";
          el.classList.remove("active");
          siteSelect.value = "";
        } else {
          selectedSite = sid;
          sitePills.querySelectorAll(".site-pill").forEach(e => e.classList.remove("active"));
          el.classList.add("active");
          siteSelect.value = sid;
        }
        render();
      });
    });
  }

  // ── Filtering ──────────────────────────────────────────────────────────────
  function filterItems(source) {
    let items = [...source];
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      items = items.filter(i =>
        (i.title || "").toLowerCase().includes(q) ||
        (i.site_name || "").toLowerCase().includes(q) ||
        (i.source || "").toLowerCase().includes(q) ||
        (i.summary || "").toLowerCase().includes(q)
      );
    }
    if (selectedSite) {
      items = items.filter(i => i.site_id === selectedSite);
    }
    // Sort: by score (desc) or by time (desc)
    items.sort((a, b) => {
      if (currentSort === "score") {
        const sa = a.score || 0, sb = b.score || 0;
        if (sa !== sb) return sb - sa;
      }
      return String(b.published_at || "").localeCompare(String(a.published_at || ""));
    });
    return items;
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  function render() {
    const source = currentMode === "green" ? greenItems : allItems;
    const filtered = filterItems(source);

    modeHint.textContent = currentMode === "green" ? "绿色动态" : "全量";
    advancedSummary.textContent = currentMode === "green"
      ? `绿色动态 ${greenItems.length} 条 / 全量 ${allItems.length} 条`
      : `全量 ${allItems.length} 条`;

    // Populate site select
    const siteIds = new Set();
    const siteOptions = [["", "全部站点"]];
    source.forEach(i => {
      if (!siteIds.has(i.site_id)) {
        siteIds.add(i.site_id);
        siteOptions.push([i.site_id, i.site_name]);
      }
    });
    siteSelect.innerHTML = siteOptions.map(([id, name]) =>
      `<option value="${id}" ${selectedSite === id ? "selected" : ""}>${name}</option>`
    ).join("");

    // 综合榜：Top N
    overallCount.textContent = `${filtered.length} 条`;
    renderList(overallList, filtered.slice(0, OVERALL_LIMIT), "暂无动态");

    // 四维榜
    DIMS.forEach(dim => {
      const dimItems = filtered.filter(i => (i.dimension || "政策") === dim.key);
      document.getElementById(dim.countId).textContent = `${dimItems.length} 条`;
      renderList(document.getElementById(dim.id), dimItems.slice(0, dim.limit), "暂无动态");
    });
  }

  function renderList(container, items, emptyText) {
    if (items.length === 0) {
      container.innerHTML = `<p style="color:var(--text-dim);padding:1rem;text-align:center;font-size:.8rem;">${emptyText}</p>`;
      return;
    }

    container.innerHTML = "";
    const frag = document.createDocumentFragment();

    items.forEach(item => {
      const card = itemTpl.content.cloneNode(true);
      // 分数徽章（News Minimalist 风格）
      const badge = card.querySelector(".score-badge");
      const score = item.score || 0;
      const level = item.score_level || "";
      badge.textContent = score ? `${level}${score}` : "—";
      badge.classList.add(`lv-${level || "none"}`);
      const bd = item.score_breakdown || {};
      badge.title = score
        ? `综合 ${score} 分（${level}级）\n来源权威 ${bd.source} + 政策类型 ${bd.type} + 主题相关 ${bd.topic} + 人物 ${bd.people} + 时效 ${bd.freshness}`
        : "暂无评分";

      // 四维标签
      const dimTag = card.querySelector(".dim-tag");
      const dim = item.dimension || "政策";
      dimTag.textContent = dim;
      dimTag.classList.add(`dim-${dim}`);

      card.querySelector(".site").textContent = item.site_name || item.site_id;
      const timeEl = card.querySelector(".time");
      const timeTxt = formatTime(item.published_at);
      timeEl.textContent = item.time_source === "scraped" ? `收录 ${timeTxt}` : timeTxt;
      timeEl.title = item.time_source === "scraped"
        ? "源站未提供发布时间，此时间为收录（抓取）时间"
        : "发布时间";

      const titleLink = card.querySelector(".title");
      titleLink.href = item.url;
      titleLink.textContent = item.title;
      titleLink.title = item.title;

      // 可展开摘要（News Minimalist 风格；summary 来自 JSON 回填）
      const summary = item.summary || "";
      const sumEl = card.querySelector(".summary");
      const toggleBtn = card.querySelector(".summary-toggle");
      if (summary && summary.length > 8) {
        sumEl.textContent = summary;
        toggleBtn.hidden = false;
        toggleBtn.addEventListener("click", () => {
          const expanded = sumEl.hidden === false;
          sumEl.hidden = expanded;
          toggleBtn.textContent = expanded ? "摘要" : "收起";
          toggleBtn.classList.toggle("open", !expanded);
        });
      }
      frag.appendChild(card);
    });

    container.appendChild(frag);
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
    if (diffMin < 0) return abs; // future-dated
    if (diffMin < 60) return `${Math.floor(diffMin)}分钟前 · ${abs}`;
    if (diffMin < 24 * 60) return `${Math.floor(diffMin / 60)}小时前 · ${abs}`;
    return abs;
  }

  // ── Event listeners ────────────────────────────────────────────────────────
  searchInput.addEventListener("input", () => {
    searchQuery = searchInput.value.trim();
    render();
  });

  siteSelect.addEventListener("change", () => {
    selectedSite = siteSelect.value;
    render();
  });

  function setMode(mode, activeBtn, otherBtn) {
    currentMode = mode;
    activeBtn.classList.add("active");
    otherBtn.classList.remove("active");
    selectedSite = "";
    siteSelect.value = "";
    render();
  }
  modeGreenBtn.addEventListener("click", () => setMode("green", modeGreenBtn, modeAllBtn));
  modeAllBtn.addEventListener("click", () => setMode("all", modeAllBtn, modeGreenBtn));

  // ── Sort ───────────────────────────────────────────────────────────────────
  function setSort(sort, activeBtn, otherBtn) {
    currentSort = sort;
    activeBtn.classList.add("active");
    otherBtn.classList.remove("active");
    render();
  }
  sortScoreBtn.addEventListener("click", () => setSort("score", sortScoreBtn, sortTimeBtn));
  sortTimeBtn.addEventListener("click", () => setSort("time", sortTimeBtn, sortScoreBtn));

  // ── Init ───────────────────────────────────────────────────────────────────
  loadData();

  // Auto-refresh every 10 min
  setInterval(loadData, 10 * 60 * 1000);
})();
