"""
strategies/arb_yesno.py
Strategy A — YES+NO < $1.00 Arbitrage + Cross-platform Polymarket/Kalshi arb.
"""
import os
from loguru import logger
from core.client import get_client
from core.risk import safe_trade

MIN_EDGE = float(os.environ.get("MIN_ARB_EDGE", "0.015"))   # 1.5 % minimum


# ── Single-venue YES+NO arb ───────────────────────────────────────────────────

def scan_yesno_arb(venue: str = "simmer") -> list[dict]:
    client  = get_client(venue)
    markets = client.get_markets(status="active", import_source="polymarket", limit=60)
    opps    = []

    for m in markets:
        prob_yes = m.current_probability
        prob_no  = 1.0 - m.current_probability
        gap      = 1.0 - (prob_yes + prob_no)        # Positive → arb exists

        if gap >= MIN_EDGE:
            opps.append({
                "market_id":  m.id,
                "question":   m.question,
                "yes_price":  round(prob_yes, 4),
                "no_price":   round(prob_no,  4),
                "gap":        round(gap,  4),
                "edge_pct":   round(gap * 100, 2),
            })
            logger.info(f"💡 ARB FOUND: {m.question[:55]} | Edge={gap*100:.2f}%")

    return sorted(opps, key=lambda x: x["gap"], reverse=True)


def execute_yesno_arb(opp: dict, amount_per_side: float = 10.0, venue: str = "simmer") -> dict:
    client = get_client(venue)
    expected_profit = amount_per_side * 2 * opp["gap"]

    yes_result = safe_trade(client, opp["market_id"], "yes", amount_per_side, "sdk:arb")
    no_result  = safe_trade(client, opp["market_id"], "no",  amount_per_side, "sdk:arb")

    return {
        "market_id":        opp["market_id"],
        "question":         opp["question"],
        "edge_pct":         opp["edge_pct"],
        "expected_profit":  round(expected_profit, 4),
        "yes_executed":     bool(yes_result and yes_result.success),
        "no_executed":      bool(no_result  and no_result.success),
    }


def run_arb_cycle(venue: str = "simmer") -> list[dict]:
    logger.info(f"🔍 Arb scan [{venue}]...")
    opps    = scan_yesno_arb(venue)
    results = []
    for opp in opps[:3]:   # Execute top 3
        results.append(execute_yesno_arb(opp, amount_per_side=10.0, venue=venue))
    return results


# ── Cross-platform Polymarket ↔ Kalshi arb ───────────────────────────────────

def _keyword_overlap(a: str, b: str) -> float:
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


def run_cross_platform_arb(min_spread: float = 0.05) -> list[dict]:
    poly_client   = get_client("polymarket")
    kalshi_client = get_client("kalshi")

    poly_mkts   = poly_client.get_markets(import_source="polymarket", limit=50)
    kalshi_mkts = kalshi_client.get_markets(import_source="kalshi",   limit=50)

    results = []
    for pm in poly_mkts:
        for km in kalshi_mkts:
            if _keyword_overlap(pm.question, km.question) < 0.55:
                continue
            spread = pm.current_probability - km.current_probability
            if abs(spread) < min_spread:
                continue

            # Buy YES where cheaper, buy NO (equivalent to selling YES) where more expensive
            if spread > 0:   # Polymarket YES > Kalshi YES → buy Kalshi YES + Polymarket NO
                r1 = safe_trade(kalshi_client, km.id, "yes", 15, "sdk:xplatform")
                r2 = safe_trade(poly_client,   pm.id, "no",  15, "sdk:xplatform")
            else:            # Kalshi YES > Polymarket YES → buy Polymarket YES + Kalshi NO
                r1 = safe_trade(poly_client,   pm.id, "yes", 15, "sdk:xplatform")
                r2 = safe_trade(kalshi_client, km.id, "no",  15, "sdk:xplatform")

            results.append({
                "poly_question":   pm.question[:50],
                "kalshi_question": km.question[:50],
                "spread":          round(abs(spread), 4),
                "executed":        bool(r1 and r1.success and r2 and r2.success),
            })
    return results
