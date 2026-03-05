"""
core/risk.py
Server-side risk checks — daily limits, per-trade caps, flip-flop guard.
Uses in-memory dict (Vercel serverless resets between invocations — use Redis for prod).
"""
import os
from datetime import date
from loguru import logger
from core.client import get_client

# ── Limits (read from env, fallback to safe defaults) ────────────────────────
MAX_TRADE = float(os.environ.get("MAX_TRADE_USD", "25"))
MAX_DAILY = float(os.environ.get("MAX_DAILY_USD", "200"))

# In-memory daily spend tracker (reset each cold start — acceptable for Alpha)
_daily: dict[str, float] = {}


def today() -> str:
    return str(date.today())


def daily_spent() -> float:
    return _daily.get(today(), 0.0)


def record_spend(amount: float) -> None:
    _daily[today()] = daily_spent() + amount


def check_limits(amount: float) -> tuple[bool, str]:
    """Returns (ok, reason). Call before every trade."""
    if amount > MAX_TRADE:
        return False, f"Trade ${amount:.2f} exceeds per-trade cap ${MAX_TRADE:.2f}"
    remaining = MAX_DAILY - daily_spent()
    if amount > remaining:
        return False, f"Daily cap reached (${daily_spent():.2f}/${MAX_DAILY:.2f})"
    return True, "ok"


def stop_loss_triggered(threshold: float = -50.0) -> bool:
    """Halt all trading when total unrealised P&L drops below threshold."""
    try:
        client = get_client()
        pnl = client.get_total_pnl()
        if pnl < threshold:
            logger.critical(f"🛑 STOP LOSS: P&L ${pnl:.2f} < ${threshold:.2f} — halting")
            return True
    except Exception as exc:
        logger.warning(f"stop_loss check failed: {exc}")
    return False


def safe_trade(client, market_id: str, side: str, amount: float, source: str = "sdk:bot"):
    """
    Wrap client.trade() with risk + context checks.
    Returns TradeResult or None if blocked.
    """
    # 1. Stop-loss
    if stop_loss_triggered():
        return None

    # 2. Limit checks
    ok, reason = check_limits(amount)
    if not ok:
        logger.warning(f"❌ Risk block [{source}]: {reason}")
        return None

    # 3. Market context safeguards
    try:
        ctx = client.get_market_context(market_id)
        if ctx.get("warnings"):
            logger.warning(f"⚠️  Skipping {market_id[:12]} — warnings: {ctx['warnings']}")
            return None
        if ctx.get("discipline", {}).get("is_flip_flop"):
            logger.warning(f"⚠️  Flip-flop guard on {market_id[:12]} — skipping")
            return None
    except Exception as exc:
        logger.warning(f"Market context fetch failed for {market_id}: {exc}")

    # 4. Execute
    result = client.trade(
        market_id=market_id,
        side=side,
        amount=amount,
        source=source
    )
    if result and result.success:
        record_spend(amount)
        logger.success(
            f"✅ [{source}] {side.upper()} ${amount:.2f} on {market_id[:12]} "
            f"→ {result.shares_bought:.3f} shares @ ${result.cost:.2f}"
        )
    return result
