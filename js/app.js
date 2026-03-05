// js/app.js  —  dashboard logic: polling, rendering, interactions

// ── State ─────────────────────────────────────────────────────────────────────
let state = {
  portfolio:  null,
  markets:    [],
  positions:  [],
  arbOpps:    [],
  config:     {},
  venue:      "simmer",
  tradeLog:   [],
  pollTimer:  null,
};

// ── Bootstrap ─────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await loadAll();
  startPolling();
  bindEvents();
});

async function loadAll() {
  setStatus("loading");
  try {
    const [health, portfolio, markets, positions, config] = await Promise.all([
      api.health(),
      api.portfolio(),
      api.markets(state.venue),
      api.positions(state.venue),
      api.getConfig(),
    ]);

    state.portfolio = portfolio;
    state.markets   = markets;
    state.positions = positions;
    state.config    = config;
    state.venue     = config.default_venue || "simmer";

    renderAll();
    setStatus(health.stop_loss ? "halted" : "live");
  } catch (err) {
    setStatus("error");
    console.error(err);
    showToast("⚠️ Cannot reach API — check your config.js URL", "error");
  }
}

function startPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(loadAll, CONFIG.POLL_INTERVAL_MS);
}

// ── Render ────────────────────────────────────────────────────────────────────
function renderAll() {
  renderHeader();
  renderPortfolio();
  renderMarkets();
  renderPositions();
  renderConfig();
}

function renderHeader() {
  const el = document.getElementById("venue-badge");
  if (el) el.textContent = state.venue.toUpperCase();
}

function renderPortfolio() {
  const p = state.portfolio;
  if (!p) return;
  setText("balance",    fmt$(p.balance_usdc));
  setText("total-pnl",  fmt$(p.total_pnl));
  setText("exposure",   fmt$(p.total_exposure));
  setText("daily-used", fmt$(p.daily_spent) + " / " + fmt$(p.daily_limit));

  const pnlEl = document.getElementById("total-pnl");
  if (pnlEl) {
    pnlEl.classList.toggle("positive", p.total_pnl >= 0);
    pnlEl.classList.toggle("negative", p.total_pnl < 0);
  }
}

function renderMarkets() {
  const tbody = document.getElementById("markets-body");
  if (!tbody) return;
  tbody.innerHTML = state.markets.map(m => `
    <tr class="market-row" data-id="${m.id}">
      <td class="q-cell" title="${m.question}">${m.question.slice(0,58)}${m.question.length>58?"…":""}</td>
      <td>
        <div class="prob-bar-wrap">
          <div class="prob-bar" style="width:${(m.current_probability*100).toFixed(1)}%"></div>
          <span class="prob-label">${(m.current_probability*100).toFixed(1)}%</span>
        </div>
      </td>
      <td class="${m.divergence > 0 ? 'pos' : m.divergence < 0 ? 'neg' : ''}">${m.divergence != null ? (m.divergence*100).toFixed(2)+"%" : "—"}</td>
      <td>${m.resolves_at ? m.resolves_at.slice(0,10) : "—"}</td>
      <td>
        <div class="trade-btns">
          <button class="btn-yes" onclick="quickTrade('${m.id}','yes')">YES</button>
          <button class="btn-no"  onclick="quickTrade('${m.id}','no')">NO</button>
        </div>
      </td>
    </tr>
  `).join("");
}

function renderPositions() {
  const tbody = document.getElementById("positions-body");
  if (!tbody) return;
  if (!state.positions.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">No open positions</td></tr>`;
    return;
  }
  tbody.innerHTML = state.positions.map(p => `
    <tr>
      <td title="${p.question}">${p.question.slice(0,50)}${p.question.length>50?"…":""}</td>
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

  setChecked("toggle-arb",  c.strategy_arb);
  setChecked("toggle-mm",   c.strategy_mm);
  setChecked("toggle-ai",   c.strategy_ai);
  setChecked("toggle-corr", c.strategy_correlation);

  setVal("cfg-venue",     c.default_venue   || "simmer");
  setVal("cfg-max-trade", c.max_trade_usd   || 25);
  setVal("cfg-max-daily", c.max_daily_usd   || 200);
  setVal("cfg-min-edge",  (c.min_arb_edge * 100).toFixed(1) || 1.5);
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
    logTrade(marketId, side, amount, result);
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
      <p class="arb-q">${o.question.slice(0,60)}</p>
      <div class="arb-meta">
        <span>YES ${(o.yes_price*100).toFixed(1)}¢</span>
        <span>NO ${(o.no_price*100).toFixed(1)}¢</span>
        <span class="arb-edge">Edge: <b>${o.edge_pct}%</b></span>
      </div>
    </div>
  `).join("");
}

async function saveConfig() {
  const venue    = getVal("cfg-venue");
  const maxTrade = parseFloat(getVal("cfg-max-trade"));
  const maxDaily = parseFloat(getVal("cfg-max-daily"));
  const minEdge  = parseFloat(getVal("cfg-min-edge")) / 100;

  const body = {
    default_venue:        venue,
    max_trade_usd:        maxTrade,
    max_daily_usd:        maxDaily,
    min_arb_edge:         minEdge,
    strategy_arb:         getChecked("toggle-arb"),
    strategy_mm:          getChecked("toggle-mm"),
    strategy_ai:          getChecked("toggle-ai"),
    strategy_correlation: getChecked("toggle-corr"),
  };

  try {
    const updated = await api.updateConfig(body);
    state.config  = updated;
    state.venue   = updated.default_venue;
    showToast("⚙️ Config saved", "success");
    await loadAll();
  } catch (err) {
    showToast("Config save failed", "error");
  }
}

// ── Log ───────────────────────────────────────────────────────────────────────
function logTrade(marketId, side, amount, result) {
  state.tradeLog.unshift({
    time:   new Date().toLocaleTimeString(),
    market: marketId.slice(0, 10) + "…",
    side,
    amount,
    shares: result.shares_bought,
    cost:   result.cost,
  });
  state.tradeLog = state.tradeLog.slice(0, 30);   // Keep last 30

  const tbody = document.getElementById("log-body");
  if (!tbody) return;
  tbody.innerHTML = state.tradeLog.map(t => `
    <tr>
      <td class="mono">${t.time}</td>
      <td class="mono">${t.market}</td>
      <td class="${t.side === 'yes' ? 'pos' : 'neg'}">${t.side.toUpperCase()}</td>
      <td>${fmt$(t.amount)}</td>
      <td class="mono">${(t.shares||0).toFixed(3)}</td>
    </tr>
  `).join("");
}

// ── Bind events ───────────────────────────────────────────────────────────────
function bindEvents() {
  document.getElementById("arb-scan-btn")?.addEventListener("click", runArbScan);
  document.getElementById("save-config-btn")?.addEventListener("click", saveConfig);
  document.getElementById("refresh-btn")?.addEventListener("click", loadAll);

  document.getElementById("venue-select")?.addEventListener("change", async (e) => {
    state.venue = e.target.value;
    await api.updateConfig({ default_venue: state.venue });
    await loadAll();
  });
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setText(id, val)        { const e = document.getElementById(id); if (e) e.textContent = val; }
function setVal(id, val)         { const e = document.getElementById(id); if (e) e.value = val; }
function setChecked(id, val)     { const e = document.getElementById(id); if (e) e.checked = !!val; }
function getVal(id)              { return document.getElementById(id)?.value; }
function getChecked(id)          { return document.getElementById(id)?.checked; }
function fmt$(v)                 { return "$" + (parseFloat(v)||0).toFixed(2); }

function setStatus(s) {
  const dot = document.getElementById("status-dot");
  const lbl = document.getElementById("status-label");
  if (!dot || !lbl) return;
  const map = {
    live:    ["#00ff88", "LIVE"],
    loading: ["#f5a623", "SYNCING"],
    error:   ["#ff4d4d", "OFFLINE"],
    halted:  ["#ff4d4d", "HALTED"],
  };
  const [color, text] = map[s] || ["#888", s];
  dot.style.background = color;
  lbl.textContent      = text;
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
