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

_BUILD = "ai-full-v3.2-learn"
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MIN = float(os.environ.get("AI_FULL_CACHE_MINUTES") or "1080")

_FB_LOCK = threading.Lock()
_FB_PATH = Path(
    os.environ.get("AI_FEEDBACK_PATH")
    or os.path.join(os.path.dirname(__file__), "ai_feedback.json")
)
_MAX_FEEDBACK = 200

_DISCLAIMER = (
    "AssetCore desk synthesis: quantitative model outputs + fundamentals/macro + news. "
    "Price forecasts come from the AssetCore model, not from the LLM. "
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
    hz = "3M" if str(horizon).upper().startswith("3") else "1M"
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

def _ck(ticker: str, horizon: str) -> str:
    return f"{ticker.upper().strip()}|{horizon.upper().strip()}|v3.2"


def _cache_get(ticker: str, horizon: str) -> Optional[Dict[str, Any]]:
    key = _ck(ticker, horizon)
    with _CACHE_LOCK:
        row = _CACHE.get(key)
        if not row:
            return None
        if time.time() - row["ts"] > _CACHE_MIN * 60:
            _CACHE.pop(key, None)
            return None
        out = dict(row["data"])
        out["cached"] = True
        return out


def _cache_set(ticker: str, horizon: str, data: Dict[str, Any]) -> None:
    key = _ck(ticker, horizon)
    with _CACHE_LOCK:
        _CACHE[key] = {"ts": time.time(), "data": dict(data)}
        if len(_CACHE) > 100:
            oldest = sorted(_CACHE.items(), key=lambda kv: kv[1]["ts"])[:30]
            for k, _ in oldest:
                _CACHE.pop(k, None)


def ranking_rows(horizon: str = "1M", limit: int = 12) -> List[Dict[str, Any]]:
    """Slim rows from the in-memory AI cache (forecast stays the model number)."""
    hz = "3M" if str(horizon).upper().startswith("3") else "1M"
    suffix = f"|{hz}|v3.2"
    rows: List[Dict[str, Any]] = []
    with _CACHE_LOCK:
        items = list(_CACHE.items())
    for key, row in items:
        if not str(key).endswith(suffix):
            continue
        data = row.get("data") or {}
        q = data.get("quant") or {}
        if not isinstance(q, dict):
            q = {}
        rows.append(
            {
                "ticker": data.get("ticker") or q.get("ticker"),
                "horizon": hz,
                "current_price": q.get("current_price"),
                "predicted_price": q.get("predicted_price"),
                "predicted_change_pct": q.get("predicted_change_pct"),
                "direction": q.get("direction"),
                "hit_rate": q.get("hit_rate"),
                "sector": q.get("sector"),
                "fundamental_rating": q.get("fundamental_rating"),
                "sentiment": data.get("sentiment"),
                "confidence": data.get("confidence"),
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


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def _agent_fundamentals(ticker: str, desk: Dict[str, Any]) -> Dict[str, Any]:
    prompt = f"""You are a senior fundamental analyst at a buy-side desk covering {ticker}.

Authoritative desk data (do not invent metrics that are missing/null):
{json.dumps(desk, ensure_ascii=False, default=str)[:7000]}

Return ONLY valid JSON:
{{
  "fundamentals_summary": "6-9 sentences: quality of business, profitability, growth, leverage, valuation vs sector if possible",
  "strengths": ["..."],
  "weaknesses": ["..."],
  "macro_overlay": "2-4 sentences on country/macro vs company",
  "fundamental_stance": "constructive|neutral|cautious",
  "data_gaps": ["list metrics that are missing and limit confidence"]
}}

Rules:
- Use only provided numbers. If a metric is null/missing, say so in data_gaps.
- English. No buy/sell recommendation. No price targets of your own.
"""
    raw = ai_brief._gemini_generate(prompt, temperature=0.22)
    data = ai_brief._extract_json(raw)
    if not data.get("fundamentals_summary"):
        data["fundamentals_summary"] = str(data.get("raw") or raw)[:1500]
    return data


def _agent_quant(ticker: str, desk: Dict[str, Any], fund_view: Dict[str, Any], feedback_blob: str) -> Dict[str, Any]:
    prompt = f"""You are a quantitative strategist for {ticker}.

Desk quant + risk pack:
{json.dumps(desk.get('quant', {}), ensure_ascii=False, default=str)}

3Y perspective:
{json.dumps(desk.get('perspective_3y', {}), ensure_ascii=False, default=str)}

Fundamentals agent view:
{json.dumps(fund_view, ensure_ascii=False)[:2500]}

{feedback_blob}

Return ONLY valid JSON:
{{
  "quant_summary": "5-8 sentences on forecast, Hit%, score, technical context",
  "hit_interpretation": "how trustworthy the model looks given hit_rate, mae, n_significant",
  "confidence_from_model": "low|medium|high",
  "key_drivers": ["..."],
  "warnings": ["..."],
  "horizon_notes": "what 1M vs 3Y risk implies together"
}}

Rules:
- predicted_change_pct and predicted_price are AUTHORITATIVE — do not replace them.
- Low hit_rate or small n_significant → lower confidence_from_model.
- English. No buy/sell.
"""
    raw = ai_brief._gemini_generate(prompt, temperature=0.22)
    data = ai_brief._extract_json(raw)
    if not data.get("quant_summary"):
        data["quant_summary"] = str(data.get("raw") or raw)[:1500]
    return data


def _agent_world(
    ticker: str,
    headlines: List[Dict[str, str]],
    fund_view: Dict[str, Any],
    quant_view: Dict[str, Any],
    desk: Dict[str, Any],
) -> Dict[str, Any]:
    titles = "\n".join(
        f"- {h.get('title')}" + (f" ({h.get('source')})" if h.get("source") else "")
        for h in headlines[:18]
    ) or "(no headlines)"
    peers = desk.get("sector_peers") or []
    prompt = f"""You are a macro and news analyst for {ticker} (sector peers for context: {peers}).

Fundamentals stance: {json.dumps(fund_view.get('fundamental_stance'))}
Quant view excerpt: {json.dumps(quant_view.get('quant_summary'))[:800]}
Macro from desk: {json.dumps(desk.get('fundamentals', {}).get('macro_data', {}), ensure_ascii=False)[:1500]}

Headlines:
{titles}

Return ONLY valid JSON:
{{
  "news_summary": "5-8 sentences",
  "sentiment": "bullish|bearish|neutral|mixed",
  "alignment_with_model": "supports|contradicts|mixed|unclear",
  "alignment_with_fundamentals": "supports|contradicts|mixed|unclear",
  "world_risks": ["..."],
  "themes": ["..."],
  "catalysts": ["near-term events or themes to watch"]
}}

Rules: Do not invent earnings figures. English. No buy/sell.
"""
    raw = ai_brief._gemini_generate(prompt, temperature=0.28)
    data = ai_brief._extract_json(raw)
    if not data.get("news_summary"):
        data["news_summary"] = str(data.get("raw") or raw)[:1500]
    return data


def _agent_editor(
    ticker: str,
    desk: Dict[str, Any],
    fund_view: Dict[str, Any],
    quant_view: Dict[str, Any],
    world: Dict[str, Any],
    feedback_blob: str,
) -> Dict[str, Any]:
    prompt = f"""You are the Chief Investment Office editor for AssetCore covering {ticker}.
Your job: produce the closest thing to an institutional one-pager using ONLY the desk pack.
You do NOT replace the quant price forecast.

DESK QUANT (authoritative prices):
{json.dumps(desk.get('quant', {}), ensure_ascii=False, default=str)}

FUNDAMENTALS pack:
{json.dumps(desk.get('fundamentals', {}), ensure_ascii=False, default=str)[:4000]}

3Y:
{json.dumps(desk.get('perspective_3y', {}), ensure_ascii=False, default=str)}

Agent — Fundamentals:
{json.dumps(fund_view, ensure_ascii=False)[:3000]}

Agent — Quant:
{json.dumps(quant_view, ensure_ascii=False)[:2500]}

Agent — News/Macro:
{json.dumps(world, ensure_ascii=False)[:2500]}

{feedback_blob}

Sector peers (names only, for relative context — no peer prices unless in pack):
{json.dumps(desk.get('sector_peers', []), ensure_ascii=False)}

Return ONLY valid JSON:
{{
  "executive_summary": "10-14 sentences: integrated view of situation, fundamentals, forecast, news",
  "situation_assessment": "where the company/stock stands now in 4-6 sentences",
  "fundamentals_verdict": "4-6 sentences",
  "base_scenario": "most likely path over the stated horizon if model holds",
  "risk_scenario": "what breaks the thesis (drawdown / news / macro)",
  "devil_advocate": "4-7 sentences: strongest case AGAINST the model-implied direction; force skepticism",
  "key_objections": ["3-5 concrete objections"],
  "sentiment": "bullish|bearish|neutral|mixed",
  "confidence": "low|medium|high",
  "model_vs_news": "agreement/disagreement paragraph",
  "model_vs_fundamentals": "short paragraph",
  "peer_context": "2-4 sentences on how this name sits vs sector peers list (qualitative only)",
  "watchpoints": ["5-8 concrete watchpoints"],
  "uses_model_forecast": true
}}

Rules:
- Mention predicted_change_pct from DESK QUANT; do not invent a different forecast %.
- Confidence must respect hit_rate and data_gaps (missing fundamentals → not high).
- devil_advocate is mandatory even when sentiment is bullish — challenge the thesis.
- English. No explicit buy/sell. Be specific, not generic filler.
"""
    raw = ai_brief._gemini_generate(prompt, temperature=0.22)
    data = ai_brief._extract_json(raw)
    if not data.get("executive_summary"):
        data["executive_summary"] = str(data.get("raw") or raw)[:2500]

    conf = str(data.get("confidence") or "medium").lower()
    if conf not in ("low", "medium", "high"):
        conf = "medium"
    quant = desk.get("quant") or {}
    try:
        hr = quant.get("hit_rate")
        n = quant.get("n_significant")
        if hr is not None and float(hr) < 45:
            conf = "low"
        elif hr is not None and float(hr) < 55 and conf == "high":
            conf = "medium"
        if n is not None and int(n) < 4 and conf == "high":
            conf = "medium"
    except Exception:
        pass
    gaps = fund_view.get("data_gaps") or []
    if isinstance(gaps, list) and len(gaps) >= 3 and conf == "high":
        conf = "medium"
    data["confidence"] = conf

    sent = str(data.get("sentiment") or world.get("sentiment") or "neutral").lower()
    if sent not in ("bullish", "bearish", "neutral", "mixed"):
        sent = "neutral"
    data["sentiment"] = sent
    data["uses_model_forecast"] = True
    if not data.get("devil_advocate"):
        data["devil_advocate"] = (
            "Counter-thesis not fully generated; treat confidence conservatively "
            "and verify headlines and fundamentals independently."
        )
    if not isinstance(data.get("key_objections"), list):
        data["key_objections"] = []
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
    hz = "3M" if str(horizon).upper().startswith("3") else "1M"

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

    fund_view = _agent_fundamentals(t, desk)
    quant_view = _agent_quant(t, desk, fund_view, feedback_blob)
    world = _agent_world(t, headlines, fund_view, quant_view, desk)
    final = _agent_editor(t, desk, fund_view, quant_view, world, feedback_blob)

    out: Dict[str, Any] = {
        "ticker": t,
        "horizon": hz,
        "quant": q,
        "fundamentals_pack": fund_pack,
        "perspective_3y": pers_pack,
        "sector_peers": peers,
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
            {"title": h.get("title"), "link": h.get("link"), "source": h.get("source")}
            for h in headlines[:12]
        ],
        "engine": _BUILD,
        "model": ai_brief.GEMINI_MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
        "disclaimer": _DISCLAIMER,
        "feedback_injected": True,
    }
    _cache_set(t, hz, out)
    return out


def build_board_row(
    ticker: str,
    quant: Dict[str, Any],
    *,
    horizon: str = "1M",
    use_cache: bool = True,
) -> Dict[str, Any]:
    """
    Fast path for the post-deploy Top 12 board:
    one Gemini call only (not the 4-agent desk). Full analysis stays on /ai/full.
    """
    t = (ticker or "").upper().strip()
    if not t:
        raise ValueError("Invalid ticker")
    hz = "3M" if str(horizon).upper().startswith("3") else "1M"

    if use_cache:
        hit = _cache_get(t, hz)
        if hit:
            return hit

    if not configured():
        raise RuntimeError("GEMINI_API_KEY not set")

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
        "fundamental_rating": quant.get("fundamental_rating"),
        "rsi": quant.get("rsi"),
        "sector": quant.get("sector"),
    }

    prompt = f"""You are a desk assistant. AssetCore model numbers below are FIXED — do not invent other prices or % forecasts.

Model pack:
{json.dumps(q, ensure_ascii=False, default=str)}

Return ONLY valid JSON:
{{
  "executive_summary": "3-5 sentences: what the model says and caveats",
  "sentiment": "bullish|neutral|bearish",
  "confidence": "low|medium|high",
  "watchpoints": ["2-4 short bullets"]
}}
Rules: if hit_rate < 50 use low/medium confidence; never change predicted_change_pct.
"""
    text = ai_brief._gemini_generate(prompt, temperature=0.25)
    parsed = ai_brief._extract_json(text)
    if not isinstance(parsed, dict):
        parsed = {}

    sent = str(parsed.get("sentiment") or "neutral").lower()
    if sent not in ("bullish", "neutral", "bearish"):
        sent = "neutral"
    conf = str(parsed.get("confidence") or "medium").lower()
    if conf not in ("low", "medium", "high"):
        conf = "medium"
    watches = parsed.get("watchpoints") or []
    if not isinstance(watches, list):
        watches = []

    out: Dict[str, Any] = {
        "ticker": t,
        "horizon": hz,
        "quant": q,
        "executive_summary": parsed.get("executive_summary")
        or f"{t}: model {q.get('predicted_change_pct')}% ({hz}), hit {q.get('hit_rate')}.",
        "sentiment": sent,
        "confidence": conf,
        "watchpoints": [str(x)[:160] for x in watches[:4]],
        "engine": "ai-board-fast-v1",
        "model": ai_brief.GEMINI_MODEL,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
        "disclaimer": _DISCLAIMER,
        "board_fast": True,
    }
    _cache_set(t, hz, out)
    return out
