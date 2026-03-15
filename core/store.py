"""
core/store.py
─────────────────────────────────────────────────────────────────────────────
Thin wrapper around Upstash Redis REST API for persistent config storage.

Requires two environment variables in Vercel:
  UPSTASH_REDIS_REST_URL   — e.g. https://xxxx.upstash.io
  UPSTASH_REDIS_REST_TOKEN — your Upstash REST token

Get them free at https://upstash.com (no credit card, 10k commands/day free).
If these env vars are not set, falls back to in-memory config (no error).
"""
import os
import json
import requests
from loguru import logger

CONFIG_KEY = "simmer:config"
_TIMEOUT   = 3   # seconds — fast enough for serverless cold start


def redis_request(command: str, *args):
    """Call the Upstash Redis REST API with a command and arguments.

    Correct format: POST {base_url} with body ["COMMAND", "arg1", "arg2", ...]
    Vercel's Upstash integration sets KV_REST_API_URL and KV_REST_API_TOKEN.
    """
    # Vercel's native Upstash Redis integration sets these env vars:
    url   = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL")
    token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
    if not url or not token:
        return None  # Redis not configured — graceful fallback
    try:
        # Upstash REST API: the full command + args goes in the POST body
        resp = requests.post(
            url,                              # base URL only (no path suffix)
            json=[command] + list(args),      # e.g. ["set", "simmer:config", "{...}"]
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
        )
        if resp.ok:
            return resp.json().get("result")
        else:
            logger.warning(f"Redis error {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        logger.warning(f"Redis request failed: {exc}")
    return None


def load_config(defaults: dict) -> dict:
    """
    Load saved config from Redis.
    If Redis is not configured or the key doesn't exist, returns defaults.
    Stored values are merged on top of defaults so new keys always have a value.
    """
    raw = redis_request("get", CONFIG_KEY)
    if raw:
        try:
            stored = json.loads(raw)
            merged = {**defaults, **stored}
            logger.info("Config loaded from Redis.")
            return merged
        except Exception as exc:
            logger.warning(f"Failed to parse Redis config: {exc}")
    return dict(defaults)


def save_config(config: dict) -> bool:
    """
    Persist the current config dict to Redis.
    Returns True on success, False if Redis is unavailable.
    """
    result = redis_request("set", CONFIG_KEY, json.dumps(config))
    if result == "OK":
        logger.info("Config saved to Redis.")
        return True
    logger.warning("Config NOT saved to Redis (Redis may not be configured).")
    return False

CREDENTIALS_KEY = "simmer:credentials"


def load_credentials() -> dict:
    """Load saved API credentials from Redis. Returns empty dict if not set."""
    raw = redis_request("get", CREDENTIALS_KEY)
    if raw:
        try:
            return json.loads(raw)
        except Exception as exc:
            logger.warning(f"Failed to parse Redis credentials: {exc}")
    return {}


def save_credentials(creds: dict) -> bool:
    """Save API credentials to Redis. Returns True on success."""
    result = redis_request("set", CREDENTIALS_KEY, json.dumps(creds))
    if result == "OK":
        logger.info("Credentials saved to Redis.")
        return True
    logger.warning("Credentials NOT saved to Redis.")
    return False
