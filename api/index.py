"""
api/index.py
FastAPI application — deployed as a single Vercel serverless function.
All /api/* routes → portfolio, markets, positions, trade, config, cron.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger

from core.client import get_client
from core.risk import daily_spent, MAX_TRADE, MAX_DAILY, check_limits, stop_loss_triggered
from core.store import load_config, save_config
from strategies.arb_yesno   import run_arb_cycle, run_cross_platform_arb
from strategies.market_maker import run_market_making
from strategies.ai_prob      import run_ai_prob_cycle
from strategies.correlation  import run_correlation_cycle
from strategies.clawhub_weather import run_weather_strategy

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="Simmer Trading Bot API", version="1.0.0")

DASHBOARD_ORIGIN = os.environ.get("DASHBOARD_ORIGIN", "https://clkhoo5211.github.io")
CRON_SECRET      = os.environ.get("CRON_SECRET", "")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[DASHBOARD_ORIGIN, "http://localhost:5500", "http://127.0.0.1:5500"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request, call_next):
    """Inject standard security headers to harden the API."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response


# ── Auth helpers ──────────────────────────────────────────────────────────────
def verify_cron(authorization: str = Header(default="")):
    """Vercel passes 'Bearer <CRON_SECRET>' on cron invocations."""
    if CRON_SECRET and authorization != f"Bearer {CRON_SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized cron request")


# ── Request / response models ─────────────────────────────────────────────────
class TradeRequest(BaseModel):
    market_id:  str
    side:       str           # "yes" | "no"
    amount:     float
    reasoning:  str = ""
    venue:      str = ""      # Override default venue if set


class ConfigUpdate(BaseModel):
    max_trade_usd:        float | None = None
    max_daily_usd:        float | None = None
    min_arb_edge:         float | None = None
    default_venue:        str   | None = None
    strategy_arb:         bool  | None = None
    strategy_mm:          bool  | None = None
    strategy_ai:          bool  | None = None
    strategy_correlation: bool  | None = None


# Runtime config — loaded from Redis on cold start, falls back to defaults
_DEFAULTS = {
    "default_venue":        os.environ.get("DEFAULT_VENUE", "simmer"),
    "max_trade_usd":        MAX_TRADE,
    "max_daily_usd":        MAX_DAILY,
    "min_arb_edge":         float(os.environ.get("MIN_ARB_EDGE", "0.015")),
    "strategy_arb":         True,
    "strategy_mm":          True,
    "strategy_ai":          False,
    "strategy_correlation": True,
}
_config = load_config(_DEFAULTS)


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "simmer-bot-api"}


@app.get("/api/health")
def health():
    return {
        "status":       "ok",
        "venue":        _config["default_venue"],
        "daily_spent":  round(daily_spent(), 2),
        "stop_loss":    stop_loss_triggered(),
    }


# ── Portfolio ─────────────────────────────────────────────────────────────────
@app.get("/api/portfolio")
def get_portfolio():
    try:
        client    = get_client(_config["default_venue"])
        portfolio = client.get_portfolio()
        total_pnl = client.get_total_pnl()
        return {
            "balance_usdc":   portfolio.get("balance_usdc", 0),
            "total_exposure": portfolio.get("total_exposure", 0),
            "total_pnl":      round(total_pnl, 4),
            "daily_spent":    round(daily_spent(), 2),
            "daily_limit":    MAX_DAILY,
            "by_source":      portfolio.get("by_source", {}),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Markets ───────────────────────────────────────────────────────────────────
@app.get("/api/markets")
def get_markets(
    venue:         str = "",
    import_source: str = "polymarket",
    status:        str = "active",
    limit:         int = 25,
):
    try:
        v      = venue or _config["default_venue"]
        client = get_client(v)
        mkts   = client.get_markets(status=status, import_source=import_source, limit=limit)
        return [
            {
                "id":                  m.id,
                "question":            m.question,
                "status":              m.status,
                "current_probability": round(m.current_probability, 4),
                "divergence":          round(m.divergence, 4) if m.divergence else None,
                "resolves_at":         m.resolves_at,
                "import_source":       m.import_source,
            }
            for m in mkts
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Positions ─────────────────────────────────────────────────────────────────
@app.get("/api/positions")
def get_positions(venue: str = ""):
    try:
        v         = venue or _config["default_venue"]
        client    = get_client(v)
        positions = client.get_positions()
        return [
            {
                "market_id":     p.market_id,
                "question":      p.question,
                "shares_yes":    round(p.shares_yes, 4),
                "shares_no":     round(p.shares_no, 4),
                "current_value": round(p.current_value, 4),
                "pnl":           round(p.pnl, 4),
                "status":        p.status,
            }
            for p in positions
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Price History ─────────────────────────────────────────────────────────────
@app.get("/api/markets/{market_id}/history")
def get_price_history(market_id: str, venue: str = ""):
    try:
        client = get_client(venue or _config["default_venue"])
        return client.get_price_history(market_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Manual Trade ──────────────────────────────────────────────────────────────
@app.post("/api/trade")
def manual_trade(req: TradeRequest):
    try:
        v      = req.venue or _config["default_venue"]
        client = get_client(v)

        ok, reason = check_limits(req.amount)
        if not ok:
            raise HTTPException(status_code=400, detail=reason)

        result = client.trade(
            market_id=req.market_id,
            side=req.side,
            amount=req.amount,
            reasoning=req.reasoning or None,
            source="sdk:manual",
        )
        if not result or not result.success:
            raise HTTPException(
                status_code=400,
                detail=getattr(result, "error", "Trade failed") or "Trade returned no result"
            )

        return {
            "trade_id":      result.trade_id,
            "market_id":     result.market_id,
            "side":          result.side,
            "shares_bought": round(result.shares_bought, 4),
            "cost":          round(result.cost, 4),
            "new_price":     round(result.new_price, 4) if result.new_price else None,
            "order_status":  result.order_status,
        }
    except HTTPException:
        raise   # re-raise our own structured errors unchanged
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("manual_trade error")
        raise HTTPException(status_code=500, detail=f"Trade error: {exc}")




# ── Config ────────────────────────────────────────────────────────────────────
@app.get("/api/config")
def get_config():
    return _config


@app.post("/api/config")
def update_config(body: ConfigUpdate):
    for field, val in body.model_dump(exclude_none=True).items():
        _config[field] = val
    save_config(_config)   # ← persist to Upstash Redis so toggles survive cold starts
    logger.info(f"⚙️  Config updated: {body.model_dump(exclude_none=True)}")
    return _config


# ── Arb Scan (read-only) ──────────────────────────────────────────────────────
@app.get("/api/arb/scan")
def arb_scan(venue: str = ""):
    from strategies.arb_yesno import scan_yesno_arb
    v = venue or _config["default_venue"]
    return scan_yesno_arb(v)


# ── Cron Endpoints (called by Vercel scheduler) ───────────────────────────────
@app.get("/cron/arb", dependencies=[Depends(verify_cron)])
def cron_arb():
    if not _config.get("strategy_arb"):
        return {"skipped": "strategy disabled"}
    if stop_loss_triggered():
        return {"skipped": "stop loss active"}
    return {"results": run_arb_cycle(_config["default_venue"])}


@app.get("/cron/correlation", dependencies=[Depends(verify_cron)])
def cron_correlation():
    if not _config.get("strategy_correlation"):
        return {"skipped": "strategy disabled"}
    if stop_loss_triggered():
        return {"skipped": "stop loss active"}
    return {"results": run_correlation_cycle(_config["default_venue"])}


@app.get("/cron/ai-prob", dependencies=[Depends(verify_cron)])
def cron_ai_prob():
    if not _config.get("strategy_ai"):
        return {"skipped": "strategy disabled"}
    if stop_loss_triggered():
        return {"skipped": "stop loss active"}
    return {"results": run_ai_prob_cycle(_config["default_venue"])}


@app.get("/cron/market-making", dependencies=[Depends(verify_cron)])
def cron_market_making():
    if not _config.get("strategy_mm"):
        return {"skipped": "strategy disabled"}
    if stop_loss_triggered():
        return {"skipped": "stop loss active"}
    # Fetch active market IDs and run MM on them
    client = get_client(_config["default_venue"])
    mkts   = client.get_markets(status="active", limit=20)
    ids    = [m.id for m in mkts]
    return {"results": run_market_making(ids, _config["default_venue"])}

@app.get("/cron/weather", dependencies=[Depends(verify_cron)])
def cron_weather():
    """
    Run the ClawHub Weather Trader skill.
    """
    if stop_loss_triggered():
        return {"status": "skipped", "message": "stop loss active"}
    
    # Needs to match how get_client is imported in index.py
    client = get_client(_config["default_venue"])
    result = run_weather_strategy(client, _config["default_venue"])
    return result
