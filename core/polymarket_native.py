import os
import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
from core.store import load_credentials
from loguru import logger

# USDC has 6 decimals on Polygon
USDC_DECIMALS = 6

_clob_client = None

def _creds_with_env() -> dict:
    """Merge Redis credentials with env vars (env wins for Polymarket CLOB fields)."""
    creds = load_credentials()
    env_map = {
        "wallet_private_key": os.environ.get("WALLET_PRIVATE_KEY") or os.environ.get("SIMMER_PRIVATE_KEY"),
        "polymarket_api_key": os.environ.get("POLYMARKET_API_KEY"),
        "polymarket_api_secret": os.environ.get("POLYMARKET_API_SECRET"),
        "polymarket_passphrase": os.environ.get("POLYMARKET_PASSPHRASE"),
        "polymarket_sig_type": os.environ.get("POLYMARKET_SIGNATURE_TYPE"),
        "polymarket_funder_addr": os.environ.get("POLY_FUNDER_ADDRESS"),
        "polymarket_wallet_addr": os.environ.get("POLYMARKET_WALLET_ADDRESS"),
    }
    for k, v in env_map.items():
        if v is not None:
            creds[k] = v
    return creds


def get_native_clob_client() -> ClobClient:
    global _clob_client
    if _clob_client is None:
        creds_data = _creds_with_env()
        
        pkey = creds_data.get("wallet_private_key")
        if not pkey:
            raise ValueError("Missing WALLET_PRIVATE_KEY for Polymarket native client")

        funder = creds_data.get("polymarket_funder_addr")
        raw_sig = creds_data.get("polymarket_sig_type", "2")
        sig_type = int(raw_sig) if raw_sig is not None else 2

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
    """Fetch native portfolio via Polymarket CLOB (balance) and Data API (exposure, PnL)."""
    creds = _creds_with_env()
    wallet_address = creds.get("polymarket_wallet_addr")

    if not wallet_address:
        raise ValueError("Missing polymarket_wallet_addr in credentials")

    client = get_native_clob_client()
    balance_usdc = 0.0
    total_exposure = 0.0
    total_pnl = 0.0

    # 1. Fetch USDC balance from CLOB (requires L2 auth)
    try:
        params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        result = client.get_balance_allowance(params)
        raw = result.get("balance") or result.get("balanceAllowance") or 0
        if isinstance(raw, str):
            raw = int(raw, 10) if raw.isdigit() else 0
        balance_usdc = float(int(raw) / (10 ** USDC_DECIMALS))
    except Exception as e:
        logger.warning(f"CLOB balance fetch failed: {e}")

    # 2. Data API positions: exposure, unrealized PnL, and position list
    active_positions = []
    try:
        pos_url = f"https://data-api.polymarket.com/positions?user={wallet_address}&limit=500"
        r = requests.get(pos_url, timeout=10)
        r.raise_for_status()
        positions_data = r.json()
        for p in positions_data:
            size = float(p.get("size", 0))
            if size <= 0:
                continue
            cash_pnl = p.get("cashPnl")
            if cash_pnl is not None:
                total_pnl += float(cash_pnl)
            else:
                cur_price = float(p.get("curPrice") or p.get("currentPrice") or 0)
                avg_price = float(p.get("avgPrice") or 0)
                if cur_price and avg_price:
                    total_pnl += (cur_price - avg_price) * size
            current_value = p.get("currentValue")
            if current_value is not None:
                total_exposure += float(current_value)
            else:
                cur_price = float(p.get("curPrice") or p.get("currentPrice") or 0)
                if cur_price:
                    total_exposure += cur_price * size
            active_positions.append(p)
    except Exception as e:
        logger.warning(f"Data API positions for portfolio failed: {e}")

    # 3. If exposure still 0, try Data API GET /value?user=...
    if total_exposure == 0.0 and active_positions:
        try:
            value_url = f"https://data-api.polymarket.com/value?user={wallet_address}"
            r = requests.get(value_url, timeout=10)
            r.raise_for_status()
            value_data = r.json()
            if isinstance(value_data, list) and len(value_data) > 0 and "value" in value_data[0]:
                total_exposure = float(value_data[0].get("value", 0) or 0)
            elif isinstance(value_data, dict) and "value" in value_data:
                total_exposure = float(value_data.get("value", 0) or 0)
        except Exception as e:
            logger.warning(f"Data API value failed: {e}")

    # 4. Daily used: sum of (size * price) for all trades today (UTC) from Data API
    daily_spent = 0.0
    try:
        from datetime import datetime, timezone
        trades_url = f"https://data-api.polymarket.com/trades?user={wallet_address}&limit=300"
        r = requests.get(trades_url, timeout=8)
        r.raise_for_status()
        trades = r.json()
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        today_ts = int(today_start.timestamp())
        for t in trades:
            ts = t.get("timestamp")
            if ts is None:
                continue
            ts_val = int(ts) if isinstance(ts, (int, float)) else int(ts)
            if ts_val < today_ts:
                break
            size = float(t.get("size", 0) or 0)
            price = float(t.get("price", 0) or 0)
            daily_spent += size * price
    except Exception as e:
        logger.warning(f"Data API trades for daily used failed: {e}")

    try:
        from core.risk import MAX_DAILY
        daily_limit = float(MAX_DAILY)
    except Exception:
        daily_limit = 0.0

    return {
        "balance_usdc": round(balance_usdc, 2),
        "total_exposure": round(total_exposure, 2),
        "total_pnl": round(total_pnl, 2),
        "daily_spent": round(daily_spent, 2),
        "daily_limit": daily_limit,
        "by_source": {},
        "positions": active_positions,
        "source": "native",
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
    creds = _creds_with_env()
    wallet_address = creds.get("polymarket_wallet_addr")
    
    if not wallet_address:
        logger.warning("Missing polymarket_wallet_addr, skipping native positions")
        return []

    # The Data API is more reliable for user-specific position summaries
    data_url = f"https://data-api.polymarket.com/positions?user={wallet_address}&limit=500"
    try:
        resp = requests.get(data_url, timeout=10)
        resp.raise_for_status()
        positions_data = resp.json()
        
        parsed = []
        for p in positions_data:
            size = float(p.get("size", 0))
            if size <= 0:
                continue
            outcome_raw = (p.get("outcome") or "").strip()
            outcome_idx = p.get("outcomeIndex")
            is_yes = outcome_raw.lower() == "yes" or outcome_idx == 0
            is_no = outcome_raw.lower() == "no" or outcome_idx == 1
            if not is_yes and not is_no:
                is_yes = True
            avg_price = float(p.get("avgPrice", 0) or 0)
            cur_price = float(p.get("curPrice", 0) or p.get("currentPrice", 0) or 0)
            current_value = p.get("currentValue")
            if current_value is not None:
                current_value = round(float(current_value), 4)
            else:
                current_value = round((cur_price * size) if cur_price else (size * avg_price), 4)
            cash_pnl = p.get("cashPnl")
            if cash_pnl is not None:
                pnl = round(float(cash_pnl), 4)
            elif cur_price and avg_price:
                pnl = round((cur_price - avg_price) * size, 4)
            else:
                pnl = float(p.get("realizedPnl", 0) or 0)
            parsed.append({
                "market_id": p.get("conditionId", "unknown"),
                "question": p.get("title", "Unknown Market"),
                "shares_yes": round(size, 4) if is_yes else 0,
                "shares_no": round(size, 4) if is_no else 0,
                "current_value": current_value,
                "pnl": pnl,
                "status": "open",
            })
        return parsed
    except Exception as e:
        logger.warning(f"Native Polymarket get_positions failed: {e}")
        raise

def get_native_closed_positions() -> list:
    """Fetch closed positions from Data API."""
    creds = _creds_with_env()
    wallet_address = creds.get("polymarket_wallet_addr")

    if not wallet_address:
        logger.warning("Missing polymarket_wallet_addr, skipping native closed positions")
        return []

    data_url = f"https://data-api.polymarket.com/closed-positions?user={wallet_address}&limit=50"
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
        return []


def get_native_trades_for_log(limit: int = 20, offset: int = 0) -> list:
    """Fetch closed positions from Data API and format as trade log rows with title, shares, and net PnL (for Polymarket Live).
    Uses Polymarket Data API: https://docs.polymarket.com/api-reference/core/get-closed-positions-for-a-user
    """
    from datetime import datetime
    creds = _creds_with_env()
    wallet_address = creds.get("polymarket_wallet_addr")
    if not wallet_address:
        return []

    # API supports limit (max 50) and offset for pagination
    limit = min(max(1, limit), 50)
    url = f"https://data-api.polymarket.com/closed-positions?user={wallet_address}&limit={limit}&offset={offset}&sortBy=TIMESTAMP&sortDirection=DESC"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        closed = resp.json()
        out = []
        for cp in closed:
            ts = cp.get("timestamp")
            time_str = datetime.fromtimestamp(int(ts)).strftime("%H:%M:%S") if ts else "??:??:??"
            avg = float(cp.get("avgPrice") or 0)
            total_bought = float(cp.get("totalBought") or 0)
            shares = total_bought / avg if avg > 0 else 0
            out.append({
                "time": time_str,
                "market_id": cp.get("conditionId", "unknown"),
                "title": cp.get("title") or "Unknown Market",
                "side": (cp.get("outcome") or "Yes").lower()[:3],
                "amount": round(total_bought, 2),
                "shares": round(shares, 3),
                "net_pnl": round(float(cp.get("realizedPnl", 0)), 2),
                "status": "closed",
            })
        return out
    except Exception as e:
        logger.warning(f"Native Polymarket closed-positions for trade log failed: {e}")
        return []


def get_native_trades(limit: int = 20, offset: int = 0) -> list:
    """Fetch user trades from Polymarket Data API. For Live, returns closed-positions as trade log with title, shares, net_pnl."""
    creds = _creds_with_env()
    wallet_address = creds.get("polymarket_wallet_addr")
    if not wallet_address:
        logger.warning("Missing polymarket_wallet_addr, skipping native trades")
        return []

    try:
        return get_native_trades_for_log(limit=limit, offset=offset)
    except Exception as e:
        logger.warning(f"Native Polymarket get_native_trades failed: {e}")
        return []
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
