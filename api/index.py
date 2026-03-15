"""
api/index.py
FastAPI application — deployed as a single Vercel serverless function.
All /api/* routes → portfolio, markets, positions, trade, config, cron.
"""
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, _root)
# Load .env.local for local development (Vercel injects env in production)
_env_local = os.path.join(_root, ".env.local")
if os.path.isfile(_env_local):
    from dotenv import load_dotenv
    load_dotenv(_env_local)

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger

from core.client import get_client
from core.risk import daily_spent, stop_loss_triggered, MAX_DAILY, MAX_TRADE, check_limits
from core.store import load_config, save_config, load_credentials, save_credentials
from core.settings_schema import SETTINGS_SCHEMA
from strategies.arb_yesno import scan_yesno_arb
from strategies.registry import (
    get_all,
    get_by_id,
    config_defaults,
    run_enabled_strategies,
)
from core.telegram import send_telegram_message
# from core.history import record_trade, get_trade_history

# ── Background Bot Loop ──────────────────────────────────────────────────────
_bot_stop_event = threading.Event()

def _trading_loop():
    """Continuous background loop. Runs strategies when automation is enabled."""
    logger.info("🤖 Background trading thread started.")
    while not _bot_stop_event.is_set():
        try:
            cfg = load_config(_DEFAULTS)
            if not cfg.get("automation_enabled") or stop_loss_triggered():
                _bot_stop_event.wait(timeout=15)  # sleep 15s between checks
                continue

            venue = cfg.get("default_venue", "polymarket_paper")
            # SDK only knows simmer/polymarket; paper Polymarket runs on simmer
            effective_venue = "simmer" if venue == "polymarket_paper" else venue
            logger.info(f"⚡ Running automated strategy cycle on [{venue}]...")

            results = run_enabled_strategies(effective_venue, cfg)
            for strategy_id, result in results.items():
                if result:
                    logger.info(f"  {strategy_id}: {len(result) if isinstance(result, list) else 1} result(s)")

        except Exception as e:
            logger.exception(f"Trading loop error: {e}")

        _bot_stop_event.wait(timeout=15)  # wait 15s between cycles


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start bot thread on startup
    bot_thread = threading.Thread(target=_trading_loop, daemon=True, name="trading-loop")
    bot_thread.start()
    logger.info("✅ Trading loop thread launched.")
    yield
    # Signal stop on shutdown
    _bot_stop_event.set()
    logger.info("🛑 Trading loop thread stopped.")


# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="Simmer Trading Bot API", version="1.0.0", lifespan=lifespan)

DASHBOARD_ORIGIN = os.environ.get("DASHBOARD_ORIGIN", "https://clkhoo5211.github.io")
CRON_SECRET      = os.environ.get("CRON_SECRET", "")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        DASHBOARD_ORIGIN,
        "http://localhost:5500",
        "http://127.0.0.1:5500",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
    ],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
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
    automation_enabled:   bool  | None = None
    strategy_arb:         bool  | None = None
    strategy_mm:          bool  | None = None
    strategy_ai:          bool  | None = None
    strategy_correlation: bool  | None = None
    strategy_weather:     bool  | None = None

    class Config:
        extra = "allow"   # allow new strategy_* keys without changing this model


class CredentialsUpdate(BaseModel):
    # Allow any fields from the dynamic schema
    class Config:
        extra = "allow"


# Runtime config — loaded from Redis on cold start, falls back to defaults.
# Strategy toggles come from the registry so new strategies only need to be added there.
_DEFAULTS = {
    "default_venue":        os.environ.get("DEFAULT_VENUE", "polymarket_paper"),
    "max_trade_usd":        MAX_TRADE,
    "max_daily_usd":        MAX_DAILY,
    "min_arb_edge":         float(os.environ.get("MIN_ARB_EDGE", "0.015")),
    "automation_enabled":   False,   # ← must be turned ON from dashboard
    **config_defaults(),   # strategy_arb, strategy_mm, strategy_ai, strategy_correlation, strategy_weather, ...
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


def _polymarket_paper_market_ids(limit: int = 500) -> set:
    """Polymarket market IDs from Gamma (for filtering paper positions/trades)."""
    try:
        from core.gamma_markets import get_gamma_markets
        mkts = get_gamma_markets(status="active", limit=limit)
        return {m["id"] for m in mkts}
    except Exception:
        return set()


# ── Portfolio ─────────────────────────────────────────────────────────────────
@app.get("/api/portfolio")
def get_portfolio(venue: str = ""):
    v = venue or _config["default_venue"]
    
    if v == "polymarket_paper":
        v = "simmer"  # use Simmer paper balance
    if v == "polymarket":
        try:
            from core.polymarket_native import get_native_portfolio
            logger.info("Attempting native Polymarket API calculation...")
            return get_native_portfolio()
        except Exception as e:
            logger.warning(f"Native Polymarket failed, falling back to simmer-sdk: {e}")

    # --- Simmer SDK Fallback / Default for 'simmer' venue ---
    try:
        client    = get_client(v)
        portfolio = client.get_portfolio()
        total_pnl = client.get_total_pnl()
        logger.info(f"📊 Portfolio for {v}: balance={portfolio.get('balance_usdc')}, pnl={total_pnl}")
        return {
            "balance_usdc":   portfolio.get("balance_usdc", 0),
            "total_exposure": portfolio.get("total_exposure", 0),
            "total_pnl":      round(total_pnl, 4),
            "daily_spent":    round(daily_spent(), 2),
            "daily_limit":    MAX_DAILY,
            "by_source":      portfolio.get("by_source", {}),
            "positions":      [], # Populated if frontend supports generic
            "source":         "simmer-sdk"
        }
    except Exception as exc:
        logger.error(f"Portfolio fetch failed for {v}: {exc}")
        # Return a partial object so frontend doesn't crash, but status shows issues
        return {
            "error": str(exc),
            "balance_usdc": 0,
            "total_exposure": 0,
            "total_pnl": 0,
            "daily_spent": round(daily_spent(), 2),
            "daily_limit": MAX_DAILY,
            "source": "error-fallback"
        }


# ── Markets ───────────────────────────────────────────────────────────────────
@app.get("/api/markets")
def get_markets(
    venue:         str = "",
    import_source: str = "",
    status:        str = "active",
    limit:         int = 25,
):
    try:
        v = venue or _config["default_venue"]
        
        if v == "polymarket_paper" or v == "polymarket":
            from core.gamma_markets import get_gamma_markets
            return get_gamma_markets(status=status, limit=limit)

        # --- Simmer SDK Fallback ---
        client = get_client(v)
        _src = import_source or None
        mkts   = client.get_markets(status=status, import_source=_src, limit=limit)
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
        v = venue or _config["default_venue"]

        if v == "polymarket_paper":
            def _fetch_paper_positions():
                pm_ids = _polymarket_paper_market_ids()
                client = get_client("simmer")
                positions = client.get_positions()
                return [p for p in positions if p.market_id in pm_ids]
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(_fetch_paper_positions)
                    positions = fut.result(timeout=8)
                logger.info(f"📍 Positions for polymarket_paper: Found {len(positions)} items")
                return [
                    {
                        "market_id": p.market_id, "question": p.question,
                        "shares_yes": round(p.shares_yes, 4), "shares_no": round(p.shares_no, 4),
                        "current_value": round(p.current_value, 4), "pnl": round(p.pnl, 4),
                        "status": p.status,
                    }
                    for p in positions
                ]
            except FuturesTimeoutError:
                logger.warning("Polymarket paper positions timed out after 8s, returning empty")
                return []
            except Exception as e:
                logger.warning(f"Polymarket paper positions failed (show empty): {e}")
                return []
        if v == "polymarket":
            def _fetch_live_positions():
                from core.polymarket_native import get_native_positions
                return get_native_positions()
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(_fetch_live_positions)
                    return fut.result(timeout=8)
            except FuturesTimeoutError:
                logger.warning("Polymarket live positions timed out after 8s, returning empty")
                return []
            except Exception as e:
                logger.warning(f"Native Polymarket get_positions failed: {e}")
                return []

        # Simmer / Fallback
        client = get_client(v)
        try:
            positions = client.get_positions()
            logger.info(f"📍 Positions for {v}: Found {len(positions)} items")
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
        except Exception as e:
            logger.error(f"Failed to fetch positions for {v}: {e}")
            return {"error": str(e), "positions": []}
    except Exception as exc:
        logger.error(f"Outer positions error: {exc}")
        return {"error": str(exc), "positions": []}


def get_simmer_trades():
    """Fetch history from Simmer API (combining active & resolved positions)."""
    try:
        client = get_client("simmer")
        history = []
        
        # 1. Fetch RESOLVED positions
        try:
            res_data = client._request("GET", "/api/sdk/positions", params={"status": "resolved", "limit": 100})
            resolved_positions = res_data.get("positions", [])
            for p in resolved_positions:
                history.append({
                    "time": "RESOLVED",
                    "market_id": p.get("market_id", "???"),
                    "question": p.get("question", "Unknown Market"),
                    "side": "yes" if p.get("shares_yes", 0) > 0 else "no",
                    "amount": p.get("cost_basis", 0) or 10.0,
                    "shares": p.get("shares_yes", 0) or p.get("shares_no", 0),
                    "status": "resolved"
                })
        except Exception as e:
            logger.warning(f"Failed to fetch resolved positions for history: {e}")

        # 2. Fetch ACTIVE positions (Simmer History tab shows active buys too)
        try:
            act_data = client._request("GET", "/api/sdk/positions", params={"status": "active", "limit": 100})
            active_positions = act_data.get("positions", [])
            for p in active_positions:
                history.append({
                    "time": p.get("created_at", "RECENT")[-8:] if p.get("created_at") else "ACTIVE",
                    "market_id": p.get("market_id", "???"),
                    "question": p.get("question", "Unknown Market"),
                    "side": "yes" if p.get("shares_yes", 0) > 0 else "no",
                    "amount": p.get("cost_basis", 0) or 10.0,
                    "shares": p.get("shares_yes", 0) or p.get("shares_no", 0),
                    "status": "executed"
                })
        except Exception as e:
            logger.warning(f"Failed to fetch active positions for history: {e}")
            
        logger.info(f"📜 Combined History for Simmer: Found {len(history)} items")
        return history
    except Exception as e:
        logger.error(f"Fatal error in get_simmer_trades: {e}")
        return []

# ── Trade History (paginated: limit=20, offset=0) ─────────────────────────────
@app.get("/api/trades")
def get_trades(venue: str = "", limit: int = 20, offset: int = 0):
    v = venue or _config["default_venue"]
    limit = min(max(1, limit), 50)
    offset = max(0, offset)

    if v == "polymarket_paper":
        def _fetch_paper_trades():
            pm_ids = _polymarket_paper_market_ids()
            history = get_simmer_trades()
            filtered = [t for t in history if t.get("market_id") in pm_ids]
            total = len(filtered)
            page = filtered[offset : offset + limit]
            # Normalize: ensure title + shares for dashboard (paper may send question)
            for row in page:
                if "title" not in row and "question" in row:
                    row["title"] = row["question"]
                if "shares" not in row:
                    row["shares"] = row.get("shares_yes") or row.get("shares_no") or None
            return {"trades": page, "total": total}
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_fetch_paper_trades)
                return fut.result(timeout=8)
        except FuturesTimeoutError:
            logger.warning("Polymarket paper trades timed out after 8s, returning empty")
            return {"trades": [], "total": 0}
        except Exception as e:
            logger.warning(f"Polymarket paper trades failed (show empty): {e}")
            return {"trades": [], "total": 0}
    if v == "polymarket":
        try:
            from core.polymarket_native import get_native_trades
            page = get_native_trades(limit=limit, offset=offset)
            # Polymarket API does not return total count; frontend uses hasMore = (len == limit)
            return {"trades": page, "total": None}
        except Exception as e:
            logger.warning(f"Native Polymarket trades failed: {e}")
            return {"trades": [], "total": None}

    # Simmer (non-paper): paginate in memory
    full = get_simmer_trades()
    for row in full:
        if "title" not in row and "question" in row:
            row["title"] = row["question"]
    total = len(full)
    page = full[offset : offset + limit]
    return {"trades": page, "total": total}


# ── Price History ─────────────────────────────────────────────────────────────
@app.get("/api/markets/{market_id}/history")
def get_price_history(market_id: str, venue: str = ""):
    try:
        v = venue or _config["default_venue"]
        if v == "polymarket_paper":
            v = "simmer"
        client = get_client(v)
        return client.get_price_history(market_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Manual Trade ──────────────────────────────────────────────────────────────
@app.post("/api/trade")
def manual_trade(req: TradeRequest):
    try:
        v      = req.venue or _config["default_venue"]
        ok, reason = check_limits(req.amount)
        if not ok:
            raise HTTPException(status_code=400, detail=reason)

        # 1. Polymarket paper: Simmer paper trades (Polymarket-imported markets only)
        if v == "polymarket_paper":
            client = get_client("simmer")
            result = client.trade(
                market_id=req.market_id, side=req.side, amount=req.amount,
                reasoning=req.reasoning or None, source="sdk:manual",
            )
            if not result or not result.success:
                raise HTTPException(
                    status_code=400,
                    detail=getattr(result, "error", "Trade failed") or "Trade returned no result",
                )
            return {
                "trade_id": result.trade_id, "market_id": result.market_id, "side": result.side,
                "shares_bought": round(result.shares_bought, 4), "cost": result.cost,
                "order_status": "paper", "new_price": getattr(result, "new_price", None),
            }
        # 2. Native live Polymarket
        if v == "polymarket":
            try:
                from core.polymarket_native import place_native_order
                logger.info("Redirecting to native Polymarket order placement...")
                resp = place_native_order(req.market_id, req.side, req.amount)
                
                # Persistent history log for native trades
                return {
                    "trade_id":      resp.get("id"), # Assuming 'id' is the trade ID
                    "market_id":     req.market_id,
                    "side":          req.side,
                    "shares_bought": 0,
                    "cost":          req.amount,
                    "order_status":  "placed",
                    "new_price":     None, # Native Polymarket doesn't return new price directly here
                }
            except Exception as e:
                logger.warning(f"Native Polymarket trade failed, falling back to simmer-sdk: {e}")

        # 3. Simmer SDK Fallback
        client = get_client(v)
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
    # Always re-read from Redis to ensure serverless instances are in sync
    return load_config(_DEFAULTS)


@app.post("/api/config")
def update_config(body: ConfigUpdate):
    for field, val in body.model_dump(exclude_none=True).items():
        _config[field] = val
    save_config(_config)   # ← persist to Upstash Redis so toggles survive cold starts
    logger.info(f"⚙️  Config updated: {body.model_dump(exclude_none=True)}")
    return _config


@app.delete("/api/config")
def delete_config():
    """Reset configuration by deleting the Redis key."""
    from core.store import redis_request, CONFIG_KEY
    if redis_request("del", CONFIG_KEY) is not None:
        # Also reset local in-memory cache to defaults
        global _config
        _config = dict(_DEFAULTS)
        return {"status": "success", "message": "Configuration deleted"}
    raise HTTPException(status_code=500, detail="Failed to delete config from Redis")


@app.get("/api/strategies")
def get_strategies():
    """List all registered strategies (id, config_key, name, default_enabled). Dashboard can use this to render toggles."""
    return [
        {"id": s.id, "config_key": s.config_key, "name": s.name, "default_enabled": s.default_enabled}
        for s in get_all()
    ]


# ── Credentials ───────────────────────────────────────────────────────────────
def _mask(val: str | None) -> str | None:
    """Mask sensitive string — show only last 4 chars."""
    if not val or len(val) < 4:
        return "****" if val else None
    return "****" + val[-4:]


@app.get("/api/settings/schema")
def get_settings_schema():
    """Return the centralized settings definition."""
    return SETTINGS_SCHEMA


@app.get("/api/credentials")
def get_credentials():
    """Return saved credentials with sensitive values masked dynamically."""
    creds = load_credentials()
    
    response = {
        "configured": {}
    }
    
    # Iterate through Categories
    for category in SETTINGS_SCHEMA:
        cat_id = category["id"]
        any_field_set = False
        
        # Iterate through fields in this category
        for field in category["fields"]:
            fid = field["id"]
            
            # 1. Get value (Redis -> Env fallback)
            val = creds.get(fid)
            if not val and "env" in field:
                val = os.environ.get(field["env"])
                
            # 2. Track if category is configured
            if val:
                any_field_set = True
                
            # 3. Mask if secret
            if val and field.get("secret"):
                response[fid] = _mask(val)
            else:
                response[fid] = val
                
        response["configured"][cat_id] = any_field_set
        
    return response


@app.post("/api/credentials")
def update_credentials(body: CredentialsUpdate):
    """Save API credentials to Redis. Only provided fields are updated."""
    existing = load_credentials()
    updates  = body.model_dump(exclude_none=True)
    existing.update(updates)
    save_credentials(existing)
    logger.info(f"🔑 Credentials updated: {list(updates.keys())}")
    return {"ok": True, "updated": list(updates.keys())}


# ── Arb Scan (read-only) ──────────────────────────────────────────────────────
@app.get("/api/arb/scan")
def arb_scan(venue: str = ""):
    from strategies.arb_yesno import scan_yesno_arb
    v = venue or _config["default_venue"]
    if v == "polymarket_paper":
        v = "simmer"
    return scan_yesno_arb(v)


# ── Cron Endpoints (called by Vercel scheduler) ───────────────────────────────
def _automation_check():
    """Returns a skip-response dict if master automation is off, else None."""
    global _config
    _config = load_config(_DEFAULTS) # Refresh from Redis for every cron run
    
    if not _config.get("automation_enabled"):
        return {"skipped": "automation disabled — enable in dashboard"}
    if stop_loss_triggered():
        return {"skipped": "stop loss active"}
    return None


def _effective_venue() -> str:
    v = _config.get("default_venue", "polymarket_paper")
    return "simmer" if v == "polymarket_paper" else v


@app.get("/cron/arb", dependencies=[Depends(verify_cron)])
def cron_arb():
    skip = _automation_check()
    if skip: return skip
    s = get_by_id("arb")
    if not s or not _config.get(s.config_key):
        return {"skipped": "strategy disabled"}
    results = s.run(_effective_venue(), _config)
    if results:
        send_telegram_message(f"💰 <b>Arb Cycle Complete</b> ({_config['default_venue']})\nResults: {len(results)} opportunities executed.")
    return {"results": results if isinstance(results, list) else [results]}


@app.get("/cron/correlation", dependencies=[Depends(verify_cron)])
def cron_correlation():
    skip = _automation_check()
    if skip: return skip
    s = get_by_id("correlation")
    if not s or not _config.get(s.config_key):
        return {"skipped": "strategy disabled"}
    results = s.run(_effective_venue(), _config)
    if results:
        send_telegram_message(f"📊 <b>Correlation Cycle Complete</b> ({_config['default_venue']})\nMatched: {len(results)} pairs.")
    return {"results": results if isinstance(results, list) else [results]}


@app.get("/cron/ai-prob", dependencies=[Depends(verify_cron)])
def cron_ai_prob():
    skip = _automation_check()
    if skip: return skip
    s = get_by_id("ai")
    if not s or not _config.get(s.config_key):
        return {"skipped": "strategy disabled"}
    results = s.run(_effective_venue(), _config)
    if results:
        send_telegram_message(f"🧠 <b>AI Probability Cycle Complete</b> ({_config['default_venue']})")
    return {"results": results if isinstance(results, list) else [results]}


@app.get("/cron/market-making", dependencies=[Depends(verify_cron)])
def cron_market_making():
    skip = _automation_check()
    if skip: return skip
    s = get_by_id("mm")
    if not s or not _config.get(s.config_key):
        return {"skipped": "strategy disabled"}
    results = s.run(_effective_venue(), _config)
    if results:
        send_telegram_message(f"⚖️ <b>Market Making Complete</b> ({_config['default_venue']})\nMarkets: {len(results)}")
    return {"results": results if isinstance(results, list) else [results]}


@app.get("/cron/weather", dependencies=[Depends(verify_cron)])
def cron_weather():
    skip = _automation_check()
    if skip: return skip
    s = get_by_id("weather")
    if not s or not _config.get(s.config_key):
        return {"skipped": "strategy disabled"}
    result = s.run(_effective_venue(), _config)
    return result if isinstance(result, dict) else {"results": result}
