"""
Plany Demo / Standard / Pro + limity + (opcjonalnie) Supabase Auth.

Env:
  AUTH_REQUIRED=1          – wymagaj logowania na chronionych endpointach (domyślnie 1)
  SUPABASE_URL=https://xxx.supabase.co
  SUPABASE_ANON_KEY=...
  SUPABASE_SERVICE_ROLE_KEY=...   (tylko serwer – update profilu / licznik)
  SUPABASE_JWT_SECRET=...         (Settings → API → JWT Secret) do weryfikacji Bearer
  STRIPE_WEBHOOK_SECRET=whsec_...
  STRIPE_PRICE_STANDARD=price_...
  STRIPE_PRICE_PRO=price_...
  DEV_AUTH_BYPASS=1               – lokalnie: nagłówek X-Dev-Email zamiast JWT
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import requests

# ---------------------------------------------------------------------------
# Macierz planów (zgodnie z produktem)
# ---------------------------------------------------------------------------
# Demo:     2× analyze (1M lub 3M) / miesiąc kalendarzowy UTC
# Standard: 1M/3M, fundamenty, tech (w analyze), raporty, strategy backtest, 3Y
# Pro:      Standard + hybrid + signals + portfolio (gdy będzie endpoint)

PLAN_FEATURES: Dict[str, Set[str]] = {
    "demo": {
        "analyze",  # z limitem liczbowym
    },
    "standard": {
        "analyze",
        "rankings",
        "fundamentals",
        "perspective_3y",
        "report",
        "backtest_forecast",
        "backtest_strategy",
        "crypto",  # gdy dodacie endpoint
    },
    "pro": {
        "analyze",
        "rankings",
        "fundamentals",
        "perspective_3y",
        "report",
        "backtest_forecast",
        "backtest_strategy",
        "crypto",
        "hybrid",
        "signals",
        "portfolio",
    },
}

DEMO_ANALYZE_LIMIT = 2
VALID_PLANS = ("demo", "standard", "pro")

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_ANON = os.environ.get("SUPABASE_ANON_KEY") or ""
SUPABASE_SERVICE = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET") or ""
AUTH_REQUIRED = os.environ.get("AUTH_REQUIRED", "1") == "1"
DEV_AUTH_BYPASS = os.environ.get("DEV_AUTH_BYPASS", "0") == "1"


def _month_key() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def plan_allows(plan: str, feature: str) -> bool:
    p = (plan or "demo").lower().strip()
    if p not in PLAN_FEATURES:
        p = "demo"
    return feature in PLAN_FEATURES[p]


def features_for_plan(plan: str) -> List[str]:
    p = (plan or "demo").lower().strip()
    return sorted(PLAN_FEATURES.get(p, PLAN_FEATURES["demo"]))


# ---------------------------------------------------------------------------
# Supabase profiles (REST)
# Tabela: public.profiles
#   id uuid PK (= auth.users.id)
#   email text
#   plan text default 'demo'
#   analyze_count int default 0
#   analyze_month text  -- 'YYYY-MM'
# ---------------------------------------------------------------------------

def _sb_headers(service: bool = True) -> Dict[str, str]:
    key = SUPABASE_SERVICE if service and SUPABASE_SERVICE else SUPABASE_ANON
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def supabase_configured() -> bool:
    return bool(SUPABASE_URL and (SUPABASE_SERVICE or SUPABASE_ANON) and SUPABASE_JWT_SECRET)


def verify_supabase_jwt(token: str) -> Dict[str, Any]:
    """Dekoduje JWT Supabase (HS256, secret z dashboardu)."""
    try:
        import jwt  # PyJWT
    except ImportError as e:
        raise RuntimeError("Zainstaluj PyJWT: pip install PyJWT") from e

    if not SUPABASE_JWT_SECRET:
        raise RuntimeError("Brak SUPABASE_JWT_SECRET")

    payload = jwt.decode(
        token,
        SUPABASE_JWT_SECRET,
        algorithms=["HS256"],
        audience="authenticated",
    )
    uid = payload.get("sub")
    if not uid:
        raise ValueError("Brak sub w JWT")
    return {
        "id": uid,
        "email": payload.get("email") or payload.get("user_metadata", {}).get("email"),
        "role": payload.get("role"),
    }


def fetch_profile(user_id: str) -> Optional[Dict[str, Any]]:
    if not SUPABASE_URL or not SUPABASE_SERVICE:
        return None
    url = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}&select=*"
    r = requests.get(url, headers=_sb_headers(True), timeout=15)
    if r.status_code != 200:
        print("fetch_profile", r.status_code, r.text[:200])
        return None
    rows = r.json()
    if not rows:
        return None
    return rows[0]


def ensure_profile(user_id: str, email: Optional[str] = None) -> Dict[str, Any]:
    """Pobierz profil; jeśli brak – utwórz demo."""
    prof = fetch_profile(user_id)
    if prof:
        return _normalize_month(prof)
    if not SUPABASE_URL or not SUPABASE_SERVICE:
        # lokalny fallback bez bazy
        return {
            "id": user_id,
            "email": email,
            "plan": "demo",
            "analyze_count": 0,
            "analyze_month": _month_key(),
        }
    payload = {
        "id": user_id,
        "email": email,
        "plan": "demo",
        "analyze_count": 0,
        "analyze_month": _month_key(),
    }
    url = f"{SUPABASE_URL}/rest/v1/profiles"
    r = requests.post(url, headers=_sb_headers(True), json=payload, timeout=15)
    if r.status_code not in (200, 201):
        # conflict – spróbuj get
        prof = fetch_profile(user_id)
        if prof:
            return _normalize_month(prof)
        print("ensure_profile create", r.status_code, r.text[:300])
        return payload
    rows = r.json()
    return _normalize_month(rows[0] if isinstance(rows, list) and rows else payload)


def _normalize_month(prof: Dict[str, Any]) -> Dict[str, Any]:
    """Reset licznika analyze przy nowym miesiącu UTC."""
    month = _month_key()
    if str(prof.get("analyze_month") or "") != month:
        prof = dict(prof)
        prof["analyze_count"] = 0
        prof["analyze_month"] = month
        _update_profile(prof["id"], {"analyze_count": 0, "analyze_month": month})
    return prof


def _update_profile(user_id: str, fields: Dict[str, Any]) -> None:
    if not SUPABASE_URL or not SUPABASE_SERVICE:
        return
    url = f"{SUPABASE_URL}/rest/v1/profiles?id=eq.{user_id}"
    r = requests.patch(url, headers=_sb_headers(True), json=fields, timeout=15)
    if r.status_code not in (200, 204):
        print("update_profile", r.status_code, r.text[:200])


def set_plan(user_id: str, plan: str) -> None:
    plan = plan.lower().strip()
    if plan not in VALID_PLANS:
        raise ValueError(f"Nieprawidłowy plan: {plan}")
    _update_profile(user_id, {"plan": plan})


def increment_analyze(user_id: str, current_count: int) -> int:
    new_c = int(current_count) + 1
    _update_profile(user_id, {"analyze_count": new_c, "analyze_month": _month_key()})
    return new_c


def check_analyze_quota(prof: Dict[str, Any]) -> None:
    """Rzuca HTTP-friendly dict jeśli limit Demo wyczerpany."""
    plan = (prof.get("plan") or "demo").lower()
    if plan != "demo":
        return
    cnt = int(prof.get("analyze_count") or 0)
    if cnt >= DEMO_ANALYZE_LIMIT:
        raise PermissionError(
            f"Limit Demo: {DEMO_ANALYZE_LIMIT} analizy 1M/3M na miesiąc. "
            f"Użyto {cnt}. Ulepsz plan Standard lub Pro."
        )


def require_feature(prof: Dict[str, Any], feature: str) -> None:
    plan = (prof.get("plan") or "demo").lower()
    if not plan_allows(plan, feature):
        need = "pro" if feature in ("hybrid", "signals", "portfolio") else "standard"
        raise PermissionError(
            f"Funkcja '{feature}' wymaga planu {need}+ (Twój plan: {plan})."
        )


def remaining_analyze(prof: Dict[str, Any]) -> Optional[int]:
    plan = (prof.get("plan") or "demo").lower()
    if plan != "demo":
        return None  # unlimited
    return max(0, DEMO_ANALYZE_LIMIT - int(prof.get("analyze_count") or 0))


def public_me(prof: Dict[str, Any]) -> Dict[str, Any]:
    plan = (prof.get("plan") or "demo").lower()
    return {
        "id": prof.get("id"),
        "email": prof.get("email"),
        "plan": plan,
        "features": features_for_plan(plan),
        "analyze_count": int(prof.get("analyze_count") or 0),
        "analyze_month": prof.get("analyze_month") or _month_key(),
        "analyze_remaining": remaining_analyze(prof),
        "analyze_limit_demo": DEMO_ANALYZE_LIMIT,
        "plans": {
            "demo": {
                "analyze_per_month": DEMO_ANALYZE_LIMIT,
                "features": features_for_plan("demo"),
            },
            "standard": {
                "features": features_for_plan("standard"),
                "includes": [
                    "1M/3M forecasts",
                    "Fundamental analysis",
                    "Technical analysis",
                    "Report generation",
                    "Strategy backtesting",
                    "3-year risk/chance",
                ],
            },
            "pro": {
                "features": features_for_plan("pro"),
                "includes": [
                    "Everything in Standard",
                    "Hybrid buy/sell signals",
                    "Specialist technical forecast (Hybrid)",
                    "Signals scanner",
                    "Portfolio management simulator",
                ],
            },
        },
    }
