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

class NativePolymarketClient:
    """
    Wrapper for SimmerClient that intercepts trades and uses the native CLOB client.
    This ensures that even automated strategies use the native Polymarket integration.
    """
    def __init__(self, sdk_client):
        self._sdk = sdk_client
        
    def __getattr__(self, name):
        # Proxy all other calls (get_markets, etc) to the SDK client
        return getattr(self._sdk, name)
        
    def trade(self, market_id: str, side: str, amount: float, **kwargs):
        from core.polymarket_native import place_native_order
        from loguru import logger
        
        logger.info(f"Native automation trade: {side} {amount} on {market_id}")
        res = place_native_order(market_id, side, amount)
        
        # Convert native response to a format compatible with strategies
        from dataclasses import dataclass
        @dataclass
        class SimpleResult:
            success: bool
            trade_id: str
            market_id: str
            side: str
            shares_bought: float
            cost: float
            new_balance: float = 0.0
            
        return SimpleResult(
            success=res.get("success", False),
            trade_id=res.get("trade_id", ""),
            market_id=res.get("market_id", ""),
            side=res.get("side", ""),
            shares_bought=res.get("shares_bought", 0.0),
            cost=res.get("cost", 0.0)
        )

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
            
        sdk_client = SimmerClient(**kwargs)
        
        # If venue is polymarket, wrap the client to use our native trade logic
        if venue == "polymarket":
            _clients[venue] = NativePolymarketClient(sdk_client)
        else:
            _clients[venue] = sdk_client
        
    return _clients[venue]
