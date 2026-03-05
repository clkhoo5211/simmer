"""
strategies/correlation.py
Strategy D — Logical/correlation arbitrage between related markets.
"""
from loguru import logger
from core.client import get_client
from core.risk import safe_trade

# Add market pairs where one event IMPLIES another.
# If P(parent) > P(child) by > BUFFER → child is underpriced → buy child YES.
IMPLIES_RULES = [
    {
        "desc":           "Trump win → Republican win",
        "parent_kw":      "trump wins 2028",
        "child_kw":       "republican wins 2028",
    },
    {
        "desc":           "BTC >100k → BTC >80k",
        "parent_kw":      "bitcoin above 100k",
        "child_kw":       "bitcoin above 80k",
    },
    {
        "desc":           "BTC >120k → BTC >100k",
        "parent_kw":      "bitcoin above 120k",
        "child_kw":       "bitcoin above 100k",
    },
    {
        "desc":           "ETH >5k → ETH >4k",
        "parent_kw":      "ethereum above 5000",
        "child_kw":       "ethereum above 4000",
    },
]

BUFFER = 0.03   # 3 % tolerance for fees/slippage


def _match(market, keyword: str) -> bool:
    return keyword.lower() in market.question.lower()


def detect_violations(markets: list, rules: list) -> list[dict]:
    violations = []
    for rule in rules:
        parent = next((m for m in markets if _match(m, rule["parent_kw"])), None)
        child  = next((m for m in markets if _match(m, rule["child_kw"])),  None)
        if not parent or not child:
            continue
        gap = parent.current_probability - child.current_probability
        if gap > BUFFER:
            violations.append({
                "rule":       rule["desc"],
                "parent_id":  parent.id,
                "child_id":   child.id,
                "parent_q":   parent.question[:55],
                "child_q":    child.question[:55],
                "parent_prob": round(parent.current_probability, 4),
                "child_prob":  round(child.current_probability, 4),
                "gap":         round(gap, 4),
                "action":      "buy_child_yes",
            })
            logger.info(
                f"🔍 LOGICAL VIOLATION: {rule['desc']} "
                f"| parent={parent.current_probability:.2f} child={child.current_probability:.2f}"
            )
    return violations


def run_correlation_cycle(venue: str = "simmer") -> list[dict]:
    client     = get_client(venue)
    markets    = client.get_markets(status="active", limit=100)
    violations = detect_violations(markets, IMPLIES_RULES)
    results    = []

    for v in violations:
        result = safe_trade(client, v["child_id"], "yes", 15.0, "sdk:corr-arb")
        results.append({**v, "executed": bool(result and result.success)})

    if not violations:
        logger.info("No correlation violations found.")
    return results
