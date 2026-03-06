import os
import requests
from py_clob_client.client import ClobClient
from core.store import load_credentials
from loguru import logger

_clob_client = None

def get_native_clob_client() -> ClobClient:
    global _clob_client
    if _clob_client is None:
        creds_data = load_credentials()
        
        pkey = creds_data.get("wallet_private_key") or os.environ.get("WALLET_PRIVATE_KEY") or os.environ.get("SIMMER_PRIVATE_KEY")
        if not pkey:
            raise ValueError("Missing WALLET_PRIVATE_KEY for Polymarket native client")

        funder = creds_data.get("polymarket_funder_addr")
        sig_type = int(creds_data.get("polymarket_sig_type", 2))

        # We initialize the client without credentials first
        # Then use create_or_derive_api_creds to get the linked set from Polymarket.
        # This resolves 401 Unauthorized issues seen with manual API Key entry.
        _clob_client = ClobClient(
            host="https://clob.polymarket.com",
            key=pkey,
            chain_id=137,
            signature_type=sig_type,
            funder=funder
        )
        
        try:
            logger.info("Auto-deriving Polymarket API credentials...")
            _clob_client.set_api_creds(_clob_client.create_or_derive_api_creds())
            logger.info("Polymarket credentials linked successfully")
        except Exception as e:
            logger.error(f"Failed to derive Polymarket credentials: {e}")
            # If derivation fails, we try to fall back to provided creds if they exist
            if creds_data.get("polymarket_api_key"):
                from py_clob_client.clob_types import ApiCreds
                api_creds = ApiCreds(
                    api_key=creds_data.get("polymarket_api_key", ""),
                    api_secret=creds_data.get("polymarket_api_secret", ""),
                    api_passphrase=creds_data.get("polymarket_passphrase", "")
                )
                _clob_client.set_api_creds(api_creds)
                logger.info("Falling back to manual API credentials")
            else:
                raise ValueError(f"Could not authenticate with Polymarket: {e}")
                
    return _clob_client

def get_native_portfolio() -> dict:
    """Fetch native portfolio via Polymarket Gamma API and CLOB."""
    creds = load_credentials()
    wallet_address = creds.get("polymarket_wallet_addr")
    
    if not wallet_address:
        raise ValueError("Missing polymarket_wallet_addr in credentials")
        
    client = get_native_clob_client()
    
    # 1. Fetch active positions from Gamma
    gamma_url = f"https://gamma-api.polymarket.com/users/{wallet_address}/positions"
    active_positions = []
    total_exposure = 0.0
    
    try:
        resp = requests.get(gamma_url, timeout=10)
        resp.raise_for_status()
        positions_data = resp.json()
        
        # Gamma API returns a list of positions
        for p in positions_data:
            # Polymarket represents shares as decimals (e.g., 1000000 = 1 share depending on condition)
            size = float(p.get("size", 0))
            if size > 0:
                price = getattr(p, "currentPrice", 0)  # Gamma might return different structure
                current_value = size * price if price else 0
                total_exposure += current_value
                active_positions.append(p)
    except Exception as e:
        logger.warning(f"Gamma API failed: {e}")
        # Soft fail, continue to return what we can
    
    return {
        "balance_usdc": 0.0, 
        "total_exposure": total_exposure,
        "total_pnl": 0.0, 
        "daily_spent": 0.0,
        "by_source": {},
        "positions": active_positions,
        "source": "native"
    }

def get_native_markets(status: str = "active", limit: int = 25) -> list:
    """Fetch native markets via Polymarket Gamma API."""
    closed_str = "false" if status == "active" else "true"
    gamma_url = f"https://gamma-api.polymarket.com/events?closed={closed_str}&limit={limit}"
    
    results = []
    try:
        resp = requests.get(gamma_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        for e in data:
            for m in e.get("markets", []):
                try:
                    outcome_prices = json.loads(m.get("outcomePrices", '["0","0"]'))
                    prob = float(outcome_prices[0])
                except Exception:
                    prob = 0.5
                    
                results.append({
                    "id": m.get("conditionId", m.get("id", "")),
                    "question": m.get("question", ""),
                    "status": "active" if m.get("active") else "closed",
                    "current_probability": prob,
                    "divergence": None,
                    "resolves_at": m.get("endDate"),
                    "import_source": "polymarket"
                })
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
        return results
    except Exception as e:
        logger.warning(f"Native Polymarket get_markets failed: {e}")
        raise

def get_native_positions() -> list:
    """Fetch structured positions dynamically based on Polymarket Data API."""
    creds = load_credentials()
    wallet_address = creds.get("polymarket_wallet_addr")
    
    if not wallet_address:
        raise ValueError("Missing polymarket_wallet_addr")

    # The Data API is more reliable for user-specific position summaries
    data_url = f"https://data-api.polymarket.com/positions?user={wallet_address}&limit=500"
    try:
        resp = requests.get(data_url, timeout=10)
        resp.raise_for_status()
        positions_data = resp.json()
        
        parsed = []
        for p in positions_data:
            size = float(p.get("size", 0))
            if size > 0:
                parsed.append({
                    "market_id": p.get("conditionId", "unknown"),
                    "question": p.get("title", "Unknown Market"),
                    "shares_yes": size if p.get("outcome", "") == "Yes" else 0,
                    "shares_no": size if p.get("outcome", "") == "No" else 0,
                    "current_value": size * float(p.get("avgPrice", 0)),
                    "pnl": float(p.get("realizedPnl", 0)),
                    "status": "open"
                })
        return parsed
    except Exception as e:
        logger.warning(f"Native Polymarket get_positions failed: {e}")
        raise

def get_native_closed_positions() -> list:
    """Fetch closed positions from Data API."""
    creds = load_credentials()
    wallet_address = creds.get("polymarket_wallet_addr")
    
    if not wallet_address:
        raise ValueError("Missing polymarket_wallet_addr")

    data_url = f"https://data-api.polymarket.com/closed-positions?user={wallet_address}&limit=500"
    try:
        resp = requests.get(data_url, timeout=10)
        resp.raise_for_status()
        closed_data = resp.json()
        
        parsed = []
        for cp in closed_data:
            parsed.append({
                "market_id": cp.get("conditionId", "unknown"),
                "question": cp.get("title", "Unknown Market"),
                "pnl": float(cp.get("realizedPnl", 0)),
                "status": "closed"
            })
        return parsed
    except Exception as e:
        logger.warning(f"Native Polymarket get_closed_positions failed: {e}")
        raise
def place_native_order(market_id: str, side: str, amount: float) -> dict:
    """Place a native order on Polymarket CLOB."""
    client = get_native_clob_client()
    
    try:
        from py_clob_client.clob_types import OrderArgs
        
        # 1. Resolve condition ID to token ID if necessary
        # Simmer uses condition IDs. CLOB uses token IDs.
        token_id = market_id
        if market_id.startswith("0x"):
            logger.info(f"Resolving condition ID {market_id} to token ID...")
            try:
                # Gamma API can help us get the market details
                resp = requests.get(f"https://gamma-api.polymarket.com/markets/{market_id}", timeout=5)
                if resp.ok:
                    m_data = resp.json()
                    # Simmer: 'yes' -> Token 0, 'no' -> Token 1 (usually)
                    clob_tokens = m_data.get("clobTokenIds")
                    if clob_tokens:
                        # Map yes/no to the correct token
                        token_id = clob_tokens[0] if side.lower() == "yes" else clob_tokens[1]
                        logger.info(f"Resolved to token ID: {token_id}")
            except Exception as e:
                logger.warning(f"Failed to resolve token ID via Gamma: {e}")

        logger.info(f"Attempting native Polymarket CLOB order: {side} {amount} on {token_id}")
        
        # Determine price (use a default or fetch mid)
        # For a manual trade, we might want to fetch the orderbook first
        # But for this verification tool, we'll try a price that's likely to trigger balance checks
        price = 0.50 # Default to 0.50 for testing
        size = amount / price
        
        order_args = OrderArgs(
            token_id=token_id,
            price=price,
            size=size,
            side="BUY" # Simmer manual trade is always a BUY of the outcome
        )
        
        order = client.create_order(order_args)
        resp = client.post_order(order)
        
        return {
            "success": resp.get("success", False),
            "trade_id": resp.get("orderID"),
            "market_id": market_id,
            "side": side,
            "shares_bought": 0,
            "cost": amount,
            "order_status": "placed",
            "source": "native_clob",
            "raw": resp
        }
    except Exception as e:
        logger.error(f"Native Polymarket trade failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "source": "native_clob"
        }
