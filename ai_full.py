"""
AI Full Analysis – AssetCore

Łączy:
  • liczby z Waszego silnika (prognoza, Hit%, fundamenty, 3Y)
  • newsy (RSS)
  • multi-agent Gemini (analyst → news → editor)
  • feedback Hit% / jakości (tylko do AI – nie zmienia matematyki prognoz)

Env: te same co ai_brief (GEMINI_API_KEY, GEMINI_MODEL, …)
     AI_FULL_CACHE_MINUTES (default 120)
     AI_FEEDBACK_PATH (opcjonalnie ścieżka pliku JSON)
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

_BUILD = "ai-full-v1"
_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_MIN = float(os.environ.get("AI_FULL_CACHE_MINUTES") or "120")

_FB_LOCK = threading.Lock()
_FB_PATH = Path(
    os.environ.get("AI_FEEDBACK_PATH")
    or os.path.join(os.path.dirname(__file__), "ai_feedback.json")
)
_MAX_FEEDBACK = 80

_DISCLAIMER = (
    "Full AI analysis combines AssetCore quantitative outputs with news context. "
    "Price forecasts come from the AssetCore model, not from the LLM. "
    "Not investment advice."
)


def configured() -> bool:
    return ai_brief.configured()


# ---------------------------------------------------------------------------
# Feedback store (Hit% / quality → only for AI prompts)
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
) -> Dict[str, Any]:
    """Zapis feedbacku dla AI (kalibracja pewności / tonu)."""
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "ticker": (ticker or "").upper().strip(),
        "horizon": horizon,
        "hit_rate": hit_rate,
        "narrative_ok": narrative_ok,
        "note": (note or "")[:500],
    }
    with _FB_LOCK:
        rows = _load_feedback()
        rows.append(row)
        rows = rows[-_MAX_FEEDBACK:]
        _save_feedback(rows)
    return {"ok": True, "stored": row, "n": len(rows)}


def _feedback_for_prompt(ticker: str, limit: int = 12) -> str:
    t = (ticker or "").upper().strip()
    rows = _load_feedback()
    if not rows:
        return "No prior AI feedback stored yet."
    # najpierw ten ticker, potem globalne
    related = [r for r in rows if r.get("ticker") == t][-6:]
    global_ = [r for r in rows if r.get("ticker") != t][-limit:]
    pick = (related + global_)[-limit:]
    lines = []
    for r in pick:
        ok = r.get("narrative_ok")
        ok_s = "yes" if ok is True else ("no" if ok is False else "n/a")
        lines.append(
            f"- {r.get('ticker')} {r.get('horizon')}: hit_rate={r.get('hit_rate')}, "
            f"narrative_ok={ok_s}, note={r.get('note') or '—'}"
        )
    return "Recent feedback (for confidence calibration only):\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _ck(ticker: str, horizon: str) -> str:
    return f"{ticker.upper().strip()}|{horizon.upper().strip()}"


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


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def _agent_quant(ticker: str, quant: Dict[str, Any], feedback_blob: str) -> Dict[str, Any]:
    prompt = f"""You are a quantitative research analyst for equity {ticker}.

AssetCore model outputs (AUTHORITATIVE for numbers — do not invent different prices):
{json.dumps(quant, ensure_ascii=False, default=str)}

{feedback_blob}

Return ONLY valid JSON:
{{
  "quant_summary": "4-6 sentences on what the numbers imply",
  "hit_interpretation": "how reliable the model looks given hit_rate, mae, n_significant",
  "confidence_from_model": "low|medium|high",
  "key_drivers": ["driver1", "driver2"],
  "warnings": ["warning1"]
}}

Rules:
- Treat predicted_change_pct / predicted_price as given; do not replace them.
- If hit_rate is low or n_significant is small, confidence_from_model must be low or medium.
- English only. No buy/sell recommendation.
"""
    raw = ai_brief._gemini_generate(prompt, temperature=0.25)
    data = ai_brief._extract_json(raw)
    if not data.get("quant_summary"):
        data["quant_summary"] = str(data.get("raw") or raw)[:1200]
    return data


def _agent_world(ticker: str, headlines: List[Dict[str, str]], quant_view: Dict[str, Any]) -> Dict[str, Any]:
    titles = "\n".join(f"- {h.get('title')}" for h in headlines[:12]) or "(no headlines)"
    prompt = f"""You are a macro/news analyst for {ticker}.

Quant desk view:
{json.dumps(quant_view, ensure_ascii=False)[:2000]}

Headlines:
{titles}

Return ONLY valid JSON:
{{
  "news_summary": "4-6 sentences",
  "sentiment": "bullish|bearish|neutral|mixed",
  "alignment_with_model": "supports|contradicts|mixed|unclear",
  "world_risks": ["..."],
  "themes": ["..."]
}}

Rules: Do not invent earnings numbers. English only. No buy/sell.
"""
    raw = ai_brief._gemini_generate(prompt, temperature=0.3)
    data = ai_brief._extract_json(raw)
    if not data.get("news_summary"):
        data["news_summary"] = str(data.get("raw") or raw)[:1200]
    return data


def _agent_editor(
    ticker: str,
    quant: Dict[str, Any],
    quant_view: Dict[str, Any],
    world: Dict[str, Any],
    feedback_blob: str,
) -> Dict[str, Any]:
    prompt = f"""You are the final editor for AssetCore Full Analysis on {ticker}.

QUANT numbers (do not change):
{json.dumps(quant, ensure_ascii=False, default=str)}

Quant agent:
{json.dumps(quant_view, ensure_ascii=False)}

News agent:
{json.dumps(world, ensure_ascii=False)}

{feedback_blob}

Return ONLY valid JSON:
{{
  "executive_summary": "6-10 sentence integrated brief",
  "base_scenario": "what is most likely if model + news both roughly hold",
  "risk_scenario": "what breaks the thesis",
  "sentiment": "bullish|bearish|neutral|mixed",
  "confidence": "low|medium|high",
  "model_vs_news": "short paragraph on agreement/disagreement",
  "watchpoints": ["..."],
  "uses_model_forecast": true
}}

Rules:
- Price path must stay consistent with predicted_change_pct from QUANT (mention it, do not invent another %).
- Confidence must respect hit_rate / feedback (low hit → lower confidence).
- English. No explicit buy/sell.
"""
    raw = ai_brief._gemini_generate(prompt, temperature=0.25)
    data = ai_brief._extract_json(raw)
    if not data.get("executive_summary"):
        data["executive_summary"] = str(data.get("raw") or raw)[:2000]
    conf = str(data.get("confidence") or "medium").lower()
    if conf not in ("low", "medium", "high"):
        conf = "medium"
    # twarda kalibracja z Hit%
    try:
        hr = quant.get("hit_rate")
        n = quant.get("n_significant") or quant.get("n_sig")
        if hr is not None and float(hr) < 45:
            conf = "low"
        elif hr is not None and float(hr) < 55 and conf == "high":
            conf = "medium"
        if n is not None and int(n) < 4 and conf == "high":
            conf = "medium"
    except Exception:
        pass
    data["confidence"] = conf
    sent = str(data.get("sentiment") or world.get("sentiment") or "neutral").lower()
    if sent not in ("bullish", "bearish", "neutral", "mixed"):
        sent = "neutral"
    data["sentiment"] = sent
    data["uses_model_forecast"] = True
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
    """
    quant = wynik Waszego /analyze (dict).
    fundamentals / perspective opcjonalne.
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

    # zbity pakiet liczb dla AI
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
    if fundamentals:
        q["fundamentals_excerpt"] = {
            k: fundamentals.get(k)
            for k in (
                "score",
                "rating",
                "sector",
                "macro_score",
                "fundamental_rating",
            )
            if k in fundamentals or fundamentals.get(k) is not None
        }
    if perspective:
        q["perspective_3y_excerpt"] = {
            k: perspective.get(k)
            for k in (
                "trend_3y",
                "risk_of_drop_pct",
                "upside_potential_pct",
                "crash_risk_score",
                "risk_tier",
                "position_in_range",
            )
            if perspective.get(k) is not None
        }

    feedback_blob = _feedback_for_prompt(t)
    headlines = ai_brief.fetch_headlines(t, limit=ai_brief.MAX_HEADLINES)

    quant_view = _agent_quant(t, q, feedback_blob)
    world = _agent_world(t, headlines, quant_view)
    final = _agent_editor(t, q, quant_view, world, feedback_blob)

    out: Dict[str, Any] = {
        "ticker": t,
        "horizon": hz,
        "quant": q,
        "executive_summary": final.get("executive_summary"),
        "base_scenario": final.get("base_scenario"),
        "risk_scenario": final.get("risk_scenario"),
        "sentiment": final.get("sentiment"),
        "confidence": final.get("confidence"),
        "model_vs_news": final.get("model_vs_news"),
        "watchpoints": final.get("watchpoints") or [],
        "quant_summary": quant_view.get("quant_summary"),
        "hit_interpretation": quant_view.get("hit_interpretation"),
        "news_summary": world.get("news_summary"),
        "alignment_with_model": world.get("alignment_with_model"),
        "headlines": [
            {"title": h.get("title"), "link": h.get("link")}
            for h in headlines[:10]
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
