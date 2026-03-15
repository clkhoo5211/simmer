import json
import time
from core.store import redis_request
from loguru import logger

HISTORY_KEY_PREFIX = "simmer:history:"
MAX_HISTORY = 50

def record_trade(venue: str, trade_data: dict):
    """
    Append a trade to the persistent history in Redis.
    Structure: {'time': ..., 'market': ..., 'side': ..., 'amount': ..., 'shares': ...}
    """
    key = f"{HISTORY_KEY_PREFIX}{venue}"
    
    # Add timestamp if missing
    if "time" not in trade_data:
        trade_data["time"] = time.strftime("%H:%M:%S")
    
    trade_json = json.dumps(trade_data)
    
    try:
        # Push to the front of the list
        redis_request("lpush", key, trade_json)
        # Trim to keep only the latest MAX_HISTORY
        redis_request("ltrim", key, "0", str(MAX_HISTORY - 1))
        logger.info(f"Trade recorded in history for {venue}")
    except Exception as e:
        logger.error(f"Failed to record trade in history: {e}")

def get_trade_history(venue: str) -> list:
    """Retrieve the last 50 trades for the given venue."""
    key = f"{HISTORY_KEY_PREFIX}{venue}"
    try:
        raw_list = redis_request("lrange", key, "0", str(MAX_HISTORY - 1))
        if not raw_list:
            return []
        
        return [json.loads(t) for t in raw_list]
    except Exception as e:
        logger.error(f"Failed to fetch trade history: {e}")
        return []
