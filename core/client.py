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
from core.store import load_credentials

_clients: dict[str, SimmerClient] = {}

def get_client(venue: str | None = None) -> SimmerClient:
    venue = venue or os.environ.get("DEFAULT_VENUE", "simmer")
    
    if venue not in _clients:
        # Load credentials from Redis and inject into os.environ 
        # so the SDK can auto-detect them seamlessly.
        creds = load_credentials()
        
        # Overlay Redis creds into os.environ if present, for SDK auto-detection
        if creds.get("simmer_api_key"): 
            os.environ["SIMMER_API_KEY"] = creds["simmer_api_key"]
        if creds.get("wallet_private_key"): 
            os.environ["WALLET_PRIVATE_KEY"] = creds["wallet_private_key"]
        if creds.get("solana_private_key"): 
            os.environ["SOLANA_PRIVATE_KEY"] = creds["solana_private_key"]
            
        api_key = os.environ.get("SIMMER_API_KEY")
        if not api_key:
            raise RuntimeError(
                "SIMMER_API_KEY missing. Please add it via the Dashboard API KEYS page "
                "or in Vercel Environment Variables."
            )
            
        kwargs = dict(api_key=api_key, venue=venue)
        
        # Explicitly pass Polymarket private key if the SDK needs it passed directly
        pk = os.environ.get("WALLET_PRIVATE_KEY") or os.environ.get("SIMMER_PRIVATE_KEY")
        if venue == "polymarket" and pk:
            kwargs["private_key"] = pk
            
        _clients[venue] = SimmerClient(**kwargs)
        
    return _clients[venue]
