"""
core/client.py
Simmer SDK client factory — venue-aware, singleton per venue.
"""
import os
from simmer_sdk import SimmerClient

_clients: dict[str, SimmerClient] = {}

def get_client(venue: str | None = None) -> SimmerClient:
    venue = venue or os.environ.get("DEFAULT_VENUE", "simmer")
    if venue not in _clients:
        kwargs = dict(api_key=os.environ["SIMMER_API_KEY"], venue=venue)
        # Attach EVM private key for polymarket
        if venue == "polymarket" and os.environ.get("SIMMER_PRIVATE_KEY"):
            kwargs["private_key"] = os.environ["SIMMER_PRIVATE_KEY"]
        # Kalshi uses SIMMER_SOLANA_KEY env var automatically
        _clients[venue] = SimmerClient(**kwargs)
    return _clients[venue]
