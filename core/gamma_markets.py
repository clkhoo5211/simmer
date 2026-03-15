"""
core/gamma_markets.py
─────────────────────────────────────────────────────────────────────────────
Fetch Polymarket markets from Gamma API. Response shapes follow the official
OpenAPI specs (camelCase):

  • List events:  GET /events  → array of Event (each has markets[], tags[], category, subcategory)
    https://docs.polymarket.com/api-reference/events/list-events
  • List markets: GET /markets → array of Market (each has conditionId, endDate, endDateIso,
    closedTime, tags[], categories[], category, groupItemTitle, slug)
    https://docs.polymarket.com/api-reference/markets/list-markets
  • Sports:       GET /sports/market-types then GET /markets?sports_market_types=...

Params: closed=false, active=true, end_date_min=now. order=endDate, ascending=true.
"""

import json
import requests
from datetime import datetime, timedelta, timezone
from loguru import logger

GAMMA_BASE = "https://gamma-api.polymarket.com"
TIMEOUT = 15


def _now_iso_utc() -> str:
    """Current time in ISO UTC for end_date_min (only future resolution dates)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_resolves_at(iso: str) -> datetime | None:
    """Parse resolves_at ISO string to timezone-aware datetime (UTC). Always returns aware or None so comparisons with cutoff never raise."""
    if not iso:
        return None
    try:
        s = (iso or "").strip()
        if not s:
            return None
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        elif "+" in s or s.count("-") > 2:
            dt = datetime.fromisoformat(s)
        else:
            dt = datetime.fromisoformat(s + "+00:00")
        # Ensure aware: if naive (no tzinfo), treat as UTC so we can compare with cutoff
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# Show only markets that resolve at least this many seconds from now (avoids "active" markets that are already resolved on Polymarket).
RESOLVES_BUFFER_SECONDS = 120


def _parse_prob(market: dict) -> float:
    try:
        raw = market.get("outcomePrices") or market.get("outcome_prices")
        if isinstance(raw, str):
            raw = json.loads(raw) if raw else ["0.5", "0.5"]
        return float(raw[0]) if raw else 0.5
    except Exception:
        return 0.5


def _tag_slugs_from_tags(tags: list) -> list:
    """Extract slug or label from Gamma Tag objects: { id, label, slug }."""
    slugs = []
    for t in tags or []:
        if isinstance(t, dict):
            s = t.get("slug") or t.get("label")
            if s and s not in slugs:
                slugs.append(s)
        elif isinstance(t, str) and t not in slugs:
            slugs.append(t)
    return slugs


def _tag_slugs_from_categories(categories: list) -> list:
    """Extract slug or label from Gamma Category objects: { id, label, slug }."""
    slugs = []
    for c in categories or []:
        if isinstance(c, dict):
            s = c.get("slug") or c.get("label")
            if s and s not in slugs:
                slugs.append(s)
        elif isinstance(c, str) and c not in slugs:
            slugs.append(c)
    return slugs


def _event_tag_slugs(event: dict) -> list:
    """Extract tag slugs from Event (list-events): tags[], categories[], category, subcategory, groupItemTitle."""
    slugs = []
    slugs.extend(_tag_slugs_from_tags(event.get("tags")))
    slugs.extend(_tag_slugs_from_categories(event.get("categories")))
    for s in (event.get("category"), event.get("subcategory"), event.get("groupItemTitle")):
        if s and str(s).strip() and str(s) not in slugs:
            slugs.append(str(s).strip())
    for label in event.get("labels") or []:
        if isinstance(label, str) and label not in slugs:
            slugs.append(label)
        elif isinstance(label, dict) and label.get("label") and label["label"] not in slugs:
            slugs.append(label["label"])
    return slugs


def _event_markets_to_list(events: list, limit: int, *, is_sports: bool = False) -> list:
    """Build flat market list from list-events response. Event and Market use camelCase."""
    out = []
    for e in events:
        tag_slugs = _event_tag_slugs(e)
        for m in e.get("markets", []):
            if len(out) >= limit:
                return out
            if not (m.get("active", True) and not m.get("closed", False)):
                continue
            cid = m.get("conditionId") or m.get("id") or ""
            if not cid:
                continue
            # Merge event-level tags with market-level tags/categories (Market has tags[], categories[])
            m_slugs = _tag_slugs_from_tags(m.get("tags")) + _tag_slugs_from_categories(m.get("categories"))
            if m.get("category") and m["category"] not in m_slugs:
                m_slugs.append(m["category"])
            combined = list(dict.fromkeys(tag_slugs + m_slugs))  # preserve order, no dupes
            # Prefer full ISO datetime so still_active cutoff works (date-only parses as midnight UTC and can drop valid markets)
            resolves = (
                m.get("endDate") or e.get("endDate")
                or m.get("endDateIso") or e.get("endDateIso")
                or m.get("closedTime") or e.get("closedTime")
            )
            out.append({
                "id": cid,
                "question": (m.get("question") or "").strip() or (e.get("title") or "Unknown"),
                "status": "active",
                "current_probability": _parse_prob(m),
                "divergence": None,
                "resolves_at": resolves,
                "import_source": "polymarket",
                "is_sports": is_sports,
                "slug": m.get("slug") or e.get("slug"),
                "tag_slugs": combined,
            })
    return out


def _raw_markets_to_list(markets: list, limit: int, *, is_sports: bool = False) -> list:
    """Build flat market list from list-markets response. Market schema uses camelCase."""
    out = []
    for m in markets:
        if len(out) >= limit:
            break
        if not (m.get("active", True) and not m.get("closed", False)):
            continue
        cid = m.get("conditionId") or m.get("id") or ""
        if not cid:
            continue
        q = (m.get("question") or "").strip()
        if not q:
            continue
        tag_slugs = _tag_slugs_from_tags(m.get("tags")) + _tag_slugs_from_categories(m.get("categories"))
        if m.get("category") and m["category"] not in tag_slugs:
            tag_slugs.append(m["category"])
        if m.get("groupItemTitle") and m["groupItemTitle"] not in tag_slugs:
            tag_slugs.append(m["groupItemTitle"])
        # Prefer full endDate over date-only endDateIso so still_active cutoff works
        resolves = m.get("endDate") or m.get("endDateIso") or m.get("closedTime")
        out.append({
            "id": cid,
            "question": q,
            "status": "active",
            "current_probability": _parse_prob(m),
            "divergence": None,
            "resolves_at": resolves,
            "import_source": "polymarket",
            "is_sports": is_sports,
            "slug": m.get("slug"),
            "tag_slugs": tag_slugs,
        })
    return out


def _sort_by_resolves_asc(markets: list) -> list:
    """Sort by resolves_at ascending (ending soon first)."""
    def key(m):
        s = m.get("resolves_at") or ""
        return (s or "z")  # no date last
    return sorted(markets, key=key)


def get_gamma_markets(status: str = "active", limit: int = 200) -> list:
    """
    Fetch markets from Gamma API: events, /markets, and sports channel.
    - Only active=True, closed=False. Ordered by endDate ascending (ending soon first).
    - Sports from /sports/market-types + /markets?sports_market_types; tagged is_sports=True.
    """
    closed = status != "active"
    seen = set()
    results = []
    order_params = {"order": "endDate", "ascending": True}
    page_size = min(100, max(limit, 50))
    # Only show markets that resolve today or later (so RESOLVES column is current year, not last year)
    end_date_min = _now_iso_utc() if not closed else None

    # 1) List events (per API reference: list-events) with pagination
    if not closed:
        try:
            for offset in (0, page_size, page_size * 2):  # up to 3 pages
                params_events = {
                    "closed": False,
                    "active": True,
                    "limit": page_size,
                    "offset": offset,
                    **order_params,
                }
                if end_date_min:
                    params_events["end_date_min"] = end_date_min
                r = requests.get(
                    f"{GAMMA_BASE}/events",
                    params=params_events,
                    timeout=TIMEOUT,
                )
                r.raise_for_status()
                events = r.json()
                if not events:
                    break
                for item in _event_markets_to_list(events, limit * 3, is_sports=False):
                    if item["id"] not in seen:
                        seen.add(item["id"])
                        results.append(item)
        except Exception as e:
            logger.warning(f"Gamma events fetch failed: {e}")

    # 2) List markets (per API reference: list-markets) with pagination
    try:
        for offset in (0, page_size, page_size * 2):
            params = {
                "limit": page_size,
                "offset": offset,
                **order_params,
            }
            params["closed"] = closed
            if end_date_min:
                params["end_date_min"] = end_date_min
            r = requests.get(f"{GAMMA_BASE}/markets", params=params, timeout=TIMEOUT)
            r.raise_for_status()
            raw = r.json()
            markets = raw if isinstance(raw, list) else raw.get("data", raw.get("markets", []))
            if not markets:
                break
            for item in _raw_markets_to_list(markets, limit * 3, is_sports=False):
                if item["id"] not in seen:
                    seen.add(item["id"])
                    results.append(item)
    except Exception as e:
        logger.warning(f"Gamma markets fetch failed: {e}")

    # 3) Sports channel: same filters, tag is_sports=True for verification
    if not closed:
        try:
            r = requests.get(f"{GAMMA_BASE}/sports/market-types", timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
            types = data.get("marketTypes", [])[:10]
            for st in types:
                if len(results) >= limit * 2:
                    break
                sports_params = {
                    "limit": 50,
                    "sports_market_types": st,
                    "closed": False,
                    **order_params,
                }
                if end_date_min:
                    sports_params["end_date_min"] = end_date_min
                r2 = requests.get(
                    f"{GAMMA_BASE}/markets",
                    params=sports_params,
                    timeout=TIMEOUT,
                )
                if not r2.ok:
                    continue
                raw2 = r2.json()
                for item in _raw_markets_to_list(raw2, limit, is_sports=True):
                    if item["id"] not in seen:
                        seen.add(item["id"])
                        results.append(item)
        except Exception as e:
            logger.debug(f"Gamma sports market types optional fetch: {e}")

    # Drop any that have already resolved or resolve within the buffer (avoids showing "active" markets that are already resolved on Polymarket or about to resolve).
    if not closed:
        now_utc = datetime.now(timezone.utc)
        cutoff = now_utc + timedelta(seconds=RESOLVES_BUFFER_SECONDS)
        def still_active(m):
            r = _parse_resolves_at(m.get("resolves_at") or "")
            return r is not None and r > cutoff
        results = [m for m in results if still_active(m)]

    # Ending-soon first: sort by resolves_at ascending
    results = _sort_by_resolves_asc(results)
    return results[:limit]
