import os
import kalshi_python
from core.store import load_credentials
from loguru import logger

_kalshi_client = None

def get_native_kalshi_client():
    global _kalshi_client
    if _kalshi_client is None:
        creds = load_credentials()
        
        email = creds.get("kalshi_email")
        password = creds.get("kalshi_password")
        
        if not email or not password:
            raise ValueError("Missing kalshi_email or kalshi_password for native client")
            
        config = kalshi_python.Configuration()
        config.host = "https://trading-api.kalshi.com/trade-api/v2"
        
        _kalshi_client = kalshi_python.ApiClient(config)
        
        # Login
        auth_api = kalshi_python.AuthApi(_kalshi_client)
        login_request = kalshi_python.LoginRequest(
            email=email,
            password=password
        )
        try:
            login_response = auth_api.login(login_request)
            _kalshi_client.configuration.access_token = login_response.token
        except Exception as e:
            raise ValueError(f"Kalshi login failed: {e}")
            
    return _kalshi_client

def get_native_portfolio() -> dict:
    """Fetch native portfolio via Kalshi Python SDK."""
    client = get_native_kalshi_client()
    portfolio_api = kalshi_python.PortfolioApi(client)
    
    balance_usd = 0.0
    active_orders = []
    
    try:
        balance_resp = portfolio_api.get_portfolio_balance()
        balance_usd = balance_resp.balance / 100.0  # Convert cents to USD
        
        orders_resp = portfolio_api.get_orders(status="resting")
        if orders_resp and hasattr(orders_resp, 'orders'):
            active_orders = [o.to_dict() for o in orders_resp.orders]
            
    except Exception as e:
        logger.warning(f"Native Kalshi portfolio fetch failed: {e}")
        raise
        
    return {
        "balance_usdc": balance_usd, 
        "total_exposure": 0.0, 
        "total_pnl": 0.0,
        "daily_spent": 0.0,
        "by_source": {},
        "positions": active_orders,
        "source": "native"
    }

def get_native_markets(status: str = "active", limit: int = 25) -> list:
    """Fetch structured markets from Kalshi Python SDK."""
    client = get_native_kalshi_client()
    market_api = kalshi_python.MarketApi(client)
    try:
        markets_resp = market_api.get_markets(status=status, limit=limit)
        results = []
        if hasattr(markets_resp, 'markets'):
            for m in markets_resp.markets:
                prob = m.yes_ask / 100.0 if hasattr(m, "yes_ask") and m.yes_ask else 0.5
                results.append({
                    "id": m.ticker,
                    "question": m.title,
                    "status": m.status,
                    "current_probability": prob,
                    "divergence": None,
                    "resolves_at": getattr(m, "close_time", None),
                    "import_source": "kalshi"
                })
        return results
    except Exception as e:
        logger.warning(f"Native Kalshi get_markets failed: {e}")
        raise

def get_native_positions() -> list:
    """Fetch structured positions from Kalshi Python SDK."""
    client = get_native_kalshi_client()
    portfolio_api = kalshi_python.PortfolioApi(client)
    
    try:
        orders_resp = portfolio_api.get_orders(status="resting")
        parsed = []
        if orders_resp and hasattr(orders_resp, 'orders'):
            for o in orders_resp.orders:
                parsed.append({
                    "market_id": o.ticker,
                    "question": f"Kalshi: {o.ticker}",
                    "shares_yes": o.client_order_id, # Simplified map
                    "shares_no": 0,
                    "current_value": 0.0,
                    "pnl": 0.0,
                    "status": "open"
                })
        return parsed
    except Exception as e:
        logger.warning(f"Native Kalshi get_positions failed: {e}")
        raise
