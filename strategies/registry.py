"""
strategies/registry.py
─────────────────────────────────────────────────────────────────────────────
Pluggable strategy registry. Add new strategies here to have them appear in
the trading loop, config toggles, and cron without editing api/index.py.

Each strategy has:
  - id: short key (e.g. "arb", "mm")
  - config_key: key in config dict (e.g. "strategy_arb")
  - name: human-readable name
  - default_enabled: whether the strategy is on by default
  - run(venue: str, config: dict) -> list[dict] | dict: entry point

Do NOT put Polymarket API key/signature (e.g. signature type 1) logic here;
that stays in core/polymarket_native.py.

How to add a new strategy:
  1. Implement your strategy in strategies/your_strategy.py with a function
     run_xyz(venue: str, ...) that returns list[dict] or dict.
  2. In this file, add a _run_xyz(venue, config) wrapper that calls your module.
  3. Append a Strategy(id="xyz", config_key="strategy_xyz", name="...", ...) to STRATEGIES.
  4. (Optional) Add strategy_xyz to ConfigUpdate in api/index.py for type hints;
     otherwise extra="allow" already accepts any strategy_* key.
  5. Add a cron route in api/index.py for /cron/xyz if you want Vercel to schedule it separately.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger


@dataclass
class Strategy:
    id: str
    config_key: str
    name: str
    default_enabled: bool
    run: Callable[[str, dict], list[dict] | dict]


def _run_arb(venue: str, config: dict) -> list[dict]:
    from strategies.arb_yesno import run_arb_cycle
    return run_arb_cycle(venue)


def _run_correlation(venue: str, config: dict) -> list[dict]:
    from strategies.correlation import run_correlation_cycle
    return run_correlation_cycle(venue)


def _run_ai(venue: str, config: dict) -> list[dict]:
    from strategies.ai_prob import run_ai_prob_cycle
    return run_ai_prob_cycle(venue)


def _run_mm(venue: str, config: dict) -> list[dict]:
    from strategies.market_maker import run_market_making
    from core.client import get_client
    client = get_client(venue)
    mkts = client.get_markets(status="active", limit=20)
    ids = [m.id for m in mkts]
    if not ids:
        return []
    return run_market_making(ids, venue)


def _run_weather(venue: str, config: dict) -> dict[str, Any]:
    from strategies.clawhub_weather import run_weather_strategy
    from core.client import get_client
    client = get_client(venue)
    return run_weather_strategy(client, venue)


# ── Registry: add new strategies here ───────────────────────────────────────

STRATEGIES: list[Strategy] = [
    Strategy(
        id="arb",
        config_key="strategy_arb",
        name="YES/NO arbitrage",
        default_enabled=True,
        run=_run_arb,
    ),
    Strategy(
        id="correlation",
        config_key="strategy_correlation",
        name="Correlation / logical arb",
        default_enabled=True,
        run=_run_correlation,
    ),
    Strategy(
        id="ai",
        config_key="strategy_ai",
        name="AI probability divergence",
        default_enabled=False,
        run=_run_ai,
    ),
    Strategy(
        id="mm",
        config_key="strategy_mm",
        name="Market making",
        default_enabled=True,
        run=_run_mm,
    ),
    Strategy(
        id="weather",
        config_key="strategy_weather",
        name="ClawHub weather",
        default_enabled=False,
        run=_run_weather,
    ),
]


def get_all() -> list[Strategy]:
    return list(STRATEGIES)


def get_by_id(strategy_id: str) -> Strategy | None:
    return next((s for s in STRATEGIES if s.id == strategy_id), None)


def get_by_config_key(config_key: str) -> Strategy | None:
    return next((s for s in STRATEGIES if s.config_key == config_key), None)


def config_defaults() -> dict[str, bool]:
    """Default enabled flags for all registered strategies (for _DEFAULTS)."""
    return {s.config_key: s.default_enabled for s in STRATEGIES}


def run_enabled_strategies(venue: str, config: dict) -> dict[str, list[dict] | dict]:
    """
    Run every strategy that is enabled in config. Returns a dict
    strategy_id -> result (list or dict).
    """
    effective_venue = "simmer" if venue == "polymarket_paper" else venue
    results = {}
    for s in STRATEGIES:
        if not config.get(s.config_key, False):
            continue
        try:
            out = s.run(effective_venue, config)
            results[s.id] = out if isinstance(out, list) else [out]
        except Exception as e:
            logger.exception(f"Strategy {s.id} error: {e}")
            results[s.id] = [{"error": str(e), "strategy_id": s.id}]
    return results
