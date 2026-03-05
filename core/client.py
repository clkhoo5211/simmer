"""
core/client.py
Simmer SDK client factory — venue-aware, singleton per venue.

Environment variables read by the SDK automatically:
  SIMMER_API_KEY      — required for all venues
  WALLET_PRIVATE_KEY  — EVM private key for Polymarket (0x prefixed 64-char hex)
                        (legacy alias: SIMMER_PRIVATE_KEY — still works but deprecated)
  SOLANA_PRIVATE_KEY  — base58 secret key for Kalshi via DFlow
"""
import os
from simmer_sdk import SimmerClient

_clients: dict[str, SimmerClient] = {}

def get_client(venue: str | None = None) -> SimmerClient:
    venue = venue or os.environ.get("DEFAULT_VENUE", "simmer")
    if venue not in _clients:
        api_key = os.environ.get("SIMMER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "SIMMER_API_KEY environment variable is not set. "
                "Please add it in your Vercel project settings under Settings > Environment Variables."
            )
        kwargs = dict(api_key=api_key, venue=venue)
        # Explicitly pass Polymarket private key if provided
        # SDK also auto-detects WALLET_PRIVATE_KEY (or legacy SIMMER_PRIVATE_KEY) from env
        pk = os.environ.get("WALLET_PRIVATE_KEY") or os.environ.get("SIMMER_PRIVATE_KEY")
        if venue == "polymarket" and pk:
            kwargs["private_key"] = pk
        # Kalshi: SDK auto-reads SOLANA_PRIVATE_KEY from env — no explicit pass needed
        _clients[venue] = SimmerClient(**kwargs)
    return _clients[venue]
