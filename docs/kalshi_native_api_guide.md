# Native Kalshi API Integration Guide

This guide outlines the architecture required to bypass the Simmer SDK wrapper and directly utilize the official Kalshi infrastructure (REST API and Kalshi Python SDK) in your backend when the venue is set to "kalshi".

## 1. Required Dependencies
First, install the official Kalshi Python SDK. Add this to your `simmer-backend/requirements.txt`:
```txt
kalshi-python>=2.0.0
```

## 2. Authentication & Keys
Kalshi uses a different authentication mechanism depending on your account type:
*   **Standard Kalshi:** Requires an API Email, Password, and RSA Private Key for signing requests.
*   **Kalshi via DFlow (Crypto):** Uses Solana wallets (which is what Simmer currently supports via the `SOLANA_PRIVATE_KEY` for Kalshi USDC trading).

If you are using the official Kalshi SDK with standard accounts, you'll need standard API keys from the Kalshi developer portal. If using DFlow, you'll need the specific DFlow Kalshi SDK. 

Assuming you are moving to the **Standard Kalshi Python SDK**:

```python
import os
import kalshi_python
from core.store import load_credentials

_kalshi_client = None

def get_kalshi_client():
    global _kalshi_client
    if _kalshi_client is None:
        creds = load_credentials()
        
        # Configure the API client
        config = kalshi_python.Configuration()
        # For production: https://trading-api.kalshi.com/trade-api/v2
        # For testing: https://demo-api.kalshi.co/trade-api/v2
        config.host = "https://trading-api.kalshi.com/trade-api/v2"
        
        # You would need to store these in Redis via the dashboard Settings
        kalshi_email = creds.get("kalshi_email")
        kalshi_password = creds.get("kalshi_password")
        
        _kalshi_client = kalshi_python.ApiClient(config)
        
        # Step 1: Login to get an access token
        auth_api = kalshi_python.AuthApi(_kalshi_client)
        login_request = kalshi_python.LoginRequest(
            email=kalshi_email,
            password=kalshi_password
        )
        login_response = auth_api.login(login_request)
        
        # Step 2: Set the token for future requests
        _kalshi_client.configuration.access_token = login_response.token
        
    return _kalshi_client
```

## 3. Reading the Portfolio & Markets

### Fetching Balance
Update your `api/index.py` portfolio endpoint to fetch the user's Kalshi balance:
```python
import kalshi_python

@app.get("/api/portfolio")
def get_portfolio(venue: str):
    if venue == "kalshi":
        client = get_kalshi_client()
        portfolio_api = kalshi_python.PortfolioApi(client)
        
        try:
            balance_resp = portfolio_api.get_portfolio_balance()
            active_orders = portfolio_api.get_orders(status="resting")
            
            return {
                "balance_usd": balance_resp.balance / 100.0, # Kalshi balances are usually in cents
                "total_exposure": 0.0, # Calculate from active orders if needed
                "positions": active_orders.orders,
            }
        except kalshi_python.ApiException as e:
            return {"error": f"Kalshi API exception: {e}"}
```

### Fetching Markets
To get a list of active markets:
```python
market_api = kalshi_python.MarketApi(get_kalshi_client())
# Fetch active markets
markets_resp = market_api.get_markets(status="active", limit=20)

for market in markets_resp.markets:
    print(f"{market.ticker}: YES price = {market.yes_ask_price}")
```

## 4. Executing Trades (Placing Orders)
To place orders directly on the Kalshi exchange:

```python
import uuid
import kalshi_python

def place_kalshi_trade(ticker: str, side: str, price_cents: int, count: int):
    client = get_kalshi_client()
    exchange_api = kalshi_python.ExchangeApi(client)
    
    # Map sides to Kalshi constants
    kalshi_side = "yes" if side.lower() == "yes" else "no"
    
    # Create the order object
    order_create_req = kalshi_python.OrderCreateRequest(
        ticker=ticker,
        client_order_id=str(uuid.uuid4()),
        action="buy",              # 'buy' or 'sell'
        type="limit",              # 'limit' or 'market'
        side=kalshi_side,
        count=count,               # Number of contracts
        yes_price=price_cents,     # Price in cents (1-99)
    )
    
    try:
        response = exchange_api.create_order(order_create_req)
        return response.order
    except kalshi_python.ApiException as e:
        print("Exception when trading:", e)
        return None
```

## 5. Important Differences from Simmer/Polymarket
1. **Currency**: Standard Kalshi trades in USD Cents (1 contract = $1.00 payout = 100 cents). Polymarket trades in USDC decimals.
2. **Authentication**: If you move away from the Simmer SDK (which handles Kalshi-via-Solana automatically), you will likely need to move to standard Email/Password + RSA Key authentication, which requires you to update the `Settings` page on the Dashboard to capture these new fields instead of just the `SOLANA_PRIVATE_KEY`.
3. **Websockets**: Similar to Polymarket, Kalshi has a robust WebSocket API for live orderbooks. This cannot run on Vercel Serverless and would require migrating the backend to a persistent server.
