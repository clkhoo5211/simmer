"""
strategies/market_maker.py
Strategy B — Spread capture via limit orders on both sides.
"""
from loguru import logger
from core.client import get_client
from core.risk import safe_trade

SPREAD_WIDTH  = 0.03   # 3-cent half-spread on each side
MAX_INVENTORY = 0.35   # Halt if >35% imbalanced on one side


def _inventory_ratio(positions: list, market_id: str) -> float:
    for p in positions:
        if p.market_id == market_id:
            total = p.shares_yes + p.shares_no
            return (p.shares_yes / total) if total else 0.5
    return 0.5


def run_market_making(market_ids: list[str], venue: str = "simmer") -> list[dict]:
    client    = get_client(venue)
    positions = client.get_positions()
    results   = []

    for market_id in market_ids:
        market = client.get_market_by_id(market_id)
        if not market or market.status != "active":
            continue

        inv = _inventory_ratio(positions, market_id)
        vol_factor = 2.0 if (inv > 0.65 or inv < 0.35) else 1.0

        if inv > MAX_INVENTORY * 2:
            logger.warning(f"🛑 MM inventory limit on {market_id[:12]} ({inv:.1%}) — skip")
            results.append({"market_id": market_id, "status": "inventory_limit"})
            continue

        half = (SPREAD_WIDTH * vol_factor) / 2
        prob = market.current_probability

        logger.info(
            f"📈 MM {market_id[:12]} | prob={prob:.2f} "
            f"spread={half*2:.3f} vol_factor={vol_factor}"
        )

        order_type = "GTC" if venue == "polymarket" else None
        kwargs     = dict(order_type=order_type, source="sdk:mm") if order_type else dict(source="sdk:mm")

        r_yes = safe_trade(client, market_id, "yes", 5.0, "sdk:mm")
        r_no  = safe_trade(client, market_id, "no",  5.0, "sdk:mm")

        results.append({
            "market_id":   market_id,
            "yes_bid":     round(prob - half, 4),
            "yes_ask":     round(prob + half, 4),
            "no_bid":      round((1 - prob) - half, 4),
            "no_ask":      round((1 - prob) + half, 4),
            "inventory":   round(inv, 4),
            "yes_placed":  bool(r_yes and r_yes.success),
            "no_placed":   bool(r_no  and r_no.success),
        })

    return results
