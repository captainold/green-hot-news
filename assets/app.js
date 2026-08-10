// ── Green Hot News · 绿色政策雷达 — App ──────────────────────────────────────
(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────────────────────────
  let allItems = [];
  let greenItems = [];
  let allItemsRaw = [];
  let searchQuery = "";
  let selectedSite = "";
  let currentMode = "green"; // "green" | "all"

  // ── Dom refs ───────────────────────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const newsList = $("#newsList");
  const searchInput = $("#searchInput");
  const siteSelect = $("#siteSelect");
  const resultCount = $("#resultCount");
  const updatedAt = $("#updatedAt");
  const stats = $("#stats");
  const modeGreenBtn = $("#modeGreenBtn");
  const modeAllBtn = $("#modeAllBtn");
  const modeHint = $("#modeHint");
  const listTitle = $("#listTitle");
  const advancedSummary = $("#advancedSummary");
  const sourceHealth = $("#sourceHealth");
  const sitePills = $("#sitePills");
  const itemTpl = $("#itemTpl");

  // ── Load data ──────────────────────────────────────────────────────────────
  // Cache-buster: GitHub Pages serves data with max-age=600; a changing query
  // param forces the browser (and CDN) to fetch fresh JSON every load.
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

      // Merge green flag into allItemsRaw
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
      newsList.innerHTML = '<p style="color:var(--text-dim);padding:2rem;">数据加载中，请稍候...</p>';
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
      `<span class="stat-item">🟢 <strong>${totalGreen}</strong> 条政策信号</span>`,
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
    // Build counts from greenItems
    const counts = {};
    greenItems.forEach(i => { counts[i.site_id] = (counts[i.site_id] || 0) + 1; });

    const pills = sites.map(s => {
      const count = counts[s.site_id] || 0;
      const cls = s.ok ? "" : "err";
      return `<span class="site-pill ${cls}" data-site="${s.site_id}" title="${s.site_name}: ${count} 条">${s.site_name}<span class="count">${count}</span></span>`;
    });

    sitePills.innerHTML = pills.join("");

    // Click handler
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

  // ── Render ─────────────────────────────────────────────────────────────────
  function render() {
    const source = currentMode === "green" ? greenItems : allItems;
    let items = [...source];

    // Filter by search
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      items = items.filter(i =>
        (i.title || "").toLowerCase().includes(q) ||
        (i.site_name || "").toLowerCase().includes(q) ||
        (i.source || "").toLowerCase().includes(q)
      );
    }

    // Filter by site
    if (selectedSite) {
      items = items.filter(i => i.site_id === selectedSite);
    }

    resultCount.textContent = `${items.length} 条`;
    listTitle.textContent = currentMode === "green" ? "绿色政策信号流" : "全量信号流";
    modeHint.textContent = currentMode === "green" ? "绿色政策" : "全量";
    advancedSummary.textContent = currentMode === "green"
      ? `绿色政策 ${greenItems.length} 条 / 全量 ${allItems.length} 条`
      : `全量 ${allItems.length} 条`;

    // Populate site select
    const siteIds = new Set();
    const siteOptions = [["", "全部站点"]];
    (currentMode === "green" ? greenItems : allItems).forEach(i => {
      if (!siteIds.has(i.site_id)) {
        siteIds.add(i.site_id);
        siteOptions.push([i.site_id, i.site_name]);
      }
    });
    siteSelect.innerHTML = siteOptions.map(([id, name]) =>
      `<option value="${id}" ${selectedSite === id ? "selected" : ""}>${name}</option>`
    ).join("");

    // Render cards
    if (items.length === 0) {
      newsList.innerHTML = '<p style="color:var(--text-dim);padding:2rem;text-align:center;">暂无匹配的政策信号</p>';
      return;
    }

    newsList.innerHTML = "";
    const frag = document.createDocumentFragment();

    items.forEach(item => {
      const card = itemTpl.content.cloneNode(true);
      card.querySelector(".site").textContent = item.site_name || item.site_id;
      card.querySelector(".source").textContent = item.source || "";
      const timeEl = card.querySelector(".time");
      const timeTxt = formatTime(item.published_at);
      // Scrape-time fallback (source site gives no publish time): mark it clearly
      timeEl.textContent = item.time_source === "scraped" ? `收录 ${timeTxt}` : timeTxt;
      timeEl.title = item.time_source === "scraped"
        ? "源站未提供发布时间，此时间为收录（抓取）时间"
        : "发布时间";
      const titleLink = card.querySelector(".title");
      titleLink.href = item.url;
      titleLink.textContent = item.title;
      titleLink.title = item.title;
      frag.appendChild(card);
    });

    newsList.appendChild(frag);
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  // Always show an absolute publish time (Beijing-local), hour precision,
  // with 上午/下午 phrasing. Recent items get a relative hint appended.
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

  modeGreenBtn.addEventListener("click", () => {
    currentMode = "green";
    modeGreenBtn.classList.add("active");
    modeAllBtn.classList.remove("active");
    selectedSite = "";
    siteSelect.value = "";
    render();
  });

  modeAllBtn.addEventListener("click", () => {
    currentMode = "all";
    modeAllBtn.classList.add("active");
    modeGreenBtn.classList.remove("active");
    selectedSite = "";
    siteSelect.value = "";
    render();
  });

  // ── Init ───────────────────────────────────────────────────────────────────
  loadData();

  // Auto-refresh every 10 min
  setInterval(loadData, 10 * 60 * 1000);
})();
