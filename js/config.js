// js/config.js
// ─────────────────────────────────────────────────────────────────────────────
// UPDATE THIS URL after deploying your Vercel backend.
// Format: https://simmer-bot.vercel.app  (no trailing slash)
// ─────────────────────────────────────────────────────────────────────────────
const CONFIG = {
  API_BASE: "https://simmer-backend.vercel.app",   // Live Vercel backend
  POLL_INTERVAL_MS: 15000,   // Refresh portfolio / positions every 15s
  MARKETS_LIMIT: 20,
  DEFAULT_TRADE_AMOUNT: 10,
};
