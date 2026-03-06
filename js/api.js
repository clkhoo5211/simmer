// js/api.js  —  thin wrapper around all Vercel backend endpoints
const api = (() => {
  const base = () => CONFIG.API_BASE;
  const get = (path) => fetch(`${base()}${path}`).then(r => {
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  });
  const post = (path, body) =>
    fetch(`${base()}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    });

  return {
    health: () => get("/api/health"),
    portfolio: (venue = "") => get(`/api/portfolio?venue=${venue}`),
    markets: (venue = "") => get(`/api/markets?venue=${venue}&limit=${CONFIG.MARKETS_LIMIT}`),
    positions: (venue = "") => get(`/api/positions?venue=${venue}`),
    trades: (venue = "") => get(`/api/trades?venue=${venue}`),
    arbScan: (venue = "") => get(`/api/arb/scan?venue=${venue}`),
    priceHistory: (id, venue) => get(`/api/markets/${id}/history?venue=${venue}`),
    trade: (body) => post("/api/trade", body),
    getConfig: () => get("/api/config"),
    updateConfig: (body) => post("/api/config", body),
    getSettingsSchema: () => get("/api/settings/schema"),
    getCredentials: () => get("/api/credentials"),
    updateCredentials: (body) => post("/api/credentials", body),
    resetConfig: () => fetch(`${base()}/api/config`, { method: 'DELETE' }).then(r => r.json()),
  };
})();
