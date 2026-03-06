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
        "title": "POLYMARKET (Real USDC)",
        "fields": [
            {
                "id": "polymarket_funder_addr",
                "label": "Polymarket Funder Address (Optional)",
                "type": "text",
                "placeholder": "EOA Address if using MetaMask/Gnosis",
                "env": "POLY_FUNDER_ADDRESS"
            },
            {
                "id": "wallet_private_key",
                "label": "Wallet Private Key (EVM)",
                "type": "password",
                "placeholder": "0x...",
                "env": "WALLET_PRIVATE_KEY",
                "secret": True
            },
            {
                "id": "polymarket_sig_type",
                "label": "Signature Type",
                "type": "select",
                "options": [
                    {"label": "2 — GNOSIS_SAFE (MetaMask / Browser Wallets)", "value": "2"},
                    {"label": "0 — EOA (Direct wallet, pay gas in POL)", "value": "0"},
                    {"label": "1 — POLY_PROXY (Magic Link / Email Account)", "value": "1"}
                ],
                "default": "2",
                "description": "Choose 2 if using MetaMask. Choose 1 if using an email login key."
            },
            {
                "id": "polymarket_api_key",
                "label": "Polymarket CLOB API Key",
                "type": "password",
                "placeholder": "...",
                "secret": True
            },
            {
                "id": "polymarket_api_secret",
                "label": "Polymarket CLOB Secret",
                "type": "password",
                "placeholder": "...",
                "secret": True
            },
            {
                "id": "polymarket_passphrase",
                "label": "Polymarket CLOB Passphrase",
                "type": "password",
                "placeholder": "...",
                "secret": True
            },
            {
                "id": "polymarket_wallet_addr",
                "label": "Wallet Address (Public)",
                "type": "text",
                "placeholder": "0x...",
                "secret": False
            }
        ]
    },
    {
        "id": "kalshi",
        "title": "KALSHI (Real USD via USDC on Solana)",
        "fields": [
            {
                "id": "solana_private_key",
                "label": "Solana Private Key (Base58)",
                "type": "password",
                "placeholder": "...",
                "env": "SOLANA_PRIVATE_KEY",
                "secret": True
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
