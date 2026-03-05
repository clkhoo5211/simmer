// js/settings.js — Logic for the credentials settings page

document.addEventListener("DOMContentLoaded", async () => {
  await loadCredentials();
  document.getElementById("save-btn")?.addEventListener("click", saveCredentials);
});

async function loadCredentials() {
  const btn = document.getElementById("save-btn");
  if (btn) btn.textContent = "LOADING...";

  try {
    const creds = await api.getCredentials();

    // Fill placeholders with masked values
    if (creds.simmer_api_key) setPlaceholder("simmer_api_key", creds.simmer_api_key);
    if (creds.wallet_private_key) setPlaceholder("wallet_private_key", creds.wallet_private_key);
    if (creds.polymarket_api_key) setPlaceholder("polymarket_api_key", creds.polymarket_api_key);
    if (creds.polymarket_api_secret) setPlaceholder("polymarket_api_secret", creds.polymarket_api_secret);
    if (creds.polymarket_passphrase) setPlaceholder("polymarket_passphrase", creds.polymarket_passphrase);
    if (creds.polymarket_wallet_addr) setVal("polymarket_wallet_addr", creds.polymarket_wallet_addr);
    if (creds.solana_private_key) setPlaceholder("solana_private_key", creds.solana_private_key);

    // Update status badges
    updateStatus("status-simmer", creds.configured.simmer);
    updateStatus("status-polymarket", creds.configured.polymarket);
    updateStatus("status-kalshi", creds.configured.kalshi);

  } catch (err) {
    console.error(err);
    showToast("⚠️ Could not load credentials. Is backend running?", "error");
  } finally {
    if (btn) btn.textContent = "SAVE CREDENTIALS";
  }
}

async function saveCredentials() {
  const btn = document.getElementById("save-btn");
  if (btn) btn.textContent = "SAVING...";

  // Only send fields that the user actually typed something into
  const body = {};
  const fields = [
    "simmer_api_key", "wallet_private_key", "polymarket_api_key",
    "polymarket_api_secret", "polymarket_passphrase", "polymarket_wallet_addr", "solana_private_key"
  ];

  for (const f of fields) {
    const val = getVal(f).trim();
    if (val) body[f] = val;
  }

  if (Object.keys(body).length === 0) {
    showToast("No new credentials to save", "info");
    if (btn) btn.textContent = "SAVE CREDENTIALS";
    return;
  }

  try {
    const result = await api.updateCredentials(body);
    if (result.ok) {
      showToast("✅ Credentials saved securely to Redis", "success");
      // Clear inputs since they are now saved
      fields.forEach(f => {
        const el = document.getElementById(f);
        if (el) el.value = "";
      });
      // Reload to show new masked placeholders and statuses
      await loadCredentials();
    }
  } catch (err) {
    console.error(err);
    showToast("❌ Failed to save credentials", "error");
  } finally {
    if (btn) btn.textContent = "SAVE CREDENTIALS";
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function setPlaceholder(id, val) {
  const e = document.getElementById(id);
  if (e) e.placeholder = "Set via Vercel env or Redis: " + val;
}
function setVal(id, val) {
  const e = document.getElementById(id);
  if (e) e.value = val;
}
function getVal(id) {
  return document.getElementById(id)?.value || "";
}

function updateStatus(id, isConfigured) {
  const badge = document.getElementById(id);
  if (!badge) return;
  if (isConfigured) {
    badge.className = "status-badge configured";
    badge.textContent = "Configured";
  } else {
    badge.className = "status-badge missing";
    badge.textContent = "Missing";
  }
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
