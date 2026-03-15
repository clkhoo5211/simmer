// js/app.js  —  dashboard logic: polling, rendering, interactions

// ── State ─────────────────────────────────────────────────────────────────────
let state = {
  portfolio: null,
  markets: [],
  positions: [],
  arbOpps: [],
  config: {},
  venue: "polymarket_paper",
  tradeLog: [],
  tradeLogPage: 0,
  tradeLogTotal: null,  // null for Polymarket live (API doesn't return total)
  pollTimer: null,
  probSyncTimer: null,
  marketListSyncTimer: null,  // Polymarket: full market list refresh (ending-soon order, resolved status)
  isLoading: false,
  syncFailCount: 0,  // consecutive failures; only show OFFLINE after 2+
  marketTagFilter: null,  // tag slug to filter Active Markets; null = show all
};

const POLYMARKET_PROB_SYNC_MS = 15000;   // 15s YES probability refresh
const POLYMARKET_MARKET_LIST_SYNC_MS = 30000;  // 30s full list refresh (active/closed + endDate order verified)

// ── Bootstrap ─────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await loadAll();
  startPolling();
  bindEvents();
});

async function loadAll() {
  if (state.isLoading) return;
  state.isLoading = true;
  setStatus("loading");
  try {
    // 1. Fetch config and health first to establish baseline
    const [health, config] = await Promise.all([
      api.health(),
      api.getConfig(),
    ]);

    // 2. Only set venue from config if it's the very first load or specifically requested
    if (!state.config || Object.keys(state.config).length === 0) {
      state.venue = config.default_venue || "polymarket_paper";
    }
    state.config = config;

    // 3. Fetch venue-specific data in parallel for speed (all with timeouts so we never hang)
    const timeoutMs = (typeof CONFIG !== "undefined" && CONFIG.POSITIONS_TRADES_TIMEOUT_MS) || 12000;
    const marketsTimeoutMs = (typeof CONFIG !== "undefined" && CONFIG.MARKETS_TIMEOUT_MS) || 20000;
    const timeoutPromise = (ms) => new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), ms));
    const positionsPromise = api.positions(state.venue).catch(e => ({ error: e.message }));
    const tradesPromise = api.trades(state.venue, 20, 0).catch(e => ({ error: e.message }));
    const marketsPromise = api.markets(state.venue).catch(e => ({ error: e.message }));

    const [p, m, pos, t] = await Promise.all([
      api.portfolio(state.venue).catch(e => ({ error: e.message })),
      Promise.race([marketsPromise, timeoutPromise(marketsTimeoutMs)]).catch(() => ({ error: "Markets request timed out" })),
      Promise.race([positionsPromise, timeoutPromise(timeoutMs)]).catch(() => []),
      Promise.race([tradesPromise, timeoutPromise(timeoutMs)]).catch(() => []),
    ]);

    // Guarded updates: Only overwrite if response is valid (not an error object)
    if (p && !p.error) state.portfolio = p;
    if (Array.isArray(m)) {
      state.markets = m;
    } else {
      state.markets = []; // timeout or error — show empty so we don't stick on "Loading…"
      if (m && m.error && state.syncFailCount === 0) {
        showToast(`Markets: ${m.error}`, "error");
      }
    }

    // Positions: backend may return a list or { positions: [], error?: string }
    state.positions = Array.isArray(pos) ? pos : (pos && Array.isArray(pos.positions) ? pos.positions : []);

    // Trade log: backend returns { trades: [], total: number | null } (paginated, 20 per page)
    state.tradeLog = (t && Array.isArray(t.trades) ? t.trades : Array.isArray(t) ? t : []);
    state.tradeLogTotal = (t && typeof t.total === "number") ? t.total : null;
    state.tradeLogPage = 0;

    state.isLoading = false;  // Clear loading before render so empty []/total 0 show "No positions" / "No trades" not "Loading…"
    renderAll();
    state.syncFailCount = 0;
    setStatus(health.stop_loss ? "halted" : "live");
    startPolymarketProbSync();
    startPolymarketMarketListSync();  // Polymarket: full list refresh (ending-soon order, resolved status)
  } catch (err) {
    state.syncFailCount = (state.syncFailCount || 0) + 1;
    console.error("API sync error:", err);
    state.positions = state.positions || [];
    state.tradeLog = state.tradeLog || [];
    setStatus("error");
    const base = typeof CONFIG !== "undefined" && CONFIG.API_BASE ? CONFIG.API_BASE : "(unknown)";
    if (state.syncFailCount === 1) {
      showToast(
        `⚠️ API Sync Failed — cannot reach ${base}. Is the backend running? Open the dashboard at http://localhost:8081 (not file://) and hard-refresh (Cmd+Shift+R).`,
        "error"
      );
    }
    state.isLoading = false;
    renderAll();
  } finally {
    state.isLoading = false;
  }
}

function startPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(loadAll, CONFIG.POLL_INTERVAL_MS);
}

function stopPolymarketProbSync() {
  if (state.probSyncTimer) {
    clearInterval(state.probSyncTimer);
    state.probSyncTimer = null;
  }
}

function stopPolymarketMarketListSync() {
  if (state.marketListSyncTimer) {
    clearInterval(state.marketListSyncTimer);
    state.marketListSyncTimer = null;
  }
}

function startPolymarketMarketListSync() {
  stopPolymarketMarketListSync();
  if (state.venue !== "polymarket" && state.venue !== "polymarket_paper") return;
  state.marketListSyncTimer = setInterval(syncPolymarketMarketList, POLYMARKET_MARKET_LIST_SYNC_MS);
}

/** Re-fetch full market list (active/closed, endDate order) and refresh table. */
async function syncPolymarketMarketList() {
  if (state.venue !== "polymarket" && state.venue !== "polymarket_paper") return;
  try {
    const fresh = await api.markets(state.venue);
    if (!Array.isArray(fresh)) return;
    state.markets = fresh;
    renderMarkets();
  } catch (_) { /* ignore */ }
}

function startPolymarketProbSync() {
  stopPolymarketProbSync();
  if (state.venue !== "polymarket" && state.venue !== "polymarket_paper") return;
  state.probSyncTimer = setInterval(syncPolymarketProbabilities, POLYMARKET_PROB_SYNC_MS);
}

/** Fetch markets and update only YES probability in DOM (no table re-render). */
async function syncPolymarketProbabilities() {
  if (state.venue !== "polymarket" && state.venue !== "polymarket_paper") return;
  if (!state.markets || state.markets.length === 0) return;
  try {
    const fresh = await api.markets(state.venue);
    if (!Array.isArray(fresh)) return;
    const byId = Object.fromEntries(fresh.map(m => [m.id, m]));
    let updated = false;
    for (const m of state.markets) {
      const f = byId[m.id];
      if (f != null && typeof f.current_probability === "number" && f.current_probability !== m.current_probability) {
        m.current_probability = f.current_probability;
        updated = true;
      }
    }
    if (!updated) return;
    const tbody = document.getElementById("markets-body");
    if (!tbody) return;
    const rows = tbody.querySelectorAll(".market-row");
    for (const row of rows) {
      const id = row.getAttribute("data-id");
      const m = state.markets.find(m => m.id === id);
      if (!m) continue;
      const bar = row.querySelector(".prob-bar");
      const label = row.querySelector(".prob-label");
      if (bar) bar.style.width = (m.current_probability * 100).toFixed(1) + "%";
      if (label) label.textContent = (m.current_probability * 100).toFixed(1) + "%";
    }
  } catch (_) { /* ignore background sync errors */ }
}

// ── Render ────────────────────────────────────────────────────────────────────
function renderAll() {
  renderHeader();
  renderPortfolio();
  renderMarkets();
  renderPositions();
  renderTradeLog();
  renderArbResults(state.arbOpps);
  renderConfig();
}

const VENUE_LABELS = {
  simmer: "SIMMER (Paper)",
  polymarket_paper: "POLYMARKET (Paper)",
  polymarket: "POLYMARKET (Live)",
};
function renderHeader() {
  const el = document.getElementById("venue-badge");
  if (el) el.textContent = VENUE_LABELS[state.venue] || state.venue.toUpperCase();
}

function renderPortfolio() {
  const p = state.portfolio;
  if (!p) return;
  setText("balance", fmt$(p.balance_usdc));
  setText("total-pnl", fmt$(p.total_pnl));
  setText("exposure", fmt$(p.total_exposure));
  setText("daily-used", fmt$(p.daily_spent) + " / " + fmt$(p.daily_limit));

  const pnlEl = document.getElementById("total-pnl");
  if (pnlEl) {
    pnlEl.classList.toggle("positive", p.total_pnl >= 0);
    pnlEl.classList.toggle("negative", p.total_pnl < 0);
  }
}

function setMarketTagFilter(tagSlug) {
  state.marketTagFilter = tagSlug || null;
  renderMarkets();
}

function renderMarkets() {
  const tbody = document.getElementById("markets-body");
  const chipEl = document.getElementById("market-tag-filter-chip");
  if (!tbody) return;
  const list = state.markets || [];
  const filtered = state.marketTagFilter
    ? list.filter(m => (m.tag_slugs || []).includes(state.marketTagFilter))
    : list;
  if (chipEl) {
    if (state.marketTagFilter) {
      chipEl.style.display = "inline";
      chipEl.innerHTML = `Filter: <strong>${escapeHtml(state.marketTagFilter)}</strong> <button type="button" class="tag-filter-clear" data-clear-tag-filter>✕</button>`;
    } else {
      chipEl.style.display = "none";
      chipEl.innerHTML = "";
    }
  }
  if (!list.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">${state.isLoading ? "Loading markets…" : "No markets"}</td></tr>`;
    return;
  }
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">No markets with tag “${escapeHtml(state.marketTagFilter)}”. <button type="button" class="link-button" data-clear-tag-filter>Show all</button></td></tr>`;
    return;
  }
  tbody.innerHTML = filtered.map(m => {
    const slugs = m.tag_slugs || [];
    const tagCell = slugs.length
      ? slugs.map(s => `<button type="button" class="tag-slug-btn" data-tag-slug="${escapeHtml(s)}" title="Filter by ${escapeHtml(s)}">${escapeHtml(s)}</button>`).join(" ")
      : "—";
    const conditionId = m.id || "—";
    const conditionIdShort = conditionId.length > 20 ? conditionId.slice(0, 20) + "…" : conditionId;
    const viewLink = (m.slug && m.slug.trim())
      ? `<a class="link-view" href="https://polymarket.com/event/${encodeURIComponent(m.slug)}" target="_blank" rel="noopener" title="Open on Polymarket">View</a>`
      : "";
    return `
    <tr class="market-row" data-id="${escapeHtml(conditionId)}">
      <td class="q-cell" title="${escapeHtml(m.question)}">${escapeHtml(m.question.slice(0, 58))}${m.question.length > 58 ? "…" : ""}${m.is_sports ? ' <span class="badge-sports" title="Sports market">Sports</span>' : ""}</td>
      <td>
        <div class="prob-bar-wrap">
          <div class="prob-bar" style="width:${(m.current_probability * 100).toFixed(1)}%"></div>
          <span class="prob-label">${(m.current_probability * 100).toFixed(1)}%</span>
        </div>
      </td>
      <td class="${m.divergence > 0 ? 'pos' : m.divergence < 0 ? 'neg' : ''}">${m.divergence != null ? (m.divergence * 100).toFixed(2) + "%" : "—"}</td>
      <td class="resolves-cell">${formatResolvesAt(m.resolves_at)}</td>
      <td class="condition-id-cell mono" title="${escapeHtml(conditionId)}">${escapeHtml(conditionIdShort)}</td>
      <td class="tag-cell">${tagCell}</td>
      <td>
        <div class="trade-btns">
          <button type="button" class="btn-yes" data-quick-trade data-market-id="${escapeHtml(conditionId)}" data-side="yes">YES</button>
          <button type="button" class="btn-no" data-quick-trade data-market-id="${escapeHtml(conditionId)}" data-side="no">NO</button>
          ${viewLink}
        </div>
      </td>
    </tr>
  `;
  }).join("");
}

function escapeHtml(s) {
  if (s == null) return "";
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}

function renderPositions() {
  const tbody = document.getElementById("positions-body");
  if (!tbody) return;
  if (!state.positions || !state.positions.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">${state.isLoading ? "Loading…" : "No open positions"}</td></tr>`;
    return;
  }
  tbody.innerHTML = state.positions.map(p => `
    <tr>
      <td title="${p.question}">${p.question.slice(0, 50)}${p.question.length > 50 ? "…" : ""}</td>
      <td>${p.shares_yes.toFixed(3)}</td>
      <td>${p.shares_no.toFixed(3)}</td>
      <td>${fmt$(p.current_value)}</td>
      <td class="${p.pnl >= 0 ? 'positive' : 'negative'}">${fmt$(p.pnl)}</td>
      <td><span class="badge badge-${p.status}">${p.status}</span></td>
    </tr>
  `).join("");
}

function renderConfig() {
  const c = state.config;
  if (!c) return;

  // Master automation toggle
  const isOn = !!c.automation_enabled;
  setChecked("toggle-automation", isOn);
  const panel = document.getElementById("automation-panel");
  const status = document.getElementById("automation-status");
  if (panel) panel.classList.toggle("active", isOn);
  if (status) { status.textContent = isOn ? "RUNNING" : "STOPPED"; status.className = `automation-status${isOn ? " on" : ""}`; }

  setChecked("toggle-arb", c.strategy_arb);
  setChecked("toggle-mm", c.strategy_mm);
  setChecked("toggle-ai", c.strategy_ai);
  setChecked("toggle-corr", c.strategy_correlation);

  setVal("cfg-venue", c.default_venue || "polymarket_paper");
  // Don't force venue-select to change here if user is mid-interaction
  const venueSelect = document.getElementById("venue-select");
  if (venueSelect && venueSelect.value !== state.venue) {
    venueSelect.value = state.venue;
  }

  setVal("cfg-max-trade", c.max_trade_usd || 25);
  setVal("cfg-max-daily", c.max_daily_usd || 200);
  setVal("cfg-min-edge", (c.min_arb_edge * 100).toFixed(1) || 1.5);
}

// ── Actions ───────────────────────────────────────────────────────────────────
async function quickTrade(marketId, side) {
  const amount = parseFloat(document.getElementById("quick-amount")?.value)
    || CONFIG.DEFAULT_TRADE_AMOUNT;
  const reason = document.getElementById("quick-reason")?.value || "";

  showToast(`Placing ${side.toUpperCase()} $${amount}…`, "info");
  try {
    const result = await api.trade({
      market_id: marketId,
      side,
      amount,
      reasoning: reason,
      venue: state.venue,
    });
    // Removed logTrade() - history is now fetched from backend in loadAll()
    showToast(`✅ ${side.toUpperCase()} ${result.shares_bought?.toFixed(3)} shares @ $${result.cost?.toFixed(2)}`, "success");
    await loadAll();
  } catch (err) {
    showToast(`❌ Trade failed: ${err.message}`, "error");
  }
}

async function runArbScan() {
  const btn = document.getElementById("arb-scan-btn");
  if (btn) btn.disabled = true;
  try {
    const opps = await api.arbScan(state.venue);
    state.arbOpps = opps;
    renderArbResults(opps);
  } catch (err) {
    showToast("Arb scan failed", "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function renderArbResults(opps) {
  const el = document.getElementById("arb-results");
  if (!el) return;
  if (!opps.length) {
    el.innerHTML = `<p class="empty-arb">No opportunities found right now.</p>`;
    return;
  }
  el.innerHTML = opps.map(o => `
    <div class="arb-card">
      <p class="arb-q">${o.question.slice(0, 60)}</p>
      <div class="arb-meta">
        <span>YES ${(o.yes_price * 100).toFixed(1)}¢</span>
        <span>NO ${(o.no_price * 100).toFixed(1)}¢</span>
        <span class="arb-edge">Edge: <b>${o.edge_pct}%</b></span>
      </div>
    </div>
  `).join("");
}

async function saveConfig() {
  const venue = getVal("cfg-venue");
  const maxTrade = parseFloat(getVal("cfg-max-trade"));
  const maxDaily = parseFloat(getVal("cfg-max-daily"));
  const minEdge = parseFloat(getVal("cfg-min-edge")) / 100;

  const body = {
    default_venue: venue,
    max_trade_usd: maxTrade,
    max_daily_usd: maxDaily,
    min_arb_edge: minEdge,
    automation_enabled: getChecked("toggle-automation"),
    strategy_arb: getChecked("toggle-arb"),
    strategy_mm: getChecked("toggle-mm"),
    strategy_ai: getChecked("toggle-ai"),
    strategy_correlation: getChecked("toggle-corr"),
  };

  showToast("Saving configuration...", "info");
  try {
    const updated = await api.updateConfig(body);
    state.config = updated;
    // We DON'T force state.venue = updated.default_venue here 
    // to allow user to keep viewing their current venue.
    renderConfig();
    showToast("⚙️ Config saved", "success");
    // Only reload venue data, don't reset everything
    await loadAll();
  } catch (err) {
    showToast("Config save failed", "error");
  }
}

// Toggle master automation on/off immediately
async function toggleAutomation() {
  const enabled = getChecked("toggle-automation");
  try {
    const updated = await api.updateConfig({ automation_enabled: enabled });
    state.config = updated;
    renderConfig();
    showToast(enabled ? "⚡ Automation STARTED" : "⏹ Automation STOPPED", enabled ? "success" : "info");
  } catch (err) {
    showToast("Failed to update automation state", "error");
    // Revert toggle on failure
    setChecked("toggle-automation", !enabled);
  }
}

// ── Manual Strategy Triggers ──────────────────────────────────────────────────
async function triggerCron(strategy) {
  const btnId = strategy === 'arb' ? 'btn-run-arb' : 'btn-run-mm';
  const btn = document.getElementById(btnId);
  const originalText = btn ? btn.textContent : 'RUN';

  if (btn) {
    btn.disabled = true;
    btn.textContent = 'RUNNING...';
  }

  showToast(`Running ${strategy.toUpperCase()} strategy...`, "info");

  try {
    const result = await api.triggerCron(strategy);
    if (result.skipped) {
      showToast(`Skipped: ${result.skipped}`, "warning");
    } else {
      showToast(`✅ ${strategy.toUpperCase()} execution complete`, "success");
      await loadAll();
    }
  } catch (err) {
    showToast(`❌ Strategy execution failed: ${err.message}`, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  }
}

// ── Log (paginated: 20 per page; shares & net_pnl from backend) ─────────────────
const TRADE_LOG_PAGE_SIZE = 20;

function renderTradeLog() {
  const tbody = document.getElementById("log-body");
  const paginationEl = document.getElementById("log-pagination");
  const pageInfoEl = document.getElementById("log-page-info");
  const prevBtn = document.getElementById("log-prev");
  const nextBtn = document.getElementById("log-next");
  if (!tbody) return;
  if (!state.tradeLog || !state.tradeLog.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="empty">${state.isLoading ? "Loading…" : "No trades this session"}</td></tr>`;
    if (paginationEl) paginationEl.style.display = "none";
    return;
  }
  const titleOrQuestion = (t) => (t.title != null && t.title !== "") ? t.title : (t.question != null ? t.question : "");
  tbody.innerHTML = state.tradeLog.map(t => {
    const titleStr = titleOrQuestion(t);
    const title = titleStr ? escapeHtml(String(titleStr).slice(0, 50)) + (titleStr.length > 50 ? "…" : "") : "—";
    const hasPnl = t.net_pnl != null && t.net_pnl !== "";
    const netPnl = hasPnl ? fmt$(Number(t.net_pnl)) : "—";
    const pnlClass = hasPnl ? (Number(t.net_pnl) >= 0 ? "positive" : "negative") : "";
    const sharesVal = t.shares != null && t.shares !== "" ? Number(t.shares) : null;
    const sharesStr = sharesVal != null ? sharesVal.toFixed(3) : "—";
    return `
    <tr>
      <td class="mono">${t.time || "—"}</td>
      <td class="mono" title="${escapeHtml(t.market_id || "")}">${(t.market_id || "???").slice(0, 10)}…</td>
      <td class="log-title-cell" title="${escapeHtml(titleStr)}">${title}</td>
      <td class="${(t.side || "").toLowerCase() === 'yes' ? 'pos' : 'neg'}">${(t.side || "—").toUpperCase()}</td>
      <td>${t.amount != null && t.amount !== "" ? fmt$(Number(t.amount)) : "—"}</td>
      <td class="mono">${sharesStr}</td>
      <td class="mono ${pnlClass}">${netPnl}</td>
    </tr>
  `;
  }).join("");

  if (paginationEl) paginationEl.style.display = "flex";
  const page = state.tradeLogPage ?? 0;
  const total = state.tradeLogTotal;
  const totalPages = total != null ? Math.max(1, Math.ceil(total / TRADE_LOG_PAGE_SIZE)) : null;
  if (pageInfoEl) {
    pageInfoEl.textContent = totalPages != null
      ? `Page ${page + 1} of ${totalPages} (${total} total)`
      : `Page ${page + 1}`;
  }
  if (prevBtn) {
    prevBtn.disabled = page <= 0;
  }
  if (nextBtn) {
    const hasMore = state.tradeLog.length >= TRADE_LOG_PAGE_SIZE;
    const noMoreByTotal = total != null && (page + 1) * TRADE_LOG_PAGE_SIZE >= total;
    nextBtn.disabled = !hasMore || noMoreByTotal;
  }
}

async function loadTradesPage(page) {
  const offset = page * TRADE_LOG_PAGE_SIZE;
  try {
    const t = await api.trades(state.venue, TRADE_LOG_PAGE_SIZE, offset);
    state.tradeLog = Array.isArray(t.trades) ? t.trades : [];
    state.tradeLogTotal = typeof t.total === "number" ? t.total : null;
    state.tradeLogPage = page;
    renderTradeLog();
  } catch (e) {
    console.error("Failed to load trade log page:", e);
    showToast("Failed to load trade log page", "error");
  }
}

// ── Bind events ───────────────────────────────────────────────────────────────
function bindEvents() {
  document.getElementById("arb-scan-btn")?.addEventListener("click", runArbScan);
  document.getElementById("save-config-btn")?.addEventListener("click", saveConfig);
  document.getElementById("refresh-btn")?.addEventListener("click", loadAll);

  document.getElementById("log-prev")?.addEventListener("click", () => {
    if (state.tradeLogPage > 0) loadTradesPage(state.tradeLogPage - 1);
  });
  document.getElementById("log-next")?.addEventListener("click", () => {
    loadTradesPage(state.tradeLogPage + 1);
  });

  document.addEventListener("click", (e) => {
    const tradeBtn = e.target.closest("[data-quick-trade]");
    if (tradeBtn) {
      const marketId = tradeBtn.getAttribute("data-market-id");
      const side = tradeBtn.getAttribute("data-side");
      if (marketId && (side === "yes" || side === "no")) quickTrade(marketId, side);
      return;
    }
    const tagBtn = e.target.closest("[data-tag-slug]");
    const clearBtn = e.target.closest("[data-clear-tag-filter]");
    if (tagBtn) {
      setMarketTagFilter(tagBtn.getAttribute("data-tag-slug"));
    } else if (clearBtn) {
      setMarketTagFilter(null);
    }
  });

  document.getElementById("venue-select")?.addEventListener("change", async (e) => {
    const newVenue = e.target.value;
    if (state.venue === newVenue) return;

    state.venue = newVenue;
    state.marketTagFilter = null;
    stopPolymarketProbSync();
    stopPolymarketMarketListSync();
    // Clear venue-scoped data so UI does not show previous venue's data
    state.markets = [];
    state.positions = [];
    state.tradeLog = [];
    state.tradeLogPage = 0;
    state.tradeLogTotal = null;
    state.arbOpps = [];
    state.portfolio = null;
    renderHeader();
    renderAll(); // Show loading/empty state immediately
    showToast(`Switching to ${VENUE_LABELS[newVenue] || newVenue}…`, "info");

    try {
      await api.updateConfig({ default_venue: state.venue });
      await loadAll(); // Re-pull markets, positions, trades, portfolio for new venue
    } catch (err) {
      console.warn("Failed to persist default venue change:", err);
      await loadAll();
    }
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setText(id, val) { const e = document.getElementById(id); if (e) e.textContent = val; }
function setVal(id, val) { const e = document.getElementById(id); if (e) e.value = val; }
/** Format resolves_at to date + time (ISO or YYYY-MM-DD from Gamma). */
function formatResolvesAt(iso) {
  if (!iso || typeof iso !== "string") return "—";
  const s = iso.trim();
  if (!s) return "—";
  // Gamma often returns date-only "YYYY-MM-DD"; parse as UTC noon so time shows consistently
  const isoWithTime = /^\d{4}-\d{2}-\d{2}$/.test(s) ? s + "T12:00:00Z" : s;
  const date = new Date(isoWithTime);
  if (Number.isNaN(date.getTime())) return s.slice(0, 16) || "—";
  try {
    return date.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
  } catch (_) {
    return date.toLocaleString();
  }
}
function setChecked(id, val) { const e = document.getElementById(id); if (e) e.checked = !!val; }
function getVal(id) { return document.getElementById(id)?.value; }
function getChecked(id) { return document.getElementById(id)?.checked; }
function fmt$(v) { return "$" + (parseFloat(v) || 0).toFixed(2); }

function setStatus(s) {
  const dot = document.getElementById("status-dot");
  const lbl = document.getElementById("status-label");
  if (!dot || !lbl) return;
  const map = {
    live: ["#00ff88", "LIVE"],
    loading: ["#f5a623", "SYNCING"],
    error: ["#ff4d4d", "OFFLINE"],
    halted: ["#ff4d4d", "HALTED"],
  };
  const [color, text] = map[s] || ["#888", s];
  dot.style.background = color;
  lbl.textContent = text;
}

function showToast(msg, type = "info") {
  const container = document.getElementById("toasts");
  if (!container) return;
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = msg;
  container.appendChild(el);
  setTimeout(() => el.classList.add("visible"), 10);
  setTimeout(() => {
    el.classList.remove("visible");
    setTimeout(() => el.remove(), 400);
  }, 3500);
}
