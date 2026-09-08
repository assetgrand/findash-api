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

def _env(*names: str) -> str:
    """Pierwsza niepusta zmienna; obcina spacje i otaczające cudzysłowy."""
    for n in names:
        v = os.environ.get(n)
        if v is None:
            continue
        v = str(v).strip().strip('"').strip("'")
        if v:
            return v
    return ""


SUPABASE_URL = _env("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL").rstrip("/")
SUPABASE_ANON = _env("SUPABASE_ANON_KEY", "SUPABASE_ANON", "NEXT_PUBLIC_SUPABASE_ANON_KEY")
SUPABASE_SERVICE = _env("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SERVICE_KEY", "SUPABASE_SERVICE_ROLE")
SUPABASE_JWT_SECRET = _env("SUPABASE_JWT_SECRET", "JWT_SECRET", "SUPABASE_JWT")
AUTH_REQUIRED = (os.environ.get("AUTH_REQUIRED", "1") or "1").strip() in ("1", "true", "True", "yes")
DEV_AUTH_BYPASS = (os.environ.get("DEV_AUTH_BYPASS", "0") or "0").strip() in ("1", "true", "True", "yes")


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


def supabase_status() -> dict:
    """Do /health – co jest ustawione (bez wartości sekretów)."""
    return {
        "url_set": bool(SUPABASE_URL),
        "url_looks_ok": SUPABASE_URL.startswith("https://") and "supabase.co" in SUPABASE_URL,
        "anon_key_set": bool(SUPABASE_ANON),
        "service_role_key_set": bool(SUPABASE_SERVICE),
        "jwt_secret_set": bool(SUPABASE_JWT_SECRET),
        "configured": supabase_configured(),
        "hint": (
            None
            if supabase_configured()
            else "Brakuje: "
            + ", ".join(
                x
                for x, ok in [
                    ("SUPABASE_URL", bool(SUPABASE_URL)),
                    ("SUPABASE_ANON_KEY lub SUPABASE_SERVICE_ROLE_KEY", bool(SUPABASE_ANON or SUPABASE_SERVICE)),
                    ("SUPABASE_JWT_SECRET", bool(SUPABASE_JWT_SECRET)),
                ]
                if not ok
            )
        ),
    }


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
        "trusted_ip": {
            "enabled": TRUSTED_IP_ENABLED,
            "mode": TRUSTED_IP_MODE,
            "max_addresses": MAX_TRUSTED_IPS,
            "current_ip_trusted": bool(prof.get("_ip_trusted", True)),
            "is_new_ip": bool(prof.get("_ip_new", False)),
            "trusted_count": int(prof.get("_ip_count") or 0),
            "message": prof.get("_ip_message"),
        },
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


# ---------------------------------------------------------------------------
# Zaufane adresy IP (anti account-sharing, miękki tryb domyślnie)
# ---------------------------------------------------------------------------
# Env:
#   TRUSTED_IP_ENABLED=1          – włącz (domyślnie 1)
#   TRUSTED_IP_MODE=soft|strict   – soft: dodaj/rotuj; strict: blokuj 4. nowe IP
#   MAX_TRUSTED_IPS=3
#
# Supabase (opcjonalnie, SQL w dashboardzie):
#   create table public.trusted_addresses (
#     user_id uuid not null,
#     ip_hash text not null,
#     ip_hint text,
#     first_seen timestamptz default now(),
#     last_seen timestamptz default now(),
#     primary key (user_id, ip_hash)
#   );
# ---------------------------------------------------------------------------

import hashlib
import json
from pathlib import Path as _Path

TRUSTED_IP_ENABLED = (os.environ.get("TRUSTED_IP_ENABLED", "1") or "1").strip() in (
    "1", "true", "True", "yes",
)
TRUSTED_IP_MODE = (os.environ.get("TRUSTED_IP_MODE", "soft") or "soft").strip().lower()
if TRUSTED_IP_MODE not in ("soft", "strict"):
    TRUSTED_IP_MODE = "soft"
MAX_TRUSTED_IPS = int(os.environ.get("MAX_TRUSTED_IPS", "3"))
_TRUST_FILE = _Path(os.environ.get("TRUSTED_IP_FILE", "/tmp/findash_trusted_ips.json"))


def _hash_ip(ip: str) -> str:
    raw = (ip or "").strip().lower()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _ip_hint(ip: str) -> str:
    """Krótki podgląd bez pełnego IP w logach UI (np. 203.0.*.*)."""
    parts = (ip or "").split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.*.*"
    if ":" in (ip or ""):
        return (ip or "")[:10] + "…"
    return "***"


def _load_local_store() -> Dict[str, Any]:
    try:
        if _TRUST_FILE.exists():
            return json.loads(_TRUST_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print("trusted_ip load", e)
    return {}


def _save_local_store(data: Dict[str, Any]) -> None:
    try:
        _TRUST_FILE.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        print("trusted_ip save", e)


def _fetch_trusted_rows(user_id: str) -> List[Dict[str, Any]]:
    """Z Supabase lub pliku lokalnego."""
    if SUPABASE_URL and SUPABASE_SERVICE:
        try:
            url = (
                f"{SUPABASE_URL}/rest/v1/trusted_addresses"
                f"?user_id=eq.{user_id}&select=ip_hash,ip_hint,first_seen,last_seen&order=last_seen.asc"
            )
            r = requests.get(url, headers=_sb_headers(True), timeout=12)
            if r.status_code == 200:
                rows = r.json()
                if isinstance(rows, list):
                    return rows
            # tabela może nie istnieć – fallback
            if r.status_code in (404, 400, 406):
                print("trusted_addresses table?", r.status_code, r.text[:120])
        except Exception as e:
            print("trusted_ip supabase fetch", e)

    store = _load_local_store()
    rows = store.get(str(user_id), [])
    if isinstance(rows, list):
        return rows
    return []


def _upsert_trusted(user_id: str, ip_hash: str, ip_hint: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    if SUPABASE_URL and SUPABASE_SERVICE:
        try:
            url = f"{SUPABASE_URL}/rest/v1/trusted_addresses"
            # upsert
            headers = dict(_sb_headers(True))
            headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
            r = requests.post(
                url,
                headers=headers,
                json={
                    "user_id": user_id,
                    "ip_hash": ip_hash,
                    "ip_hint": ip_hint,
                    "last_seen": now,
                },
                timeout=12,
            )
            if r.status_code in (200, 201, 204):
                return
            # update last_seen if exists
            u = (
                f"{SUPABASE_URL}/rest/v1/trusted_addresses"
                f"?user_id=eq.{user_id}&ip_hash=eq.{ip_hash}"
            )
            requests.patch(
                u,
                headers=_sb_headers(True),
                json={"last_seen": now, "ip_hint": ip_hint},
                timeout=12,
            )
            return
        except Exception as e:
            print("trusted_ip supabase upsert", e)

    store = _load_local_store()
    uid = str(user_id)
    rows = list(store.get(uid, []))
    found = False
    for row in rows:
        if row.get("ip_hash") == ip_hash:
            row["last_seen"] = now
            row["ip_hint"] = ip_hint
            found = True
            break
    if not found:
        rows.append(
            {
                "ip_hash": ip_hash,
                "ip_hint": ip_hint,
                "first_seen": now,
                "last_seen": now,
            }
        )
    store[uid] = rows
    _save_local_store(store)


def _delete_trusted(user_id: str, ip_hash: str) -> None:
    if SUPABASE_URL and SUPABASE_SERVICE:
        try:
            url = (
                f"{SUPABASE_URL}/rest/v1/trusted_addresses"
                f"?user_id=eq.{user_id}&ip_hash=eq.{ip_hash}"
            )
            requests.delete(url, headers=_sb_headers(True), timeout=12)
            return
        except Exception as e:
            print("trusted_ip delete", e)
    store = _load_local_store()
    uid = str(user_id)
    rows = [r for r in store.get(uid, []) if r.get("ip_hash") != ip_hash]
    store[uid] = rows
    _save_local_store(store)


def apply_trusted_ip(prof: Dict[str, Any], client_ip: Optional[str]) -> Dict[str, Any]:
    """
    Dołącz info o IP do profilu; w trybie strict rzuć PermissionError przy nadmiarze.
    Miękki: max N adresów, najstarszy wypada; nowe IP = flaga is_new_ip.
    """
    if not TRUSTED_IP_ENABLED:
        prof["_ip_trusted"] = True
        prof["_ip_new"] = False
        prof["_ip_count"] = 0
        return prof

    ip = (client_ip or "").strip()
    if not ip or ip in ("127.0.0.1", "::1", "unknown"):
        # lokal / brak IP – nie karz
        prof["_ip_trusted"] = True
        prof["_ip_new"] = False
        prof["_ip_count"] = 0
        return prof

    uid = str(prof.get("id") or "")
    if not uid or uid == "anonymous":
        return prof

    ip_h = _hash_ip(ip)
    hint = _ip_hint(ip)
    rows = _fetch_trusted_rows(uid)
    hashes = [str(r.get("ip_hash")) for r in rows if r.get("ip_hash")]

    is_new = ip_h not in hashes
    if not is_new:
        _upsert_trusted(uid, ip_h, hint)
        prof["_ip_trusted"] = True
        prof["_ip_new"] = False
        prof["_ip_count"] = len(hashes)
        prof["_ip_message"] = None
        return prof

    # Nowe IP
    if len(hashes) >= MAX_TRUSTED_IPS and TRUSTED_IP_MODE == "strict":
        prof["_ip_trusted"] = False
        prof["_ip_new"] = True
        prof["_ip_count"] = len(hashes)
        prof["_ip_message"] = (
            f"Login from a new network blocked (max {MAX_TRUSTED_IPS} trusted addresses). "
            "Sign in from a known network or contact support."
        )
        raise PermissionError(prof["_ip_message"])

    # soft: rotuj najstarszy
    if len(hashes) >= MAX_TRUSTED_IPS and rows:
        oldest = rows[0]
        old_h = oldest.get("ip_hash")
        if old_h:
            _delete_trusted(uid, str(old_h))
            hashes = [h for h in hashes if h != old_h]

    _upsert_trusted(uid, ip_h, hint)
    prof["_ip_trusted"] = True
    prof["_ip_new"] = True
    prof["_ip_count"] = min(len(hashes) + 1, MAX_TRUSTED_IPS)
    prof["_ip_message"] = (
        "New network detected and added to trusted addresses "
        f"(max {MAX_TRUSTED_IPS}). If this was not you, change your password."
    )
    return prof
