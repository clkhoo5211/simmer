// js/config.js
// ─────────────────────────────────────────────────────────────────────────────
// UPDATE THIS URL after deploying your Vercel backend.
// Format: https://simmer-bot.vercel.app  (no trailing slash)
// ─────────────────────────────────────────────────────────────────────────────
const CONFIG = {
  API_BASE: "http://localhost:8000",   // Local backend (use https://simmer-backend.vercel.app for production)
  POLL_INTERVAL_MS: 15000,   // Refresh portfolio / positions every 15s
  MARKETS_LIMIT: 20,
  MARKETS_TIMEOUT_MS: 20000, // Stop waiting for markets after 20s (Gamma can be slow; avoids endless "Loading markets…")
  DEFAULT_TRADE_AMOUNT: 10,
  POSITIONS_TRADES_TIMEOUT_MS: 12000,  // Stop waiting for positions/trades after 12s (avoids endless "Loading…")
};
