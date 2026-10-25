"""
AI Full Analysis – AssetCore (ultimate desk synthesis)

Pakiet danych (nie „wiedza o wszystkim”, tylko to co system realnie ma):
  • prognoza + Hit% + score (quant)
  • pełniejsze fundamenty + makro kraju
  • perspektywa 3Y
  • newsy (RSS, więcej tytułów)
  • feedback Hit% tylko do kalibracji pewności AI

Agenci: Fundamentals → Quant → World/News → Editor
Ceny pochodzą WYŁĄCZNIE z modelu AssetCore.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import ai_brief

_BUILD = "ai-full-v6.1-board-fix"
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MIN = float(os.environ.get("AI_FULL_CACHE_MINUTES") or "1080")
_CACHE_DISK = Path(
    os.environ.get("AI_FULL_CACHE_PATH")
    or os.path.join(os.path.dirname(__file__), "ai_full_cache.json")
)
_DISK_LOADED = False

_FB_LOCK = threading.Lock()
_FB_PATH = Path(
    os.environ.get("AI_FEEDBACK_PATH")
    or os.path.join(os.path.dirname(__file__), "ai_feedback.json")
)
_MAX_FEEDBACK = 200

_DISCLAIMER = (
    "AssetCore desk synthesis v6: quant model + fundamentals/macro + news reaction. "
    "Base price path from AssetCore model; agents may apply a bounded adjustment. "
    "Not omniscient; data can be incomplete or delayed. Not investment advice."
)

# Klucze metryk spółki (jeśli są w company_fundamentals)
_FUND_METRIC_KEYS = (
    "P/E", "Forward P/E", "PEG", "P/B", "P/S",
    "ROE", "ROA", "ROIC",
    "Profit Margin", "Operating Margin", "Gross Margin",
    "Revenue Growth", "Earnings Growth",
    "Debt/Equity", "Current Ratio",
    "EPS", "Book Value", "Dividend Yield",
)


def configured() -> bool:
    return ai_brief.configured()


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

def _load_feedback() -> List[Dict[str, Any]]:
    try:
        if not _FB_PATH.exists():
            return []
        data = json.loads(_FB_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[ai_full] feedback load: {e}")
        return []


def _save_feedback(rows: List[Dict[str, Any]]) -> None:
    try:
        _FB_PATH.write_text(
            json.dumps(rows[-_MAX_FEEDBACK:], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[ai_full] feedback save: {e}")


def add_feedback(
    ticker: str,
    *,
    hit_rate: Optional[float] = None,
    note: str = "",
    narrative_ok: Optional[bool] = None,
    horizon: str = "1M",
    quality: Optional[int] = None,
    predicted_change_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """User / system feedback for AI tone & confidence only — never changes quant prices."""
    q = None
    if quality is not None:
        try:
            q = max(1, min(5, int(quality)))
        except Exception:
            q = None
    hz = str(horizon or "3M").upper().strip()
    if hz.startswith("6"):
        hz = "6M"
    elif hz.startswith("3"):
        hz = "3M"
    else:
        hz = "3M"  # AI desk default
    row = {
        "type": "feedback",
        "ts": datetime.now(timezone.utc).isoformat(),
        "ticker": (ticker or "").upper().strip(),
        "horizon": hz,
        "hit_rate": hit_rate,
        "narrative_ok": narrative_ok,
        "quality": q,
        "predicted_change_pct": predicted_change_pct,
        "note": (note or "")[:500],
    }
    with _FB_LOCK:
        rows = _load_feedback()
        rows.append(row)
        rows = rows[-_MAX_FEEDBACK:]
        _save_feedback(rows)
    return {"ok": True, "stored": row, "n": len(rows)}


def log_outcome(
    ticker: str,
    *,
    horizon: str = "1M",
    predicted_change_pct: Optional[float] = None,
    realized_change_pct: Optional[float] = None,
    hit_rate_at_forecast: Optional[float] = None,
    note: str = "",
) -> Dict[str, Any]:
    """
    Record predicted vs realized return after the horizon.
    Calibrates AI confidence language only — does not retrain quant model.
    """
    pred = predicted_change_pct
    real = realized_change_pct
    direction_ok = None
    abs_err = None
    try:
        if pred is not None and real is not None:
            direction_ok = (float(pred) >= 0 and float(real) >= 0) or (
                float(pred) < 0 and float(real) < 0
            )
            abs_err = abs(float(pred) - float(real))
    except Exception:
        pass
    row = {
        "type": "outcome",
        "ts": datetime.now(timezone.utc).isoformat(),
        "ticker": (ticker or "").upper().strip(),
        "horizon": "3M" if str(horizon).upper().startswith("3") else "1M",
        "predicted_change_pct": pred,
        "realized_change_pct": real,
        "direction_ok": direction_ok,
        "abs_error_pct": abs_err,
        "hit_rate": hit_rate_at_forecast,
        "note": (note or "")[:500],
    }
    with _FB_LOCK:
        rows = _load_feedback()
        rows.append(row)
        rows = rows[-_MAX_FEEDBACK:]
        _save_feedback(rows)
    return {"ok": True, "stored": row, "n": len(rows)}


def feedback_summary(ticker: Optional[str] = None) -> Dict[str, Any]:
    rows = _load_feedback()
    t = (ticker or "").upper().strip() or None
    if t:
        rows = [r for r in rows if r.get("ticker") == t]
    outcomes = [r for r in rows if r.get("type") == "outcome"]
    feedbacks = [r for r in rows if r.get("type") != "outcome"]
    dir_ok = [r for r in outcomes if r.get("direction_ok") is True]
    dir_bad = [r for r in outcomes if r.get("direction_ok") is False]
    narrative_yes = [r for r in feedbacks if r.get("narrative_ok") is True]
    narrative_no = [r for r in feedbacks if r.get("narrative_ok") is False]
    return {
        "ok": True,
        "n_total": len(rows),
        "n_feedback": len(feedbacks),
        "n_outcomes": len(outcomes),
        "direction_ok_rate": (
            round(100.0 * len(dir_ok) / max(len(dir_ok) + len(dir_bad), 1), 1)
            if (dir_ok or dir_bad)
            else None
        ),
        "narrative_ok_rate": (
            round(
                100.0 * len(narrative_yes) / max(len(narrative_yes) + len(narrative_no), 1),
                1,
            )
            if (narrative_yes or narrative_no)
            else None
        ),
        "recent": rows[-15:],
    }


def _feedback_for_prompt(ticker: str, limit: int = 14) -> str:
    t = (ticker or "").upper().strip()
    rows = _load_feedback()
    if not rows:
        return "No prior AI feedback or outcomes stored yet."

    related = [r for r in rows if r.get("ticker") == t][-8:]
    global_ = [r for r in rows if r.get("ticker") != t][-limit:]
    pick = (related + global_)[-limit:]

    lines = []
    for r in pick:
        typ = r.get("type") or "feedback"
        if typ == "outcome":
            lines.append(
                f"- OUTCOME {r.get('ticker')} {r.get('horizon')}: pred={r.get('predicted_change_pct')}% "
                f"realized={r.get('realized_change_pct')}% direction_ok={r.get('direction_ok')} "
                f"abs_err={r.get('abs_error_pct')} note={r.get('note') or '—'}"
            )
        else:
            ok = r.get("narrative_ok")
            ok_s = "yes" if ok is True else ("no" if ok is False else "n/a")
            lines.append(
                f"- FEEDBACK {r.get('ticker')} {r.get('horizon')}: hit_rate={r.get('hit_rate')}, "
                f"quality={r.get('quality')}, narrative_ok={ok_s}, note={r.get('note') or '—'}"
            )

    outcomes = [r for r in rows if r.get("type") == "outcome" and r.get("direction_ok") is not None]
    digest = ""
    if outcomes:
        ok_n = sum(1 for r in outcomes if r.get("direction_ok") is True)
        rate = 100.0 * ok_n / len(outcomes)
        digest = (
            f"\nReliability digest (historical outcomes, n={len(outcomes)}): "
            f"direction match rate ≈ {rate:.0f}%. "
            f"If rate is low, keep confidence lower and strengthen devil_advocate."
        )

    gold = [
        r
        for r in rows
        if r.get("type") != "outcome"
        and r.get("narrative_ok") is True
        and (r.get("quality") or 0) >= 4
        and (r.get("note") or "").strip()
    ][-5:]
    few = ""
    if gold:
        few = "\nPreferred brief qualities (from rated examples):\n" + "\n".join(
            f"- {g.get('note')}" for g in gold
        )

    return (
        "Learning memory (confidence & style only — do not change price forecasts):\n"
        + "\n".join(lines)
        + digest
        + few
    )


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _disk_load() -> None:
    """Load AI cache from disk once (survives process restart on same instance)."""
    global _DISK_LOADED
    if _DISK_LOADED:
        return
    _DISK_LOADED = True
    try:
        if not _CACHE_DISK.exists():
            return
        raw = json.loads(_CACHE_DISK.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        now = time.time()
        with _CACHE_LOCK:
            for k, v in raw.items():
                if not isinstance(v, dict):
                    continue
                ts = float(v.get("ts") or 0)
                if now - ts > _CACHE_MIN * 60:
                    continue
                data = v.get("data")
                if isinstance(data, dict):
                    _CACHE[str(k)] = {"ts": ts, "data": data}
        print(f"[ai_full] disk cache loaded: {len(_CACHE)} entries from {_CACHE_DISK}")
    except Exception as e:
        print(f"[ai_full] disk load: {e}")


def _disk_save() -> None:
    try:
        with _CACHE_LOCK:
            payload = {
                k: {"ts": v.get("ts"), "data": v.get("data")}
                for k, v in _CACHE.items()
                if isinstance(v, dict) and isinstance(v.get("data"), dict)
            }
        _CACHE_DISK.write_text(
            json.dumps(payload, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[ai_full] disk save: {e}")


def _ck(ticker: str, horizon: str) -> str:
    return f"{ticker.upper().strip()}|{horizon.upper().strip()}|v6.0"


def peek_cache(ticker: str, horizon: str) -> Optional[Dict[str, Any]]:
    """Read AI cache without building — used by API to serve post-deploy results only."""
    return _cache_get(ticker, horizon)


def _cache_get(ticker: str, horizon: str) -> Optional[Dict[str, Any]]:
    _disk_load()
    key = _ck(ticker, horizon)
    with _CACHE_LOCK:
        row = _CACHE.get(key)
        if not row:
            # fallback: any version for same ticker|horizon
            prefix = f"{ticker.upper().strip()}|{horizon.upper().strip()}|"
            for k, r in _CACHE.items():
                if str(k).startswith(prefix):
                    row = r
                    break
        if not row:
            return None
        if time.time() - row["ts"] > _CACHE_MIN * 60:
            return None
        out = dict(row["data"])
        out["cached"] = True
        return out


def _cache_set(ticker: str, horizon: str, data: Dict[str, Any]) -> None:
    _disk_load()
    key = _ck(ticker, horizon)
    with _CACHE_LOCK:
        _CACHE[key] = {"ts": time.time(), "data": dict(data)}
        if len(_CACHE) > 200:
            oldest = sorted(_CACHE.items(), key=lambda kv: kv[1]["ts"])[:50]
            for k, _ in oldest:
                _CACHE.pop(k, None)
    _disk_save()


def ranking_rows(horizon: str = "1M", limit: int = 12) -> List[Dict[str, Any]]:
    """Slim rows from AI cache (memory + disk). Match any cache version for this horizon."""
    _disk_load()
    hz = str(horizon or "3M").upper().strip()
    if hz.startswith("6"):
        hz = "6M"
    elif hz.startswith("3"):
        hz = "3M"
    else:
        hz = "3M"  # AI desk default
    # Keys look like: AAPL|3M|v6.0  — accept any version suffix
    needle = f"|{hz}|"
    rows: List[Dict[str, Any]] = []
    with _CACHE_LOCK:
        items = list(_CACHE.items())
    for key, row in items:
        ks = str(key)
        if needle not in ks:
            continue
        # skip expired
        try:
            if time.time() - float(row.get("ts") or 0) > _CACHE_MIN * 60:
                continue
        except Exception:
            pass
        data = row.get("data") or {}
        q = data.get("quant") or {}
        if not isinstance(q, dict):
            q = {}
        rows.append(
            {
                "ticker": data.get("ticker") or q.get("ticker"),
                "horizon": hz,
                "current_price": q.get("current_price"),
                "predicted_price": q.get("predicted_price") or data.get("predicted_price"),
                "predicted_change_pct": data.get("predicted_change_pct", q.get("predicted_change_pct")),
                "model_predicted_change_pct": data.get("model_predicted_change_pct")
                or q.get("model_predicted_change_pct"),
                "agent_adjustment_pct": data.get("agent_adjustment_pct")
                or q.get("agent_adjustment_pct"),
                "direction": data.get("direction") or q.get("direction"),
                "hit_rate": q.get("hit_rate"),
                "sector": q.get("sector"),
                "fundamental_rating": q.get("fundamental_rating"),
                "sentiment": data.get("sentiment"),
                "confidence": data.get("confidence"),
                "agents_influenced_forecast": bool(
                    data.get("agents_influenced_forecast") or q.get("agents_influenced_forecast")
                ),
                "generated_at": data.get("generated_at"),
            }
        )
    rows.sort(
        key=lambda r: (
            r.get("predicted_change_pct") is None,
            -(r.get("predicted_change_pct") or 0),
        ),
    )
    return rows[: max(1, min(int(limit or 12), 50))]


# ---------------------------------------------------------------------------
# Desk pack (maximize real data into the LLM)
# ---------------------------------------------------------------------------

def _safe_num(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, (int, float, str, bool)):
        return v
    try:
        return float(v)
    except Exception:
        return str(v)[:120]


def _pack_fundamentals(fundamentals: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not fundamentals or not isinstance(fundamentals, dict):
        return {}
    out: Dict[str, Any] = {}
    for k in (
        "sector",
        "country_code",
        "country_score",
        "macro_rating",
        "basic_company_score",
        "comprehensive_company_score",
        "sector_position_score",
        "management_quality_score",
        "growth_momentum_score",
        "risk_assessment_score",
        "innovation_score",
        "analyst_revision_score",
        "recommendation_momentum_score",
        "combined_score",
        "fundamental_rating",
    ):
        if fundamentals.get(k) is not None:
            out[k] = _safe_num(fundamentals.get(k))

    macro = fundamentals.get("macro_data")
    if isinstance(macro, dict):
        # skrót makro (inflacja, bezrobocie, stopy jeśli są)
        out["macro_data"] = {
            str(k): _safe_num(v) for k, v in list(macro.items())[:12]
        }

    cf = fundamentals.get("company_fundamentals")
    if isinstance(cf, dict):
        metrics = {}
        for k in _FUND_METRIC_KEYS:
            if cf.get(k) is not None:
                metrics[k] = _safe_num(cf.get(k))
        # wszystko inne numeryczne (limit)
        for k, v in cf.items():
            if k in metrics:
                continue
            if isinstance(v, (int, float)) and len(metrics) < 24:
                metrics[str(k)] = v
        if metrics:
            out["company_metrics"] = metrics
    return out


def _pack_perspective(perspective: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not perspective or not isinstance(perspective, dict):
        return {}
    keys = (
        "trend_3y",
        "position_in_range",
        "risk_of_drop_pct",
        "upside_potential_pct",
        "crash_risk_score",
        "risk_tier",
        "sharpe_ratio",
        "volatility",
        "best_analogy",
        "best_similarity",
        "hist_dd_p50",
        "hist_dd_p75",
        "hist_max_dd",
        "duza_okazja",
        "duze_zagrozenie",
        "high_3y",
        "low_3y",
    )
    return {k: _safe_num(perspective.get(k)) for k in keys if perspective.get(k) is not None}


def _sector_peers(ticker: str, sector: Optional[str], limit: int = 6) -> List[str]:
    """Peerzy z tego samego sektora (mapa w core), bez dodatkowego API."""
    try:
        import core_analysis as core
        mapping = getattr(core, "sector_mapping", None) or {}
        if not sector or sector in ("Unknown", "Index"):
            sector = mapping.get(ticker.upper())
        if not sector:
            return []
        peers = [t for t, s in mapping.items() if s == sector and t != ticker.upper()]
        return peers[:limit]
    except Exception:
        return []


def _parse_news_date(published: Any):
    """Best-effort parse of RSS pubDate / Atom updated → date."""
    from datetime import datetime, timezone, timedelta
    import email.utils

    if published is None:
        return None
    s = str(published).strip()
    if not s:
        return None
    # RFC 2822 (RSS)
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt is not None:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.date()
    except Exception:
        pass
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            raw = s.replace("Z", "+0000") if fmt.endswith("%z") and s.endswith("Z") else s
            if fmt.endswith("Z") and s.endswith("Z"):
                dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            else:
                dt = datetime.strptime(raw[: len(s)], fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.date()
        except Exception:
            continue
    return None


def _price_on_or_before(closes, target_date):
    """Last close on or before target_date from a DatetimeIndex series."""
    try:
        import pandas as pd

        if closes is None or len(closes) == 0:
            return None, None
        idx = pd.to_datetime(closes.index)
        # normalize to dates
        mask = idx.date <= target_date
        if not mask.any():
            return None, None
        sub = closes[mask]
        if len(sub) == 0:
            return None, None
        return float(sub.iloc[-1]), sub.index[-1]
    except Exception:
        return None, None


def _price_n_sessions_after(closes, after_date, n: int = 3):
    """Close n trading sessions after after_date (strictly later sessions)."""
    try:
        import pandas as pd

        if closes is None or len(closes) == 0:
            return None, None
        idx = pd.to_datetime(closes.index)
        later = closes[idx.date > after_date]
        if len(later) == 0:
            return None, None
        pos = min(n - 1, len(later) - 1)
        return float(later.iloc[pos]), later.index[pos]
    except Exception:
        return None, None


def analyze_news_market_reaction(
    ticker: str,
    headlines: List[Dict[str, Any]],
    *,
    max_items: int = 8,
) -> Dict[str, Any]:
    """
    For each headline with a date: measure if the market already moved after the news.
    Does NOT change the quant forecast — only desk context for the AI.
    """
    t = (ticker or "").upper().strip()
    out_items: List[Dict[str, Any]] = []
    try:
        import core_analysis as core
        import pandas as pd

        df = core.get_historical_prices(t, days=400)
        if df is None or getattr(df, "empty", True) or "Close" not in df.columns:
            return {
                "ticker": t,
                "items": [],
                "note": "No price history to check post-news reaction.",
            }
        closes = df["Close"].astype(float).dropna()
        last_close = float(closes.iloc[-1])
        last_date = pd.to_datetime(closes.index[-1]).date()
    except Exception as e:
        return {"ticker": t, "items": [], "note": f"Price load failed: {e}"}

    for h in (headlines or [])[: max_items + 4]:
        title = (h.get("title") or "").strip()
        if not title:
            continue
        pub = h.get("published") or h.get("pubDate") or ""
        nd = _parse_news_date(pub)
        row: Dict[str, Any] = {
            "title": title[:280],
            "published_raw": str(pub)[:80] if pub else None,
            "news_date": nd.isoformat() if nd else None,
            "source": (h.get("source") or "")[:60],
            "link": (h.get("link") or "")[:400],
        }
        if nd is None:
            row["priced_in_status"] = "unknown_date"
            row["note"] = "No reliable publish date — cannot check if market already moved."
            out_items.append(row)
            if len(out_items) >= max_items:
                break
            continue

        px0, _ = _price_on_or_before(closes, nd)
        px1, _ = _price_n_sessions_after(closes, nd, n=1)
        px3, _ = _price_n_sessions_after(closes, nd, n=3)
        px5, _ = _price_n_sessions_after(closes, nd, n=5)

        def _ret(a, b):
            if a is None or b is None or a == 0:
                return None
            return round((b / a - 1.0) * 100.0, 2)

        r1 = _ret(px0, px1)
        r3 = _ret(px0, px3)
        r5 = _ret(px0, px5)
        r_now = _ret(px0, last_close)

        # Heuristic: large move already happened after news → likely partially/fully priced
        abs_move = max(
            abs(r1 or 0),
            abs(r3 or 0),
            abs(r5 or 0),
        )
        days_ago = (last_date - nd).days if nd else None
        if days_ago is not None and days_ago < 0:
            status = "future_or_bad_date"
        elif abs_move >= 4.0 or (r_now is not None and abs(r_now) >= 5.0 and (days_ago or 0) <= 14):
            status = "likely_priced_in"
        elif abs_move >= 1.5:
            status = "partially_priced"
        elif days_ago is not None and days_ago <= 2 and abs_move < 1.5:
            status = "fresh_limited_reaction"
        elif days_ago is not None and days_ago > 21:
            status = "stale_news"
        else:
            status = "reaction_unclear"

        row.update(
            {
                "price_before": round(px0, 4) if px0 is not None else None,
                "ret_1s_pct": r1,
                "ret_3s_pct": r3,
                "ret_5s_pct": r5,
                "ret_since_news_to_now_pct": r_now,
                "sessions_since_news_est": days_ago,
                "priced_in_status": status,
            }
        )
        out_items.append(row)
        if len(out_items) >= max_items:
            break

    # Flag possible breakthrough-sized market moves (for AI attention)
    material = [
        x
        for x in out_items
        if x.get("priced_in_status") in ("likely_priced_in", "partially_priced", "fresh_limited_reaction")
        and (
            abs(x.get("ret_3s_pct") or 0) >= 3
            or abs(x.get("ret_since_news_to_now_pct") or 0) >= 4
            or x.get("priced_in_status") == "fresh_limited_reaction"
        )
    ]

    return {
        "ticker": t,
        "as_of_price": round(last_close, 4),
        "as_of_date": last_date.isoformat(),
        "items": out_items,
        "material_candidates": material[:5],
        "note": (
            "priced_in_status is a price-reaction heuristic after the news date, "
            "not a claim that the headline caused the move. AI must still judge if news is breakthrough."
        ),
    }


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def _calibrate_confidence(
    conf: str,
    quant: Dict[str, Any],
    fund_view: Optional[Dict[str, Any]] = None,
    world: Optional[Dict[str, Any]] = None,
) -> str:
    """Hard rules: confidence tracks hit sample, MAE, data gaps, news conflict."""
    c = str(conf or "medium").lower()
    if c not in ("low", "medium", "high"):
        c = "medium"
    rank = {"low": 0, "medium": 1, "high": 2}

    def _set_max(level: str):
        nonlocal c
        if rank[level] < rank.get(c, 1):
            c = level

    try:
        hr = quant.get("hit_rate")
        n = quant.get("n_significant")
        mae = quant.get("mae")
        if hr is not None:
            hr_f = float(hr)
            if hr_f < 40:
                _set_max("low")
            elif hr_f < 50:
                _set_max("medium")
                if c == "high":
                    c = "medium"
            elif hr_f >= 68 and n is not None and int(n) >= 7:
                # allow high only if already medium+ and sample is solid
                if c == "low":
                    c = "medium"
            if n is not None and int(n) < 4:
                _set_max("low" if hr_f < 55 else "medium")
            if n is not None and int(n) < 6 and c == "high":
                c = "medium"
        if mae is not None and float(mae) > 11:
            _set_max("medium")
            if float(mae) > 16:
                _set_max("low")
    except Exception:
        pass
    gaps = (fund_view or {}).get("data_gaps") or []
    if isinstance(gaps, list) and len(gaps) >= 2 and c == "high":
        c = "medium"
    if isinstance(gaps, list) and len(gaps) >= 4:
        _set_max("low")
    align = str((world or {}).get("alignment_with_model") or "").lower()
    if align == "contradicts":
        _set_max("medium")
        if c == "high":
            c = "medium"
    advice = str((world or {}).get("model_adjustment_advice") or "").lower()
    if "elevated_event_risk" in advice or "stale" in advice:
        if c == "high":
            c = "medium"
    # Breakthrough still unpriced → cap confidence
    try:
        bt = (world or {}).get("breakthrough_news") or []
        if isinstance(bt, list):
            for item in bt[:5]:
                if not isinstance(item, dict):
                    continue
                pi = str(item.get("priced_in") or "").lower()
                if pi in ("no", "unknown", "partially"):
                    if c == "high":
                        c = "medium"
                    break
    except Exception:
        pass
    return c


def _agent_fundamentals(ticker: str, desk: Dict[str, Any]) -> Dict[str, Any]:
    hz = (desk.get("quant") or {}).get("horizon") or "3M"
    prompt = f"""You are a senior fundamental analyst at a top long-only desk covering {ticker}.
Investment horizon for this memo: {hz}.
Write like an internal research note — precise, skeptical, number-driven.

Authoritative desk data (never invent missing metrics):
{json.dumps(desk, ensure_ascii=False, default=str)[:8000]}

Return ONLY valid JSON:
{{
  "fundamentals_summary": "8-12 sentences: quality of earnings, margins trajectory, growth durability, balance sheet, valuation vs history/peers if data allows; what rating/score implies for a {hz} hold",
  "strengths": ["3-5 specific strengths tied to numbers in the pack"],
  "weaknesses": ["3-5 specific weaknesses or open risks"],
  "macro_overlay": "3-5 sentences: country/macro transmission into this company's earnings over {hz}",
  "fundamental_stance": "constructive|neutral|cautious",
  "valuation_read": "cheap|fair|rich|unknown — based only on provided multiples",
  "horizon_fit": "1-3 sentences: are fundamentals more relevant on {hz} than on a pure short-term technical tape?",
  "data_gaps": ["metrics missing that should lower confidence"]
}}

Rules:
- Cite concrete figures from the pack (P/E, margins, scores, rating) when present.
- If fundamentals are thin, say so and lean cautious — do not bluff.
- Separate cyclical noise from structural franchise quality.
- English. No buy/sell. No personal price targets.
"""
    raw = ai_brief._gemini_generate(prompt, temperature=0.18)
    data = ai_brief._extract_json(raw)
    if not data.get("fundamentals_summary"):
        data["fundamentals_summary"] = str(data.get("raw") or raw)[:1800]
    return data


def _agent_quant(ticker: str, desk: Dict[str, Any], fund_view: Dict[str, Any], feedback_blob: str) -> Dict[str, Any]:
    hz = (desk.get("quant") or {}).get("horizon") or "3M"
    prompt = f"""You are a quantitative strategist for {ticker} on a {hz} horizon.
Your job is brutal honesty about model reliability — not cheerleading the forecast.

Desk quant:
{json.dumps(desk.get('quant', {}), ensure_ascii=False, default=str)}

3Y risk pack:
{json.dumps(desk.get('perspective_3y', {}), ensure_ascii=False, default=str)}

Fundamentals agent:
{json.dumps(fund_view, ensure_ascii=False)[:3000]}

{feedback_blob}

Return ONLY valid JSON:
{{
  "quant_summary": "7-10 sentences: direction, predicted_change_pct, RSI/score, whether the {hz} setup is clean or noisy",
  "hit_interpretation": "explicit: hit_rate, mae, n_significant for THIS ticker/horizon (e.g. hit~50% with n<5 = weak sample; hit>=65 with n>=7 = usable directional edge)",
  "confidence_from_model": "low|medium|high",
  "edge_quality": "weak|moderate|strong",
  "key_drivers": ["3-5 drivers grounded in the quant pack"],
  "warnings": ["2-5 model-risk warnings"],
  "horizon_notes": "how this {hz} forecast interacts with 3Y drop/crash risk and position-in-range if present",
  "regime_read": "trending|mean-reverting|high-vol|unclear — one short justification"
}}

Rules:
- predicted_change_pct and predicted_price are FIXED model outputs — never replace them with your own %.
- Reliability map: hit<45 or n<4 → low; hit 45-58 → medium at best; hit>=62 and n>=6 → medium/high only if MAE is not extreme.
- If model direction conflicts with fundamental_stance, flag it in warnings.
- Prefer under-confidence to over-confidence.
- English. No buy/sell.
"""
    raw = ai_brief._gemini_generate(prompt, temperature=0.18)
    data = ai_brief._extract_json(raw)
    if not data.get("quant_summary"):
        data["quant_summary"] = str(data.get("raw") or raw)[:1800]
    return data


def _agent_world(
    ticker: str,
    headlines: List[Dict[str, str]],
    fund_view: Dict[str, Any],
    quant_view: Dict[str, Any],
    desk: Dict[str, Any],
) -> Dict[str, Any]:
    titles = "\n".join(
        f"- {h.get('title')}"
        + (f" | date={h.get('published')}" if h.get("published") else "")
        + (f" ({h.get('source')})" if h.get("source") else "")
        for h in headlines[:18]
    ) or "(no headlines)"
    peers = desk.get("sector_peers") or []
    q = desk.get("quant") or {}
    reaction = desk.get("news_reaction") or {}
    prompt = f"""You are a macro and news risk analyst for {ticker}.
Peers (context only): {peers}
Model direction: {q.get('direction')} | model %: {q.get('predicted_change_pct')} | hit: {q.get('hit_rate')}

Fundamentals stance: {json.dumps(fund_view.get('fundamental_stance'))}
Quant excerpt: {json.dumps(quant_view.get('quant_summary'))[:900]}
Macro from desk: {json.dumps(desk.get('fundamentals', {}).get('macro_data', {}), ensure_ascii=False)[:1500]}

Headlines (with dates when available):
{titles}

MARKET REACTION AFTER NEWS DATES (measured from price history — not causation proof):
{json.dumps(reaction, ensure_ascii=False, default=str)[:4500]}

Your job:
1) Flag any BREAKTHROUGH / material news (earnings shock, guidance, regulation, M&A, major product, fraud, macro shock).
2) For each material item, use news_date + priced_in_status + ret_*_pct to say whether the market ALREADY moved after that date.
3) Say whether residual (not-yet-priced) risk/opportunity remains for the model horizon.

Return ONLY valid JSON:
{{
  "news_summary": "6-9 sentences",
  "sentiment": "bullish|bearish|neutral|mixed",
  "alignment_with_model": "supports|contradicts|mixed|unclear",
  "alignment_with_fundamentals": "supports|contradicts|mixed|unclear",
  "breakthrough_news": [
    {{
      "title": "...",
      "news_date": "YYYY-MM-DD or null",
      "why_material": "1-2 sentences",
      "priced_in": "yes|partially|no|unknown",
      "evidence": "cite ret_1s/ret_3s/ret_since or unknown_date"
    }}
  ],
  "model_adjustment_advice": "keep_model_path|treat_as_stale_shock|elevated_event_risk — explain in 2-4 sentences WITHOUT inventing a new forecast %",
  "world_risks": ["3-5 concrete external risks"],
  "themes": ["2-5 themes"],
  "catalysts": ["2-5 near-term catalysts"],
  "noise_vs_signal": "1-3 sentences"
}}

Rules:
- Do not invent earnings numbers not in headlines.
- If priced_in_status is likely_priced_in, do NOT claim the news is still a fresh unpriced catalyst.
- If fresh_limited_reaction on a clearly major headline, flag elevated event risk.
- English. No buy/sell. Never replace predicted_change_pct.
"""
    raw = ai_brief._gemini_generate(prompt, temperature=0.2)
    data = ai_brief._extract_json(raw)
    if not data.get("news_summary"):
        data["news_summary"] = str(data.get("raw") or raw)[:1800]
    if not isinstance(data.get("breakthrough_news"), list):
        data["breakthrough_news"] = []
    return data


def apply_agent_forecast_blend(
    quant: Dict[str, Any],
    fund_view: Dict[str, Any],
    quant_view: Dict[str, Any],
    world: Dict[str, Any],
    editor: Dict[str, Any],
) -> Dict[str, Any]:
    """
    FORCED agent influence on displayed forecast %.
    Base = AssetCore model. Agents always contribute a scored adjustment.
    Gemini often returns adjustment=0 — fund/news/quant still score in code.
    """
    try:
        if quant.get("model_predicted_change_pct") is not None:
            model_pct = float(quant.get("model_predicted_change_pct"))
        else:
            model_pct = float(quant.get("predicted_change_pct"))
    except Exception:
        model_pct = 0.0

    try:
        editor_adj = float(editor.get("forecast_adjustment_pct") or 0.0)
    except Exception:
        editor_adj = 0.0

    align_n = str(world.get("alignment_with_model") or "").lower()
    stance = str(fund_view.get("fundamental_stance") or "").lower()
    sent = str(editor.get("sentiment") or world.get("sentiment") or "").lower()
    advice = str(
        world.get("model_adjustment_advice")
        or editor.get("model_adjustment_advice")
        or ""
    ).lower()
    conf_m = str(quant_view.get("confidence_from_model") or "").lower()
    edge = str(quant_view.get("edge_quality") or editor.get("edge_call") or "").lower()

    score = 0.0
    reasons: List[str] = []

    if stance == "constructive":
        score += 1.4
        reasons.append("fundamentals constructive")
    elif stance == "cautious":
        score -= 1.4
        reasons.append("fundamentals cautious")

    if align_n == "supports":
        score += 1.6
        reasons.append("news supports model")
    elif align_n == "contradicts":
        score -= 2.2
        reasons.append("news contradicts model")
    elif align_n == "mixed":
        score -= 0.4
        reasons.append("news mixed vs model")

    if sent == "bullish":
        score += 0.8
        reasons.append("sentiment bullish")
    elif sent == "bearish":
        score -= 0.8
        reasons.append("sentiment bearish")

    if "elevated_event_risk" in advice:
        score -= 1.2
        reasons.append("elevated event risk")

    bt = world.get("breakthrough_news") or editor.get("breakthrough_news") or []
    if isinstance(bt, list):
        for item in bt[:6]:
            if not isinstance(item, dict):
                continue
            pi = str(item.get("priced_in") or "").lower()
            blob = (str(item.get("why_material") or "") + " " + str(item.get("title") or "")).lower()
            if pi in ("yes", "likely_priced_in"):
                continue
            bull_w = ("beat", "raise", "approval", "win", "surge", "record", "growth", "upgrade")
            bear_w = ("miss", "cut", "probe", "lawsuit", "ban", "recall", "fraud", "downgrade", "delay")
            if any(w in blob for w in bull_w):
                score += 1.1
                reasons.append("unpriced positive headline")
            if any(w in blob for w in bear_w):
                score -= 1.1
                reasons.append("unpriced negative headline")

    if conf_m == "low" or "weak" in edge:
        if model_pct > 0:
            score -= 0.7
        elif model_pct < 0:
            score += 0.7
        reasons.append("quant edge weak → dampen")
    elif conf_m == "high" or "strong" in edge:
        if model_pct > 0:
            score += 0.5
        elif model_pct < 0:
            score -= 0.5
        reasons.append("quant edge strong → reinforce")

    score += max(-3.0, min(3.0, editor_adj * 0.85))
    if abs(editor_adj) >= 0.25:
        reasons.append(f"editor adj {editor_adj:+.2f}")

    adj = score * 0.85

    # Always make a visible delta if we have any agent signal
    if abs(adj) < 0.35:
        if score > 0.05 or stance == "constructive" or align_n == "supports" or sent == "bullish":
            adj = 0.7 if model_pct >= 0 else -0.7
        elif score < -0.05 or stance == "cautious" or align_n == "contradicts" or sent == "bearish":
            adj = -0.7 if model_pct >= 0 else 0.7
        else:
            # pure neutral agents still show a tiny dampen toward zero so % is not identical
            adj = -0.5 if model_pct > 0.5 else (0.5 if model_pct < -0.5 else 0.4)
        reasons.append("forced visible agent delta")

    try:
        hr = float(quant.get("hit_rate")) if quant.get("hit_rate") is not None else 55.0
    except Exception:
        hr = 55.0
    max_adj = min(9.0, abs(model_pct) * 0.65 + 2.5)
    if hr < 45:
        max_adj *= 0.55
    elif hr < 55:
        max_adj *= 0.8
    adj = max(-max_adj, min(max_adj, adj))
    final_pct = model_pct + adj

    cur = quant.get("current_price")
    try:
        cur_f = float(cur) if cur is not None else None
    except Exception:
        cur_f = None
    pred_price = None
    if cur_f is not None and cur_f > 0:
        pred_price = round(cur_f * (1.0 + final_pct / 100.0), 4)

    if final_pct > 1.0:
        direction = "WZROSTOWY"
    elif final_pct < -1.0:
        direction = "SPADKOWY"
    else:
        direction = "NEUTRAL"

    reason = editor.get("adjustment_reason") or ""
    if not reason:
        reason = "; ".join(reasons[:8]) if reasons else "neutral agent set"
    else:
        reason = f"{reason} | signals: {'; '.join(reasons[:6])}"

    return {
        "model_predicted_change_pct": round(model_pct, 2),
        "agent_adjustment_pct": round(adj, 2),
        "predicted_change_pct": round(final_pct, 2),
        "predicted_price": pred_price,
        "direction": direction,
        "adjustment_reason": str(reason)[:600],
        "agents_influenced_forecast": True,
        "max_adjustment_allowed": round(max_adj, 2),
        "agent_score": round(score, 2),
    }


def _agent_editor(
    ticker: str,
    desk: Dict[str, Any],
    fund_view: Dict[str, Any],
    quant_view: Dict[str, Any],
    world: Dict[str, Any],
    feedback_blob: str,
) -> Dict[str, Any]:
    quant = desk.get("quant") or {}
    model_pct = quant.get("predicted_change_pct")
    hz = quant.get("horizon") or "3M"
    hr = quant.get("hit_rate")
    nsig = quant.get("n_significant")
    prompt = f"""You are CIO desk editor for AssetCore covering {ticker} on a {hz} horizon.
Write an institutional research synthesis — crisp, non-hype, decision-useful.

Integrate agents: fundamentals, quant, news/macro.
AssetCore MODEL base forecast: {model_pct}% | hit_rate={hr} | n_significant={nsig}.

You MAY adjust the forecast in percentage POINTS via forecast_adjustment_pct
(e.g. model +5.0 and adjustment -1.5 → displayed +3.5).
Hard limit: -8 to +8. Prefer |adj| <= 3 when hit_rate < 55 or n_significant < 6.
Start from the model; apply agent pressure only with evidence.

DESK QUANT (model base):
{json.dumps(quant, ensure_ascii=False, default=str)}

FUNDAMENTALS pack:
{json.dumps(desk.get('fundamentals', {}), ensure_ascii=False, default=str)[:4200]}

3Y risk:
{json.dumps(desk.get('perspective_3y', {}), ensure_ascii=False, default=str)}

NEWS REACTION (priced-in checks):
{json.dumps(desk.get('news_reaction', {}), ensure_ascii=False, default=str)[:3500]}

Agent — Fundamentals:
{json.dumps(fund_view, ensure_ascii=False)[:3200]}

Agent — Quant:
{json.dumps(quant_view, ensure_ascii=False)[:2800]}

Agent — News/Macro:
{json.dumps(world, ensure_ascii=False)[:2800]}

{feedback_blob}

Peers: {json.dumps(desk.get('sector_peers', []), ensure_ascii=False)}

Return ONLY valid JSON:
{{
  "executive_summary": "10-14 sentences: {hz} thesis, model base %, agent tilt, hit reliability, whether news is priced in",
  "situation_assessment": "4-6 sentences on positioning and regime",
  "fundamentals_verdict": "4-6 sentences",
  "base_scenario": "most likely {hz} path after agent blend",
  "bull_case": "2-4 sentences: what has to go right",
  "risk_scenario": "what breaks the thesis on {hz}",
  "devil_advocate": "5-8 sentences arguing the OPPOSITE of the blended direction with specific mechanisms",
  "key_objections": ["4-6 concrete objections"],
  "sentiment": "bullish|bearish|neutral|mixed",
  "confidence": "low|medium|high",
  "model_vs_news": "paragraph",
  "model_vs_fundamentals": "paragraph",
  "peer_context": "2-4 sentences",
  "watchpoints": ["6-9 falsifiable watchpoints for the next weeks"],
  "what_would_change_mind": ["2-4 concrete data points that would flip the stance"],
  "edge_call": "one sentence: is the edge usable, informational, or noise?",
  "forecast_adjustment_pct": 0.0,
  "adjustment_reason": "2-4 sentences: evidence for pulling % vs model base {model_pct}",
  "uses_model_forecast": true
}}

Rules:
1) forecast_adjustment_pct = percentage POINTS added to model (not a full replacement %).
2) priced_in=yes breakthrough → do not re-shock the path for that headline.
3) Fresh unpriced negative → negative adj; unpriced positive → positive adj.
4) Weak hit_rate / small n → smaller |adjustment| and confidence not high.
5) Devil advocate must not repeat the bull case in softer words.
6) English. No buy/sell label. No invented earnings numbers.
"""
    raw = ai_brief._gemini_generate(prompt, temperature=0.18)
    data = ai_brief._extract_json(raw)
    if not data.get("executive_summary"):
        data["executive_summary"] = str(data.get("raw") or raw)[:2800]

    data["confidence"] = _calibrate_confidence(
        str(data.get("confidence") or "medium"),
        quant if isinstance(quant, dict) else {},
        fund_view,
        world,
    )

    sent = str(data.get("sentiment") or world.get("sentiment") or "neutral").lower()
    if sent not in ("bullish", "bearish", "neutral", "mixed"):
        sent = "neutral"
    data["sentiment"] = sent
    data["uses_model_forecast"] = True
    if not data.get("devil_advocate"):
        data["devil_advocate"] = (
            "Counter-thesis incomplete; treat confidence conservatively and verify "
            "headlines, hit sample size, and fundamentals independently."
        )
    if not isinstance(data.get("key_objections"), list):
        data["key_objections"] = []
    if not data.get("bull_case"):
        data["bull_case"] = data.get("base_scenario") or "Upside path not separately specified."
    if not isinstance(data.get("what_would_change_mind"), list):
        data["what_would_change_mind"] = data.get("watchpoints")[:3] if isinstance(data.get("watchpoints"), list) else []
    # Soft clamp LLM adjustment when sample is weak (code-side, not hit manipulation)
    try:
        hr_f = float(quant.get("hit_rate")) if quant.get("hit_rate") is not None else None
        n_f = int(quant.get("n_significant")) if quant.get("n_significant") is not None else None
        adj = float(data.get("forecast_adjustment_pct") or 0.0)
        cap = 8.0
        if hr_f is not None and hr_f < 48:
            cap = 2.5
        elif hr_f is not None and hr_f < 55:
            cap = 4.0
        if n_f is not None and n_f < 5:
            cap = min(cap, 2.5)
        data["forecast_adjustment_pct"] = float(max(-cap, min(cap, adj)))
    except Exception:
        pass
    if not data.get("edge_call"):
        try:
            hr = quant.get("hit_rate")
            data["edge_call"] = (
                f"Model hit_rate={hr}: treat edge as informational until sample size and alignment improve."
            )
        except Exception:
            data["edge_call"] = "Edge quality unclear — verify hit_rate and n_significant."
    try:
        data["forecast_adjustment_pct"] = float(data.get("forecast_adjustment_pct") or 0.0)
    except Exception:
        data["forecast_adjustment_pct"] = 0.0
    return data


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def build_full(
    ticker: str,
    quant: Dict[str, Any],
    *,
    fundamentals: Optional[Dict[str, Any]] = None,
    perspective: Optional[Dict[str, Any]] = None,
    horizon: str = "1M",
    use_cache: bool = True,
) -> Dict[str, Any]:
    t = (ticker or "").upper().strip()
    if not t:
        raise ValueError("Invalid ticker")
    hz = str(horizon or "3M").upper().strip()
    if hz.startswith("6"):
        hz = "6M"
    elif hz.startswith("3"):
        hz = "3M"
    else:
        hz = "3M"  # AI desk default

    if use_cache:
        hit = _cache_get(t, hz)
        if hit:
            return hit

    if not configured():
        raise RuntimeError("GEMINI_API_KEY not set")

    fund_pack = _pack_fundamentals(fundamentals)
    pers_pack = _pack_perspective(perspective)
    sector = (
        (fund_pack.get("sector") if fund_pack else None)
        or quant.get("sector")
    )
    peers = _sector_peers(t, str(sector) if sector else None)

    q = {
        "ticker": t,
        "horizon": hz,
        "current_price": quant.get("current_price"),
        "predicted_price": quant.get("predicted_price"),
        "predicted_change_pct": quant.get("predicted_change_pct"),
        "direction": quant.get("direction"),
        "hit_rate": quant.get("hit_rate"),
        "mae": quant.get("mae"),
        "n_significant": quant.get("n_significant"),
        "combined_score": quant.get("combined_score"),
        "fundamental_rating": quant.get("fundamental_rating")
        or fund_pack.get("fundamental_rating"),
        "rsi": quant.get("rsi"),
        "sector": sector,
    }

    desk = {
        "quant": q,
        "fundamentals": fund_pack,
        "perspective_3y": pers_pack,
        "sector_peers": peers,
    }

    feedback_blob = _feedback_for_prompt(t)
    # Soft Hit% calibration for this run only (does not change quant math)
    try:
        hr = q.get("hit_rate")
        mae = q.get("mae")
        nsig = q.get("n_significant")
        if hr is not None:
            feedback_blob += (
                f"\n\nLive model reliability for this ticker/horizon: "
                f"hit_rate={hr}, mae={mae}, n_significant={nsig}. "
                f"If hit_rate < 50, keep confidence low/medium and stress devil_advocate."
            )
    except Exception:
        pass
    headlines = ai_brief.fetch_headlines(t, limit=max(ai_brief.MAX_HEADLINES, 18))
    news_reaction = analyze_news_market_reaction(t, headlines, max_items=8)
    desk["news_reaction"] = news_reaction

    # v6 pipeline: fund → quant (with fund) → world → editor (quality over parallel race)
    fund_view = _agent_fundamentals(t, desk)
    quant_view = _agent_quant(t, desk, fund_view if isinstance(fund_view, dict) else {}, feedback_blob)
    if isinstance(quant_view, dict) and isinstance(fund_view, dict):
        quant_view = dict(quant_view)
        quant_view["fundamentals_stance_ref"] = fund_view.get("fundamental_stance")

    world = _agent_world(t, headlines, fund_view, quant_view, desk)
    final = _agent_editor(t, desk, fund_view, quant_view, world, feedback_blob)

    blend = apply_agent_forecast_blend(q, fund_view, quant_view, world, final)
    q_out = dict(q)
    q_out["model_predicted_change_pct"] = blend.get("model_predicted_change_pct")
    q_out["agent_adjustment_pct"] = blend.get("agent_adjustment_pct")
    q_out["predicted_change_pct"] = blend.get("predicted_change_pct")
    q_out["predicted_price"] = blend.get("predicted_price") or q_out.get("predicted_price")
    q_out["direction"] = blend.get("direction") or q_out.get("direction")
    q_out["agents_influenced_forecast"] = True
    q_out["adjustment_reason"] = blend.get("adjustment_reason")

    out: Dict[str, Any] = {
        "ticker": t,
        "horizon": hz,
        "quant": q_out,
        # Top-level mirrors for UI that reads predicted_change_pct on root
        "predicted_change_pct": q_out.get("predicted_change_pct"),
        "predicted_price": q_out.get("predicted_price"),
        "direction": q_out.get("direction"),
        "model_predicted_change_pct": blend.get("model_predicted_change_pct"),
        "agent_adjustment_pct": blend.get("agent_adjustment_pct"),
        "adjustment_reason": blend.get("adjustment_reason"),
        "agents_used": ["fundamentals", "quant", "world_news", "editor"],
        "fundamentals_pack": fund_pack,
        "perspective_3y": pers_pack,
        "sector_peers": peers,
        "news_reaction": news_reaction,
        "breakthrough_news": world.get("breakthrough_news") or [],
        "model_adjustment_advice": world.get("model_adjustment_advice"),
        "executive_summary": final.get("executive_summary"),
        "situation_assessment": final.get("situation_assessment"),
        "fundamentals_verdict": final.get("fundamentals_verdict"),
        "fundamentals_summary": fund_view.get("fundamentals_summary"),
        "base_scenario": final.get("base_scenario"),
        "risk_scenario": final.get("risk_scenario"),
        "sentiment": final.get("sentiment"),
        "confidence": final.get("confidence"),
        "model_vs_news": final.get("model_vs_news"),
        "model_vs_fundamentals": final.get("model_vs_fundamentals"),
        "watchpoints": final.get("watchpoints") or [],
        "devil_advocate": final.get("devil_advocate"),
        "key_objections": final.get("key_objections") or [],
        "peer_context": final.get("peer_context"),
        "edge_call": final.get("edge_call"),
        "quant_summary": quant_view.get("quant_summary"),
        "hit_interpretation": quant_view.get("hit_interpretation"),
        "news_summary": world.get("news_summary"),
        "alignment_with_model": world.get("alignment_with_model"),
        "themes": world.get("themes") or [],
        "world_risks": world.get("world_risks") or [],
        "strengths": fund_view.get("strengths") or [],
        "weaknesses": fund_view.get("weaknesses") or [],
        "data_gaps": fund_view.get("data_gaps") or [],
        "headlines": [
            {
                "title": h.get("title"),
                "link": h.get("link"),
                "source": h.get("source"),
                "published": h.get("published"),
            }
            for h in headlines[:12]
        ],
        "engine": _BUILD,
        "model": ai_brief.GEMINI_MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
        "disclaimer": _DISCLAIMER,
        "feedback_injected": True,
        "agents_influenced_forecast": True,
    }
    _cache_set(t, hz, out)
    return out


def build_board_row(
    ticker: str,
    quant: Dict[str, Any],
    *,
    horizon: str = "1M",
    use_cache: bool = True,
    fundamentals: Optional[Dict[str, Any]] = None,
    perspective: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Board / quick desk note: quant + fundamentals + 3Y + headlines in ONE strong synthesis.
    Still not the 4-agent full desk (that is /ai/full), but much richer than a 3-line summary.
    """
    t = (ticker or "").upper().strip()
    if not t:
        raise ValueError("Invalid ticker")
    hz = str(horizon or "3M").upper().strip()
    if hz.startswith("6"):
        hz = "6M"
    elif hz.startswith("3"):
        hz = "3M"
    else:
        hz = "3M"  # AI desk default

    if use_cache:
        hit = _cache_get(t, hz)
        if hit:
            return hit

    if not configured():
        raise RuntimeError("GEMINI_API_KEY not set")

    fund_pack = _pack_fundamentals(fundamentals)
    pers_pack = _pack_perspective(perspective)
    sector = (fund_pack.get("sector") if fund_pack else None) or quant.get("sector")

    q = {
        "ticker": t,
        "horizon": hz,
        "current_price": quant.get("current_price"),
        "predicted_price": quant.get("predicted_price"),
        "predicted_change_pct": quant.get("predicted_change_pct"),
        "direction": quant.get("direction"),
        "hit_rate": quant.get("hit_rate"),
        "mae": quant.get("mae"),
        "n_significant": quant.get("n_significant"),
        "combined_score": quant.get("combined_score"),
        "fundamental_rating": quant.get("fundamental_rating")
        or fund_pack.get("fundamental_rating"),
        "rsi": quant.get("rsi"),
        "sector": sector,
    }

    headlines: List[Dict[str, str]] = []
    try:
        headlines = ai_brief.fetch_headlines(t, limit=12)
    except Exception as e:
        print(f"[ai_board] headlines {t}: {e}")

    news_reaction = analyze_news_market_reaction(t, headlines, max_items=8)

    titles = "\n".join(
        f"- {h.get('title')}"
        + (f" | date={h.get('published')}" if h.get("published") else "")
        + (f" ({h.get('source')})" if h.get("source") else "")
        for h in headlines[:12]
    ) or "(no recent headlines)"

    feedback_blob = _feedback_for_prompt(t)
    prompt = f"""You are a senior multi-asset desk analyst at AssetCore writing an institutional board note on {t}.
Integrate: quant model, fundamentals, 3Y risk, AND news with whether the market already priced it.
Model prices and predicted_change_pct are FIXED — never invent a different forecast %.

QUANT (authoritative):
{json.dumps(q, ensure_ascii=False, default=str)}

FUNDAMENTALS pack:
{json.dumps(fund_pack, ensure_ascii=False, default=str)[:3500]}

3Y RISK pack:
{json.dumps(pers_pack, ensure_ascii=False, default=str)}

HEADLINES:
{titles}

NEWS DATE → PRICE REACTION (from history; not proof of causation):
{json.dumps(news_reaction, ensure_ascii=False, default=str)[:4500]}

{feedback_blob}

Return ONLY valid JSON:
{{
  "executive_summary": "10-14 dense sentences including forecast %, hit_rate, and whether any breakthrough news looks unpriced vs already moved",
  "situation_assessment": "4-6 sentences",
  "fundamentals_verdict": "3-5 sentences",
  "base_scenario": "most likely path over {hz} if model holds",
  "risk_scenario": "what breaks the thesis",
  "devil_advocate": "5-7 sentences against model direction",
  "breakthrough_news": [
    {{
      "title": "...",
      "news_date": "YYYY-MM-DD or null",
      "why_material": "...",
      "priced_in": "yes|partially|no|unknown",
      "evidence": "cite ret_1s/ret_3s/ret_since or unknown_date"
    }}
  ],
  "model_adjustment_advice": "keep_model_path|treat_as_stale_shock|elevated_event_risk — 2-4 sentences, no new forecast %",
  "key_objections": ["4-6 concrete objections"],
  "sentiment": "bullish|bearish|neutral|mixed",
  "confidence": "low|medium|high",
  "model_vs_news": "short paragraph",
  "model_vs_fundamentals": "short paragraph",
  "edge_call": "one sentence on desk edge quality",
  "watchpoints": ["5-8 concrete watchpoints"],
  "uses_model_forecast": true
}}

Hard rules:
1) If a headline is material AND priced_in_status is likely_priced_in, say residual impact is limited.
2) If material AND fresh_limited_reaction, flag elevated event risk (do not invent a new %).
3) hit_rate < 45 or n_significant < 4 → confidence low.
4) English. No buy/sell.
"""
    text = ai_brief._gemini_generate(prompt, temperature=0.15)
    parsed = ai_brief._extract_json(text)
    if not isinstance(parsed, dict):
        parsed = {}

    conf = _calibrate_confidence(
        str(parsed.get("confidence") or "medium"),
        q,
        {"data_gaps": [] if fund_pack else ["fundamentals missing"]},
        {"alignment_with_model": "mixed" if "conflict" in str(parsed.get("model_vs_news") or "").lower() else None},
    )
    sent = str(parsed.get("sentiment") or "neutral").lower()
    if sent not in ("bullish", "bearish", "neutral", "mixed"):
        sent = "neutral"

    watches = parsed.get("watchpoints") or []
    if not isinstance(watches, list):
        watches = []
    objections = parsed.get("key_objections") or []
    if not isinstance(objections, list):
        objections = []
    breakthrough = parsed.get("breakthrough_news") or []
    if not isinstance(breakthrough, list):
        breakthrough = []

    # Force agent influence on % even on the single-call board path
    blend = apply_agent_forecast_blend(
        q,
        {"fundamental_stance": parsed.get("fundamentals_verdict") and "neutral" or "neutral"},
        {},
        {
            "alignment_with_model": "mixed",
            "sentiment": parsed.get("sentiment"),
            "model_adjustment_advice": parsed.get("model_adjustment_advice"),
            "breakthrough_news": breakthrough,
        },
        parsed,
    )
    # Improve stance from text
    fv_text = str(parsed.get("fundamentals_verdict") or "").lower()
    stance = "neutral"
    if any(w in fv_text for w in ("strong", "solid", "robust", "healthy", "constructive")):
        stance = "constructive"
    if any(w in fv_text for w in ("weak", "levered", "risk", "caution", "fragile", "deterior")):
        stance = "cautious"
    mvn = str(parsed.get("model_vs_news") or "").lower()
    align = "mixed"
    if "support" in mvn or "agree" in mvn:
        align = "supports"
    if "conflict" in mvn or "contradict" in mvn or "disagree" in mvn:
        align = "contradicts"
    blend = apply_agent_forecast_blend(
        q,
        {"fundamental_stance": stance},
        {"confidence_from_model": parsed.get("confidence"), "edge_quality": parsed.get("edge_call")},
        {
            "alignment_with_model": align,
            "sentiment": parsed.get("sentiment"),
            "model_adjustment_advice": parsed.get("model_adjustment_advice"),
            "breakthrough_news": breakthrough,
        },
        parsed,
    )
    q = dict(q)
    q["model_predicted_change_pct"] = blend["model_predicted_change_pct"]
    q["agent_adjustment_pct"] = blend["agent_adjustment_pct"]
    q["predicted_change_pct"] = blend["predicted_change_pct"]
    q["predicted_price"] = blend.get("predicted_price") or q.get("predicted_price")
    q["direction"] = blend.get("direction") or q.get("direction")
    q["agents_influenced_forecast"] = True
    q["adjustment_reason"] = blend.get("adjustment_reason")

    out: Dict[str, Any] = {
        "ticker": t,
        "horizon": hz,
        "quant": q,
        "predicted_change_pct": q.get("predicted_change_pct"),
        "predicted_price": q.get("predicted_price"),
        "direction": q.get("direction"),
        "model_predicted_change_pct": q.get("model_predicted_change_pct"),
        "agent_adjustment_pct": q.get("agent_adjustment_pct"),
        "adjustment_reason": q.get("adjustment_reason"),
        "agents_influenced_forecast": True,
        "fundamentals_pack": fund_pack,
        "perspective_3y": pers_pack,
        "news_reaction": news_reaction,
        "breakthrough_news": breakthrough[:6],
        "model_adjustment_advice": parsed.get("model_adjustment_advice"),
        "executive_summary": parsed.get("executive_summary")
        or f"{t}: model {q.get('predicted_change_pct')}% ({hz}), hit {q.get('hit_rate')}.",
        "situation_assessment": parsed.get("situation_assessment"),
        "fundamentals_verdict": parsed.get("fundamentals_verdict"),
        "base_scenario": parsed.get("base_scenario"),
        "risk_scenario": parsed.get("risk_scenario"),
        "devil_advocate": parsed.get("devil_advocate")
        or "Counter-thesis incomplete — verify news and hit sample independently.",
        "key_objections": [str(x)[:200] for x in objections[:6]],
        "sentiment": sent,
        "confidence": conf,
        "model_vs_news": parsed.get("model_vs_news"),
        "model_vs_fundamentals": parsed.get("model_vs_fundamentals"),
        "edge_call": parsed.get("edge_call"),
        "watchpoints": [str(x)[:180] for x in watches[:8]],
        "headlines": [
            {
                "title": h.get("title"),
                "link": h.get("link"),
                "source": h.get("source"),
                "published": h.get("published"),
            }
            for h in headlines[:10]
        ],
        "engine": "ai-board-news-react-v1",
        "model": ai_brief.GEMINI_MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
        "disclaimer": _DISCLAIMER,
        "board_fast": True,
        "uses_model_forecast": True,
    }
    _cache_set(t, hz, out)
    return out
