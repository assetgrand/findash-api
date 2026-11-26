"""
Przyznane kontrakty federalne USA – USASpending.gov (oficjalne API, bez klucza).

Dokumentacja: https://api.usaspending.gov/
Endpoint search: POST /api/v2/search/spending_by_award/
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

USASPENDING_SEARCH = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
USASPENDING_AUTOCOMPLETE = "https://api.usaspending.gov/api/v2/autocomplete/recipient/"

# A,B,C,D = contract award types (nie granty)
CONTRACT_TYPE_CODES = ["A", "B", "C", "D"]

DEFAULT_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Recipient DUNS Number",
    "Recipient UEI",
    "Award Amount",
    "Total Outlays",
    "Description",
    "Start Date",
    "End Date",
    "Awarding Agency",
    "Awarding Sub Agency",
    "NAICS Code",
    "NAICS Description",
    "Place of Performance State Code",
    "Place of Performance City Name",
    "Contract Award Type",
]

_CACHE: Dict[str, Any] = {}
_CACHE_TTL = 900  # 15 min


def _cache_get(key: str) -> Optional[Any]:
    row = _CACHE.get(key)
    if not row:
        return None
    if time.time() - row["ts"] > _CACHE_TTL:
        return None
    return row["data"]


def _cache_set(key: str, data: Any) -> None:
    _CACHE[key] = {"ts": time.time(), "data": data}
    if len(_CACHE) > 80:
        oldest = sorted(_CACHE.items(), key=lambda kv: kv[1]["ts"])[:20]
        for k, _ in oldest:
            _CACHE.pop(k, None)



# Priority federal agencies (higher strategic weight)
_PRIORITY_AGENCIES = (
    "department of defense",
    "department of energy",
    "department of homeland security",
    "department of veterans affairs",
    "national aeronautics",
    "nasa",
    "department of health",
    "general services administration",
    "department of justice",
    "department of state",
    "department of the treasury",
    "department of commerce",
    "department of transportation",
    "department of the interior",
    "department of agriculture",
    "environmental protection",
    "cybersecurity",
)


def _parse_date(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d")
    except Exception:
        return None


def contract_importance(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Importance 1–3 stars. Recency is NOT used.
    Any single strong signal can push to 3 stars (no need to meet all conditions).
    Signals: award amount, contract duration, priority agency.
    """
    amount = 0.0
    try:
        amount = float(row.get("amount") or 0)
    except Exception:
        amount = 0.0

    start = _parse_date(row.get("start_date"))
    end = _parse_date(row.get("end_date"))
    years = 0.0
    if start and end and end > start:
        years = (end - start).days / 365.25

    agency = str(row.get("agency") or row.get("sub_agency") or "").lower()
    priority = any(p in agency for p in _PRIORITY_AGENCIES)

    # Independent points (OR-friendly stacking, not AND-gate)
    pts = 0
    reasons = []
    if amount >= 100_000_000:
        pts += 3
        reasons.append("amount>=$100M")
    elif amount >= 25_000_000:
        pts += 2
        reasons.append("amount>=$25M")
    elif amount >= 5_000_000:
        pts += 1
        reasons.append("amount>=$5M")

    if years >= 4:
        pts += 2
        reasons.append("duration>=4y")
    elif years >= 2:
        pts += 1
        reasons.append("duration>=2y")

    if priority:
        pts += 1
        reasons.append("priority_agency")

    # Map points → stars (one strong signal enough for ★★★)
    if pts >= 3 or amount >= 50_000_000:
        stars = 3
    elif pts >= 1 or amount >= 1_000_000:
        stars = 2
    else:
        stars = 1

    return {
        "importance": stars,
        "importance_stars": stars,
        "importance_points": pts,
        "importance_reasons": reasons,
    }


def _attach_importance(results: List[Dict[str, Any]], min_stars: int = 1) -> List[Dict[str, Any]]:
    out = []
    min_stars = max(1, min(3, int(min_stars or 1)))
    for row in results:
        if not isinstance(row, dict):
            continue
        meta = contract_importance(row)
        merged = dict(row)
        merged.update(meta)
        if int(merged.get("importance") or 1) >= min_stars:
            out.append(merged)
    # Higher importance first, then amount
    out.sort(
        key=lambda r: (
            int(r.get("importance") or 0),
            float(r.get("amount") or 0),
        ),
        reverse=True,
    )
    return out


def _date_range(days: int) -> List[Dict[str, str]]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(1, min(days, 3650)))
    return [{"start_date": start.isoformat(), "end_date": end.isoformat()}]


def search_awarded_contracts(
    *,
    keywords: Optional[List[str]] = None,
    recipient_name: Optional[str] = None,
    days: int = 30,
    limit: int = 25,
    page: int = 1,
    min_amount: Optional[float] = None,
    min_stars: int = 1,
    sort_by: str = "Start Date",
    order: str = "desc",
) -> Dict[str, Any]:
    """
    Szuka przyznanych kontraktów (nie grantów).
    keywords – frazy w opisie/nazwie (API keywords filter)
    recipient_name – filtr po nazwie odbiorcy (recipient_search_text)
    min_stars – filter importance 1–3
    """
    limit = max(1, min(int(limit), 100))
    page = max(1, int(page))
    days = max(1, min(int(days), 365 * 5))
    min_stars = max(1, min(3, int(min_stars or 1)))

    cache_key = f"aw|{keywords}|{recipient_name}|{days}|{limit}|{page}|{min_amount}|{min_stars}"
    cached = _cache_get(cache_key)
    if cached is not None:
        out = dict(cached)
        out["cached"] = True
        return out

    filters: Dict[str, Any] = {
        "time_period": _date_range(days),
        "award_type_codes": CONTRACT_TYPE_CODES,
    }
    kw: List[str] = []
    if keywords:
        kw.extend([k.strip() for k in keywords if k and str(k).strip()])
    # Nazwa firmy: keywords dziala stabilnie; recipient_search_text bywa kaprysne
    if recipient_name and recipient_name.strip():
        name = recipient_name.strip()
        if name not in kw:
            kw.append(name)
        filters["recipient_search_text"] = [name]
    if kw:
        filters["keywords"] = kw
    if min_amount is not None and min_amount > 0:
        filters["award_amounts"] = [
            {"lower_bound": float(min_amount)}
        ]

    # "Start Date" desc = najnowsze kontrakty; "Award Amount" = największe
    sort_field = sort_by if sort_by in ("Start Date", "Award Amount", "End Date") else "Start Date"
    ord_ = order if order in ("asc", "desc") else "desc"
    payload = {
        "filters": filters,
        "fields": DEFAULT_FIELDS,
        "sort": sort_field,
        "order": ord_,
        "page": page,
        "limit": limit,
    }

    def _post(pl: Dict[str, Any]) -> Dict[str, Any]:
        r = requests.post(
            USASPENDING_SEARCH,
            json=pl,
            headers={"Content-Type": "application/json"},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()

    try:
        raw = _post(payload)
    except requests.RequestException as e:
        # fallback: tylko keywords (bez recipient_search_text)
        if "recipient_search_text" in filters:
            try:
                f2 = {k: v for k, v in filters.items() if k != "recipient_search_text"}
                if not f2.get("keywords") and recipient_name:
                    f2["keywords"] = [recipient_name.strip()]
                pl2 = dict(payload)
                pl2["filters"] = f2
                raw = _post(pl2)
            except requests.RequestException as e2:
                return {
                    "ok": False,
                    "error": str(e2),
                    "results": [],
                    "page": page,
                    "limit": limit,
                    "source": "usaspending.gov",
                }
        else:
            return {
                "ok": False,
                "error": str(e),
                "results": [],
                "page": page,
                "limit": limit,
                "source": "usaspending.gov",
            }

    results_raw = raw.get("results") or []
    results: List[Dict[str, Any]] = []
    for row in results_raw:
        if not isinstance(row, dict):
            continue
        results.append(
            {
                "award_id": row.get("Award ID"),
                "recipient_name": row.get("Recipient Name"),
                "recipient_uei": row.get("Recipient UEI"),
                "amount": row.get("Award Amount"),
                "outlays": row.get("Total Outlays"),
                "description": row.get("Description"),
                "start_date": row.get("Start Date"),
                "end_date": row.get("End Date"),
                "agency": row.get("Awarding Agency"),
                "sub_agency": row.get("Awarding Sub Agency"),
                "naics_code": row.get("NAICS Code"),
                "naics": row.get("NAICS Description"),
                "state": row.get("Place of Performance State Code"),
                "city": row.get("Place of Performance City Name"),
                "award_type": row.get("Contract Award Type"),
            }
        )

    results = _attach_importance(results, min_stars=min_stars)
    out = {
        "ok": True,
        "source": "usaspending.gov",
        "page": page,
        "limit": limit,
        "days": days,
        "filters": {
            "keywords": keywords,
            "recipient_name": recipient_name,
            "min_amount": min_amount,
            "min_stars": min_stars,
        },
        "count": len(results),
        "results": results,
        "cached": False,
        "disclaimer": (
            "Official USASpending.gov awarded federal contracts. "
            "Importance stars (1-3) reflect size, duration and agency weight — not investment advice."
        ),
    }
    _cache_set(cache_key, out)
    return out


def search_by_company_name(name: str, days: int = 365, limit: int = 25, min_stars: int = 1) -> Dict[str, Any]:
    """Skrót: kontrakty dla firmy po nazwie (np. 'Lockheed', 'Microsoft')."""
    return search_awarded_contracts(
        recipient_name=name,
        days=days,
        limit=limit,
        page=1,
        min_stars=min_stars,
    )

def latest_awarded_contracts(days: int = 30, limit: int = 40, min_stars: int = 1) -> Dict[str, Any]:
    """Lista najnowszych przyznanych kontraktów federalnych (bez filtra słowa kluczowego)."""
    return search_awarded_contracts(
        keywords=None,
        recipient_name=None,
        days=days,
        limit=limit,
        page=1,
        min_stars=min_stars,
        sort_by="Start Date",
        order="desc",
    )
