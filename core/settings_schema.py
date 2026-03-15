"""
core/settings_schema.py
─────────────────────────────────────────────────────────────────────────────
Centralized definition of all backend settings. This schema is consumed by
the frontend to dynamically render the API Keys / Settings page.
"""

SETTINGS_SCHEMA = [
    {
        "id": "simmer",
        "title": "SIMMER (Paper Trading)",
        "fields": [
            {
                "id": "simmer_api_key",
                "label": "Simmer API Key",
                "type": "password",
                "placeholder": "sk_live_...",
                "env": "SIMMER_API_KEY",
                "secret": True
            }
        ]
    },
    {
        "id": "polymarket",
        "title": "POLYMARKET (Live & Paper)",
        "description": "Per [Polymarket API](https://docs.polymarket.com/api-reference/introduction): Gamma (markets), Data (positions), CLOB (trading). L2 trading needs API Key, Secret, Passphrase.",
        "fields": [
            {
                "id": "wallet_private_key",
                "label": "Wallet Private Key (EVM)",
                "type": "password",
                "placeholder": "0x...",
                "env": "WALLET_PRIVATE_KEY",
                "secret": True,
                "description": "Required for L1 auth and deriving L2 API credentials."
            },
            {
                "id": "polymarket_api_key",
                "label": "Polymarket CLOB API Key (L2)",
                "type": "password",
                "placeholder": "From create/derive API key",
                "env": "POLYMARKET_API_KEY",
                "secret": True
            },
            {
                "id": "polymarket_api_secret",
                "label": "Polymarket CLOB Secret (L2)",
                "type": "password",
                "placeholder": "Base64 secret",
                "env": "POLYMARKET_API_SECRET",
                "secret": True
            },
            {
                "id": "polymarket_passphrase",
                "label": "Polymarket CLOB Passphrase (L2)",
                "type": "password",
                "placeholder": "Passphrase from API credentials",
                "env": "POLYMARKET_PASSPHRASE",
                "secret": True
            },
            {
                "id": "polymarket_sig_type",
                "label": "Signature Type",
                "type": "select",
                "options": [
                    {"label": "2 — GNOSIS_SAFE (MetaMask / Browser)", "value": "2"},
                    {"label": "0 — EOA (Direct wallet, pay gas in POL)", "value": "0"},
                    {"label": "1 — POLY_PROXY (Magic Link / Email)", "value": "1"}
                ],
                "default": "2",
                "env": "POLYMARKET_SIGNATURE_TYPE",
                "description": "2 = MetaMask/Gnosis Safe. 1 = email login key."
            },
            {
                "id": "polymarket_funder_addr",
                "label": "Funder Address (Proxy/Safe)",
                "type": "text",
                "placeholder": "From polymarket.com/settings",
                "env": "POLY_FUNDER_ADDRESS",
                "description": "Wallet shown on Polymarket; required for GNOSIS_SAFE."
            },
            {
                "id": "polymarket_wallet_addr",
                "label": "Wallet Address (Public)",
                "type": "text",
                "placeholder": "0x...",
                "env": "POLYMARKET_WALLET_ADDRESS",
                "secret": False,
                "description": "Used for positions/portfolio (Data API)."
            }
        ]
    },
    {
        "id": "telegram",
        "title": "TELEGRAM NOTIFICATIONS",
        "fields": [
            {
                "id": "telegram_bot_token",
                "label": "Bot Token",
                "type": "password",
                "placeholder": "123456:ABC-DEF...",
                "env": "TELEGRAM_BOT_TOKEN",
                "secret": True
            },
            {
                "id": "telegram_chat_id",
                "label": "Chat ID",
                "type": "text",
                "placeholder": "-123456789",
                "env": "TELEGRAM_CHAT_ID"
            }
        ]
    }
]
