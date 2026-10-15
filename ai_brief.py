"""
AI News Brief – multi-agent pipeline (Gemini API) for AssetCore.

Flow:
  1) Fetch recent headlines (RSS, no paid news API required)
  2) Agent News   – themes + factual summary
  3) Agent Risk   – risks / counterpoints
  4) Agent Editor – single structured brief for the UI

Env:
  GEMINI_API_KEY              – required
  GEMINI_MODEL                – default gemini-3.8-flash
  AI_BRIEF_CACHE_MINUTES      – default 180
  AI_BRIEF_MAX_HEADLINES      – default 10
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.environ.get("GEMINI_MODEL") or "gemini-3.8-flash").strip()
CACHE_MINUTES = float(os.environ.get("AI_BRIEF_CACHE_MINUTES") or "180")
MAX_HEADLINES = int(os.environ.get("AI_BRIEF_MAX_HEADLINES") or "10")

_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_LOCK = threading.Lock()
_BUILD = "ai-brief-v1"

_DISCLAIMER = (
    "AI-assisted news context only. Not investment advice. "
    "Headlines may be incomplete or delayed; always verify primary sources."
)


def configured() -> bool:
    return bool(GEMINI_API_KEY)


def status() -> Dict[str, Any]:
    return {
        "configured": configured(),
        "model": GEMINI_MODEL,
        "cache_minutes": CACHE_MINUTES,
        "build": _BUILD,
        "cache_entries": len(_CACHE),
    }


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _cache_key(ticker: str) -> str:
    return ticker.upper().strip()


def _cache_get(ticker: str) -> Optional[Dict[str, Any]]:
    key = _cache_key(ticker)
    with _CACHE_LOCK:
        row = _CACHE.get(key)
        if not row:
            return None
        if time.time() - row["ts"] > CACHE_MINUTES * 60:
            _CACHE.pop(key, None)
            return None
        out = dict(row["data"])
        out["cached"] = True
        return out


def _cache_set(ticker: str, data: Dict[str, Any]) -> None:
    key = _cache_key(ticker)
    with _CACHE_LOCK:
        _CACHE[key] = {"ts": time.time(), "data": dict(data)}
        if len(_CACHE) > 200:
            oldest = sorted(_CACHE.items(), key=lambda kv: kv[1]["ts"])[:50]
            for k, _ in oldest:
                _CACHE.pop(k, None)


# ---------------------------------------------------------------------------
# News fetch (free RSS)
# ---------------------------------------------------------------------------

def _parse_rss_items(xml_text: str, limit: int = 10) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return items
    # RSS 2.0
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        source = (item.findtext("source") or "").strip()
        if title:
            items.append(
                {
                    "title": title[:300],
                    "link": link[:500],
                    "published": pub[:80],
                    "source": source[:80],
                }
            )
        if len(items) >= limit:
            break
    if items:
        return items
    # Atom
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for entry in root.findall(".//a:entry", ns):
        title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
        link_el = entry.find("a:link", ns)
        link = ""
        if link_el is not None:
            link = (link_el.get("href") or "").strip()
        pub = (entry.findtext("a:updated", default="", namespaces=ns) or "").strip()
        if title:
            items.append(
                {
                    "title": title[:300],
                    "link": link[:500],
                    "published": pub[:80],
                    "source": "",
                }
            )
        if len(items) >= limit:
            break
    return items


def fetch_headlines(ticker: str, limit: int = MAX_HEADLINES) -> List[Dict[str, str]]:
    """Best-effort headlines from public RSS (no API key)."""
    t = ticker.upper().strip()
    queries = [
        f"https://news.google.com/rss/search?q={quote_plus(t + ' stock')}&hl=en-US&gl=US&ceid=US:en",
        f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote_plus(t)}&region=US&lang=en-US",
    ]
    headers = {
        "User-Agent": "AssetCoreAlpha/1.0 (research; +https://assetcore.example)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    collected: List[Dict[str, str]] = []
    seen = set()
    for url in queries:
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code != 200 or not r.text:
                continue
            for it in _parse_rss_items(r.text, limit=limit):
                key = it["title"].lower()
                if key in seen:
                    continue
                seen.add(key)
                collected.append(it)
                if len(collected) >= limit:
                    return collected
        except Exception as e:
            print(f"[ai_brief] rss error {url[:60]}: {e}")
            continue
    return collected


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

def _model_candidates() -> List[str]:
    """Primary model + fallbacks when Google returns 503 / overload."""
    primary = GEMINI_MODEL
    extras = [
        x.strip()
        for x in (os.environ.get("GEMINI_FALLBACK_MODELS") or "").split(",")
        if x.strip()
    ]
    # Sensowne zapasowe nazwy (API i tak odrzuci nieistniejące).
    defaults = [
        "gemini-3.8-flash",
        "gemini-2.5-flash",
        "gemini-2.0-flash-lite",
        "gemini-flash-latest",
        "gemini-1.5-flash",
    ]
    out: List[str] = []
    for m in [primary] + extras + defaults:
        if m and m not in out:
            out.append(m)
    return out


def _gemini_generate(prompt: str, temperature: float = 0.3) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not configured")

    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": 1024,
        },
    }

    last_err = "unknown"
    models = _model_candidates()
    # 503 = przeciążenie — retry z backoff + inny model
    for model in models:
        for attempt in range(3):
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={GEMINI_API_KEY}"
            )
            try:
                r = requests.post(url, json=body, timeout=60)
            except requests.RequestException as e:
                last_err = f"network: {e}"
                time.sleep(1.5 * (attempt + 1))
                continue

            if r.status_code == 200:
                data = r.json()
                try:
                    parts = data["candidates"][0]["content"]["parts"]
                    text = "".join(p.get("text", "") for p in parts)
                    return text.strip()
                except Exception as e:
                    last_err = f"parse ({model}): {e}"
                    break

            # 404 = zły model → następny model
            if r.status_code == 404:
                last_err = f"HTTP 404 model={model}"
                print(f"[ai_brief] model unavailable: {model}")
                break

            # 429 / 503 = limit lub przeciążenie → poczekaj i spróbuj
            if r.status_code in (429, 503):
                last_err = f"HTTP {r.status_code} model={model}: {r.text[:200]}"
                wait = 2.0 * (attempt + 1)
                print(f"[ai_brief] {r.status_code} on {model}, retry in {wait}s")
                time.sleep(wait)
                continue

            last_err = f"HTTP {r.status_code} model={model}: {r.text[:300]}"
            break

    raise RuntimeError(
        f"Gemini unavailable after retries/fallbacks. Last error: {last_err}. "
        "Try again in a minute or set GEMINI_MODEL / GEMINI_FALLBACK_MODELS."
    )


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {"raw": text}


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

def _agent_news(ticker: str, headlines: List[Dict[str, str]]) -> Dict[str, Any]:
    lines = []
    for i, h in enumerate(headlines, 1):
        lines.append(f"{i}. {h.get('title', '')}")
    blob = "\n".join(lines) if lines else "(no headlines retrieved)"
    prompt = f"""You are a financial news analyst. Ticker: {ticker}.

Recent headlines:
{blob}

Return ONLY valid JSON (no markdown):
{{
  "themes": ["theme1", "theme2"],
  "summary": "4-6 sentence neutral summary of what the news suggests about {ticker}",
  "sentiment_hint": "bullish|bearish|neutral|mixed",
  "facts_only": true
}}

Rules:
- Do not invent numbers, earnings, or events not implied by headlines.
- If headlines are thin, say so in summary and use neutral sentiment_hint.
- English only.
"""
    raw = _gemini_generate(prompt, temperature=0.25)
    data = _extract_json(raw)
    if "summary" not in data:
        data["summary"] = str(data.get("raw") or raw)[:1200]
    if "themes" not in data or not isinstance(data["themes"], list):
        data["themes"] = []
    if "sentiment_hint" not in data:
        data["sentiment_hint"] = "neutral"
    return data


def _agent_risk(ticker: str, news: Dict[str, Any], headlines: List[Dict[str, str]]) -> Dict[str, Any]:
    titles = "; ".join(h.get("title", "") for h in headlines[:8])
    prompt = f"""You are a risk analyst for equity {ticker}.

News summary:
{news.get('summary', '')}

Themes: {news.get('themes', [])}
Headline sample: {titles}

Return ONLY valid JSON:
{{
  "risks": ["risk1", "risk2", "risk3"],
  "counterpoints": ["why the bullish reading might be wrong", "..."],
  "uncertainty": "low|medium|high"
}}

Rules:
- Focus on downside and uncertainty; do not give buy/sell recommendations.
- English only. No invented precise financial figures.
"""
    raw = _gemini_generate(prompt, temperature=0.3)
    data = _extract_json(raw)
    if not isinstance(data.get("risks"), list):
        data["risks"] = []
    if not isinstance(data.get("counterpoints"), list):
        data["counterpoints"] = []
    if data.get("uncertainty") not in ("low", "medium", "high"):
        data["uncertainty"] = "medium"
    return data


def _agent_editor(
    ticker: str,
    news: Dict[str, Any],
    risk: Dict[str, Any],
    n_headlines: int,
) -> Dict[str, Any]:
    prompt = f"""You are the final editor for an equity research brief on {ticker}.

News agent output:
{json.dumps(news, ensure_ascii=False)}

Risk agent output:
{json.dumps(risk, ensure_ascii=False)}

Headlines available: {n_headlines}

Return ONLY valid JSON:
{{
  "sentiment": "bullish|bearish|neutral|mixed",
  "summary": "cohesive 5-8 sentence brief for a dashboard (English)",
  "key_themes": ["..."],
  "risks": ["..."],
  "counterpoints": ["..."],
  "confidence": "low|medium|high"
}}

Rules:
- confidence must be low if few headlines or high uncertainty.
- No buy/sell language. No price targets.
- Neutral professional tone.
"""
    raw = _gemini_generate(prompt, temperature=0.25)
    data = _extract_json(raw)
    # normalize
    sent = str(data.get("sentiment") or news.get("sentiment_hint") or "neutral").lower()
    if sent not in ("bullish", "bearish", "neutral", "mixed"):
        sent = "neutral"
    data["sentiment"] = sent
    if not data.get("summary"):
        data["summary"] = news.get("summary") or "Insufficient news to form a brief."
    if not isinstance(data.get("key_themes"), list) or not data.get("key_themes"):
        data["key_themes"] = list(news.get("themes") or [])
    if not isinstance(data.get("risks"), list) or not data.get("risks"):
        data["risks"] = list(risk.get("risks") or [])
    if not isinstance(data.get("counterpoints"), list) or not data.get("counterpoints"):
        data["counterpoints"] = list(risk.get("counterpoints") or [])
    conf = str(data.get("confidence") or risk.get("uncertainty") or "medium").lower()
    if conf not in ("low", "medium", "high"):
        conf = "medium"
    if n_headlines < 3:
        conf = "low"
    data["confidence"] = conf
    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_brief(ticker: str, use_cache: bool = True) -> Dict[str, Any]:
    """
    Full multi-agent brief for ticker.
    Raises RuntimeError on config / upstream failures.
    """
    t = (ticker or "").upper().strip()
    if not t or len(t) > 12:
        raise ValueError("Invalid ticker")

    if use_cache:
        hit = _cache_get(t)
        if hit:
            return hit

    if not configured():
        raise RuntimeError("GEMINI_API_KEY not set on server")

    headlines = fetch_headlines(t, limit=MAX_HEADLINES)
    news = _agent_news(t, headlines)
    risk = _agent_risk(t, news, headlines)
    final = _agent_editor(t, news, risk, n_headlines=len(headlines))

    out: Dict[str, Any] = {
        "ticker": t,
        "sentiment": final.get("sentiment", "neutral"),
        "summary": final.get("summary", ""),
        "key_themes": final.get("key_themes") or [],
        "risks": final.get("risks") or [],
        "counterpoints": final.get("counterpoints") or [],
        "confidence": final.get("confidence", "medium"),
        "headlines": [
            {"title": h.get("title"), "link": h.get("link"), "published": h.get("published")}
            for h in headlines[:MAX_HEADLINES]
        ],
        "n_headlines": len(headlines),
        "model": GEMINI_MODEL,
        "engine": _BUILD,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cached": False,
        "disclaimer": _DISCLAIMER,
    }
    _cache_set(t, out)
    return out
