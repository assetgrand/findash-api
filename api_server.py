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

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# --- import logiki analitycznej (bez GUI) ---
import core_analysis as core

API_BUILD = "precompute-v1-full-hit"
import hybrid_engine as hybrid
import report_engine as reports

# Klucz: najpierw ENV (produkcja), potem stała z core
if os.environ.get("POLYGON_API_KEY"):
    core.POLYGON_API_KEY = os.environ["POLYGON_API_KEY"].strip()

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


class AnalyzeResponse(BaseModel):
    ticker: str
    horizon: str
    days_forward: int
    current_price: Optional[float] = None
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

# ============================================================
# PRECOMPUTE – serwer liczy w tle, Lovable tylko czyta
# ============================================================
# Co PRECOMPUTE_INTERVAL sekund odświeża 1M+3M dla listy tickerów.
# GET /analyze/{t} najpierw bierze gotowy wynik (ms), nie liczy od zera.

_PRECOMPUTE: Dict[str, Any] = {}  # key "AAPL|1M" -> {"ts": ..., "data": {...}}
_PRECOMPUTE_STATUS: Dict[str, Any] = {
    "running": False,
    "last_full_run_ts": None,
    "last_ticker": None,
    "last_error": None,
    "tickers_done": 0,
    "tickers_total": 0,
}
_PRECOMPUTE_LOCK = threading.Lock()
_PRECOMPUTE_INTERVAL = int(os.environ.get("PRECOMPUTE_INTERVAL", "900"))  # 15 min
_PRECOMPUTE_ENABLED = os.environ.get("PRECOMPUTE_ENABLED", "1") == "1"


def _precompute_key(ticker: str, horizon_label: str) -> str:
    return f"{ticker.upper()}|{horizon_label}"


def _store_precompute(ticker: str, horizon_label: str, data: Dict[str, Any]) -> None:
    with _PRECOMPUTE_LOCK:
        _PRECOMPUTE[_precompute_key(ticker, horizon_label)] = {
            "ts": time.time(),
            "data": data,
        }


def _get_precompute(ticker: str, horizon_label: str, max_age: Optional[float] = None) -> Optional[Dict[str, Any]]:
    max_age = _PRECOMPUTE_INTERVAL * 2 if max_age is None else max_age
    with _PRECOMPUTE_LOCK:
        row = _PRECOMPUTE.get(_precompute_key(ticker, horizon_label))
    if not row:
        return None
    if time.time() - row["ts"] > max_age:
        return None
    return row["data"]


def _precompute_worker() -> None:
    """W tle: liczy analyze (z Hit%) dla wszystkich tickerów, 1M i 3M."""
    # krótki start delay – API najpierw wstanie
    time.sleep(3)
    while True:
        if not _PRECOMPUTE_ENABLED:
            time.sleep(30)
            continue
        tickers = list(getattr(core, "tickers", []) or [])
        if not tickers:
            tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "JPM", "JNJ"]
        _PRECOMPUTE_STATUS["running"] = True
        _PRECOMPUTE_STATUS["tickers_total"] = len(tickers)
        _PRECOMPUTE_STATUS["tickers_done"] = 0
        _PRECOMPUTE_STATUS["last_error"] = None
        print(f"[precompute] start: {len(tickers)} tickerów × 2 horyzonty")
        for t in tickers:
            _PRECOMPUTE_STATUS["last_ticker"] = t
            for hz in ("1M", "3M"):
                try:
                    # quality=False, ale Hit i tak zawsze w _analyze_one
                    data = _analyze_one(t, hz, fast=True, quality=False)
                    _store_precompute(t, hz, data)
                except Exception as e:
                    msg = f"{t}/{hz}: {e}"
                    print("[precompute]", msg)
                    _PRECOMPUTE_STATUS["last_error"] = msg
            _PRECOMPUTE_STATUS["tickers_done"] = _PRECOMPUTE_STATUS.get("tickers_done", 0) + 1
            # oddech między tickerami – mniej banów / CPU spike
            time.sleep(float(os.environ.get("PRECOMPUTE_PAUSE", "1.5")))
        _PRECOMPUTE_STATUS["last_full_run_ts"] = time.time()
        _PRECOMPUTE_STATUS["running"] = False
        print(f"[precompute] gotowe, sleep {_PRECOMPUTE_INTERVAL}s")
        time.sleep(_PRECOMPUTE_INTERVAL)



def _analyze_one(ticker: str, horizon: str = "1M", fast: bool = True, quality: bool = False) -> Dict[str, Any]:
    """
    Analiza pod Lovable/Render – ZAWSZE z Hit%/MAE (wymagane w produkcie).

    Przyspieszenie bez wywalania Hit%:
      - cache 15 min (powtórne requesty = instant)
      - max_points=8 w walk-forward (ta sama definicja hitu, mniej okien)
      - rankingi równolegle
    Parametr quality zwiększa max_points (dokładniejsza próba, wolniej).
    """
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 12:
        raise HTTPException(status_code=400, detail="Nieprawidłowy ticker")

    days = _horizon_days(horizon)
    horizon_label = "3M" if days > 30 else "1M"
    # cache rozróżnia quality (więcej punktów backtestu)
    mode = "q" if quality else "std"
    cache_key = f"v5|{ticker}|{horizon_label}|{mode}|fullhit"
    now = time.time()
    hit = _ANALYZE_CACHE.get(cache_key)
    if hit and now - hit["ts"] < _ANALYZE_CACHE_TTL:
        return hit["data"]

    sector = core.sector_mapping.get(ticker, "Unknown")

    # 400 dni wystarcza na 1M/3M backtest; 500 przy quality
    hist_days = 500 if quality else 400
    df = core.get_historical_prices(ticker, days=hist_days)
    if df is None or getattr(df, "empty", True):
        raise HTTPException(status_code=404, detail=f"Brak danych cenowych dla {ticker}")

    df = core.calculate_indicators_on_df(df)
    if df is None or getattr(df, "empty", True):
        raise HTTPException(status_code=500, detail="Błąd wskaźników technicznych")

    current_price = _safe_float(df["Close"].iloc[-1])
    rsi = _safe_float(df["RSI"].iloc[-1]) if "RSI" in df.columns else None

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

    # Hit% ZAWSZE – ta sama definicja co desktop; mniej okien = szybciej, nie „fałszywy” hit
    hit_rate = mae = n_sig = None
    max_pts = 12 if quality else 8
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
        "fast_mode": False,  # Hit zawsze włączony
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
        th = threading.Thread(target=_precompute_worker, name="precompute", daemon=True)
        th.start()
        print(f"[precompute] worker started (interval={_PRECOMPUTE_INTERVAL}s)")
    else:
        print("[precompute] wyłączony (PRECOMPUTE_ENABLED=0)")


@app.get("/health")
def health():
    key_ok = bool(core.POLYGON_API_KEY) and len(core.POLYGON_API_KEY) > 10 and not str(
        core.POLYGON_API_KEY
    ).startswith("WPISZ")
    with _PRECOMPUTE_LOCK:
        n_pre = len(_PRECOMPUTE)
    return {
        "status": "ok",
        "polygon_key_configured": key_ok,
        "ts": int(time.time()),
        "build": API_BUILD,
        "hit_mode": "full",
        "precompute_enabled": _PRECOMPUTE_ENABLED,
        "precompute_entries": n_pre,
        "precompute_status": dict(_PRECOMPUTE_STATUS),
    }


@app.get("/tickers")
def list_tickers():
    return {"tickers": list(getattr(core, "tickers", []))}


@app.get("/analyze/{ticker}", response_model=AnalyzeResponse)
def analyze(
    ticker: str,
    horizon: str = Query("1M", description="1M lub 3M"),
    fast: int = Query(1, description="kompatybilność – Hit i tak zawsze liczony w precompute"),
    quality: int = Query(0, description="1=więcej punktów backtestu przy live compute"),
    refresh: int = Query(0, description="1=wymuś przeliczenie teraz (wolne)"),
):
    """
    Domyślnie: wynik z precompute (ms).
    refresh=1: liczy na żywo (gdy klient chce świeże / ticker spoza listy).
    """
    days = _horizon_days(horizon)
    horizon_label = "3M" if days > 30 else "1M"
    ticker_u = ticker.upper().strip()

    if not refresh:
        cached = _get_precompute(ticker_u, horizon_label)
        if cached:
            data = dict(cached)
            data.pop("fast_mode", None)
            data["from_precompute"] = True
            # AnalyzeResponse może nie mieć from_precompute – usuń
            data.pop("from_precompute", None)
            return AnalyzeResponse(**{k: v for k, v in data.items() if k in AnalyzeResponse.model_fields})

    data = _analyze_one(ticker_u, horizon, fast=bool(fast), quality=bool(quality))
    data.pop("fast_mode", None)
    # zapisz też do precompute (kolejne kliknięcia instant)
    try:
        _store_precompute(ticker_u, horizon_label, data)
    except Exception:
        pass
    return AnalyzeResponse(**{k: v for k, v in data.items() if k in AnalyzeResponse.model_fields})


@app.get("/rankings", response_model=RankingsResponse)
def rankings(
    horizon: str = Query("1M"),
    limit: int = Query(12, ge=1, le=30),
):
    """Ranking po predicted_change_pct – równolegle, bez Hit% (szybko)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    tick_list = list(getattr(core, "tickers", []))[: max(limit, 6)]
    items: List[RankingItem] = []

    def _one(t: str):
        hz = "3M" if _horizon_days(horizon) > 30 else "1M"
        d = _get_precompute(t, hz) or _analyze_one(t, horizon, fast=True, quality=False)
        return RankingItem(
            ticker=d["ticker"],
            current_price=d.get("current_price"),
            predicted_change_pct=d.get("predicted_change_pct"),
            direction=d.get("direction") or "NEUTRALNY",
            sector=d.get("sector") or "Unknown",
            fundamental_rating=d.get("fundamental_rating"),
            hit_rate=d.get("hit_rate"),
        )

    # 4 wątki – Polygon Free/Starter znosi równoległość lepiej niż sekwencja × N
    workers = min(4, max(1, len(tick_list)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(_one, t): t for t in tick_list}
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                items.append(fut.result())
            except Exception as e:
                print("rankings skip", t, e)

    items.sort(
        key=lambda x: (x.predicted_change_pct is not None, x.predicted_change_pct or -999),
        reverse=True,
    )
    items = items[:limit]
    return RankingsResponse(
        horizon="3M" if _horizon_days(horizon) > 30 else "1M", items=items
    )


@app.get("/fundamentals/{ticker}")
def fundamentals(ticker: str):
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
def perspective_3y(ticker: str):
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
):
    """Walk-forward Hit%% / MAE jak w desktopie."""
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
):
    """Backtest strategii MACD/RSI/ADX + SL/TP."""
    try:
        return reports.strategy_backtest(ticker, initial_capital=capital)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/report/{ticker}")
def report_json(ticker: str):
    """Pelny raport jako JSON (pod UI / eksport)."""
    try:
        return reports.build_report_payload(ticker)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/report/{ticker}/pdf")
def report_pdf(ticker: str):
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
def report_xlsx(ticker: str):
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
):
    """Hybrid Analyzer – score, próg, sygnał KUPNO/SPRZEDAŻ (plan Pro)."""
    try:
        return hybrid.analyze_hybrid(ticker, mode=mode)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/signals")
def signals(
    mode: str = Query("Zrównoważony"),
    limit: int = Query(20, ge=1, le=50),
):
    """Skaner sygnałów Hybrid po domyślnej liście tickerów (plan Pro)."""
    tickers = list(getattr(core, "tickers", []))[:limit]
    items = hybrid.scan_signals(tickers=tickers, mode=mode)
    return {
        "mode": mode,
        "count": len(items),
        "items": items,
        "disclaimer": (
            "Sygnały hybrydowe to narzędzie techniczne, nie rekomendacja inwestycyjna."
        ),
    }



@app.get("/precompute/status")
def precompute_status():
    """Stan tła: ile tickerów policzonych, ostatni błąd, czy worker działa."""
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
def precompute_run_now():
    """
    Jednorazowo odśwież listę tickerów w tle (nie blokuje requestu).
    Przydatne po deployu / gdy chcesz ciepły cache przed klientami.
    """
    def _once():
        tickers = list(getattr(core, "tickers", []) or []) or ["AAPL"]
        for t in tickers:
            for hz in ("1M", "3M"):
                try:
                    data = _analyze_one(t, hz, fast=True, quality=False)
                    _store_precompute(t, hz, data)
                except Exception as e:
                    print("[precompute/run]", t, hz, e)
            time.sleep(1.0)
        _PRECOMPUTE_STATUS["last_full_run_ts"] = time.time()
        print("[precompute/run] done")

    threading.Thread(target=_once, daemon=True).start()
    return {"started": True, "message": "Precompute uruchomiony w tle"}


@app.get("/")
def root():
    return {
        "service": "FinDash Analysis API",
        "docs": "/docs",
        "endpoints": [
            "GET /health",
            "GET /tickers",
            "GET /analyze/{ticker}?horizon=1M|3M",
            "GET /rankings?horizon=1M&limit=12",
            "GET /fundamentals/{ticker}",
            "GET /perspective-3y/{ticker}",
            "GET /hybrid/{ticker}?mode=Zrównoważony",
            "GET /signals?mode=Zrównoważony&limit=20",
            "GET /precompute/status",
            "POST /precompute/run",
            "GET /backtest/forecast/{ticker}?horizon=1M|3M",
            "GET /backtest/strategy/{ticker}?capital=10000",
            "GET /report/{ticker}",
            "GET /report/{ticker}/pdf",
            "GET /report/{ticker}/xlsx",
        ],
    }
