// js/settings.js — Dynamic settings logic
// ─────────────────────────────────────────────────────────────────────────────
// Now centralized: fetches definitions from /api/settings/schema

let currentSchema = [];

document.addEventListener("DOMContentLoaded", async () => {
  await initSettings();
  document.getElementById("save-btn")?.addEventListener("click", saveCredentials);
  document.getElementById("reset-btn")?.addEventListener("click", resetConfigSettings);
});

async function initSettings() {
  const container = document.getElementById("settings-container");
  const btn = document.getElementById("save-btn");

  if (btn) btn.textContent = "LOADING SCHEMA...";

  try {
    // 1. Fetch schema and current creds in parallel
    const [schema, creds] = await Promise.all([
      api.getSettingsSchema(),
      api.getCredentials()
    ]);
    currentSchema = schema;

    // 2. Build HTML dynamically
    let html = "";
    for (const category of schema) {
      const isConfigured = creds.configured?.[category.id];
      const badgeClass = isConfigured ? "configured" : "missing";
      const badgeText = isConfigured ? "Configured" : "Missing";

      html += `
        <div class="card">
          <div class="card-header">
            <div class="card-title">${category.title}</div>
            <div class="status-badge ${badgeClass}" id="status-${category.id}">${badgeText}</div>
          </div>
          <div class="card-body">
      `;

      for (const field of category.fields) {
        const val = creds[field.id];
        // If it's a secret and we have a masked value, use it as placeholder
        const placeholder = field.secret && val ? val : (field.placeholder || "");

        html += `
          <div class="control-group">
            <label>${field.label}</label>
        `;

        if (field.type === "select") {
          html += `
            <select id="${field.id}" style="background: var(--bg); border: 1px solid var(--border2); color: var(--text); padding: 10px 12px; border-radius: var(--radius); font-family: var(--mono); font-size: 0.85rem; outline: none;">
              ${field.options.map(o => `<option value="${o.value}" ${val == o.value ? 'selected' : ''}>${o.label}</option>`).join('')}
            </select>
          `;
        } else {
          // Password fields are always empty on load (showing mask in placeholder)
          // Text fields show the raw value if not secret
          const displayVal = (!field.secret && val) ? val : "";
          html += `
            <input type="${field.type}" id="${field.id}" placeholder="${placeholder}" autocomplete="off" value="${displayVal}">
          `;
        }

        if (field.description) {
          html += `<p style="font-size: 0.7rem; color: var(--muted); margin-top: 4px;">${field.description}</p>`;
        }

        html += `</div>`;
      }

      html += `</div></div>`;
    }

    container.innerHTML = html;

  } catch (err) {
    console.error(err);
    container.innerHTML = `<div style="color: var(--danger); padding: 40px; text-align: center;">⚠️ FAILED TO LOAD SECURE SCHEMA</div>`;
  } finally {
    if (btn) btn.textContent = "SAVE CREDENTIALS";
  }
}

async function saveCredentials() {
  const btn = document.getElementById("save-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = "SAVING...";
  }

  const body = {};

  // Iterate through all categories and fields in the dynamic schema
  for (const cat of currentSchema) {
    for (const field of cat.fields) {
      const el = document.getElementById(field.id);
      if (!el) continue;

      const val = el.value.trim();
      // Only send if user typed something (avoid sending masks back)
      if (val) {
        body[field.id] = val;
      }
    }
  }

  if (Object.keys(body).length === 0) {
    showToast("No new credentials to save", "info");
    if (btn) {
      btn.disabled = false;
      btn.textContent = "SAVE CREDENTIALS";
    }
    return;
  }

  try {
    const result = await api.updateCredentials(body);
    if (result.ok) {
      showToast("✅ Settings saved to Redis", "success");
      // Reload to show new masked placeholders and statuses
      await initSettings();
    } else {
      showToast("❌ Server rejected update", "error");
    }
  } catch (err) {
    console.error(err);
    showToast("❌ Failed to contact backend", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "SAVE CREDENTIALS";
    }
  }
}

let resetConfirmTimer = null;

async function resetConfigSettings(e) {
  const btn = document.getElementById("reset-btn");
  if (!btn) return;

  if (btn.textContent !== "CLICK AGAIN TO CONFIRM") {
    btn.textContent = "CLICK AGAIN TO CONFIRM";
    btn.style.background = "var(--danger)";
    btn.style.color = "var(--bg)";

    clearTimeout(resetConfirmTimer);
    resetConfirmTimer = setTimeout(() => {
      btn.textContent = "RESET SETTINGS";
      btn.style.background = "rgba(244, 63, 94, 0.1)";
      btn.style.color = "var(--danger)";
    }, 3000);
    return;
  }

  clearTimeout(resetConfirmTimer);
  btn.disabled = true;
  btn.textContent = "RESETTING...";

  try {
    await api.resetConfig();
    showToast("✅ Settings reset successfully", "success");
    // Reload to clear inputs
    setTimeout(() => window.location.href = "index.html", 1500);
  } catch (err) {
    console.error(err);
    showToast("❌ Failed to reset settings", "error");
    if (btn) {
      btn.disabled = false;
      btn.textContent = "RESET SETTINGS";
    }
  }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

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
