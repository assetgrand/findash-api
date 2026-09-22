"""
Hybrid Analyzer + skaner sygnałów – wersja headless (bez Tkinter).
Używane przez api_server.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import core_analysis as core


def calculate_hybrid_indicators(
    data: pd.DataFrame,
    ticker: str,
    mode: str = "Zrównoważony",
) -> Tuple[pd.DataFrame, float, str]:
    """Pełna logika Hybrid z desktopu – bez UI."""
    data = data.copy()
    if data.empty or "Close" not in data.columns:
        raise ValueError("Brak danych OHLC")

    if "Volume" not in data.columns:
        data["Volume"] = 0.0

    data["EMA9"] = data["Close"].ewm(span=9, adjust=False).mean()
    data["EMA21"] = data["Close"].ewm(span=21, adjust=False).mean()
    data["EMA50"] = data["Close"].ewm(span=50, adjust=False).mean()
    data["EMA200"] = data["Close"].ewm(span=200, adjust=False).mean()

    delta = data["Close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(14, min_periods=1).mean()
    avg_loss = loss.rolling(14, min_periods=1).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    data["RSI"] = 100 - (100 / (1 + rs))

    ema12 = data["Close"].ewm(span=12, adjust=False).mean()
    ema26 = data["Close"].ewm(span=26, adjust=False).mean()
    data["MACD"] = ema12 - ema26
    data["MACD_Signal"] = data["MACD"].ewm(span=9, adjust=False).mean()
    data["MACD_Hist"] = data["MACD"] - data["MACD_Signal"]

    low_14 = data["Low"].rolling(14).min()
    high_14 = data["High"].rolling(14).max()
    denom = (high_14 - low_14).replace(0, np.nan)
    data["%K"] = 100 * ((data["Close"] - low_14) / denom)
    data["%D"] = data["%K"].rolling(3).mean()

    tp = (data["High"] + data["Low"] + data["Close"]) / 3
    mf = tp * data["Volume"]
    pos_mf = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    neg_mf = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    data["MFI"] = 100 - (100 / (1 + (pos_mf / neg_mf.replace(0, np.nan))))

    tr = pd.concat(
        [
            data["High"] - data["Low"],
            (data["High"] - data["Close"].shift()).abs(),
            (data["Low"] - data["Close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    data["ATR"] = tr.rolling(14).mean()

    high_diff = data["High"].diff()
    low_diff = -data["Low"].diff()
    plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
    minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)
    plus_dm = pd.Series(plus_dm, index=data.index)
    minus_dm = pd.Series(minus_dm, index=data.index)
    atr14 = tr.rolling(14).mean()
    plus_di = 100 * (plus_dm.rolling(14).mean() / atr14.replace(0, np.nan))
    minus_di = 100 * (minus_dm.rolling(14).mean() / atr14.replace(0, np.nan))
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    data["ADX"] = dx.rolling(14).mean()
    data["ADXR"] = (data["ADX"] + data["ADX"].shift(14)) / 2

    data["Vol_Avg_20"] = data["Volume"].rolling(20).mean()

    def _aroon_up(series, period=25):
        return series.rolling(period).apply(
            lambda x: (period - 1 - int(np.argmax(x))) / (period - 1) * 100 if len(x) else np.nan,
            raw=True,
        )

    def _aroon_down(series, period=25):
        return series.rolling(period).apply(
            lambda x: (period - 1 - int(np.argmin(x))) / (period - 1) * 100 if len(x) else np.nan,
            raw=True,
        )

    data["Aroon_Up"] = _aroon_up(data["High"], 25)
    data["Aroon_Down"] = _aroon_down(data["Low"], 25)

    high9 = data["High"].rolling(9).max()
    low9 = data["Low"].rolling(9).min()
    data["Tenkan"] = (high9 + low9) / 2
    high26 = data["High"].rolling(26).max()
    low26 = data["Low"].rolling(26).min()
    data["Kijun"] = (high26 + low26) / 2

    sma20 = data["Close"].rolling(20).mean()
    std20 = data["Close"].rolling(20).std()
    data["BB_Upper"] = sma20 + 2 * std20
    data["BB_Lower"] = sma20 - 2 * std20
    bb_range = (data["BB_Upper"] - data["BB_Lower"]).replace(0, np.nan)
    data["%B"] = (data["Close"] - data["BB_Lower"]) / bb_range

    tp_cci = (data["High"] + data["Low"] + data["Close"]) / 3
    sma_tp = tp_cci.rolling(20).mean()
    mad = tp_cci.rolling(20).apply(lambda x: np.abs(x - x.mean()).mean(), raw=False)
    data["CCI"] = (tp_cci - sma_tp) / (0.015 * mad.replace(0, np.nan))

    hl = (data["High"] - data["Low"]).replace(0, np.nan)
    mfm = ((data["Close"] - data["Low"]) - (data["High"] - data["Close"])) / hl
    mfv = mfm * data["Volume"]
    data["CMF"] = mfv.rolling(20).sum() / data["Volume"].rolling(20).sum().replace(0, np.nan)

    data["OBV"] = (np.sign(data["Close"].diff()) * data["Volume"]).fillna(0).cumsum()
    data["OBV_Slope"] = data["OBV"].diff(5) / 5

    data["Bull_Div"] = 0.0
    data["Bear_Div"] = 0.0
    last_40 = data.iloc[-40:]
    if len(last_40) >= 25:
        try:
            recent_low_idx = last_40["Close"].idxmin()
            before_recent = last_40.loc[:recent_low_idx].iloc[:-1]
            if not before_recent.empty:
                prev_low_idx = before_recent["Close"].idxmin()
                if pd.notna(prev_low_idx):
                    if (data.loc[recent_low_idx, "Close"] < data.loc[prev_low_idx, "Close"]) and (
                        data.loc[recent_low_idx, "RSI"] > data.loc[prev_low_idx, "RSI"]
                    ):
                        data.loc[recent_low_idx, "Bull_Div"] = 1
                    if (data.loc[recent_low_idx, "Close"] > data.loc[prev_low_idx, "Close"]) and (
                        data.loc[recent_low_idx, "RSI"] < data.loc[prev_low_idx, "RSI"]
                    ):
                        data.loc[recent_low_idx, "Bear_Div"] = 1
        except Exception:
            pass
    data["Bull_Div"] = data["Bull_Div"].rolling(3, min_periods=1).max().fillna(0)
    data["Bear_Div"] = data["Bear_Div"].rolling(3, min_periods=1).max().fillna(0)

    data["Score"] = 0.0
    data.loc[data["Close"] > data["EMA200"], "Score"] += 2.0
    data.loc[data["EMA9"] > data["EMA21"], "Score"] += 1.0
    data.loc[(data["EMA9"] > data["EMA21"]) & (data["EMA21"] > data["EMA50"]), "Score"] += 0.5
    data.loc[data["ADX"] > 20, "Score"] += 1.0
    data.loc[data["ADXR"] > 20, "Score"] += 0.5
    data.loc[(data["Aroon_Up"] > 70) & (data["Aroon_Down"] < 30), "Score"] += 0.5
    data.loc[data["OBV_Slope"] > 0, "Score"] += 0.5
    data.loc[data["Bull_Div"] == 1, "Score"] += 2.0
    data.loc[data["Bear_Div"] == 1, "Score"] -= 2.0
    data.loc[data["MACD"] > data["MACD_Signal"], "Score"] += 1.0
    data.loc[data["MACD_Hist"] > 0, "Score"] += 0.5
    data.loc[data["%K"] > data["%D"], "Score"] += 0.5
    data.loc[(data["RSI"] >= 35) & (data["RSI"] <= 65), "Score"] += 1.0
    data.loc[data["Tenkan"] > data["Kijun"], "Score"] += 0.5
    data.loc[(data["%B"] > 0.2) & (data["%B"] < 0.8), "Score"] += 0.5
    data.loc[(data["CCI"] > -100) & (data["CCI"] < 100), "Score"] += 0.5
    data.loc[data["MFI"] > 50, "Score"] += 0.5
    data.loc[data["Volume"] > 1.2 * data["Vol_Avg_20"], "Score"] += 1.0

    vwap = (data["High"] + data["Low"] + data["Close"]) / 3
    data["VWAP"] = (vwap * data["Volume"]).cumsum() / data["Volume"].cumsum().replace(0, np.nan)
    data.loc[data["Close"] > data["VWAP"], "Score"] += 0.5
    data.loc[data["CMF"] > 0.1, "Score"] += 0.5

    data.loc[data["Close"] < data["EMA200"], "Score"] -= 1.5
    data.loc[data["RSI"] > 75, "Score"] -= 1.0
    data.loc[data["%K"] > 80, "Score"] -= 0.5
    data["Score"] = data["Score"].clip(lower=0, upper=16)

    mode = mode if mode in ("Agresywny", "Zrównoważony", "Bezpieczny") else "Zrównoważony"
    base_threshold = {"Agresywny": 4.0, "Zrównoważony": 5.5, "Bezpieczny": 7.0}[mode]

    sector = core.sector_mapping.get(ticker, "Default")
    sector_mult_map = {
        "Technology": 0.85,
        "Communication Services": 0.85,
        "Consumer Cyclical": 1.0,
        "Financial Services": 1.0,
        "Healthcare": 1.0,
        "Energy": 1.15,
        "Automotive": 1.15,
        "Consumer Defensive": 1.2,
        "Index": 1.1,
        "Default": 1.0,
    }
    base_threshold *= sector_mult_map.get(sector, 1.0)

    atr_pct = (
        data["ATR"]
        .rolling(100)
        .apply(lambda x: pd.Series(x).rank(pct=True).iloc[-1] if len(x) >= 20 else 0.5, raw=False)
        .fillna(0.5)
    )
    vol_mult = pd.Series(1.0, index=data.index)
    vol_mult[atr_pct < 0.2] = 0.9
    vol_mult[atr_pct > 0.8] = 1.15
    threshold_series = base_threshold * vol_mult

    raw_buy = (data["Score"] >= threshold_series) & (data["Score"].shift(1) < threshold_series)
    raw_buy &= data["Close"] > data["EMA200"]
    data["Buy_Signal"] = np.where(raw_buy.fillna(False), data["Close"], np.nan)

    sell_condition = (
        ((data["Close"] < data["EMA200"]) & (data["Close"].shift(1) >= data["EMA200"].shift(1)))
        | ((data["Score"] < 2.0) & (data["Score"].shift(1) >= 2.0))
    )
    data["Sell_Signal"] = np.where(sell_condition.fillna(False), data["Close"], np.nan)

    thr = float(threshold_series.iloc[-1]) if len(threshold_series) else float(base_threshold)
    return data, thr, sector


def _sf(x: Any) -> Optional[float]:
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        v = float(x)
        if np.isnan(v):
            return None
        return v
    except Exception:
        return None


def analyze_hybrid(ticker: str, mode: str = "Zrównoważony") -> Dict[str, Any]:
    ticker = ticker.upper().strip()
    df = core.get_historical_prices(ticker, days=500)
    if df is None or getattr(df, "empty", True):
        raise ValueError(f"Brak danych dla {ticker}")

    data, threshold, sector = calculate_hybrid_indicators(df, ticker, mode)
    last = data.iloc[-1]
    price = _sf(last["Close"]) or 0.0
    atr = _sf(last.get("ATR")) or 0.0
    vol_avg = _sf(last.get("Vol_Avg_20")) or 0.0
    vol = _sf(last.get("Volume")) or 0.0
    vol_ratio = (vol / vol_avg) if vol_avg else 1.0
    stop_loss = (price - 2 * atr) if atr > 0 else price * 0.95

    signal = "BRAK"
    signal_price = None
    if pd.notna(last.get("Buy_Signal")):
        signal = "KUPNO"
        signal_price = _sf(last["Buy_Signal"])
    elif pd.notna(last.get("Sell_Signal")):
        signal = "SPRZEDAŻ"
        signal_price = _sf(last["Sell_Signal"])

    # ostatnie sygnały w oknie 25 sesji
    window = data.tail(25)
    last_buy = window["Buy_Signal"].dropna()
    last_sell = window["Sell_Signal"].dropna()
    recent = None
    if len(last_buy) or len(last_sell):
        if len(last_buy) and len(last_sell):
            if last_buy.index[-1] >= last_sell.index[-1]:
                recent = {"type": "KUPNO", "price": _sf(last_buy.iloc[-1]), "date": str(last_buy.index[-1].date())}
            else:
                recent = {"type": "SPRZEDAŻ", "price": _sf(last_sell.iloc[-1]), "date": str(last_sell.index[-1].date())}
        elif len(last_buy):
            recent = {"type": "KUPNO", "price": _sf(last_buy.iloc[-1]), "date": str(last_buy.index[-1].date())}
        else:
            recent = {"type": "SPRZEDAŻ", "price": _sf(last_sell.iloc[-1]), "date": str(last_sell.index[-1].date())}

    return {
        "ticker": ticker,
        "mode": mode,
        "sector": sector,
        "threshold": round(threshold, 2),
        "score": round(_sf(last.get("Score")) or 0.0, 2),
        "score_max": 16,
        "current_price": round(price, 4),
        "ema200": round(_sf(last.get("EMA200")) or 0.0, 4),
        "rsi": round(_sf(last.get("RSI")) or 0.0, 2),
        "macd_hist": round(_sf(last.get("MACD_Hist")) or 0.0, 5),
        "adx": round(_sf(last.get("ADX")) or 0.0, 2),
        "adxr": round(_sf(last.get("ADXR")) or 0.0, 2),
        "cmf": round(_sf(last.get("CMF")) or 0.0, 3),
        "aroon_up": round(_sf(last.get("Aroon_Up")) or 0.0, 1),
        "aroon_down": round(_sf(last.get("Aroon_Down")) or 0.0, 1),
        "obv_slope": round(_sf(last.get("OBV_Slope")) or 0.0, 1),
        "pct_b": round(_sf(last.get("%B")) or 0.0, 3),
        "cci": round(_sf(last.get("CCI")) or 0.0, 1),
        "bull_div": bool(_sf(last.get("Bull_Div")) or 0),
        "bear_div": bool(_sf(last.get("Bear_Div")) or 0),
        "volume_ratio": round(vol_ratio, 2),
        "stop_loss": round(stop_loss, 4),
        "signal": signal,
        "signal_price": signal_price,
        "recent_signal": recent,
        "above_ema200": bool(price > (_sf(last.get("EMA200")) or 0)),
    }


def scan_signals(
    tickers: Optional[List[str]] = None,
    mode: str = "Zrównoważony",
    lookback: int = 25,
) -> List[Dict[str, Any]]:
    """Skan listy tickerów – aktywne KUPNO/SPRZEDAŻ (logika jak w desktopie)."""
    tickers = tickers or list(getattr(core, "tickers", []))
    results: List[Dict[str, Any]] = []

    for ticker in tickers:
        ticker = str(ticker).upper().strip()
        if not ticker:
            continue
        try:
            df = core.get_historical_prices(ticker, days=500)
            if df is None or getattr(df, "empty", True):
                continue
            data, thr, sector = calculate_hybrid_indicators(df, ticker, mode)
            window = data.tail(lookback)
            buy = window["Buy_Signal"].dropna()
            sell = window["Sell_Signal"].dropna()

            signal = None
            price = None
            if len(buy) > 0 and len(sell) > 0:
                if buy.index[-1] >= sell.index[-1]:
                    signal, price = "KUPNO", float(buy.iloc[-1])
                else:
                    signal, price = "SPRZEDAŻ", float(sell.iloc[-1])
            elif len(buy) > 0:
                signal, price = "KUPNO", float(buy.iloc[-1])
            elif len(sell) > 0:
                signal, price = "SPRZEDAŻ", float(sell.iloc[-1])
            else:
                last = data.iloc[-1]
                score = float(last.get("Score", 0) or 0)
                close = float(last["Close"])
                ema200 = float(last["EMA200"]) if pd.notna(last.get("EMA200")) else close
                if score >= float(thr) and close > ema200:
                    signal, price = "KUPNO", close
                elif score < 2.5 or close < ema200:
                    long_buy = data.tail(60)["Buy_Signal"].dropna()
                    if len(long_buy) > 0:
                        signal, price = "SPRZEDAŻ", close

            if signal is None:
                continue

            try:
                current = core.get_live_price(ticker)
            except Exception:
                current = None
            if current is None:
                current = float(data["Close"].iloc[-1])

            rating = None
            try:
                fa = core.get_comprehensive_fundamental_analysis(ticker)
                if fa:
                    rating = fa.get("fundamental_rating")
            except Exception:
                pass

            results.append(
                {
                    "ticker": ticker,
                    "signal": signal,
                    "signal_price": round(price, 4) if price is not None else None,
                    "current_price": round(float(current), 4),
                    "sector": sector,
                    "fundamental_rating": rating,
                    "mode": mode,
                }
            )
        except Exception as e:
            print(f"scan_signals skip {ticker}: {e}")
            continue

    return results
