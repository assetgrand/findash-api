"""
FastAPI – most łączący dashboard (core_analysis) ze stroną Lovable.
Uruchomienie lokalne:
  export POLYGON_API_KEY="twoj_klucz"
  uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# --- import logiki analitycznej (bez GUI) ---
import core_analysis as core
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


# Prosty cache odpowiedzi analyze (TTL sekundy) – mniej powtórek na Free tier
_ANALYZE_CACHE: Dict[str, Any] = {}
_ANALYZE_CACHE_TTL = 180  # 3 min


def _analyze_one(ticker: str, horizon: str = "1M", fast: bool = True, quality: bool = False) -> Dict[str, Any]:
    """
    Pełna analiza jak desktop: fundamenty + predict + pełny Hit%/MAE (backtest_forecast_quality).
    Parametry fast/quality zostawione dla kompatybilności URL, nie okrawają Hit%.
    """
    ticker = ticker.upper().strip()
    if not ticker or len(ticker) > 12:
        raise HTTPException(status_code=400, detail="Nieprawidłowy ticker")

    days = _horizon_days(horizon)
    horizon_label = "3M" if days > 30 else "1M"
    cache_key = f"{ticker}|{horizon_label}|fast={int(fast)}|q={int(quality)}"
    now = time.time()
    hit = _ANALYZE_CACHE.get(cache_key)
    if hit and now - hit["ts"] < _ANALYZE_CACHE_TTL:
        return hit["data"]

    sector = core.sector_mapping.get(ticker, "Unknown")

    df = core.get_historical_prices(ticker, days=500)
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
    # Fundamenty ZAWSZE (żeby % były zgodne z desktopem).
    # Oszczędność czasu = tylko pomijanie ciężkiego walk-forward Hit% (chyba że quality=1).
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

    hit_rate = mae = n_sig = None
    # PEŁNY Hit%/MAE – ta sama backtest_forecast_quality co w desktopie (bez okrawania)
    try:
        q = core.backtest_forecast_quality(
            df,
            days_forward=days,
            sector=sector,
            fund_score=combined or 50,
            ticker=ticker,
            # bez max_points/step override → domyślne parametry jak w programie
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
        "fast_mode": bool(fast and not quality),
    }
    _ANALYZE_CACHE[cache_key] = {"ts": now, "data": data}
    # nie rozrastaj cache w nieskończoność
    if len(_ANALYZE_CACHE) > 200:
        oldest = sorted(_ANALYZE_CACHE.items(), key=lambda kv: kv[1]["ts"])[:50]
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


@app.get("/health")
def health():
    key_ok = bool(core.POLYGON_API_KEY) and len(core.POLYGON_API_KEY) > 10 and not str(
        core.POLYGON_API_KEY
    ).startswith("WPISZ")
    return {
        "status": "ok",
        "polygon_key_configured": key_ok,
        "ts": int(time.time()),
    }


@app.get("/tickers")
def list_tickers():
    return {"tickers": list(getattr(core, "tickers", []))}


@app.get("/analyze/{ticker}", response_model=AnalyzeResponse)
def analyze(
    ticker: str,
    horizon: str = Query("1M", description="1M lub 3M"),
    fast: int = Query(1, description="1=szybko bez pełnego Hit% backtestu (domyślne)"),
    quality: int = Query(0, description="1=pełniejsze fundamenty + lekki Hit%/MAE"),
):
    data = _analyze_one(ticker, horizon, fast=bool(fast), quality=bool(quality))
    # model może nie mieć fast_mode – wytnij przed response_model
    data.pop("fast_mode", None)
    return AnalyzeResponse(**data)


@app.get("/rankings", response_model=RankingsResponse)
def rankings(
    horizon: str = Query("1M"),
    limit: int = Query(12, ge=1, le=30),
):
    """Ranking po predicted_change_pct dla domyślnej listy tickerów."""
    items: List[RankingItem] = []
    errors = []
    for t in list(getattr(core, "tickers", []))[: max(limit, 6)]:
        try:
            d = _analyze_one(t, horizon, fast=True, quality=False)
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
            errors.append(f"{t}: {e}")
            print("rankings skip", t, e)

    items.sort(key=lambda x: (x.predicted_change_pct is not None, x.predicted_change_pct or -999), reverse=True)
    items = items[:limit]
    return RankingsResponse(horizon="3M" if _horizon_days(horizon) > 30 else "1M", items=items)


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
            "GET /backtest/forecast/{ticker}?horizon=1M|3M",
            "GET /backtest/strategy/{ticker}?capital=10000",
            "GET /report/{ticker}",
            "GET /report/{ticker}/pdf",
            "GET /report/{ticker}/xlsx",
        ],
    }
