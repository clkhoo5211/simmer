"""
strategies/ai_prob.py
Strategy C — Ensemble AI (GPT-4 + Claude) vs market price divergence.
"""
import os
import openai
import anthropic
from loguru import logger
from core.client import get_client
from core.risk import safe_trade

MIN_DIV    = float(os.environ.get("MIN_PROB_DIVERGENCE", "0.10"))
MIN_CONF   = 0.60   # Both models must agree within this band

_oai = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
_ant = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

FORECAST_PROMPT = (
    "You are a superforecaster. Estimate the probability (0.00–1.00) that the "
    "following question resolves YES. Reply with ONLY a decimal number.\n\nQuestion: {q}"
)


def _gpt4_prob(question: str) -> float:
    try:
        r = _oai.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": FORECAST_PROMPT.format(q=question)}],
            max_tokens=8,
        )
        return float(r.choices[0].message.content.strip())
    except Exception:
        return 0.5


def _claude_prob(question: str) -> float:
    try:
        r = _ant.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=8,
            messages=[{"role": "user", "content": FORECAST_PROMPT.format(q=question)}],
        )
        return float(r.content[0].text.strip())
    except Exception:
        return 0.5


def ensemble(question: str) -> dict:
    g = _gpt4_prob(question)
    c = _claude_prob(question)
    avg  = (g + c) / 2
    conf = 1.0 - abs(g - c)
    return {"gpt4": g, "claude": c, "ensemble": avg, "confidence": conf}


def kelly_size(edge: float, odds: float, bankroll: float, half: bool = True) -> float:
    b = max((1 / odds) - 1, 0.001)
    p, q = edge, 1 - edge
    k = (b * p - q) / b
    k = k * 0.5 if half else k   # Half-Kelly by default
    return min(max(k * bankroll, 0), 50)   # Cap at $50


def run_ai_prob_cycle(venue: str = "simmer") -> list[dict]:
    client    = get_client(venue)
    markets   = client.get_markets(status="active", limit=30)
    portfolio = client.get_portfolio()
    bankroll  = float(portfolio.get("balance_usdc", 100))
    results   = []

    for m in markets:
        # Skip ultra-short markets — too fast for AI round-trip
        q_lower = m.question.lower()
        if any(x in q_lower for x in ["5 min", "15 min", "30 min"]):
            continue

        ai     = ensemble(m.question)
        div    = ai["ensemble"] - m.current_probability

        if abs(div) < MIN_DIV or ai["confidence"] < MIN_CONF:
            continue

        side = "yes" if div > 0 else "no"
        odds = m.current_probability if side == "yes" else (1 - m.current_probability)
        size = kelly_size(abs(div), odds, bankroll)

        logger.info(
            f"🎯 AI signal: {m.question[:50]} | "
            f"market={m.current_probability:.2f} ai={ai['ensemble']:.2f} "
            f"edge={abs(div):.2f} size=${size:.2f}"
        )

        result = safe_trade(client, m.id, side, size, "sdk:ai-prob")
        results.append({
            "market_id":   m.id,
            "question":    m.question[:60],
            "market_prob": round(m.current_probability, 4),
            "ai_ensemble": round(ai["ensemble"], 4),
            "gpt4":        round(ai["gpt4"], 4),
            "claude":      round(ai["claude"], 4),
            "confidence":  round(ai["confidence"], 4),
            "divergence":  round(div, 4),
            "side":        side,
            "size":        round(size, 2),
            "executed":    bool(result and result.success),
        })

    return results
