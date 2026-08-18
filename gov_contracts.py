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
) -> Dict[str, Any]:
    """
    Szuka przyznanych kontraktów (nie grantów).
    keywords – frazy w opisie/nazwie (API keywords filter)
    recipient_name – filtr po nazwie odbiorcy (recipient_search_text)
    """
    limit = max(1, min(int(limit), 100))
    page = max(1, int(page))
    days = max(1, min(int(days), 365 * 5))

    cache_key = f"aw|{keywords}|{recipient_name}|{days}|{limit}|{page}|{min_amount}"
    cached = _cache_get(cache_key)
    if cached is not None:
        out = dict(cached)
        out["cached"] = True
        return out

    filters: Dict[str, Any] = {
        "time_period": _date_range(days),
        "award_type_codes": CONTRACT_TYPE_CODES,
    }
    if keywords:
        kw = [k.strip() for k in keywords if k and str(k).strip()]
        if kw:
            filters["keywords"] = kw
    if recipient_name and recipient_name.strip():
        filters["recipient_search_text"] = recipient_name.strip()
    if min_amount is not None and min_amount > 0:
        filters["award_amounts"] = [
            {"lower_bound": float(min_amount)}
        ]

    payload = {
        "filters": filters,
        "fields": DEFAULT_FIELDS,
        "sort": "Award Amount",
        "order": "desc",
        "page": page,
        "limit": limit,
    }

    try:
        r = requests.post(
            USASPENDING_SEARCH,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=45,
        )
        r.raise_for_status()
        raw = r.json()
    except requests.RequestException as e:
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
        },
        "count": len(results),
        "results": results,
        "cached": False,
        "disclaimer": (
            "Dane oficjalne USASpending.gov (przyznane kontrakty federalne). "
            "Nie stanowią rekomendacji inwestycyjnej."
        ),
    }
    _cache_set(cache_key, out)
    return out


def search_by_company_name(name: str, days: int = 365, limit: int = 25) -> Dict[str, Any]:
    """Skrót: kontrakty dla firmy po nazwie (np. 'Lockheed', 'Microsoft')."""
    return search_awarded_contracts(
        recipient_name=name,
        days=days,
        limit=limit,
        page=1,
    )
