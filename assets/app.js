// ── Green Hot News · 绿色低碳动态雷达 — App ──────────────────────────────────
// 布局（2026-08-17 v3）：区域一 排行榜（主题 × 周期 × 区域切换）+ 区域二 时间线
// （跟随筛选，新条目自动插入顶部高亮；服务器每 30 分钟抓取，页面 60s 轮询）
(function () {
  "use strict";

  // ── State ──────────────────────────────────────────────────────────────────
  let greenItems = [];        // latest-24h.json（绿色动态）
  let allItemsRaw = [];       // latest-24h-all.json（全量，仅 96h 窗口）
  let historyItems = [];      // history.json（62 天累积，日/周/月数据源）
  let historyLoaded = false;  // history 是否可用（404 → 降级 latest-24h）
  let searchQuery = "";
  let selectedSite = "";
  let currentMode = "green"; // "green" | "all"
  let currentTopic = "全部"; // 全部 | 政策 | 技术 | 金融 | AI科技
  let currentPeriod = "日";  // 日 | 周 | 月
  let currentRegion = "国际"; // 国内 | 国际（国际=全部含国内）
  let tlPaused = false;      // 时间线实时暂停
  let tlCursor = 50;         // 时间线已渲染条数（分页）
  let tlAllIds = new Set();  // 时间线已渲染 url 集合（diff 新条目用）

  const TOPICS = ["全部", "政策", "技术", "金融", "AI科技"];
  const PERIODS = ["日", "周", "月"];
  const REGIONS = ["国内", "国际"];
  const RANK_LIMIT = 20;
  const TL_PAGE = 50;
  const POLL_MS = 60 * 1000;
  const HOUR = 3600 * 1000;

  // ── Dom refs ───────────────────────────────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const rankList = $("#rankList");
  const rankCount = $("#rankCount");
  const rankSub = $("#rankSub");
  const tlList = $("#tlList");
  const tlSub = $("#tlSub");
  const tlMoreBtn = $("#tlMoreBtn");
  const livePill = $("#livePill");
  const tlPauseBtn = $("#tlPauseBtn");
  const tlTopBtn = $("#tlTopBtn");
  const topicSwitch = $("#topicSwitch");
  const periodSwitch = $("#periodSwitch");
  const regionSwitch = $("#regionSwitch");
  const searchInput = $("#searchInput");
  const siteSelect = $("#siteSelect");
  const updatedAt = $("#updatedAt");
  const stats = $("#stats");
  const modeGreenBtn = $("#modeGreenBtn");
  const modeAllBtn = $("#modeAllBtn");
  const modeHint = $("#modeHint");
  const advancedSummary = $("#advancedSummary");
  const sourceHealth = $("#sourceHealth");
  const sitePills = $("#sitePills");
  const itemTpl = $("#itemTpl");
  const digestBtn = $("#digestBtn");
  const digestMask = $("#digestMask");
  const digestContent = $("#digestContent");
  const digestCopy = $("#digestCopy");
  const digestClose = $("#digestClose");

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

      renderStats(greenData, statusData);
      renderSourcePills(statusData);
      renderSourceHealth(statusData);
      if (greenData.generated_at) updatedAt.textContent = formatTime(greenData.generated_at);

      if (!historyLoaded) await loadHistory();
      renderAll();
    } catch (err) {
      console.error("Failed to load data:", err);
      rankList.innerHTML = '<p style="color:var(--text-dim);padding:2rem;">数据加载中，请稍候...</p>';
    }
  }

  async function loadHistory() {
    try {
      const r = await fetch(`./data/history.json${cb}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      historyItems = d.items || [];
      historyLoaded = true;
    } catch (err) {
      console.warn("history.json not ready, fallback to latest-24h:", err);
      historyLoaded = false;
      historyItems = greenItems;
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
        renderAll();
      });
    });
  }

  // ── Filtering（主题 × 周期 × 区域 × 站点 × 搜索 × 模式）──────────────────
  function itemTime(i) {
    return i.published_at || i.first_seen_at || "";
  }

  function periodStart() {
    const h = currentPeriod === "日" ? 24 : currentPeriod === "周" ? 24 * 7 : 24 * 30;
    return Date.now() - h * HOUR;
  }

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
    if (selectedSite) items = items.filter(i => i.site_id === selectedSite);
    if (currentTopic !== "全部") items = items.filter(i => (i.dimension || "政策") === currentTopic);
    if (currentRegion === "国内") items = items.filter(i => (i.region || "") === "中国");
    // 周期过滤（时间线/排行榜共用）
    const start = periodStart();
    items = items.filter(i => {
      const t = Date.parse(itemTime(i));
      return isNaN(t) || t >= start; // 无时间的条目保留（收录即最新）
    });
    return items;
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  function renderAll() {
    modeHint.textContent = currentMode === "green" ? "绿色动态" : "全量";
    advancedSummary.textContent = currentMode === "green"
      ? `历史 ${historyItems.length} 条 / 近24h ${greenItems.length} 条`
      : `全量（仅96h窗口） ${allItemsRaw.length} 条`;

    populateSiteSelect(currentMode === "green" ? historyItems : allItemsRaw);

    const source = currentMode === "green" ? historyItems : allItemsRaw;
    const filtered = filterItems(source);

    renderRank(filtered);
    renderTimeline(filtered, true);
  }

  function populateSiteSelect(source) {
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
  }

  // 排行榜：综合分降序 Top N
  function renderRank(filtered) {
    const scope = currentRegion === "国内" ? "国内" : "国际";
    rankSub.textContent = `${currentTopic} · ${scope} · ${currentPeriod}`;
    rankCount.textContent = `${filtered.length} 条`;

    const ranked = [...filtered].sort((a, b) => {
      const sa = a.score || 0, sb = b.score || 0;
      if (sa !== sb) return sb - sa;
      return String(itemTime(b)).localeCompare(String(itemTime(a)));
    });
    if (currentMode === "all" && currentPeriod !== "日") {
      rankList.innerHTML = `<p style="color:var(--text-dim);padding:1.5rem;text-align:center;font-size:.8rem;">全量模式仅覆盖 96h 窗口，请切换到「日」周期查看</p>`;
      return;
    }
    renderList(rankList, ranked.slice(0, RANK_LIMIT), "暂无动态");
  }

  // 时间线：时间倒序，分页；跟随排行榜筛选
  function renderTimeline(filtered, reset) {
    const tl = [...filtered].sort((a, b) => String(itemTime(b)).localeCompare(String(itemTime(a))));
    if (reset) {
      tlCursor = TL_PAGE;
      tlAllIds = new Set(tl.slice(0, tlCursor).map(i => i.url));
    }
    tlSub.textContent = `跟随排行榜 · ${currentTopic} · ${currentRegion} · ${currentPeriod} · ${tl.length} 条`;
    const slice = tl.slice(0, tlCursor);
    if (tlAllIds.size === 0) tlAllIds = new Set(slice.map(i => i.url));
    renderList(tlList, slice, "暂无动态");
    tlMoreBtn.hidden = tl.length <= tlCursor;
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
      const badge = card.querySelector(".score-badge");
      const score = item.score || 0;
      const level = item.score_level || "";
      badge.textContent = score ? `${level}${score}` : "—";
      badge.classList.add(`lv-${level || "none"}`);
      const bd = item.score_breakdown || {};
      badge.title = score
        ? `综合 ${score} 分（${level}级）\n来源权威 ${bd.source} + 内容强度 ${bd.strength} + 主题相关 ${bd.topic} + 人物 ${bd.people} + 时效 ${bd.freshness}`
        : "暂无评分";

      const dimTag = card.querySelector(".dim-tag");
      const dim = item.dimension || "政策";
      dimTag.textContent = dim;
      dimTag.classList.add(`dim-${dim}`);

      card.querySelector(".site").textContent = item.site_name || item.site_id;
      const timeEl = card.querySelector(".time");
      const timeTxt = formatTime(itemTime(item));
      timeEl.textContent = item.time_source === "scraped" ? `收录 ${timeTxt}` : timeTxt;
      timeEl.title = item.time_source === "scraped"
        ? "源站未提供发布时间，此时间为收录（抓取）时间"
        : "发布时间";

      const titleLink = card.querySelector(".title");
      titleLink.href = item.url;
      titleLink.textContent = item.title;
      titleLink.title = item.title;

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
      if (item._flashNew) card.classList.add("flash-new");
      frag.appendChild(card);
    });
    container.appendChild(frag);
  }

  // ── 时间线实时轮询（2026-08-17）：新扫描条目自动插入顶部 ──────────────────
  async function pollNew() {
    if (tlPaused) return;
    try {
      const r = await fetch(`./data/latest-24h.json${cb}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      const latest = d.items || [];
      const known = new Set(historyItems.map(i => i.url));
      const fresh = latest.filter(i => !known.has(i.url));
      if (fresh.length === 0) {
        livePill.textContent = "🟢 实时";
        return;
      }
      // 新条目并入 historyItems（保持时间线完整性），并按当前筛选决定是否展示
      historyItems = fresh.concat(historyItems);
      if (currentMode === "green") {
        const filtered = filterItems(historyItems);
        const tl = [...filtered].sort((a, b) => String(itemTime(b)).localeCompare(String(itemTime(a))));
        const newcomers = tl.filter(i => fresh.some(f => f.url === i.url));
        if (newcomers.length > 0) {
          const atTop = tlList.scrollTop < 60;
          const slice = tl.slice(0, tlCursor);
          slice.forEach(i => { if (newcomers.some(n => n.url === i.url)) i._flashNew = true; });
          renderList(tlList, slice, "暂无动态");
          tlSub.textContent = `跟随排行榜 · ${currentTopic} · ${currentRegion} · ${currentPeriod} · ${tl.length} 条`;
          if (atTop && !tlPaused) {
            tlList.scrollTop = 0;
          } else {
            tlTopBtn.hidden = false;
          }
          livePill.textContent = `🟢 实时 · +${newcomers.length}`;
          // 动画结束后清除标记，避免下次全量重渲染误高亮
          setTimeout(() => { fresh.forEach(i => { delete i._flashNew; }); }, 3000);
        }
      }
    } catch (err) {
      console.warn("poll failed:", err);
    }
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

  // ── 当日高分浓缩（2026-08-17）────────────────────────────────────────────
  let digestText = "";
  let digestLoaded = false;
  async function loadDigest() {
    try {
      const r = await fetch(`./data/daily-digest.md?t=${Date.now()}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      digestText = await r.text();
      digestLoaded = true;
      digestContent.textContent = digestText;
    } catch (err) {
      console.warn("digest not ready:", err);
      digestLoaded = false;
      digestText = "";
      digestContent.textContent =
        "浓缩版尚未生成：服务器每次抓取后自动生成（约每 30 分钟更新一次）。\n\n可稍后刷新再试，或在本地运行：\npython3.11 scripts/daily_digest.py";
    }
  }
  function openDigest() {
    digestMask.hidden = false;
    document.body.style.overflow = "hidden";
    if (!digestLoaded) loadDigest();
  }
  function closeDigest() {
    digestMask.hidden = true;
    document.body.style.overflow = "";
  }
  digestBtn.addEventListener("click", openDigest);
  digestClose.addEventListener("click", closeDigest);
  digestMask.addEventListener("click", (e) => { if (e.target === digestMask) closeDigest(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !digestMask.hidden) closeDigest();
  });
  digestCopy.addEventListener("click", async () => {
    if (!digestText) {
      await loadDigest();
      if (!digestText) return;
    }
    let copied = false;
    try {
      await navigator.clipboard.writeText(digestText);
      copied = true;
    } catch {
      const ta = document.createElement("textarea");
      ta.value = digestText;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      copied = document.execCommand("copy");
      ta.remove();
    }
    digestCopy.textContent = copied ? "✅ 已复制" : "⚠️ 复制失败";
    setTimeout(() => { digestCopy.textContent = "📄 复制全文"; }, 2000);
  });

  // ── Event listeners ────────────────────────────────────────────────────────
  searchInput.addEventListener("input", () => {
    searchQuery = searchInput.value.trim();
    renderAll();
  });
  siteSelect.addEventListener("change", () => {
    selectedSite = siteSelect.value;
    renderAll();
  });

  function setMode(mode, activeBtn, otherBtn) {
    currentMode = mode;
    activeBtn.classList.add("active");
    otherBtn.classList.remove("active");
    selectedSite = "";
    siteSelect.value = "";
    renderAll();
  }
  modeGreenBtn.addEventListener("click", () => setMode("green", modeGreenBtn, modeAllBtn));
  modeAllBtn.addEventListener("click", () => setMode("all", modeAllBtn, modeGreenBtn));

  // 切换器
  buildSwitch(topicSwitch, TOPICS, currentTopic, (v) => { currentTopic = v; renderAll(); });
  buildSwitch(periodSwitch, PERIODS, currentPeriod, (v) => { currentPeriod = v; renderAll(); });
  buildSwitch(regionSwitch, REGIONS, currentRegion, (v) => { currentRegion = v; renderAll(); });

  // 时间线实时控制
  tlPauseBtn.addEventListener("click", () => {
    tlPaused = !tlPaused;
    tlPauseBtn.textContent = tlPaused ? "▶ 继续" : "⏸ 暂停";
    livePill.textContent = tlPaused ? "⏸ 已暂停" : "🟢 实时";
    if (!tlPaused) pollNew();
  });
  tlTopBtn.addEventListener("click", () => {
    tlList.scrollTop = 0;
    tlTopBtn.hidden = true;
  });
  tlMoreBtn.addEventListener("click", () => {
    tlCursor += TL_PAGE;
    const source = currentMode === "green" ? historyItems : allItemsRaw;
    renderTimeline(filterItems(source), false);
  });
  // 滚动到底自动加载更早
  tlList.addEventListener("scroll", () => {
    if (tlList.scrollHeight - tlList.scrollTop - tlList.clientHeight < 300) {
      const source = currentMode === "green" ? historyItems : allItemsRaw;
      const filtered = filterItems(source);
      if (filtered.length > tlCursor) {
        tlCursor += TL_PAGE;
        renderTimeline(filtered, false);
      }
    }
  });

  // ── Init ───────────────────────────────────────────────────────────────────
  loadData();
  loadDigest();
  setInterval(loadData, 10 * 60 * 1000);   // 全量刷新（含 history 重新拉取）
  setInterval(pollNew, POLL_MS);           // 时间线新条目轮询（60s）
})();
