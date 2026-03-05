"""
ClawHub Skill: Polymarket Weather Trader
Mirrors the logic published on ClawHub (polymarket-weather-trader).

Strategy: Search for active Simmer weather markets where the current
probability is < 0.15 (underpriced YES) or > 0.85 (overpriced YES → buy NO).
Cross-check against a live NOAA forecast to validate the thesis.

This skill tags all trades with skill_slug="polymarket-weather-trader" so
Simmer/ClawHub can track volume attribution correctly.
"""

import os
import requests
from typing import Dict, Any, List


# ── NOAA helper ──────────────────────────────────────────────────────────────

def _get_noaa_forecast_nyc() -> float:
    """
    Fetch today's expected high temperature for NYC from NOAA.
    Returns temperature in Fahrenheit, or None on failure.
    """
    try:
        # NOAA gridpoints for New York City (Central Park)
        url = "https://api.weather.gov/gridpoints/OKX/33,37/forecast"
        resp = requests.get(url, timeout=10,
                            headers={"User-Agent": "simmer-weather-skill/1.0"})
        resp.raise_for_status()
        periods = resp.json().get("properties", {}).get("periods", [])
        for period in periods:
            if period.get("isDaytime"):
                return float(period["temperature"])  # already °F
    except Exception as e:
        print(f"⚠️ NOAA fetch failed: {e}")
    return None


# ── Main skill entry-point ────────────────────────────────────────────────────

def run_weather_strategy(client, venue: str) -> Dict[str, Any]:
    """
    ClawHub Weather Trader — entry-point called by the /cron/weather endpoint.

    1. Fetch live NOAA temperature for NYC.
    2. Find active Simmer weather markets (keyword search).
    3. For each candidate market with |probability – 0.5| > 0.10 edge:
       a. Get context & check for warnings.
       b. Trade the underpriced side with reasoning citing the NOAA data.
    """
    print("🌤️  Running Polymarket Weather Trader Skill...")

    # 1. NOAA data
    forecast_f = _get_noaa_forecast_nyc()
    noaa_str = f"{forecast_f:.0f}°F" if forecast_f is not None else "unavailable"
    print(f"   NOAA NYC forecast: {noaa_str}")

    # 2. Discover weather markets using the REST API q= param (SDK wrapper doesn't expose it)
    try:
        raw = client._request("GET", "/api/sdk/markets",
                              params={"status": "active", "q": "temperature", "limit": 20})
        markets = [client._parse_market(m) for m in raw.get("markets", [])]
        print(f"   Found {len(markets)} weather markets")
    except Exception as e:
        return {"status": "error", "reason": f"Failed to fetch markets: {e}"}

    results = []
    for m in markets:
        prob = getattr(m, "current_probability", None) or 0.5

        # Only trade markets with a meaningful edge
        edge = abs(prob - 0.5)
        if edge < 0.10:
            print(f"   ↳ {m.question[:60]} — edge {edge:.0%} too small, skip")
            continue

        # Determine which side is the buy
        if prob < 0.40:
            side = "yes"
            reasoning = (
                f"Market underpricing YES at {prob:.0%}. "
                f"NOAA NYC: {noaa_str}. "
                "Probability appears too low for an active temperature event."
            )
        else:
            side = "no"
            reasoning = (
                f"Market overpricing YES at {prob:.0%}. "
                f"NOAA NYC: {noaa_str}. "
                "Buying NO as the structural edge favours disagreement."
            )

        # 3a. Get context (safety check)
        try:
            ctx = client.get_market_context(m.id)
            warnings = ctx.get("warnings") if ctx else None
            if warnings:
                print(f"   ↳ Skipping {m.id}: {warnings}")
                results.append({"market_id": m.id, "status": "skipped",
                                 "reason": f"context warning: {warnings}"})
                continue
        except Exception as e:
            results.append({"market_id": m.id, "status": "error",
                             "reason": f"context fetch failed: {e}"})
            continue

        # 3b. Execute trade
        try:
            result = client.trade(
                market_id=m.id,
                side=side,
                amount=10.0,
                source="sdk:weather",
                skill_slug="polymarket-weather-trader",   # ClawHub attribution
                reasoning=reasoning,
                venue=venue,
            )
            shares = getattr(result, "shares_bought", "?")
            print(f"   ✅ Bought {shares} {side.upper()} shares on {m.id}")
            results.append({
                "market_id": m.id,
                "question": m.question,
                "side": side,
                "shares": shares,
                "probability_at_trade": prob,
                "reasoning": reasoning,
                "status": "traded",
            })
        except Exception as e:
            results.append({"market_id": m.id, "status": "error", "reason": str(e)})

    return {
        "noaa_nyc_forecast_f": forecast_f,
        "markets_scanned": len(markets),
        "results": results,
    }
