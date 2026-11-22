"""
US Congress STOCK Act disclosures (House + Senate).
Public data via NexusTrade political-disclosures feed (sourced from
official House Clerk PTR / Senate eFD). Cached server-side.
Not investment advice.
"""
from __future__ import annotations

import os
import time
import threading
from typing import Any, Dict, List, Optional

import requests

BASE_URL = os.environ.get(
    "CONGRESS_TRADES_API_BASE",
    "https://nexustrade.io/api/political-disclosures",
).rstrip("/")
CACHE_TTL = int(os.environ.get("CONGRESS_TRADES_CACHE_TTL", "3600"))  # 1h
REQUEST_TIMEOUT = float(os.environ.get("CONGRESS_TRADES_TIMEOUT", "25"))

_CACHE: Dict[str, Any] = {}
_LOCK = threading.Lock()

DISCLAIMER = (
    "Public STOCK Act disclosures (U.S. House Clerk PTR and Senate eFD), "
    "aggregated via a public feed. Amounts are ranges as filed. "
    "Members may disclose up to ~45 days after a trade. "
    "Not investment advice and not a complete portfolio view."
)


def _cache_get(key: str) -> Optional[Any]:
    with _LOCK:
        row = _CACHE.get(key)
        if not row:
            return None
        if time.time() - float(row["ts"]) > CACHE_TTL:
            _CACHE.pop(key, None)
            return None
        return row["data"]


def _cache_set(key: str, data: Any) -> None:
    with _LOCK:
        _CACHE[key] = {"ts": time.time(), "data": data}
        if len(_CACHE) > 200:
            oldest = sorted(_CACHE.items(), key=lambda kv: kv[1]["ts"])[:50]
            for k, _ in oldest:
                _CACHE.pop(k, None)


def _normalize_action(raw: Any) -> str:
    s = str(raw or "").strip().lower()
    if s in ("buy", "purchase", "bought"):
        return "buy"
    if s in ("sell", "sale", "sold", "partial_sale"):
        return "sell"
    if "exchange" in s:
        return "exchange"
    return s or "unknown"


def _normalize_trade(t: Dict[str, Any]) -> Dict[str, Any]:
    action = _normalize_action(t.get("action"))
    ticker = (t.get("ticker") or "").strip().upper()
    if ticker in ("--", "N/A", "NONE"):
        ticker = ""
    amount_bracket = t.get("amountBracket") or t.get("amount_bracket")
    if not amount_bracket:
        lo, hi = t.get("amountLow"), t.get("amountHigh")
        if lo is not None or hi is not None:
            amount_bracket = f"${lo or '?'} – ${hi or '?'}"
    return {
        "id": t.get("eventId") or t.get("id"),
        "member": t.get("filerName") or t.get("member") or "Unknown",
        "chamber": str(t.get("chamber") or "").lower() or None,
        "owner": t.get("owner"),
        "action": action,
        "ticker": ticker or None,
        "asset": t.get("assetDescription") or t.get("asset") or ticker or None,
        "asset_type": t.get("assetTypeLabel") or t.get("asset_type"),
        "transaction_date": t.get("transactionDate") or t.get("transaction_date"),
        "filing_date": t.get("filingDate") or t.get("filing_date"),
        "available_at": t.get("availableAt") or t.get("firstAvailableAt"),
        "amount": amount_bracket,
        "amount_low": t.get("amountLow"),
        "amount_high": t.get("amountHigh"),
        "source_url": t.get("sourceUrl") or t.get("source_url"),
        "partial_sale": bool(t.get("partialSale") or False),
    }


def _fetch_trades(
    *,
    limit: int = 40,
    ticker: Optional[str] = None,
    action: Optional[str] = None,
    chamber: Optional[str] = None,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit), 100))
    params: Dict[str, Any] = {"limit": min(limit * 3, 150)}  # over-fetch then filter
    if ticker:
        params["ticker"] = ticker.strip().upper()

    cache_key = f"trades|{params.get('ticker','')}|{action or ''}|{chamber or ''}|{limit}"
    cached = _cache_get(cache_key)
    if cached is not None:
        out = dict(cached)
        out["cached"] = True
        return out

    url = f"{BASE_URL}/trades"
    try:
        r = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "AssetCoreAlpha/1.0 (research; +https://assetcore)"},
        )
    except Exception as e:
        return {"ok": False, "error": f"network: {e}", "results": [], "count": 0}

    if r.status_code != 200:
        return {
            "ok": False,
            "error": f"upstream {r.status_code}: {r.text[:240]}",
            "results": [],
            "count": 0,
        }

    try:
        payload = r.json()
    except Exception as e:
        return {"ok": False, "error": f"json: {e}", "results": [], "count": 0}

    raw_list: List[Dict[str, Any]] = []
    if isinstance(payload, dict):
        data = payload.get("data") or payload
        if isinstance(data, dict):
            trades = data.get("trades") or data.get("items") or []
        else:
            trades = data if isinstance(data, list) else []
        if isinstance(trades, list):
            raw_list = [x for x in trades if isinstance(x, dict)]
    elif isinstance(payload, list):
        raw_list = [x for x in payload if isinstance(x, dict)]

    rows = [_normalize_trade(t) for t in raw_list]

    if action:
        a = action.strip().lower()
        if a in ("buy", "sell"):
            rows = [x for x in rows if x.get("action") == a]
    if chamber:
        c = chamber.strip().lower()
        if c in ("house", "senate"):
            rows = [x for x in rows if (x.get("chamber") or "") == c]
    if ticker:
        tk = ticker.strip().upper()
        rows = [x for x in rows if (x.get("ticker") or "").upper() == tk]

    rows = rows[:limit]
    out = {
        "ok": True,
        "source": "STOCK Act disclosures (House Clerk / Senate eFD via public feed)",
        "count": len(rows),
        "results": rows,
        "cached": False,
        "disclaimer": DISCLAIMER,
    }
    _cache_set(cache_key, {k: v for k, v in out.items() if k != "cached"})
    return out


def latest_trades(limit: int = 40) -> Dict[str, Any]:
    return _fetch_trades(limit=limit)


def search_trades(
    *,
    ticker: Optional[str] = None,
    action: Optional[str] = None,
    chamber: Optional[str] = None,
    limit: int = 40,
) -> Dict[str, Any]:
    return _fetch_trades(
        limit=limit,
        ticker=ticker,
        action=action,
        chamber=chamber,
    )


def trades_for_ticker(ticker: str, limit: int = 40) -> Dict[str, Any]:
    t = (ticker or "").strip().upper()
    if not t:
        return {"ok": False, "error": "ticker required", "results": [], "count": 0}
    return _fetch_trades(limit=limit, ticker=t)
