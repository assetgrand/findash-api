"""
FastAPI – most łączący dashboard (core_analysis) ze stroną Lovable.
Uruchomienie lokalne:
  export POLYGON_API_KEY="twoj_klucz"
  uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import os
import time
import threading
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import auth_plans as auth

# --- import logiki analitycznej (bez GUI) ---
import core_analysis as core

API_BUILD = "signals-cache-v1"
import hybrid_engine as hybrid
import report_engine as reports
import gov_contracts as gov

# Klucz: najpierw ENV (produkcja), potem stała z core
if os.environ.get("TWELVE_DATA_API_KEY"):
    core.TWELVE_DATA_API_KEY = os.environ["TWELVE_DATA_API_KEY"].strip()
    core.POLYGON_API_KEY = core.TWELVE_DATA_API_KEY
elif os.environ.get("POLYGON_API_KEY"):
    core.POLYGON_API_KEY = os.environ["POLYGON_API_KEY"].strip()
    core.TWELVE_DATA_API_KEY = core.POLYGON_API_KEY

app = FastAPI(
    title="FinDash Analysis API",
    description="API pod frontend Lovable – prognozy 1M/3M, fundamenty, perspektywa 3Y.",
    version="1.0.0",
)

# Domeny Lovable + lokalny preview. Na produkcji dopisz swoją domenę.
DEFAULT_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "https://lovable.dev",
    "https://lovable.app",
]
extra = os.environ.get("CORS_ORIGINS", "")
allow_origins = DEFAULT_ORIGINS + [o.strip() for o in extra.split(",") if o.strip()]
# W MVP często wygodniej: "*" (bez credentials). Na produkcję zawęź listę.
if os.environ.get("CORS_ALLOW_ALL", "1") == "1":
    allow_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Auth + plany (Demo / Standard / Pro)
# ---------------------------------------------------------------------------
async def get_profile(
    authorization: Optional[str] = Header(None),
    x_dev_email: Optional[str] = Header(None, alias="X-Dev-Email"),
) -> Dict[str, Any]:
    """
    Wymaga Bearer <supabase_access_token> gdy AUTH_REQUIRED=1.
    Lokalnie: DEV_AUTH_BYPASS=1 + nagłówek X-Dev-Email.
    """
    if not auth.AUTH_REQUIRED:
        return {
            "id": "anonymous",
            "email": None,
            "plan": "pro",  # tryb otwarty – tylko dev
            "analyze_count": 0,
            "analyze_month": auth._month_key(),
        }

    # Dev bypass
    if auth.DEV_AUTH_BYPASS and x_dev_email:
        uid = "dev-" + str(abs(hash(x_dev_email.lower().strip())) % (10**12))
        return auth.ensure_profile(uid, email=x_dev_email.strip())

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Wymagane logowanie (Authorization: Bearer <token>).",
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        user = auth.verify_supabase_jwt(token)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Nieprawidłowy token: {e}")
    try:
        return auth.ensure_profile(user["id"], email=user.get("email"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profil: {e}")


def _gate(prof: Dict[str, Any], feature: str) -> None:
    try:
        auth.require_feature(prof, feature)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


class AnalyzeResponse(BaseModel):
    ticker: str
    horizon: str
    days_forward: int
    current_price: Optional[float] = None
    price_as_of: Optional[str] = None  # data ostatniego zamknięcia (Polygon daily)
    predicted_price: Optional[float] = None
    predicted_change_pct: Optional[float] = None
    direction: str = "NEUTRALNY"
    rsi: Optional[float] = None
    sector: str = "Unknown"
    fundamental_rating: Optional[str] = None
    combined_score: Optional[float] = None
    hit_rate: Optional[float] = None
    mae: Optional[float] = None
    n_significant: Optional[int] = None
    cached: Optional[bool] = None
    analyze_remaining: Optional[int] = None
    plan: Optional[str] = None
    disclaimer: str = (
        "To narzędzie analityczne, nie rekomendacja inwestycyjna. "
        "Prognozy oparte na modelu historycznym; nie uwzględniają zdarzeń losowych."
    )


class RankingItem(BaseModel):
    ticker: str
    current_price: Optional[float] = None
    predicted_change_pct: Optional[float] = None
    direction: str = "NEUTRALNY"
    sector: str = "Unknown"
    fundamental_rating: Optional[str] = None
    hit_rate: Optional[float] = None


class RankingsResponse(BaseModel):
    horizon: str
    items: List[RankingItem]
    disclaimer: str = AnalyzeResponse.model_fields["disclaimer"].default


def _horizon_days(horizon: str) -> int:
    h = (horizon or "1M").upper().strip()
    if h in ("3M", "3", "90", "63"):
        return 63
    return 21


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except Exception:
        return None


# Cache (TTL sekundy). Bez tego Free tier Render często timeoutuje.
_ANALYZE_CACHE: Dict[str, Any] = {}

_ANALYZE_CACHE_TTL = int(os.environ.get("ANALYZE_CACHE_TTL", "900"))  # 15 min

# Signals: wynik skanu trzymany na serwerze – strona tylko czyta (komercyjnie)
# Hybrid stoi na świecach dziennych → 1h domyślnie; na produkcję można 6h/24h (SIGNALS_CACHE_TTL)
_SIGNALS_CACHE: Dict[str, Any] = {}
_SIGNALS_LOCK = threading.Lock()
_SIGNALS_CACHE_TTL = int(os.environ.get("SIGNALS_CACHE_TTL", "3600"))  # 1h


# ============================================================
# PRECOMPUTE + KEEP-ALIVE
# Nie zmienia silnika analizy – tylko woła _analyze_one w tle
# i trzyma wyniki gotowe dla Lovable.
# ============================================================
_PRECOMPUTE_ENABLED = os.environ.get("PRECOMPUTE_ENABLED", "0") == "1"
_PRECOMPUTE_INTERVAL = int(os.environ.get("PRECOMPUTE_INTERVAL", "7200"))  # pełna runda co 10 min
_PRECOMPUTE_PAUSE = float(os.environ.get("PRECOMPUTE_PAUSE", "1.0"))
_PRECOMPUTE: Dict[str, Any] = {}  # "NVDA|1M" -> {"ts": float, "data": dict}
_PRECOMPUTE_LOCK = threading.Lock()
_PRECOMPUTE_STATUS: Dict[str, Any] = {
    "running": False,
    "last_full_run_ts": None,
    "last_ticker": None,
    "last_error": None,
    "tickers_done": 0,
    "tickers_total": 0,
    "started_ts": None,
}


def _pc_key(ticker: str, horizon_label: str) -> str:
    return f"{str(ticker).upper()}|{horizon_label}"


def _pc_store(ticker: str, horizon_label: str, data: Dict[str, Any]) -> None:
    with _PRECOMPUTE_LOCK:
        _PRECOMPUTE[_pc_key(ticker, horizon_label)] = {
            "ts": time.time(),
            "data": dict(data),
        }


def _pc_get(ticker: str, horizon_label: str, max_age: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Zwraca skopiowane data lub None. max_age domyślnie 2x interval."""
    if max_age is None:
        max_age = float(_PRECOMPUTE_INTERVAL) * 2.5
    with _PRECOMPUTE_LOCK:
        row = _PRECOMPUTE.get(_pc_key(ticker, horizon_label))
        if not row:
            return None
        if time.time() - row["ts"] > max_age:
            return None
        return dict(row["data"])


def _ticker_list_for_precompute() -> List[str]:
    raw = list(getattr(core, "tickers", []) or [])
    priority = [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA",
        "JPM", "V", "JNJ", "UNH", "COST", "GS", "AMD", "INTC",
    ]
    if not raw:
        raw = list(priority)
    seen = set()
    out = []
    for t in priority + raw:
        t = str(t).upper().strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _precompute_all_once() -> None:
    """Jedna pełna runda 1M+3M – tylko _analyze_one, bez zmiany logiki."""
    tickers = _ticker_list_for_precompute()
    _PRECOMPUTE_STATUS["running"] = True
    _PRECOMPUTE_STATUS["tickers_total"] = len(tickers)
    _PRECOMPUTE_STATUS["tickers_done"] = 0
    _PRECOMPUTE_STATUS["last_error"] = None
    if _PRECOMPUTE_STATUS.get("started_ts") is None:
        _PRECOMPUTE_STATUS["started_ts"] = time.time()
    print(f"[precompute] start {len(tickers)} tickerów × 1M/3M")
    for t in tickers:
        _PRECOMPUTE_STATUS["last_ticker"] = t
        for hz in ("1M", "3M"):
            try:
                data = _analyze_one(t, hz, fast=True, quality=False)
                if data and data.get("current_price") is not None:
                    _pc_store(t, hz, data)
            except Exception as e:
                msg = f"{t}/{hz}: {e}"
                print("[precompute]", msg)
                _PRECOMPUTE_STATUS["last_error"] = msg
        _PRECOMPUTE_STATUS["tickers_done"] = _PRECOMPUTE_STATUS.get("tickers_done", 0) + 1
        time.sleep(_PRECOMPUTE_PAUSE)
    # Po prognozach 1M/3M – odśwież board sygnałów (raz na rundę, nie per user refresh)
    try:
        _precompute_signals_once()
    except Exception as e:
        print("[precompute] signals:", e)

    _PRECOMPUTE_STATUS["last_full_run_ts"] = time.time()
    _PRECOMPUTE_STATUS["running"] = False
    with _PRECOMPUTE_LOCK:
        n = len(_PRECOMPUTE)
    print(f"[precompute] done, entries={n}")


def _precompute_worker() -> None:
    time.sleep(2)  # API wstaje – od razu pierwsza runda (po cold start)
    while True:
        if not _PRECOMPUTE_ENABLED:
            time.sleep(30)
            continue
        try:
            _precompute_all_once()
        except Exception as e:
            print("[precompute] worker error:", e)
            _PRECOMPUTE_STATUS["last_error"] = str(e)
            _PRECOMPUTE_STATUS["running"] = False
        time.sleep(_PRECOMPUTE_INTERVAL)




def _analyze_one(
    ticker: str,
    horizon: str = "1M",
    fast: bool = True,
    quality: bool = False,
    sector_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analiza pod Lovable/Render – ZAWSZE z Hit%/MAE (wymagane w produkcie).
    sector_override: np. "Crypto" – NIE mutuje core.sector_mapping (akcje bez zmian).
    """
    ticker = ticker.upper().strip()
    # BTC/USD = 7 znaków; pozwól do 16 (pary krypto)
    if not ticker or len(ticker) > 16:
        raise HTTPException(status_code=400, detail="Nieprawidłowy ticker")

    days = _horizon_days(horizon)
    horizon_label = "3M" if days > 30 else "1M"
    mode = "q" if quality else "std"
    day_key = time.strftime("%Y-%m-%d")
    # v8: izolacja od rankingu krypto / starych wpisów
    cache_key = f"v8|{ticker}|{horizon_label}|{mode}|{day_key}|mp30"
    now = time.time()
    hit = _ANALYZE_CACHE.get(cache_key)
    if hit and now - hit["ts"] < _ANALYZE_CACHE_TTL:
        data = dict(hit["data"])
        data["cached"] = True
        return data

    if sector_override:
        sector = sector_override
    else:
        sector = core.sector_mapping.get(ticker, "Unknown")

    # zawsze 500 dni jak desktop
    df = core.get_historical_prices(ticker, days=500)
    if df is None or getattr(df, "empty", True):
        raise HTTPException(status_code=404, detail=f"Brak danych cenowych dla {ticker}")

    df = core.calculate_indicators_on_df(df)
    if df is None or getattr(df, "empty", True):
        raise HTTPException(status_code=500, detail="Błąd wskaźników technicznych")

    current_price = _safe_float(df["Close"].iloc[-1])
    rsi = _safe_float(df["RSI"].iloc[-1]) if "RSI" in df.columns else None
    # data ostatniej świecy (Polygon daily = ostatnie zamknięcie sesji)
    try:
        last_idx = df.index[-1]
        as_of = last_idx.strftime("%Y-%m-%d") if hasattr(last_idx, "strftime") else str(last_idx)[:10]
    except Exception:
        as_of = None

    fa = None
    fund_rating = None
    combined = None
    try:
        fa = core.get_comprehensive_fundamental_analysis(ticker)
    except Exception as e:
        print(f"fundamental error {ticker}: {e}")
        fa = {"combined_score": 50, "fundamental_rating": None}

    if fa:
        fund_rating = fa.get("fundamental_rating")
        combined = _safe_float(fa.get("combined_score"))

    pred_price, direction, chg = None, "NEUTRALNY", None
    try:
        pred_price, direction, chg = core.predict_with_technical_influence(
            df, fa or {}, days, sector, ticker=ticker, quiet=True
        )
        pred_price = _safe_float(pred_price)
        chg = _safe_float(chg)
    except TypeError:
        try:
            pred_price, direction, chg = core.predict_with_technical_influence(
                df, fa or {}, days, sector
            )
            pred_price = _safe_float(pred_price)
            chg = _safe_float(chg)
        except Exception as e:
            print(f"predict error {ticker}: {e}")
    except Exception as e:
        print(f"predict error {ticker}: {e}")

    # Hit% jak desktop: default max_points=30 (wcześniej 8 → niestabilne 25% na małych próbkach)
    hit_rate = mae = n_sig = None
    max_pts = 40 if quality else 30
    try:
        q = core.backtest_forecast_quality(
            df,
            days_forward=days,
            sector=sector,
            fund_score=combined or 50,
            ticker=ticker,
            max_points=max_pts,
        )
        if q:
            hit_rate = _safe_float(q.get("hit_rate"))
            mae = _safe_float(q.get("mae"))
            n_sig = q.get("n_significant")
    except Exception as e:
        print(f"backtest quality {ticker}: {e}")

    data = {
        "ticker": ticker,
        "horizon": horizon_label,
        "days_forward": days,
        "current_price": round(current_price, 4) if current_price is not None else None,
        "price_as_of": as_of,  # data zamknięcia z Polygon (nie „live tick”)
        "predicted_price": round(pred_price, 4) if pred_price is not None else None,
        "predicted_change_pct": round(chg, 2) if chg is not None else None,
        "direction": direction or "NEUTRALNY",
        "rsi": round(rsi, 2) if rsi is not None else None,
        "sector": sector,
        "fundamental_rating": fund_rating,
        "combined_score": round(combined, 2) if combined is not None else None,
        "hit_rate": hit_rate,
        "mae": mae,
        "n_significant": n_sig,
        "fast_mode": False,
        "cached": False,
    }
    _ANALYZE_CACHE[cache_key] = {"ts": now, "data": data}
    if len(_ANALYZE_CACHE) > 300:
        oldest = sorted(_ANALYZE_CACHE.items(), key=lambda kv: kv[1]["ts"])[:80]
        for k, _ in oldest:
            _ANALYZE_CACHE.pop(k, None)
    return data


@app.on_event("startup")
def _startup():
    key = core.POLYGON_API_KEY or ""
    if not key or key.startswith("WPISZ") or len(key) < 10:
        print("⚠️  Ustaw POLYGON_API_KEY w zmiennych środowiskowych!")
    else:
        print(f"Polygon key: {key[:4]}...{key[-4:]}")
    try:
        core.init_macro_for_api()
    except Exception as e:
        print("startup macro:", e)
    if _PRECOMPUTE_ENABLED:
        threading.Thread(target=_precompute_worker, name="precompute", daemon=True).start()
        print(f"[precompute] worker ON interval={_PRECOMPUTE_INTERVAL}s")
    else:
        print("[precompute] OFF (PRECOMPUTE_ENABLED=0)")


@app.get("/health")
def health():
    """Minimalny health – nie może wywalić 500 (keepalive / Render)."""
    try:
        key = getattr(core, "TWELVE_DATA_API_KEY", None) or getattr(core, "POLYGON_API_KEY", "") or ""
        key_ok = bool(key) and len(str(key)) > 10 and not str(key).startswith("WPISZ")
    except Exception:
        key, key_ok = "", False
    n = 0
    pre = {}
    try:
        with _PRECOMPUTE_LOCK:
            n = len(_PRECOMPUTE)
            pre = dict(_PRECOMPUTE_STATUS)
    except Exception as e:
        pre = {"error": str(e)}
    return {
        "status": "ok",
        "polygon_key_configured": key_ok,
        "twelve_key_configured": key_ok,
        "ts": int(__import__("time").time()),
        "build": API_BUILD,
        "auth_required": bool(getattr(auth, "AUTH_REQUIRED", False)),
        "supabase_configured": False,
        "hit_mode": "full",
        "precompute_enabled": bool(_PRECOMPUTE_ENABLED),
        "precompute_entries": n,
        "precompute_status": pre,
    }


@app.get("/tickers")
def list_tickers():
    return {"tickers": list(getattr(core, "tickers", []))}


@app.get("/analyze/{ticker}", response_model=AnalyzeResponse)
def analyze(
    ticker: str,
    horizon: str = Query("1M", description="1M lub 3M"),
    fast: int = Query(1, description="kompatybilność"),
    quality: int = Query(0, description="1=więcej punktów Hit% backtestu"),
    refresh: int = Query(0, description="1=pomiń precompute/cache, przelicz teraz"),
    prof: Dict[str, Any] = Depends(get_profile),
):
    """
    Demo: max 2 analizy 1M/3M na miesiąc UTC.
    Standard/Pro: bez limitu liczbowego.
    """
    _gate(prof, "analyze")
    try:
        auth.check_analyze_quota(prof)
    except PermissionError as e:
        raise HTTPException(status_code=402, detail=str(e))

    t = ticker.upper().strip()
    days = _horizon_days(horizon)
    hz = "3M" if days > 30 else "1M"

    if refresh:
        for k in list(_ANALYZE_CACHE.keys()):
            if f"|{t}|" in k or k.startswith(f"v6|{t}|"):
                _ANALYZE_CACHE.pop(k, None)
        with _PRECOMPUTE_LOCK:
            _PRECOMPUTE.pop(_pc_key(t, hz), None)

    if not refresh:
        cached = _pc_get(t, hz)
        if (
            cached
            and cached.get("current_price") is not None
            and cached.get("predicted_change_pct") is not None
        ):
            cached = dict(cached)
            cached["cached"] = True
            cached.pop("fast_mode", None)
            # Licznik Demo – nawet przy cache (to jest „użycie” analizy przez usera)
            if (prof.get("plan") or "demo").lower() == "demo":
                new_c = auth.increment_analyze(prof["id"], int(prof.get("analyze_count") or 0))
                prof["analyze_count"] = new_c
            payload = {k: v for k, v in cached.items() if k in AnalyzeResponse.model_fields}
            payload["plan"] = (prof.get("plan") or "demo").lower()
            payload["analyze_remaining"] = auth.remaining_analyze(prof)
            return AnalyzeResponse(**payload)

    data = _analyze_one(t, horizon, fast=bool(fast), quality=bool(quality))
    data.pop("fast_mode", None)
    try:
        if data.get("current_price") is not None:
            _pc_store(t, hz, data)
    except Exception:
        pass
    if (prof.get("plan") or "demo").lower() == "demo":
        new_c = auth.increment_analyze(prof["id"], int(prof.get("analyze_count") or 0))
        prof["analyze_count"] = new_c
    payload = {k: v for k, v in data.items() if k in AnalyzeResponse.model_fields}
    payload["plan"] = (prof.get("plan") or "demo").lower()
    payload["analyze_remaining"] = auth.remaining_analyze(prof)
    return AnalyzeResponse(**payload)


@app.get("/rankings", response_model=RankingsResponse)
def rankings(
    horizon: str = Query("1M"),
    limit: int = Query(12, ge=1, le=30),
    prof: Dict[str, Any] = Depends(get_profile),
):
    """Ranking sekwencyjnie – bez ThreadPool (stabilniejsze Twelve / hit akcji)."""
    _gate(prof, "rankings")
    tick_list = list(getattr(core, "tickers", []))[: max(limit, 6)]
    items: List[RankingItem] = []
    for tk in tick_list:
        try:
            hz = "3M" if _horizon_days(horizon) > 30 else "1M"
            d = _pc_get(tk, hz) or _analyze_one(tk, horizon, fast=True, quality=False)
            items.append(
                RankingItem(
                    ticker=d["ticker"],
                    current_price=d.get("current_price"),
                    predicted_change_pct=d.get("predicted_change_pct"),
                    direction=d.get("direction") or "NEUTRALNY",
                    sector=d.get("sector") or "Unknown",
                    fundamental_rating=d.get("fundamental_rating"),
                    hit_rate=d.get("hit_rate"),
                )
            )
        except Exception as e:
            print("rankings skip", tk, e)
        time.sleep(0.25)
    items.sort(
        key=lambda x: (x.predicted_change_pct is not None, x.predicted_change_pct or -999),
        reverse=True,
    )
    items = items[:limit]
    return RankingsResponse(
        horizon="3M" if _horizon_days(horizon) > 30 else "1M", items=items
    )


@app.get("/fundamentals/{ticker}")
def fundamentals(ticker: str, prof: Dict[str, Any] = Depends(get_profile)):
    _gate(prof, "fundamentals")
    ticker = ticker.upper().strip()
    try:
        fa = core.get_comprehensive_fundamental_analysis(ticker)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not fa:
        raise HTTPException(status_code=404, detail="Brak danych fundamentalnych")
    # JSON-serializable
    out = {}
    for k, v in fa.items():
        if k == "company_fundamentals" and isinstance(v, dict):
            out[k] = {kk: _safe_float(vv) if not isinstance(vv, str) else vv for kk, vv in v.items()}
        elif k == "macro_data" and isinstance(v, dict):
            out[k] = {kk: (vv if isinstance(vv, str) else _safe_float(vv)) for kk, vv in v.items()}
        else:
            try:
                out[k] = v if isinstance(v, (str, int, float, bool, type(None))) else str(v)
            except Exception:
                out[k] = str(v)
    out["ticker"] = ticker
    return out


@app.get("/perspective-3y/{ticker}")
def perspective_3y(ticker: str, prof: Dict[str, Any] = Depends(get_profile)):
    _gate(prof, "perspective_3y")
    ticker = ticker.upper().strip()
    score = None
    try:
        fa = core.get_comprehensive_fundamental_analysis(ticker)
        if fa:
            score = fa.get("combined_score")
    except Exception:
        pass
    try:
        info = core.get_3year_perspective(ticker, score)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not info:
        raise HTTPException(status_code=404, detail="Brak perspektywy 3Y")
    # uprość zagnieżdżenia
    clean = {}
    for k, v in info.items():
        if isinstance(v, dict):
            clean[k] = {
                kk: (_safe_float(vv) if not isinstance(vv, (str, bool, type(None))) else vv)
                for kk, vv in v.items()
            }
        else:
            clean[k] = _safe_float(v) if isinstance(v, (int, float)) else v
    return clean



@app.get("/backtest/forecast/{ticker}")
def forecast_backtest(
    ticker: str,
    horizon: str = Query("1M"),
    prof: Dict[str, Any] = Depends(get_profile),
):
    """Walk-forward Hit%% / MAE jak w desktopie."""
    _gate(prof, "backtest_forecast")
    try:
        return reports.forecast_quality_backtest(ticker, horizon=horizon)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/backtest/strategy/{ticker}")
def strategy_backtest(
    ticker: str,
    capital: float = Query(10000, ge=100, le=1_000_000),
    prof: Dict[str, Any] = Depends(get_profile),
):
    """Backtest strategii MACD/RSI/ADX + SL/TP."""
    _gate(prof, "backtest_strategy")
    try:
        return reports.strategy_backtest(ticker, initial_capital=capital)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/report/{ticker}")
def report_json(ticker: str, prof: Dict[str, Any] = Depends(get_profile)):
    """Pelny raport jako JSON (pod UI / eksport)."""
    _gate(prof, "report")
    try:
        return reports.build_report_payload(ticker)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/report/{ticker}/pdf")
def report_pdf(ticker: str, prof: Dict[str, Any] = Depends(get_profile)):
    _gate(prof, "report")
    try:
        data = reports.report_pdf_bytes(ticker)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="findash_{ticker.upper()}.pdf"'},
    )


@app.get("/report/{ticker}/xlsx")
def report_xlsx(ticker: str, prof: Dict[str, Any] = Depends(get_profile)):
    _gate(prof, "report")
    try:
        data = reports.report_excel_bytes(ticker)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="findash_{ticker.upper()}.xlsx"'},
    )


@app.get("/hybrid/{ticker}")
def hybrid_analyze(
    ticker: str,
    mode: str = Query("Zrównoważony", description="Agresywny | Zrównoważony | Bezpieczny"),
    prof: Dict[str, Any] = Depends(get_profile),
):
    """Hybrid Analyzer – score, próg, sygnał KUPNO/SPRZEDAŻ (plan Pro)."""
    _gate(prof, "hybrid")
    try:
        return hybrid.analyze_hybrid(ticker, mode=mode)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _signals_cache_key(mode: str, limit: int) -> str:
    m = (mode or "Zrównoważony").strip()
    return f"signals|{m}|{int(limit)}"


def _build_signals_payload(mode: str, limit: int) -> Dict[str, Any]:
    """Pełny skan hybrid – wołany rzadko (cache / precompute), nie przy każdym odświeżeniu UI."""
    tickers = list(getattr(core, "tickers", []) or [])[: max(int(limit), 1)]
    items = hybrid.scan_signals(tickers=tickers, mode=mode)
    return {
        "mode": mode,
        "count": len(items),
        "items": items,
        "cached": False,
        "cache_ttl_sec": _SIGNALS_CACHE_TTL,
        "computed_at": int(time.time()),
        "disclaimer": (
            "Hybrid signals are a technical tool, not investment advice. "
            "Server caches the scan; the page only displays the last result."
        ),
    }


def _precompute_signals_once() -> None:
    """Odśwież sygnały dla 3 trybów – po rundzie 1M/3M albo gdy cache pusty."""
    modes = ("Agresywny", "Zrównoważony", "Bezpieczny")
    limit = min(20, max(len(getattr(core, "tickers", []) or []), 8))
    for mode in modes:
        try:
            payload = _build_signals_payload(mode, limit)
            key = _signals_cache_key(mode, limit)
            with _SIGNALS_LOCK:
                _SIGNALS_CACHE[key] = {"ts": time.time(), "data": payload}
            print(f"[signals-cache] refreshed mode={mode} count={payload.get('count')}")
        except Exception as e:
            print(f"[signals-cache] error mode={mode}: {e}")
        time.sleep(0.5)


@app.get("/signals")
def signals(
    mode: str = Query("Zrównoważony"),
    limit: int = Query(20, ge=1, le=50),
    refresh: int = Query(0, description="1=wymuś przeliczenie (admin/ops)"),
    prof: Dict[str, Any] = Depends(get_profile),
):
    """
    Skaner sygnałów Hybrid (Pro).
    Komercyjnie: wynik liczony rzadko i trzymany w cache; UI tylko odczytuje.
    """
    _gate(prof, "signals")
    mode = (mode or "Zrównoważony").strip()
    key = _signals_cache_key(mode, limit)
    now = time.time()

    if not refresh:
        with _SIGNALS_LOCK:
            row = _SIGNALS_CACHE.get(key)
            if row and (now - float(row["ts"])) < _SIGNALS_CACHE_TTL:
                out = dict(row["data"])
                out["cached"] = True
                out["age_sec"] = int(now - float(row["ts"]))
                return out

    # Brak cache / wygasł / refresh=1 → policz raz i zapisz
    payload = _build_signals_payload(mode, limit)
    with _SIGNALS_LOCK:
        _SIGNALS_CACHE[key] = {"ts": now, "data": dict(payload)}
    return payload



@app.get("/precompute/status")
def precompute_status():
    with _PRECOMPUTE_LOCK:
        keys = sorted(_PRECOMPUTE.keys())
        ages = {k: round(time.time() - _PRECOMPUTE[k]["ts"], 1) for k in keys}
    return {
        "enabled": _PRECOMPUTE_ENABLED,
        "interval_sec": _PRECOMPUTE_INTERVAL,
        "entries": len(keys),
        "keys": keys,
        "ages_sec": ages,
        "status": dict(_PRECOMPUTE_STATUS),
    }


@app.post("/precompute/run")
def precompute_run():
    """Odśwież wszystkie tickery w tle (po wejściu na stronę / po deployu)."""
    def _run():
        try:
            _precompute_all_once()
        except Exception as e:
            print("[precompute/run]", e)
    threading.Thread(target=_run, daemon=True).start()
    return {"started": True, "message": "Precompute uruchomiony w tle – nie blokuje UI"}


@app.get("/keepalive")
def keepalive():
    """
    Ping dla UptimeRobot / cron (co 5 min) – trzyma Render Free przy życiu.
    Nie skraca analizy timeoutem – tylko budzi dyno i dba o precompute w tle.
    """
    with _PRECOMPUTE_LOCK:
        n = len(_PRECOMPUTE)
        last = _PRECOMPUTE_STATUS.get("last_full_run_ts")
        running = bool(_PRECOMPUTE_STATUS.get("running"))
    stale = last is None or (time.time() - float(last)) > (_PRECOMPUTE_INTERVAL * 1.2)
    kicked = False
    if _PRECOMPUTE_ENABLED and not running and (n == 0 or stale):
        threading.Thread(target=_precompute_all_once, daemon=True, name="pc-keepalive").start()
        kicked = True
    return {
        "ok": True,
        "ts": int(time.time()),
        "precompute_entries": n,
        "precompute_kicked": kicked,
        "precompute_running": running,
        "build": API_BUILD,
        "hint": "Ustaw UptimeRobot HTTP(s) co 5 min na ten URL",
    }



@app.get("/me")
def me(prof: Dict[str, Any] = Depends(get_profile)):
    """Profil, plan, pozostałe analizy Demo, lista feature."""
    return auth.public_me(prof)


@app.get("/plans")
def list_plans():
    """Publiczny cennik feature (bez auth) – pod stronę Pricing."""
    return {
        "demo": auth.public_me({"plan": "demo", "analyze_count": 0, "analyze_month": auth._month_key()})["plans"]["demo"],
        "standard": auth.public_me({"plan": "standard", "analyze_count": 0})["plans"]["standard"],
        "pro": auth.public_me({"plan": "pro", "analyze_count": 0})["plans"]["pro"],
        "note": "Płatności: Stripe Checkout → webhook ustawia plan na profilu.",
    }


@app.post("/billing/stripe-webhook")
async def stripe_webhook(request: Request):
    """
    Stripe Checkout completed → profiles.plan = standard|pro.
    W Stripe Dashboard: webhook na https://TWOJ-API/billing/stripe-webhook
    Event: checkout.session.completed
    Metadata sesji: supabase_user_id, plan
    """
    secret = os.environ.get("STRIPE_WEBHOOK_SECRET") or ""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    if not secret:
        # tryb bez weryfikacji – tylko dev (NIE na prod bez secret)
        try:
            import json
            event = json.loads(payload.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="Bad payload")
    else:
        try:
            import stripe
            event = stripe.Webhook.construct_event(payload, sig, secret)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Webhook error: {e}")

    etype = event.get("type") if isinstance(event, dict) else getattr(event, "type", None)
    data_obj = event.get("data", {}).get("object", {}) if isinstance(event, dict) else {}
    if etype == "checkout.session.completed":
        meta = data_obj.get("metadata") or {}
        uid = meta.get("supabase_user_id") or meta.get("user_id")
        plan = (meta.get("plan") or "").lower()
        if uid and plan in auth.VALID_PLANS and plan != "demo":
            try:
                auth.set_plan(uid, plan)
                print(f"[stripe] plan={plan} user={uid}")
            except Exception as e:
                print("[stripe] set_plan error", e)
                raise HTTPException(status_code=500, detail=str(e))
    return {"received": True}


@app.post("/billing/set-plan-dev")
def set_plan_dev(
    plan: str = Query(..., description="demo|standard|pro"),
    prof: Dict[str, Any] = Depends(get_profile),
):
    """Tylko gdy DEV_AUTH_BYPASS=1 – ręczne ustawienie planu do testów."""
    if not auth.DEV_AUTH_BYPASS:
        raise HTTPException(status_code=403, detail="Tylko w trybie DEV_AUTH_BYPASS")
    auth.set_plan(prof["id"], plan)
    prof2 = auth.ensure_profile(prof["id"], email=prof.get("email"))
    return auth.public_me(prof2)



@app.get("/gov/contracts")
def gov_contracts(
    q: Optional[str] = Query(None, description="Słowa kluczowe (np. semiconductor, cybersecurity)"),
    company: Optional[str] = Query(None, description="Nazwa odbiorcy / firmy"),
    days: int = Query(30, ge=1, le=1825, description="Okres wstecz od dziś"),
    limit: int = Query(25, ge=1, le=100),
    page: int = Query(1, ge=1, le=50),
    min_amount: Optional[float] = Query(None, ge=0, description="Minimalna kwota kontraktu USD"),
    sort: str = Query("Start Date", description="Start Date | Award Amount | End Date"),
    order: str = Query("desc", description="desc = najnowsze / największe pierwsze"),
):
    """Przyznane kontrakty federalne USA. Bez q/company = lista najnowszych w okresie."""
    keywords = [q] if q and q.strip() else None
    data = gov.search_awarded_contracts(
        keywords=keywords,
        recipient_name=company,
        days=days,
        limit=limit,
        page=page,
        min_amount=min_amount,
        sort_by=sort,
        order=order,
    )
    if not data.get("ok"):
        raise HTTPException(status_code=502, detail=data.get("error") or "USASpending error")
    return data


@app.get("/gov/contracts/latest")
def gov_contracts_latest(
    days: int = Query(30, ge=1, le=365, description="Ile dni wstecz"),
    limit: int = Query(40, ge=1, le=100),
):
    """Najnowsze przyznane kontrakty federalne (lista pod zakładkę Kontrakty USA)."""
    data = gov.latest_awarded_contracts(days=days, limit=limit)
    if not data.get("ok"):
        raise HTTPException(status_code=502, detail=data.get("error") or "USASpending error")
    return data


@app.get("/gov/contracts/company/{name}")
def gov_contracts_company(
    name: str,
    days: int = Query(365, ge=1, le=1825),
    limit: int = Query(25, ge=1, le=100),
):
    """Kontrakty przyznane firmie (po nazwie recipient)."""
    data = gov.search_by_company_name(name, days=days, limit=limit)
    if not data.get("ok"):
        raise HTTPException(status_code=502, detail=data.get("error") or "USASpending error")
    return data




# ---------------------------------------------------------------------------
# CRYPTO – ten sam silnik, BEZ mutacji core.sector_mapping, BEZ parallel spam
# ---------------------------------------------------------------------------
CRYPTO_PAIRS = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "ADA/USD",
    "DOGE/USD", "AVAX/USD", "LINK/USD", "DOT/USD", "LTC/USD",
]


def _crypto_symbol(raw: str) -> str:
    s = (raw or "").strip().upper().replace(" ", "")
    if not s:
        raise HTTPException(status_code=400, detail="Empty crypto symbol")
    if s.startswith("X:") and s.endswith("USD") and len(s) > 5:
        return f"{s[2:-3]}/USD"
    if "/" in s:
        return s
    if s.endswith("USD") and len(s) > 3 and not s.isalpha():
        return f"{s[:-3]}/USD"
    if s.isalpha() and 2 <= len(s) <= 10:
        return f"{s}/USD"
    return s


@app.get("/crypto/tickers")
def crypto_tickers(prof: Dict[str, Any] = Depends(get_profile)):
    _gate(prof, "crypto")
    items = []
    for pair in CRYPTO_PAIRS:
        price = None
        try:
            price = core.get_live_price(pair)
        except Exception as e:
            print("crypto price", pair, e)
        items.append({
            "symbol": pair,
            "base": pair.split("/")[0],
            "quote": "USD",
            "price": _safe_float(price),
        })
        time.sleep(0.15)  # nie zjadaj limitów Twelve (akcje muszą działać)
    return {
        "count": len(items),
        "items": items,
        "disclaimer": "Crypto prices via Twelve Data. Not investment advice.",
    }


@app.get("/crypto/analyze/{symbol:path}")
def crypto_analyze(
    symbol: str,
    horizon: str = Query("1M", description="1M lub 3M"),
    refresh: int = Query(0),
    prof: Dict[str, Any] = Depends(get_profile),
):
    _gate(prof, "crypto")
    try:
        auth.check_analyze_quota(prof)
    except PermissionError as e:
        raise HTTPException(status_code=402, detail=str(e))

    pair = _crypto_symbol(symbol)
    days = _horizon_days(horizon)
    hz = "3M" if days > 30 else "1M"
    if refresh:
        for k in list(_ANALYZE_CACHE.keys()):
            if pair in k or pair.replace("/", "") in k.replace("/", ""):
                _ANALYZE_CACHE.pop(k, None)

    # Osobny silnik krypto (nie equity _analyze_one) – lepszy hit na coinach
    cache_key = f"crypto_v1|{pair}|{hz}|{time.strftime('%Y-%m-%d')}"
    now = time.time()
    hit = _ANALYZE_CACHE.get(cache_key)
    if hit and now - hit["ts"] < _ANALYZE_CACHE_TTL and not refresh:
        data = dict(hit["data"])
        data["cached"] = True
    else:
        raw = core.analyze_crypto_pair(pair, days_forward=days)
        if not raw or raw.get("current_price") is None:
            raise HTTPException(status_code=404, detail=f"Brak danych krypto dla {pair}")
        data = {
            "ticker": raw.get("symbol") or pair,
            "symbol": pair,
            "horizon": hz,
            "days_forward": days,
            "current_price": raw.get("current_price"),
            "predicted_price": raw.get("predicted_price"),
            "predicted_change_pct": raw.get("predicted_change_pct"),
            "direction": raw.get("direction") or "NEUTRALNY",
            "rsi": raw.get("rsi"),
            "sector": "Crypto",
            "fundamental_rating": None,
            "combined_score": raw.get("combined_score"),
            "hit_rate": raw.get("hit_rate"),
            "mae": raw.get("mae"),
            "n_significant": raw.get("n_significant"),
            "asset_class": "crypto",
            "engine": raw.get("engine"),
            "cached": False,
            "disclaimer": (
                "Crypto technical model (momentum/EMA/RSI). Not investment advice. High risk."
            ),
        }
        _ANALYZE_CACHE[cache_key] = {"ts": now, "data": dict(data)}

    if (prof.get("plan") or "demo").lower() == "demo":
        new_c = auth.increment_analyze(prof["id"], int(prof.get("analyze_count") or 0))
        prof["analyze_count"] = new_c

    data["plan"] = (prof.get("plan") or "demo").lower()
    data["analyze_remaining"] = auth.remaining_analyze(prof)
    return data


@app.get("/crypto/rankings")
def crypto_rankings(
    horizon: str = Query("1M"),
    limit: int = Query(8, ge=1, le=12),
    prof: Dict[str, Any] = Depends(get_profile),
):
    """Ranking krypto – silnik crypto_technical (NIE equity _analyze_one)."""
    _gate(prof, "crypto")
    days = _horizon_days(horizon)
    hz = "3M" if days > 30 else "1M"
    items = []
    for pair in CRYPTO_PAIRS[:limit]:
        try:
            raw = core.analyze_crypto_pair(pair, days_forward=days)
            if raw and raw.get("current_price") is not None:
                items.append({
                    "ticker": pair,
                    "current_price": raw.get("current_price"),
                    "predicted_change_pct": raw.get("predicted_change_pct"),
                    "direction": raw.get("direction") or "NEUTRALNY",
                    "sector": "Crypto",
                    "fundamental_rating": None,
                    "hit_rate": raw.get("hit_rate"),
                })
        except Exception as e:
            print("crypto rank skip", pair, e)
        time.sleep(0.25)
    items.sort(
        key=lambda x: (x.get("predicted_change_pct") is not None, x.get("predicted_change_pct") or -999),
        reverse=True,
    )
    return {
        "horizon": hz,
        "items": items,
        "disclaimer": "Crypto technical engine only. Does not affect equity analysis.",
    }


@app.get("/")
def root():
    return {
        "service": "FinDash Analysis API",
        "docs": "/docs",
        "endpoints": [
            "GET /health",
            "GET /me",
            "GET /gov/contracts?days=30&limit=40",
            "GET /gov/contracts/latest?days=30",
            "GET /gov/contracts/company/{name}",
            "GET /plans",
            "GET /tickers",
            "GET /analyze/{ticker}?horizon=1M|3M",
            "GET /rankings?horizon=1M&limit=12",
            "GET /fundamentals/{ticker}",
            "GET /perspective-3y/{ticker}",
            "GET /hybrid/{ticker}?mode=Zrównoważony",
            "GET /signals?mode=Zrównoważony&limit=20",
            "GET /crypto/tickers",
            "GET /crypto/analyze/{symbol}?horizon=1M|3M",
            "GET /crypto/rankings",
            "GET /precompute/status",
            "POST /precompute/run",
            "GET /keepalive",
            "GET /backtest/forecast/{ticker}?horizon=1M|3M",
            "GET /backtest/strategy/{ticker}?capital=10000",
            "GET /report/{ticker}",
            "GET /report/{ticker}/pdf",
            "GET /report/{ticker}/xlsx",
        ],
    }
