import os
import sys

# We add the local parent directory to test local code if needed
from simmer_sdk import SimmerClient

def test_trade():
    api_key = "sk_live_6a23b65324c557fa1e04fa0935181e897b9be55e834fbb9a7230509772baf036"
    print(f"Initializing SimmerClient with key {api_key[:10]}...")
    client = SimmerClient(api_key=api_key, venue="simmer")
    
    print("Fetching active markets...")
    markets = client.get_markets(status="active", limit=5)
    
    if not markets:
        print("No active markets found.")
        return
        
    target_market = markets[0]
    print(f"Target market selected: {target_market.question} (ID: {target_market.id})")
    
    print("Placing 10.0 YES shares test trade...")
    try:
        result = client.trade(
            market_id=target_market.id,
            side="yes",
            amount=10.0,
            source="sdk:test_script",
            reasoning="Manual verification test"
        )
        print("✅ Trade Successful!")
        print(f"Bought {result.shares_bought} shares for ${result.cost}")
        print(f"New Balance: ${result.new_balance}")
    except Exception as e:
        print("❌ Trade Failed!")
        print(str(e))

if __name__ == "__main__":
    test_trade()
