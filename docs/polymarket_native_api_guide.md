# Native Polymarket API Integration Guide

This guide outlines the complete architectural shift required to bypass the Simmer SDK wrapper and directly utilize the official Polymarket infrastructure (PyCLOB, Gamma API, and Websockets) in your backend.

## 1. Required Dependencies
You will need to replace `simmer-sdk` with Polymarket's official CLOB client in your `simmer-backend/requirements.txt`:
```txt
pyclob>=0.3.0
request>=2.31.0
websockets>=11.0.3   # Note: Websockets require moving off Vercel serverless
```

## 2. Setting Up the CLOB Client (Trading & Orders)
The `pyclob` Python library will handle all limit orders, market creation, and active order cancellation. You must initialize it using the credentials currently stored in Upstash Redis.

Create a new file `simmer-backend/core/polymarket_client.py`:
```python
import os
from pyclob.client import ClobClient
from core.store import load_credentials

_clob_client = None

def get_clob_client() -> ClobClient:
    global _clob_client
    if _clob_client is None:
        creds = load_credentials()
        
        _clob_client = ClobClient(
            host="https://clob.polymarket.com",
            key=creds.get("wallet_private_key"),  # Your 0x... EVM private key
            chain_id=137,                         # 137 = Polygon Mainnet
            signature_type=2,                     # 2 = EOA (Externally Owned Account)
            creds={
                "key": creds.get("polymarket_api_key"),
                "secret": creds.get("polymarket_api_secret"),
                "passphrase": creds.get("polymarket_passphrase")
            }
        )
    return _clob_client
```

## 3. Reading the Portfolio & Markets (Gamma API)
Polymarket's **Gamma API** serves read-only data for markets, prices, and user portfolios. You will hit this via standard REST requests instead of `pyclob`.

Update your `api/index.py` portfolio endpoint:
```python
import requests

@app.get("/api/portfolio")
def get_portfolio():
    creds = load_credentials()
    wallet_address = creds.get("polymarket_wallet_addr")
    
    if not wallet_address:
        return {"error": "Missing Polymarket wallet address in settings."}

    # 1. Fetch USDC balance from Polygon / CLOB
    client = get_clob_client()
    balance = client.get_allowance() # Example: Check USDC allowance/balance
    
    # 2. Fetch Active Positions from Gamma
    gamma_url = f"https://gamma-api.polymarket.com/users/{wallet_address}/positions"
    active_positions = requests.get(gamma_url).json()
    
    # Calculate PNL manually from the response...
    return {
        "balance_usdc": balance,
        "positions": active_positions,
    }
```

## 4. Market Data & Orderbooks (Data API / Websockets)

### REST Polling (Vercel-Safe)
If you remain on Vercel Serverless (where functions die after 10-60 seconds), you must use the REST API to fetch orderbooks periodically on every cron run:
```python
# Fetching the orderbook for a specific Condition ID
orderbook = client.get_order_book("0xYourConditionIdHere")
best_bid = orderbook.bids[0].price
best_ask = orderbook.asks[0].price
```

### Live Websockets (Requires Dedicated Server)
If you want to maintain a continuous, nanosecond-precise stream of the orderbook for high-frequency algorithmic trading, **you cannot host the backend on Vercel**. You must move the Python app to a persistent host (e.g., AWS EC2, Render, DigitalOcean, or a Raspberry Pi).

```python
import asyncio
import websockets
import json

async def listen_to_orderbook(condition_id: str):
    uri = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    async with websockets.connect(uri) as ws:
        # Subscribe to a specific market's orderbook
        payload = {
            "assets_ids": [condition_id],
            "type": "market"
        }
        await ws.send(json.dumps(payload))
        
        while True:
            message = await ws.recv()
            data = json.loads(message)
            print("Live Orderbook Update:", data)

# This event loop must run continuously
# asyncio.run(listen_to_orderbook("0x..."))
```

## 5. Executing Trades (Placing Limit Orders)
To replace `client.trade()`, you will construct limit orders using PyCLOB and sign them dynamically:

```python
from pyclob.client import ClobClient
from pyclob.models import OrderArgs

def place_polymarket_trade(market_id, side: str, price: float, size: float):
    client = get_clob_client()
    
    # You must map "yes"/"no" to the correct Token ID for the specific market
    token_id = get_token_id_for_side(market_id, side) 

    order_args = OrderArgs(
        price=price,             # e.g. 0.35 (35 cents)
        size=size,               # e.g. 10.0 (Buy 10 shares)
        side="BUY",              # Always BUY limit (even if buying "NO" shares)
        token_id=token_id,       # The underlying ERC1155 token ID for the asset
    )
    
    # Sign and execute the trade against the CLOB
    signed_order = client.create_and_sign_order(order_args)
    response = client.post_order(signed_order)
    return response
```
