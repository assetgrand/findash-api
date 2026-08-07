# ============================================================
# ADVANCED FINANCIAL DASHBOARD - POLYGON.IO EDITION
# ============================================================
# KOMPLETNY KOD - WSZYSTKIE FUNKCJE, OKNA, ANALIZY
# BEZ YAHOO FINANCE - TYLKO POLYGON.IO
# BEZ LIMITÓW DZIENNYCH - PLAN STARTER $29/MIES.
# ============================================================

import os
import json
import threading
import time
import warnings
import tempfile
import sys
import re
import hashlib
import logging
import sqlite3
import webbrowser
import smtplib
import pickle
import shutil
import zipfile
import random
import math
from datetime import datetime, timedelta
from collections import defaultdict, deque
from functools import lru_cache, wraps
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from abc import ABC, abstractmethod
from enum import Enum

# ============================================================
# BIBLIOTEKI ZEWNĘTRZNE
# ============================================================

import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter
from sklearn.linear_model import LinearRegression, Ridge, Lasso
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.svm import SVR
from sklearn.neural_network import MLPRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error, r2_score
from scipy import stats
from scipy.optimize import minimize

# --- Headless (API): brak GUI ---
class _DummyModule:
    def __getattr__(self, name):
        if name in ("StringVar", "IntVar", "BooleanVar"):
            return lambda *a, **k: type("V", (), {"get": lambda self: "", "set": lambda self, x: None})()
        return lambda *a, **k: None

class _DummyMsg:
    @staticmethod
    def showinfo(*a, **k): pass
    @staticmethod
    def showerror(*a, **k): pass
    @staticmethod
    def showwarning(*a, **k): pass
    @staticmethod
    def askyesno(*a, **k): return False

tk = _DummyModule()
ttk = _DummyModule()
messagebox = _DummyMsg()
filedialog = _DummyModule()
simpledialog = _DummyModule()
colorchooser = _DummyModule()
Progressbar = lambda *a, **k: None
tkfont = _DummyModule()
FigureCanvasTkAgg = None

warnings.filterwarnings("ignore")

# Bezpieczne czcionki (Arial – bez spacji w nazwie, działa wszędzie)
FONT_UI = ("Arial", 10)
FONT_UI_BOLD = ("Arial", 10, "bold")
FONT_UI_SM = ("Arial", 9)
FONT_UI_SM_BOLD = ("Arial", 9, "bold")
FONT_UI_TITLE = ("Arial", 14, "bold")
FONT_UI_LG = ("Arial", 12, "bold")
FONT_MONO = ("Consolas", 10)


# ============================================================
# ⭐⭐⭐ WPISZ SWÓJ KLUCZ API POLYGON.IO TUTAJ ⭐⭐⭐
# ============================================================
# Zarejestruj się na: https://polygon.io/
# Plan Starter: $29/mies. - NIELIMITOWANE ZAPYTANIA
# ============================================================

POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "").strip() or "WPISZ_KLUCZ_POLYGON"  # env lub tu

# ============================================================
# POLYGON.IO API - JEDYNE ŹRÓDŁO DANYCH
# ============================================================

POLYGON_BASE_URL = "https://api.polygon.io"

_CACHE_DIR = "polygon_cache"
os.makedirs(_CACHE_DIR, exist_ok=True)

def _cache_key(func_name, *args, **kwargs):
    key_str = func_name + "_" + "_".join(str(a) for a in args) + "_" + "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
    return hashlib.md5(key_str.encode()).hexdigest()

def _cache_get(key):
    path = os.path.join(_CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if datetime.now() - datetime.fromisoformat(data['_timestamp']) < timedelta(minutes=5):
                return data['data']
        except:
            pass
    return None

def _cache_set(key, data):
    path = os.path.join(_CACHE_DIR, f"{key}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'_timestamp': datetime.now().isoformat(), 'data': data}, f, indent=2)

def _api_call(url, max_retries=3):
    """Wykonuje zapytanie do Polygon.io API."""
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            if 'error' in data:
                print(f"❌ Błąd Polygon.io: {data['error']}")
                return None
            if 'status' in data and data['status'] == 'ERROR':
                print(f"❌ Błąd Polygon.io: {data.get('message', 'Nieznany błąd')}")
                return None
                
            return data
        except requests.exceptions.RequestException as e:
            print(f"❌ Błąd sieci (próba {attempt+1}): {e}")
            time.sleep(2)
        except Exception as e:
            print(f"❌ Błąd (próba {attempt+1}): {e}")
            time.sleep(2)
            
    return None

# ============================================================
# TEST API NA STARCIE
# ============================================================

def test_api_key():
    """Testuje klucz API Polygon.io."""
    print("=" * 60)
    print("🔑 TEST KLUCZA API POLYGON.IO")
    print("=" * 60)
    print(f"📌 Klucz: {POLYGON_API_KEY[:4]}...{POLYGON_API_KEY[-4:]}")
    print("-" * 60)
    
    if POLYGON_API_KEY == "TWOJ_KLUCZ_POLYGON" or len(POLYGON_API_KEY) < 10:
        print("❌❌❌ NIE WPISAŁEŚ KLUCZA API!")
        print("📌 Otwórz plik main.py i wpisz swój klucz w linii:")
        print('   POLYGON_API_KEY = "TWOJ_KLUCZ_POLYGON"')
        print("📌 Klucz możesz uzyskać na: https://polygon.io/dashboard/signup")
        input("Naciśnij ENTER, aby zakończyć...")
        sys.exit(1)
    
    url = f"{POLYGON_BASE_URL}/v2/aggs/ticker/AAPL/prev?adjusted=true&apiKey={POLYGON_API_KEY}"
    print("⏳ Wysyłam zapytanie do Polygon.io...")
    try:
        resp = requests.get(url, timeout=30)
        print(f"📡 Status HTTP: {resp.status_code}")
        
        if resp.status_code != 200:
            print(f"❌ Błąd HTTP: {resp.status_code}")
            print(f"   Odpowiedź: {resp.text[:200]}")
            return False
            
        data = resp.json()
        
        if 'error' in data:
            print(f"❌ Błąd: {data['error']}")
            return False
            
        if 'results' in data and data['results']:
            price = data['results'][0]['c']
            print(f"✅ KLUCZ DZIAŁA!")
            print(f"   📈 AAPL: ${price}")
            return True
        else:
            print(f"❌ Nieznana odpowiedź API: {data}")
            return False
            
    except Exception as e:
        print(f"❌ Błąd: {e}")
        return False

# Test klucza TYLKO przy bezpośrednim uruchomieniu core (nie przy imporcie z API)
def _run_startup_api_check():
    if not test_api_key():
        print("=" * 60)
        print("❌ KLUCZ API POLYGON NIE DZIAŁA – ustaw POLYGON_API_KEY")
        print("=" * 60)
        return False
    print("✅ KLUCZ ZATWIERDZONY")
    return True

if __name__ == "__main__":
    _run_startup_api_check()

# ============================================================
# FUNKCJE POLYGON.IO - POBIERANIE DANYCH
# ============================================================

def get_company_profile(ticker):
    """Pobiera profil spółki z Polygon.io – WSZYSTKIE pola."""
    if not ticker:
        return {}
    cache_key = _cache_key("profile", ticker)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    
    url = f"{POLYGON_BASE_URL}/v3/reference/tickers/{ticker}?apiKey={POLYGON_API_KEY}"
    data = _api_call(url)
    
    if data and 'results' in data:
        results = data['results']
        # Mapuj WSZYSTKIE dostępne pola
        profile = {
            # Podstawowe
            'Symbol': results.get('ticker'),
            'Name': results.get('name'),
            'Sector': results.get('sector'),
            'Industry': results.get('industry'),
            
            # Wycena
            'MarketCapitalization': results.get('market_cap'),
            'PERatio': results.get('pe_ratio'),
            'PriceToSalesRatioTTM': results.get('ps_ratio'),
            'PriceToBookRatio': results.get('pb_ratio'),
            'PEGRatio': results.get('peg_ratio'),
            
            # Rentowność
            'ReturnOnEquityTTM': results.get('roe'),
            'ReturnOnAssetsTTM': results.get('roa'),
            'ProfitMargin': results.get('profit_margin'),
            'OperatingMarginTTM': results.get('operating_margin'),
            'GrossProfitMarginTTM': results.get('gross_margin'),
            
            # Zadłużenie i płynność
            'DebtToEquityRatio': results.get('debt_to_equity'),
            'CurrentRatio': results.get('current_ratio'),
            'QuickRatio': results.get('quick_ratio'),
            
            # Wycena (EV)
            'EVToEBITDA': results.get('ev_to_ebitda'),
            'EVToRevenue': results.get('ev_to_revenue'),
            
            # Wzrost
            'QuarterlyRevenueGrowthYOY': results.get('revenue_growth'),
            'QuarterlyEarningsGrowthYOY': results.get('earnings_growth'),
            
            # Inne
            'EBITDA': results.get('ebitda'),
            'FreeCashFlow': results.get('free_cash_flow'),
            'TrailingEPS': results.get('eps'),
            'ForwardEPS': results.get('eps_forward'),
            'Beta': results.get('beta'),
            'DividendYield': results.get('dividend_yield'),
            '52WeekHigh': results.get('high_52_week'),
            '52WeekLow': results.get('low_52_week'),
            'TotalAssets': results.get('total_assets'),
            'TotalRevenue': results.get('total_revenue'),
            'EnterpriseValue': results.get('enterprise_value'),
            'OperatingCashflow': results.get('operating_cash_flow'),
            'NetIncomeTTM': results.get('net_income'),
        }
        _cache_set(cache_key, profile)
        return profile
    
    return {}

def get_company_fundamentals(ticker):
    """Zwraca wszystkie wskaźniki fundamentalne w jednym słowniku."""
    profile = get_company_profile(ticker)
    if not profile:
        return None

    fundamentals = {
        'P/E': profile.get('PERatio'),
        'PEG': profile.get('PEGRatio'),
        'P/S': profile.get('PriceToSalesRatioTTM'),
        'P/B': profile.get('PriceToBookRatio'),
        'EV/EBITDA': profile.get('EVToEBITDA'),
        'EV/Revenue': profile.get('EVToRevenue'),
        'ROE': profile.get('ReturnOnEquityTTM'),
        'ROA': profile.get('ReturnOnAssetsTTM'),
        'Gross Margin': profile.get('GrossProfitMarginTTM'),
        'Profit Margin': profile.get('ProfitMargin'),
        'Operating Margin': profile.get('OperatingMarginTTM'),
        'Revenue Growth': profile.get('QuarterlyRevenueGrowthYOY'),
        'Earnings Growth': profile.get('QuarterlyEarningsGrowthYOY'),
        'Debt/Equity': profile.get('DebtToEquityRatio'),
        'Current Ratio': profile.get('CurrentRatio'),
        'Quick Ratio': profile.get('QuickRatio'),
        'EBITDA': profile.get('EBITDA'),
        'Free Cash Flow': profile.get('FreeCashFlow'),
        'EPS (Trailing)': profile.get('TrailingEPS'),
        'EPS (Forward)': profile.get('ForwardEPS'),
        'Market Cap': profile.get('MarketCapitalization'),
        'Enterprise Value': profile.get('EnterpriseValue'),
        'Operating Cash Flow': profile.get('OperatingCashflow'),
        'Net Income': profile.get('NetIncomeTTM'),
        'Total Assets': profile.get('TotalAssets'),
        'Total Revenue': profile.get('TotalRevenue'),
        'Dividend Yield': profile.get('DividendYield'),
        'Beta': profile.get('Beta'),
        '52Week High': profile.get('52WeekHigh'),
        '52Week Low': profile.get('52WeekLow'),
    }

    # Konwersja procentów (Polygon zwraca ułamki, np. 0.15 = 15%)
    for key in ['ROE','ROA','Gross Margin','Profit Margin','Operating Margin',
                'Revenue Growth','Earnings Growth', 'Dividend Yield']:
        if fundamentals.get(key) is not None:
            fundamentals[key] = fundamentals[key] * 100

    return fundamentals


def get_live_price(ticker):
    """Pobiera aktualną cenę z Polygon.io (ostatnia sesja)."""
    if not ticker:
        return None
    cache_key = _cache_key("price", ticker)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    
    url = f"{POLYGON_BASE_URL}/v2/aggs/ticker/{ticker}/prev?adjusted=true&apiKey={POLYGON_API_KEY}"
    data = _api_call(url)
    
    if data and 'results' in data and data['results']:
        try:
            price = float(data['results'][0]['c'])  # c = close price
            _cache_set(cache_key, price)
            return price
        except:
            return None
    return None

def get_historical_prices(ticker, days=500):
    """Pobiera dane historyczne z Polygon.io."""
    if not ticker:
        return pd.DataFrame()
    
    cache_key = _cache_key("hist", ticker, days)
    cached = _cache_get(cache_key)
    if cached is not None:
        try:
            df = pd.DataFrame(cached)
            df.index = pd.to_datetime(df.index)
            df.sort_index(inplace=True)
            return df
        except:
            pass
    
    end = datetime.now().strftime('%Y-%m-%d')
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    url = f"{POLYGON_BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}?adjusted=true&apiKey={POLYGON_API_KEY}"
    data = _api_call(url)
    
    if data is None or 'results' not in data or not data['results']:
        return pd.DataFrame()
    
    df = pd.DataFrame(data['results'])
    df['date'] = pd.to_datetime(df['t'], unit='ms')
    df.set_index('date', inplace=True)
    df.rename(columns={
        'o': 'Open',
        'h': 'High',
        'l': 'Low',
        'c': 'Close',
        'v': 'Volume'
    }, inplace=True)
    
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
    _cache_set(cache_key, df.to_dict('records'))
    return df

def get_company_profile(ticker):
    """Pobiera profil spółki z Polygon.io."""
    if not ticker:
        return {}
    cache_key = _cache_key("profile", ticker)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    
    # Najpierw spróbuj pobrać szczegółowe dane
    url = f"{POLYGON_BASE_URL}/v3/reference/tickers/{ticker}?apiKey={POLYGON_API_KEY}"
    data = _api_call(url)
    
    if data and 'results' in data:
        results = data['results']
        # Polygon zwraca inne nazwy pól – mapujemy je na to, czego oczekuje reszta kodu
        profile = {
            'Symbol': results.get('ticker'),
            'Name': results.get('name'),
            'Sector': results.get('sector'),
            'Industry': results.get('industry'),
            'MarketCapitalization': results.get('market_cap'),
            'TotalAssets': results.get('total_assets'),
            'TotalRevenue': results.get('total_revenue'),
            'EBITDA': results.get('ebitda'),
            'EPS': results.get('eps'),
            'Beta': results.get('beta'),
            '52WeekHigh': results.get('high_52_week'),
            '52WeekLow': results.get('low_52_week'),
            'DividendYield': results.get('dividend_yield'),
        }
        _cache_set(cache_key, profile)
        return profile
    
    return {}

def get_key_metrics(ticker):
    """Pobiera kluczowe wskaźniki z Polygon.io."""
    profile = get_company_profile(ticker)
    if not profile:
        return {}
    
    # Polygon nie ma tych wskaźników bezpośrednio w ticker details
    # Musimy je pobrać z innego endpointu lub wyliczyć
    # Na razie zwracamy to, co mamy
    metrics = {
        'pegRatio': profile.get('peg_ratio'),
        'revenueGrowth': profile.get('revenue_growth'),
        'netIncomeGrowth': profile.get('net_income_growth'),
        'ebitda': profile.get('ebitda'),
        'freeCashFlow': profile.get('free_cash_flow'),
        'eps': profile.get('eps'),
        'epsForward': profile.get('eps_forward'),
        'totalAssets': profile.get('total_assets'),
        'totalRevenue': profile.get('total_revenue'),
        'operatingCashFlow': profile.get('operating_cash_flow'),
        'netIncome': profile.get('net_income'),
    }
    
    for k, v in metrics.items():
        if v is not None:
            try:
                metrics[k] = float(v)
            except:
                metrics[k] = None
    return metrics

def get_financial_ratios(ticker):
    """Pobiera wskaźniki finansowe z Polygon.io."""
    profile = get_company_profile(ticker)
    if not profile:
        return {}
    
    ratios = {
        'enterpriseValueToEbitda': profile.get('ev_to_ebitda'),
        'enterpriseValueToRevenue': profile.get('ev_to_revenue'),
        'returnOnEquity': profile.get('roe'),
        'returnOnAssets': profile.get('roa'),
        'grossProfitMargin': profile.get('gross_margin'),
        'netProfitMargin': profile.get('profit_margin'),
        'operatingProfitMargin': profile.get('operating_margin'),
        'debtEquityRatio': profile.get('debt_to_equity'),
        'currentRatio': profile.get('current_ratio'),
        'quickRatio': profile.get('quick_ratio')
    }
    
    for k, v in ratios.items():
        if v is not None:
            try:
                ratios[k] = float(v)
            except:
                ratios[k] = None
    return ratios

def get_company_fundamentals(ticker):
    """Zwraca wszystkie wskaźniki fundamentalne w jednym słowniku."""
    try:
        profile = get_company_profile(ticker)
        metrics = get_key_metrics(ticker)
        ratios = get_financial_ratios(ticker)
    except Exception as e:
        print(f"Błąd Polygon.io dla {ticker}: {e}")
        return None

    if not profile:
        return None

    fundamentals = {
        'P/E': profile.get('pe_ratio'),
        'PEG': metrics.get('pegRatio'),
        'P/S': profile.get('ps_ratio'),
        'P/B': profile.get('pb_ratio'),
        'EV/EBITDA': ratios.get('enterpriseValueToEbitda'),
        'EV/Revenue': ratios.get('enterpriseValueToRevenue'),
        'ROE': ratios.get('returnOnEquity'),
        'ROA': ratios.get('returnOnAssets'),
        'Gross Margin': ratios.get('grossProfitMargin'),
        'Profit Margin': ratios.get('netProfitMargin'),
        'Operating Margin': ratios.get('operatingProfitMargin'),
        'Revenue Growth': metrics.get('revenueGrowth'),
        'Earnings Growth': metrics.get('netIncomeGrowth'),
        'Debt/Equity': ratios.get('debtEquityRatio'),
        'Current Ratio': ratios.get('currentRatio'),
        'Quick Ratio': ratios.get('quickRatio'),
        'EBITDA': metrics.get('ebitda'),
        'Free Cash Flow': metrics.get('freeCashFlow'),
        'EPS (Trailing)': metrics.get('eps'),
        'EPS (Forward)': metrics.get('epsForward'),
        'Market Cap': profile.get('MarketCapitalization'),
        'Enterprise Value': profile.get('EnterpriseValue'),
        'Operating Cash Flow': metrics.get('operatingCashFlow'),
        'Net Income': metrics.get('netIncome'),
        'Total Assets': metrics.get('totalAssets'),
        'Total Revenue': metrics.get('totalRevenue'),
        'Dividend Yield': profile.get('DividendYield'),
        'Beta': profile.get('Beta'),
        '52Week High': profile.get('52WeekHigh'),
        '52Week Low': profile.get('52WeekLow'),
    }

    for key in ['ROE','ROA','Gross Margin','Profit Margin','Operating Margin']:
        if fundamentals.get(key) is not None:
            fundamentals[key] = fundamentals[key] * 100
    for key in ['Revenue Growth','Earnings Growth']:
        if fundamentals.get(key) is not None:
            fundamentals[key] = fundamentals[key] * 100

    return fundamentals

def _to_scalar(val, default=0.0):
    if val is None:
        return default
    if hasattr(val, 'iloc'):
        try:
            val = val.iloc[-1]
        except:
            pass
    if hasattr(val, 'item'):
        try:
            val = val.item()
        except:
            pass
    try:
        v = float(val)
        return default if np.isnan(v) else v
    except:
        return default

# ============================================================
# ZARZĄDZANIE CACHE MAKRO
# ============================================================

MACRO_CACHE_FILE = "macro_cache_meta.json"
MACRO_UPDATE_INTERVAL_DAYS = 30

def macro_cache_needs_update():
    if not os.path.exists(MACRO_CACHE_FILE):
        return True
    try:
        with open(MACRO_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        last_update = datetime.fromisoformat(data.get("last_update"))
        return datetime.now() - last_update > timedelta(days=MACRO_UPDATE_INTERVAL_DAYS)
    except Exception:
        return True

def update_macro_cache_timestamp():
    with open(MACRO_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_update": datetime.now().isoformat()}, f, indent=2)

# ============================================================
# DANE MAKRO - API BANKU ŚWIATOWEGO (ZOSTAJE BEZ ZMIAN)
# ============================================================

macro_csv_file = 'macro_data.csv'
macro_data_cache = {}

def fetch_macro_data_api(country_code):
    wb_country_map = {
        'US': 'USA', 'DE': 'DEU', 'JP': 'JPN', 'PL': 'POL',
        'UK': 'GBR', 'FR': 'FRA', 'NL': 'NLD', 'TW': 'TWN',
        'CH': 'CHE', 'EU': 'EUU'
    }
    wb_code = wb_country_map.get(country_code, country_code)

    indicators = {
        'gdp_growth': 'NY.GDP.MKTP.KD.ZG',
        'inflation': 'FP.CPI.TOTL.ZG',
        'unemployment': 'SL.UEM.TOTL.ZS',
        'interest_rate': 'FR.INR.LEND',
        'consumer_confidence': None,
        'manufacturing_pmi': None,
        'retail_sales_growth': None,
        'rating': None
    }

    result = {}
    for key, code in indicators.items():
        if code is None:
            result[key] = None
            continue
        url = f"http://api.worldbank.org/v2/country/{wb_code}/indicator/{code}?format=json&per_page=1&mrv=1"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list) and len(data) > 1 and data[1]:
                    val = data[1][0].get('value')
                    if val is not None and val != "":
                        result[key] = float(val)
                    else:
                        result[key] = None
                else:
                    result[key] = None
            else:
                result[key] = None
        except Exception as e:
            print(f"Błąd API dla {country_code} {key}: {e}")
            result[key] = None

    return result

def get_fallback_macro(country):
    fallback = {
        'US': [2.1, 3.2, 3.8, 5.5, 98.5, 52.8, 4.2, 'AAA'],
        'DE': [0.8, 2.8, 5.7, 4.0, 95.2, 48.5, 2.1, 'AAA'],
        'JP': [1.2, 2.5, 2.6, 0.1, 88.7, 51.2, 3.5, 'A+'],
        'PL': [3.5, 4.8, 5.2, 5.75, 92.3, 49.8, 5.8, 'A-'],
        'UK': [1.8, 3.5, 4.3, 5.25, 89.6, 50.5, 3.2, 'AA'],
        'FR': [1.5, 3.0, 7.2, 4.0, 93.1, 47.8, 2.5, 'AA'],
        'NL': [2.2, 2.9, 3.6, 4.0, 96.4, 52.1, 4.5, 'AAA'],
        'TW': [3.8, 2.2, 3.7, 1.875, 91.8, 53.2, 6.2, 'AA'],
        'CH': [1.8, 1.5, 4.1, 1.75, 94.2, 51.8, 2.8, 'AAA'],
        'EU': [2.0, 2.5, 5.0, 3.0, 95.0, 50.0, 3.0, 'A']
    }
    data = fallback.get(country, [2.0, 2.0, 5.0, 3.0, 90.0, 50.0, 2.0, 'A'])
    return {
        'gdp_growth': data[0],
        'inflation': data[1],
        'unemployment': data[2],
        'interest_rate': data[3],
        'consumer_confidence': data[4],
        'manufacturing_pmi': data[5],
        'retail_sales_growth': data[6],
        'rating': data[7]
    }

def ensure_macro_csv():
    countries = ['US', 'DE', 'JP', 'PL', 'UK', 'FR', 'NL', 'TW', 'CH', 'EU']
    all_data = {}

    for country in countries:
        print(f"Pobieranie danych makro dla {country}...")
        api_data = fetch_macro_data_api(country)
        fallback = get_fallback_macro(country)
        for key in ['gdp_growth', 'inflation', 'unemployment', 'interest_rate',
                    'consumer_confidence', 'manufacturing_pmi', 'retail_sales_growth', 'rating']:
            if api_data.get(key) is None:
                api_data[key] = fallback[key]
        all_data[country] = api_data

    df = pd.DataFrame.from_dict(all_data, orient='index',
                                 columns=['gdp_growth', 'inflation', 'unemployment',
                                          'interest_rate', 'consumer_confidence',
                                          'manufacturing_pmi', 'retail_sales_growth', 'rating'])
    df.to_csv(macro_csv_file)
    print(f"Zapisano dane makro do {macro_csv_file}")

def load_macro_csv():
    global macro_data_cache
    try:
        df = pd.read_csv(macro_csv_file, index_col=0)
        macro_data_cache = {}
        for idx, row in df.iterrows():
            macro_data_cache[idx] = {
                'gdp_growth': row['gdp_growth'],
                'inflation': row['inflation'],
                'unemployment': row['unemployment'],
                'interest_rate': row['interest_rate'],
                'consumer_confidence': row['consumer_confidence'],
                'manufacturing_pmi': row['manufacturing_pmi'],
                'retail_sales_growth': row['retail_sales_growth'],
                'rating': row['rating']
            }
        print(f"Wczytano dane makro z {macro_csv_file}")
        return True
    except Exception as e:
        print(f"Błąd wczytywania {macro_csv_file}: {e}")
        return False

def get_macro_indicators(country_code='US'):
    if country_code in macro_data_cache:
        return macro_data_cache[country_code]
    else:
        print(f"OSTRZEŻENIE: Brak danych makro dla {country_code}")
        return None

def ensure_macro_data_up_to_date():
    if macro_cache_needs_update():
        print("Aktualizacja danych makro...")
        try:
            ensure_macro_csv()
            update_macro_cache_timestamp()
        except Exception as e:
            print("Aktualizacja makro nie powiodła się:", e)
    else:
        print("Dane makro są aktualne.")

# ============================================================
# ZARZĄDZANIE PORTFELEM
# ============================================================

portfolio_positions = []
PORTFOLIO_FILE = "portfolio.json"
TRANSACTION_HISTORY_FILE = "transactions.json"
transaction_history = []
WATCHLIST_FILE = "watchlist.json"
watchlist = []

def save_portfolio():
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(portfolio_positions, f, indent=2)

def load_portfolio():
    global portfolio_positions
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
                portfolio_positions = json.load(f)
        except Exception:
            portfolio_positions = []
    else:
        portfolio_positions = []

def save_transactions():
    with open(TRANSACTION_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(transaction_history, f, indent=2, default=str)

def load_transactions():
    global transaction_history
    if os.path.exists(TRANSACTION_HISTORY_FILE):
        try:
            with open(TRANSACTION_HISTORY_FILE, "r", encoding="utf-8") as f:
                transaction_history = json.load(f)
        except Exception:
            transaction_history = []
    else:
        transaction_history = []

def load_watchlist():
    global watchlist
    if os.path.exists(WATCHLIST_FILE):
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                watchlist = json.load(f)
        except:
            watchlist = []
    else:
        watchlist = []

def save_watchlist():
    with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(watchlist, f, indent=2)

# ============================================================
# MAPOWANIE SPÓŁEK NA SEKTORY I KRAJE
# ============================================================

sector_mapping = {
    'AAPL': 'Technology', 'GOOGL': 'Communication Services', 'MSFT': 'Technology',
    'TSLA': 'Consumer Cyclical', 'AMZN': 'Consumer Cyclical', 'META': 'Communication Services',
    'NFLX': 'Communication Services', 'NVDA': 'Technology', 'INTC': 'Technology',
    '^GSPC': 'Index', 'JPM': 'Financial Services', 'BAC': 'Financial Services',
    'WFC': 'Financial Services', 'XOM': 'Energy', 'CVX': 'Energy',
    'JNJ': 'Healthcare', 'PFE': 'Healthcare', 'WMT': 'Consumer Defensive',
    'PG': 'Consumer Defensive', 'XTB.WA': 'Financial Services', 'ASML': 'Technology',
    'TSM': 'Technology', 'SONY': 'Consumer Cyclical', 'SIEGY': 'Automotive',
    'SAN': 'Healthcare', 'UL': 'Consumer Defensive', '^N225': 'Index',
    '^NDX': 'Index', '^DJI': 'Index', '^FCHI': 'Index', '^FTSE': 'Index',
    '^GDAXI': 'Index', '^STOXX50E': 'Index', 'KO': 'Consumer Defensive',
    'PEP': 'Consumer Defensive', 'COST': 'Consumer Defensive', 'MCD': 'Consumer Cyclical',
    'NKE': 'Consumer Cyclical', 'DIS': 'Communication Services', 'VZ': 'Communication Services',
    'T': 'Communication Services', 'GS': 'Financial Services', 'MS': 'Financial Services',
    'C': 'Financial Services', 'UNH': 'Healthcare', 'ABBV': 'Healthcare',
    'MRK': 'Healthcare', 'COP': 'Energy', 'EOG': 'Energy', 'SLB': 'Energy',
    'AMD': 'Technology', 'CRM': 'Technology', 'ADBE': 'Technology',
    'ORCL': 'Technology', 'CSCO': 'Technology', 'QCOM': 'Technology',
    'TXN': 'Technology', 'AMAT': 'Technology', 'MU': 'Technology',
    'LRCX': 'Technology', 'HD': 'Consumer Cyclical', 'LOW': 'Consumer Cyclical',
    'BKNG': 'Consumer Cyclical', 'TJX': 'Consumer Cyclical', 'SBUX': 'Consumer Cyclical',
    'MAR': 'Consumer Cyclical', 'CMG': 'Consumer Cyclical', 'ROST': 'Consumer Cyclical',
    'ABNB': 'Consumer Cyclical', 'GM': 'Automotive', 'F': 'Automotive'
}

sector_benchmarks = {
    'Technology': {'avg_pe': 25, 'avg_ps': 5, 'avg_roe': 18, 'growth_rate': 12, 'profit_margin': 15},
    'Financial Services': {'avg_pe': 12, 'avg_ps': 2, 'avg_roe': 12, 'growth_rate': 6, 'profit_margin': 20},
    'Healthcare': {'avg_pe': 22, 'avg_ps': 4, 'avg_roe': 15, 'growth_rate': 8, 'profit_margin': 12},
    'Energy': {'avg_pe': 10, 'avg_ps': 1.2, 'avg_roe': 10, 'growth_rate': 4, 'profit_margin': 8},
    'Consumer Cyclical': {'avg_pe': 18, 'avg_ps': 1.5, 'avg_roe': 14, 'growth_rate': 8, 'profit_margin': 10},
    'Consumer Defensive': {'avg_pe': 20, 'avg_ps': 1.8, 'avg_roe': 16, 'growth_rate': 6, 'profit_margin': 12},
    'Communication Services': {'avg_pe': 16, 'avg_ps': 2.5, 'avg_roe': 13, 'growth_rate': 10, 'profit_margin': 14},
    'Automotive': {'avg_pe': 14, 'avg_ps': 0.8, 'avg_roe': 11, 'growth_rate': 5, 'profit_margin': 7},
    'Index': {'avg_pe': 18, 'avg_ps': 2, 'avg_roe': 12, 'growth_rate': 6, 'profit_margin': 10}
}

country_mapping = {
    '^GSPC': 'US', 'AAPL': 'US', 'GOOGL': 'US', 'MSFT': 'US', 'TSLA': 'US',
    'AMZN': 'US', 'META': 'US', 'NFLX': 'US', 'NVDA': 'US', 'INTC': 'US',
    'ASML': 'NL', 'TSM': 'TW', 'SONY': 'JP', 'SIEGY': 'DE', 'JPM': 'US',
    'BAC': 'US', 'WFC': 'US', 'XOM': 'US', 'CVX': 'US', 'JNJ': 'US',
    'PFE': 'US', 'WMT': 'US', 'PG': 'US', 'XTB.WA': 'PL', 'SAN': 'FR',
    'UL': 'UK', '^N225': 'JP', '^NDX': 'US', '^DJI': 'US', '^FCHI': 'FR',
    '^FTSE': 'UK', '^GDAXI': 'DE', '^STOXX50E': 'EU', 'KO': 'US', 'PEP': 'US',
    'COST': 'US', 'MCD': 'US', 'NKE': 'US', 'DIS': 'US', 'VZ': 'US',
    'T': 'US', 'GS': 'US', 'MS': 'US', 'C': 'US', 'UNH': 'US',
    'ABBV': 'US', 'MRK': 'US', 'COP': 'US', 'EOG': 'US', 'SLB': 'US',
    'AMD': 'US', 'CRM': 'US', 'ADBE': 'US', 'ORCL': 'US', 'CSCO': 'US',
    'QCOM': 'US', 'TXN': 'US', 'AMAT': 'US', 'MU': 'US', 'LRCX': 'US',
    'HD': 'US', 'LOW': 'US', 'BKNG': 'US', 'TJX': 'US', 'SBUX': 'US',
    'MAR': 'US', 'CMG': 'US', 'ROST': 'US', 'ABNB': 'US', 'GM': 'US',
    'F': 'US'
}

country_names = {
    'US': 'USA', 'DE': 'Niemcy', 'JP': 'Japonia', 'NL': 'Holandia',
    'TW': 'Tajwan', 'PL': 'Polska', 'UK': 'Wielka Brytania',
    'FR': 'Francja', 'CH': 'Szwajcaria', 'EU': 'Unia Europejska',
    'IT': 'Włochy'
}

def get_country_for_ticker(ticker):
    return country_mapping.get(ticker, 'US')

# ============================================================
# WSKAŹNIKI TECHNICZNE - PEŁEN ZESTAW
# ============================================================

def calculate_rsi(data, window=14):
    delta = data['Close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=window, min_periods=1).mean()
    avg_loss = loss.rolling(window=window, min_periods=1).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(data, fast=12, slow=26, signal=9):
    fast_ema = data['Close'].ewm(span=fast, adjust=False).mean()
    slow_ema = data['Close'].ewm(span=slow, adjust=False).mean()
    macd = fast_ema - slow_ema
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    histogram = macd - signal_line
    return macd, signal_line, histogram

def calculate_bollinger_bands(data, window=20):
    sma = data['Close'].rolling(window=window).mean()
    std = data['Close'].rolling(window=window).std()
    upper_band = sma + (std * 2)
    lower_band = sma - (std * 2)
    return upper_band, sma, lower_band

def calculate_stochastic(data, k_window=14, d_window=3):
    low_min = data['Low'].rolling(window=k_window).min()
    high_max = data['High'].rolling(window=k_window).max()
    k_percent = 100 * ((data['Close'] - low_min) / (high_max - low_min))
    d_percent = k_percent.rolling(window=d_window).mean()
    return k_percent, d_percent

def calculate_williams_r(data, window=14):
    lowest_low = data['Low'].rolling(window=window).min()
    highest_high = data['High'].rolling(window=window).max()
    williams_r = -100 * ((highest_high - data['Close']) / (highest_high - lowest_low))
    return williams_r

def calculate_vwap(data):
    typical_price = (data['High'] + data['Low'] + data['Close']) / 3
    vwap = (typical_price * data['Volume']).cumsum() / data['Volume'].cumsum()
    return vwap

def calculate_cci(data, window=20):
    typical_price = (data['High'] + data['Low'] + data['Close']) / 3
    sma = typical_price.rolling(window=window).mean()
    mad = typical_price.rolling(window=window).apply(lambda x: np.abs(x - x.mean()).mean())
    cci = (typical_price - sma) / (0.015 * mad)
    return cci

def calculate_atr(data, window=14):
    high = data['High']
    low = data['Low']
    close = data['Close']
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=window).mean()
    return atr

def calculate_adx(data, window=14):
    high = data['High']
    low = data['Low']
    close = data['Close']
    tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(window=window).mean()
    up_move = high - high.shift()
    down_move = low.shift() - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
    plus_dm = pd.Series(plus_dm, index=data.index)
    minus_dm = pd.Series(minus_dm, index=data.index)
    plus_di = 100 * (plus_dm.rolling(window=window).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=window).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    adx = dx.rolling(window=window).mean()
    return adx

def calculate_obv(data):
    obv = (np.sign(data['Close'].diff()) * data['Volume']).fillna(0).cumsum()
    return obv

def calculate_mfi(data, window=14):
    typical_price = (data['High'] + data['Low'] + data['Close']) / 3
    money_flow = typical_price * data['Volume']
    positive_flow = money_flow.where(typical_price > typical_price.shift(), 0).rolling(window=window).sum()
    negative_flow = money_flow.where(typical_price < typical_price.shift(), 0).rolling(window=window).sum()
    mfi = 100 - (100 / (1 + positive_flow / negative_flow))
    return mfi

def calculate_ichimoku(data):
    high9 = data['High'].rolling(9).max()
    low9 = data['Low'].rolling(9).min()
    tenkan = (high9 + low9) / 2
    high26 = data['High'].rolling(26).max()
    low26 = data['Low'].rolling(26).min()
    kijun = (high26 + low26) / 2
    return tenkan, kijun

def calculate_aroon(data, period=25):
    aroon_up = data['High'].rolling(period).apply(lambda x: (period - x.argmax()) / period * 100, raw=False)
    aroon_down = data['Low'].rolling(period).apply(lambda x: (period - x.argmin()) / period * 100, raw=False)
    return aroon_up, aroon_down

def calculate_cmf(data, window=20):
    mfm = ((data['Close'] - data['Low']) - (data['High'] - data['Close'])) / (data['High'] - data['Low'])
    mfv = mfm * data['Volume']
    cmf = mfv.rolling(window=window).sum() / data['Volume'].rolling(window=window).sum()
    return cmf

def calculate_supertrend(df, multiplier=2, period=10):
    high = df['High']
    low = df['Low']
    close = df['Close']
    atr = calculate_atr(df, window=period)
    hl2 = (high + low) / 2
    upper_band = hl2 + multiplier * atr
    lower_band = hl2 - multiplier * atr
    supertrend = pd.Series(index=df.index, dtype=float)
    trend = pd.Series(index=df.index, dtype=int)
    for i in range(1, len(df)):
        if i == 1:
            if close.iloc[i] > upper_band.iloc[i]:
                trend.iloc[i] = 1
                supertrend.iloc[i] = lower_band.iloc[i]
            else:
                trend.iloc[i] = -1
                supertrend.iloc[i] = upper_band.iloc[i]
        else:
            if trend.iloc[i-1] == 1:
                if close.iloc[i] > lower_band.iloc[i]:
                    trend.iloc[i] = 1
                    supertrend.iloc[i] = max(lower_band.iloc[i], supertrend.iloc[i-1])
                else:
                    trend.iloc[i] = -1
                    supertrend.iloc[i] = upper_band.iloc[i]
            else:
                if close.iloc[i] < upper_band.iloc[i]:
                    trend.iloc[i] = -1
                    supertrend.iloc[i] = min(upper_band.iloc[i], supertrend.iloc[i-1])
                else:
                    trend.iloc[i] = 1
                    supertrend.iloc[i] = lower_band.iloc[i]
    return supertrend, trend

def calculate_parabolic_sar(df, step=0.02, max_step=0.2):
    high = df['High']
    low = df['Low']
    close = df['Close']
    sar = pd.Series(index=df.index, dtype=float)
    trend = pd.Series(index=df.index, dtype=int)
    if len(df) < 2:
        return sar, trend
    sar.iloc[0] = close.iloc[0]
    trend.iloc[0] = 1 if close.iloc[1] > close.iloc[0] else -1
    af = step
    for i in range(1, len(df)):
        if trend.iloc[i-1] == 1:
            sar.iloc[i] = sar.iloc[i-1] + af * (high.iloc[i-1] - sar.iloc[i-1])
            if sar.iloc[i] > low.iloc[i]:
                trend.iloc[i] = -1
                sar.iloc[i] = high.iloc[i-1]
                af = step
            else:
                trend.iloc[i] = 1
                if high.iloc[i] > high.iloc[i-1]:
                    af = min(af + step, max_step)
        else:
            sar.iloc[i] = sar.iloc[i-1] - af * (sar.iloc[i-1] - low.iloc[i-1])
            if sar.iloc[i] < high.iloc[i]:
                trend.iloc[i] = 1
                sar.iloc[i] = low.iloc[i-1]
                af = step
            else:
                trend.iloc[i] = -1
                if low.iloc[i] < low.iloc[i-1]:
                    af = min(af + step, max_step)
    return sar, trend

def calculate_fibonacci_levels(df, lookback=252):
    recent = df.tail(lookback)
    high = recent['High'].max()
    low = recent['Low'].min()
    diff = high - low
    levels = {
        '0%': high,
        '23.6%': high - 0.236 * diff,
        '38.2%': high - 0.382 * diff,
        '50%': high - 0.5 * diff,
        '61.8%': high - 0.618 * diff,
        '78.6%': high - 0.786 * diff,
        '100%': low
    }
    return levels

def calculate_indicators_on_df(df):
    if df is None or df.empty or 'Close' not in df.columns:
        return None
    if 'Volume' not in df.columns:
        df['Volume'] = 0
    df = df.copy()
    df['RSI'] = calculate_rsi(df)
    df['MACD'], df['MACD_Signal'], df['MACD_Histogram'] = calculate_macd(df)
    df['BB_Upper'], df['BB_Middle'], df['BB_Lower'] = calculate_bollinger_bands(df)
    df['Stoch_K'], df['Stoch_D'] = calculate_stochastic(df)
    df['Williams_R'] = calculate_williams_r(df)
    df['VWAP'] = calculate_vwap(df)
    df['CCI'] = calculate_cci(df)
    df['ATR'] = calculate_atr(df)
    df['ADX'] = calculate_adx(df)
    df['OBV'] = calculate_obv(df)
    df['MFI'] = calculate_mfi(df)
    df['Tenkan'], df['Kijun'] = calculate_ichimoku(df)
    df['Aroon_Up'], df['Aroon_Down'] = calculate_aroon(df)
    df['CMF'] = calculate_cmf(df)
    
    # ========== DODAJEMY KOLUMNĘ SIGNAL ==========
    df['Signal'] = 0
    valid_idx = df.dropna().index
    for idx in valid_idx:
        row = df.loc[idx]
        buy_score = 0
        sell_score = 0

        if 'RSI' in row and not pd.isna(row['RSI']):
            if row['RSI'] < 30: buy_score += 2
            elif row['RSI'] > 70: sell_score += 2

        if 'MACD' in row and 'MACD_Signal' in row and not pd.isna(row['MACD']) and not pd.isna(row['MACD_Signal']):
            if row['MACD'] > row['MACD_Signal']: buy_score += 2
            elif row['MACD'] < row['MACD_Signal']: sell_score += 2

        if 'Close' in row and 'BB_Middle' in row and not pd.isna(row['Close']) and not pd.isna(row['BB_Middle']):
            if row['Close'] > row['BB_Middle']: buy_score += 1
            else: sell_score += 1

        if 'Williams_R' in row and not pd.isna(row['Williams_R']):
            if row['Williams_R'] < -80: buy_score += 1
            elif row['Williams_R'] > -20: sell_score += 1

        if 'CCI' in row and not pd.isna(row['CCI']):
            if row['CCI'] < -100: buy_score += 1
            elif row['CCI'] > 100: sell_score += 1

        if buy_score >= 5:
            df.at[idx, 'Signal'] = 1
        elif sell_score >= 5:
            df.at[idx, 'Signal'] = -1
        else:
            df.at[idx, 'Signal'] = 0
    
    return df

# ============================================================
# ANALIZA FUNDAMENTALNA - PEŁNA
# ============================================================

def calculate_country_score(macro_data):
    """
    Score makro 0–100. Braki (None/NaN) = neutral 55, NIE zero.
    Skala dopasowana do rozwiniętych gospodarek (USA ~2% PKB = dobry wynik).
    """
    if macro_data is None:
        return 55

    def _v(key, default=None):
        val = macro_data.get(key, default) if isinstance(macro_data, dict) else default
        try:
            if val is None or (isinstance(val, float) and np.isnan(val)):
                return None
            return float(val)
        except (TypeError, ValueError):
            return None

    weights = {
        'gdp_growth': 0.28, 'inflation': 0.18, 'unemployment': 0.15,
        'interest_rate': 0.12, 'consumer_confidence': 0.10,
        'manufacturing_pmi': 0.12, 'retail_sales_growth': 0.05
    }

    # --- PKB: 2.0% = ~85, 2.5%+ = 100 (wcześniej 5% = 100 było zbyt ostre) ---
    gdp = _v('gdp_growth')
    if gdp is None:
        gdp_score = 55
    elif gdp >= 2.5:
        gdp_score = 100
    elif gdp >= 1.5:
        gdp_score = 70 + (gdp - 1.5) / 1.0 * 30  # 1.5→70, 2.5→100
    elif gdp >= 0:
        gdp_score = 40 + (gdp / 1.5) * 30        # 0→40, 1.5→70
    else:
        gdp_score = max(0, 40 + gdp * 15)        # recesja

    # --- Inflacja: komfort 1.5–3.5 (nie tylko 1.5–2.5) ---
    inf = _v('inflation')
    if inf is None:
        inflation_score = 55
    elif 1.5 <= inf <= 3.5:
        inflation_score = 100
    elif 1.0 <= inf < 1.5 or 3.5 < inf <= 4.5:
        inflation_score = 80
    elif inf < 1.0:
        inflation_score = max(40, 80 - (1.0 - inf) * 25)
    else:  # > 4.5
        inflation_score = max(0, 80 - (inf - 4.5) * 12)

    # --- Bezrobocie: 4% = ~80, 3% = ~88 (wcześniej *10 było za twarde) ---
    une = _v('unemployment')
    if une is None:
        unemployment_score = 55
    else:
        unemployment_score = max(0, min(100, 100 - (une - 3.0) * 8))

    # --- Stopy: komfort 2–5.5 (po cyklu podwyżek USA ~5% nie jest „katastrofą”) ---
    rate = _v('interest_rate')
    if rate is None:
        interest_score = 55
    elif 2.0 <= rate <= 5.5:
        interest_score = 100
    elif 1.0 <= rate < 2.0 or 5.5 < rate <= 7.0:
        interest_score = 75
    elif rate < 1.0:
        interest_score = max(40, rate / 1.0 * 70)
    else:
        interest_score = max(0, 75 - (rate - 7.0) * 10)

    # --- Consumer confidence: skala ~50–120, 90+ = mocne ---
    conf = _v('consumer_confidence')
    if conf is None:
        confidence_score = 55
    else:
        confidence_score = max(0, min(100, (conf - 50) / 50 * 100))

    # --- PMI: 50 = neutral, 55+ = dobre ---
    pmi = _v('manufacturing_pmi')
    if pmi is None:
        pmi_score = 55
    elif pmi >= 55:
        pmi_score = min(100, 80 + (pmi - 55) * 4)
    elif pmi >= 50:
        pmi_score = 55 + (pmi - 50) * 5
    else:
        pmi_score = max(0, 55 - (50 - pmi) * 4)

    # --- Retail sales growth ---
    retail = _v('retail_sales_growth')
    if retail is None:
        retail_score = 55
    else:
        retail_score = max(0, min(100, 50 + retail * 10))

    score = (
        gdp_score * weights['gdp_growth']
        + inflation_score * weights['inflation']
        + unemployment_score * weights['unemployment']
        + interest_score * weights['interest_rate']
        + confidence_score * weights['consumer_confidence']
        + pmi_score * weights['manufacturing_pmi']
        + retail_score * weights['retail_sales_growth']
    )
    return round(float(np.clip(score, 0, 100)), 2)

def score_peg(peg, sector):
    if peg is None or peg <= 0:
        return 50
    if sector in ['Technology', 'Communication Services']:
        if peg < 0.8: return 100
        elif peg < 1.2: return 80
        elif peg < 2.0: return 60
        elif peg < 3.0: return 40
        else: return 20
    elif sector in ['Consumer Defensive', 'Healthcare']:
        if peg < 1.0: return 100
        elif peg < 1.5: return 80
        elif peg < 2.5: return 60
        elif peg < 4.0: return 40
        else: return 20
    else:
        if peg < 1.2: return 100
        elif peg < 1.8: return 80
        elif peg < 3.0: return 60
        elif peg < 5.0: return 40
        else: return 20

# ============================================================
# PROGI PUNKTACJI DLA SEKTORÓW
# ============================================================

sector_thresholds = {
    'Technology': {'P/E': [18, 25, 35, 50], 'P/S': [4, 7, 10, 15], 'P/B': [3, 5, 8, 12], 'EV/EBITDA': [12, 18, 25, 35], 'ROE': [30, 20, 15, 10], 'ROA': [15, 10, 7, 4], 'Profit Margin': [25, 20, 15, 10], 'Revenue Growth': [20, 15, 10, 5], 'Debt/Equity': [0.2, 0.5, 1.0, 1.5], 'Current Ratio': [2.5, 2.0, 1.5, 1.2]},
    'Communication Services': {'P/E': [15, 22, 30, 40], 'P/S': [3, 5, 8, 12], 'P/B': [2, 3, 5, 7], 'EV/EBITDA': [8, 12, 16, 22], 'ROE': [25, 20, 15, 8], 'ROA': [12, 9, 6, 4], 'Profit Margin': [25, 20, 15, 8], 'Revenue Growth': [20, 15, 10, 5], 'Debt/Equity': [0.3, 0.7, 1.2, 1.8], 'Current Ratio': [2.5, 2.0, 1.5, 1.2]},
    'Consumer Cyclical': {'P/E': [12, 18, 25, 35], 'P/S': [1.0, 2.0, 3.5, 5.0], 'P/B': [1.5, 2.5, 4.0, 6.0], 'EV/EBITDA': [8, 12, 16, 22], 'ROE': [20, 15, 10, 5], 'ROA': [10, 7, 5, 3], 'Profit Margin': [12, 8, 5, 3], 'Revenue Growth': [15, 10, 5, 0], 'Debt/Equity': [0.5, 1.0, 1.5, 2.0], 'Current Ratio': [2.0, 1.5, 1.2, 1.0]},
    'Consumer Defensive': {'P/E': [15, 20, 25, 30], 'P/S': [1.0, 1.5, 2.5, 3.5], 'P/B': [2.0, 3.0, 4.5, 6.0], 'EV/EBITDA': [10, 14, 18, 24], 'ROE': [25, 20, 15, 10], 'ROA': [10, 8, 6, 4], 'Profit Margin': [15, 10, 7, 4], 'Revenue Growth': [8, 5, 3, 0], 'Debt/Equity': [0.5, 0.8, 1.2, 1.5], 'Current Ratio': [2.0, 1.5, 1.2, 1.0]},
    'Financial Services': {'P/E': [10, 13, 16, 20], 'P/B': [1.0, 1.3, 1.8, 2.5], 'ROE': [15, 12, 9, 6], 'ROA': [1.5, 1.2, 0.9, 0.6], 'Profit Margin': [30, 25, 20, 15], 'Debt/Equity': [1.0, 2.0, 3.0, 4.0], 'Current Ratio': [1.5, 1.2, 1.0, 0.8]},
    'Healthcare': {'P/E': [15, 20, 25, 30], 'P/S': [2.5, 4.0, 6.0, 8.0], 'EV/EBITDA': [10, 14, 18, 24], 'ROE': [25, 20, 15, 10], 'Profit Margin': [20, 15, 10, 5], 'Revenue Growth': [12, 8, 5, 2], 'Debt/Equity': [0.5, 1.0, 1.5, 2.0], 'Current Ratio': [2.5, 2.0, 1.5, 1.2]},
    'Energy': {'P/E': [10, 13, 17, 22], 'EV/EBITDA': [5, 7, 9, 12], 'ROE': [20, 15, 10, 5], 'Profit Margin': [15, 10, 7, 4], 'Debt/Equity': [0.4, 0.8, 1.2, 1.8], 'Current Ratio': [1.5, 1.2, 1.0, 0.8]},
    'Automotive': {'P/E': [8, 12, 16, 22], 'P/S': [0.5, 1.0, 1.5, 2.5], 'EV/EBITDA': [6, 9, 12, 16], 'ROE': [15, 10, 7, 4], 'Profit Margin': [8, 6, 4, 2], 'Revenue Growth': [10, 7, 4, 1], 'Debt/Equity': [0.8, 1.5, 2.5, 4.0], 'Current Ratio': [1.5, 1.2, 1.0, 0.8]},
    'Index': {'P/E': [15, 19, 24, 30], 'P/S': [1.5, 2.5, 3.5, 5.0], 'P/B': [2.0, 3.0, 4.0, 5.5], 'ROE': [18, 14, 10, 7], 'Revenue Growth': [10, 7, 4, 2], 'Debt/Equity': [0.6, 1.0, 1.5, 2.0], 'Current Ratio': [2.0, 1.5, 1.2, 1.0]},
    'Default': {'P/E': [12, 18, 25, 35], 'P/S': [1.5, 3.0, 5.0, 8.0], 'EV/EBITDA': [8, 12, 16, 22], 'ROE': [20, 15, 10, 5], 'Profit Margin': [15, 10, 7, 4], 'Revenue Growth': [12, 8, 5, 2], 'Debt/Equity': [0.5, 1.0, 1.5, 2.0], 'Current Ratio': [2.0, 1.5, 1.2, 1.0]}
}

def calculate_sector_fundamental_score(fundamentals, sector):
    if not fundamentals:
        return 45
    thr = sector_thresholds.get(sector, sector_thresholds.get('Default', {}))
    def percentile_score(value, thresholds, reverse=False):
        if value is None or np.isnan(value):
            return 50
        if len(thresholds) < 4:
            return 50
        sorted_thr = sorted(thresholds)
        q1, q2, q3, q4 = sorted_thr[:4]
        if reverse:
            if value <= q1: return 100
            elif value <= q2: return 80
            elif value <= q3: return 60
            elif value <= q4: return 40
            else: return 20
        else:
            if value >= q4: return 100
            elif value >= q3: return 80
            elif value >= q2: return 60
            elif value >= q1: return 40
            else: return 20
    weights = {'P/E': 0.12, 'P/S': 0.10, 'PEG': 0.12, 'EV/EBITDA': 0.10, 'ROE': 0.15, 'ROA': 0.05, 'Profit Margin': 0.10, 'Revenue Growth': 0.12, 'Free Cash Flow': 0.08, 'Debt/Equity': 0.07, 'Current Ratio': 0.04}
    score = 0.0
    total_weight = 0.0
    reverse_metrics = {'P/E', 'P/S', 'EV/EBITDA', 'Debt/Equity'}
    for key, weight in weights.items():
        if key == 'PEG':
            if fundamentals.get('PEG') is not None and fundamentals['PEG'] > 0:
                peg_score = score_peg(fundamentals['PEG'], sector)
                score += peg_score * weight
                total_weight += weight
            continue
        if key in fundamentals and fundamentals[key] is not None and not np.isnan(fundamentals[key]) and key in thr:
            val = fundamentals[key]
            if key in {'P/E', 'P/S', 'EV/EBITDA'} and val <= 0:
                p_score = 20
            else:
                is_reverse = key in reverse_metrics
                p_score = percentile_score(val, thr[key], reverse=is_reverse)
            score += p_score * weight
            total_weight += weight
    if total_weight > 0:
        final_score = score / total_weight
    else:
        final_score = 45
    return round(final_score, 2)

# ============================================================
# NOWE WSKAŹNIKI PRZYSZŁOŚCIOWE
# ============================================================

def get_innovation_score(ticker):
    try:
        profile = get_company_profile(ticker)
        if not profile:
            return 50
        revenue = float(profile.get('TotalRevenue', 0)) if profile.get('TotalRevenue') else 0
        rnd = float(profile.get('ResearchAndDevelopment', 0)) if profile.get('ResearchAndDevelopment') else 0
        capex = float(profile.get('CapitalExpenditures', 0)) if profile.get('CapitalExpenditures') else 0
        if revenue and revenue > 0:
            rnd_ratio = rnd / revenue
            capex_ratio = abs(capex) / revenue
        else:
            return 50
        score = 0
        if rnd_ratio > 0.15: score += 60
        elif rnd_ratio > 0.08: score += 40
        elif rnd_ratio > 0.03: score += 20
        else: score += 10
        if capex_ratio > 0.08: score += 30
        elif capex_ratio > 0.04: score += 20
        else: score += 10
        return min(score, 100)
    except:
        return 50

def get_analyst_revision_momentum(ticker):
    try:
        profile = get_company_profile(ticker)
        if not profile:
            return 50
        eps_change = profile.get('EPSChange', 0)
        if eps_change:
            eps_change = float(eps_change)
            if eps_change > 10: return 80
            elif eps_change > 5: return 70
            elif eps_change > 0: return 60
            elif eps_change > -5: return 40
            else: return 20
        return 50
    except:
        return 50

def get_recommendation_momentum(ticker):
    try:
        profile = get_company_profile(ticker)
        if not profile:
            return 50
        analyst_target = profile.get('AnalystTargetPrice')
        current_price = get_live_price(ticker)
        if analyst_target and current_price and current_price > 0:
            upside = (float(analyst_target) - current_price) / current_price * 100
            if upside > 20: return 80
            elif upside > 10: return 70
            elif upside > 5: return 60
            elif upside > -5: return 40
            else: return 20
        return 50
    except:
        return 50

def get_management_quality(ticker):
    try:
        profile = get_company_profile(ticker)
        if not profile:
            return 50
        roe = float(profile.get('ROE', 0)) if profile.get('ROE') else 0
        roe = roe * 100 if abs(roe) < 10 else roe
        if roe > 25: return 80
        elif roe > 20: return 70
        elif roe > 15: return 60
        elif roe > 10: return 50
        elif roe > 5: return 40
        else: return 30
    except:
        return 50

def get_growth_momentum(ticker):
    try:
        profile = get_company_profile(ticker)
        if not profile:
            return 50
        rev_growth = profile.get('RevenueGrowth', 0)
        eps_growth = profile.get('EarningsGrowth', 0)
        if rev_growth:
            rev_growth = float(rev_growth) * 100 if abs(float(rev_growth)) < 10 else float(rev_growth)
        else:
            rev_growth = 0
        if eps_growth:
            eps_growth = float(eps_growth) * 100 if abs(float(eps_growth)) < 10 else float(eps_growth)
        else:
            eps_growth = 0
        avg_growth = (rev_growth + eps_growth) / 2
        if avg_growth > 30: return 80
        elif avg_growth > 20: return 70
        elif avg_growth > 10: return 60
        elif avg_growth > 0: return 50
        elif avg_growth > -10: return 40
        else: return 30
    except:
        return 50

def get_risk_assessment(ticker):
    try:
        profile = get_company_profile(ticker)
        if not profile:
            return 50
        beta = float(profile.get('Beta', 1)) if profile.get('Beta') else 1
        de_ratio = float(profile.get('Debt/Equity', 0)) if profile.get('Debt/Equity') else 0
        beta_score = 0
        if beta < 0.8: beta_score = 80
        elif beta < 1.0: beta_score = 70
        elif beta < 1.2: beta_score = 60
        elif beta < 1.5: beta_score = 50
        elif beta < 2.0: beta_score = 40
        else: beta_score = 30
        de_score = 0
        if de_ratio < 0.3: de_score = 80
        elif de_ratio < 0.6: de_score = 70
        elif de_ratio < 1.0: de_score = 60
        elif de_ratio < 1.5: de_score = 50
        elif de_ratio < 2.5: de_score = 40
        else: de_score = 30
        return int(beta_score * 0.6 + de_score * 0.4)
    except:
        return 50

def get_short_interest_boost(ticker):
    return 1.0

def get_news_sentiment(ticker):
    return 1.0

def get_insider_confidence(ticker):
    return 50

def get_sector_analysis(ticker, sector):
    fundamentals = get_company_fundamentals(ticker)
    if not fundamentals:
        return 50
    benchmark = sector_benchmarks.get(sector, sector_benchmarks['Technology'])
    sector_score = 0
    if fundamentals.get('P/E') is not None and fundamentals['P/E'] < benchmark['avg_pe']:
        sector_score += 20
    elif fundamentals.get('P/E') is not None and fundamentals['P/E'] < benchmark['avg_pe'] * 1.2:
        sector_score += 10
    if fundamentals.get('ROE') is not None and fundamentals['ROE'] > benchmark['avg_roe']:
        sector_score += 20
    elif fundamentals.get('ROE') is not None and fundamentals['ROE'] > benchmark['avg_roe'] * 0.8:
        sector_score += 10
    if fundamentals.get('Revenue Growth') is not None and fundamentals['Revenue Growth'] > benchmark['growth_rate']:
        sector_score += 15
    if fundamentals.get('Profit Margin') is not None and fundamentals['Profit Margin'] > benchmark['profit_margin']:
        sector_score += 15
    return min(sector_score, 100)

# ============================================================
# KOMPLEKSOWA ANALIZA FUNDAMENTALNA
# ============================================================

def get_comprehensive_fundamental_analysis(ticker):
    country_code = get_country_for_ticker(ticker)
    macro_data = get_macro_indicators(country_code)
    country_score = calculate_country_score(macro_data)
    sector = sector_mapping.get(ticker, 'Unknown')
    company_fundamentals = get_company_fundamentals(ticker)
    
    if sector == 'Index':
        _mr = "BARDZO DOBRA" if country_score >= 78 else ("DOBRA" if country_score >= 68 else "UMIARKOWANA")
        return {
            'country_code': country_code,
            'country_score': country_score,
            'macro_rating': _mr,
            'macro_color': "green",
            'sector': sector,
            'basic_company_score': None,
            'comprehensive_company_score': None,
            'sector_position_score': 50,
            'management_quality_score': 50,
            'growth_momentum_score': 50,
            'risk_assessment_score': 50,
            'innovation_score': 50,
            'analyst_revision_score': 50,
            'recommendation_momentum_score': 50,
            'combined_score': country_score,
            'fundamental_rating': "INDEX",
            'color': "blue",
            'macro_data': macro_data,
            'company_fundamentals': None
        }

    sector_position_score = get_sector_analysis(ticker, sector)
    management_quality_score = get_management_quality(ticker)
    growth_momentum_score = get_growth_momentum(ticker)
    risk_assessment_score = get_risk_assessment(ticker)
    innovation_score = get_innovation_score(ticker)
    analyst_revision_score = get_analyst_revision_momentum(ticker)
    recommendation_momentum_score = get_recommendation_momentum(ticker)

    if company_fundamentals:
        basic_company_score = calculate_sector_fundamental_score(company_fundamentals, sector)
        comprehensive_company_score = (
            basic_company_score * 0.35 +
            sector_position_score * 0.10 +
            management_quality_score * 0.13 +
            growth_momentum_score * 0.12 +
            risk_assessment_score * 0.10 +
            innovation_score * 0.10 +
            analyst_revision_score * 0.05 +
            recommendation_momentum_score * 0.05
        )
        # Przy niepełnych fundach spółki nie karz makro (free plan / braki API)
        missing_ratio = 0.0
        try:
            keys = ['P/E', 'ROE', 'Revenue Growth', 'Profit Margin', 'Debt/Equity']
            present = sum(1 for k in keys if company_fundamentals.get(k) is not None)
            missing_ratio = 1.0 - present / max(len(keys), 1)
        except Exception:
            missing_ratio = 0.5
        company_w = max(0.35, 0.55 - missing_ratio * 0.25)
        country_w = 1.0 - company_w
        combined_score = country_w * country_score + company_w * comprehensive_company_score
    else:
        comprehensive_company_score = None
        basic_company_score = None
        # Bez danych spółki → rating ≈ makro kraju (USA nie spada do SŁABA przez brak fundów)
        combined_score = country_score * 0.90 + 60 * 0.10

    def _rating_from_score(sc):
        if sc >= 88:
            return "WYBITNA", "darkgreen"
        if sc >= 78:
            return "BARDZO DOBRA", "green"
        if sc >= 68:
            return "DOBRA", "lightgreen"
        if sc >= 55:
            return "UMIARKOWANA", "yellow"
        if sc >= 42:
            return "SŁABA", "orange"
        return "BARDZO SŁABA", "red"

    fundamental_rating, color = _rating_from_score(combined_score)
    macro_rating, macro_color = _rating_from_score(country_score)

    return {
        'country_code': country_code,
        'country_score': country_score,
        'macro_rating': macro_rating,
        'macro_color': macro_color,
        'sector': sector,
        'basic_company_score': basic_company_score,
        'comprehensive_company_score': comprehensive_company_score,
        'sector_position_score': sector_position_score,
        'management_quality_score': management_quality_score,
        'growth_momentum_score': growth_momentum_score,
        'risk_assessment_score': risk_assessment_score,
        'innovation_score': innovation_score,
        'analyst_revision_score': analyst_revision_score,
        'recommendation_momentum_score': recommendation_momentum_score,
        'combined_score': combined_score,
        'fundamental_rating': fundamental_rating,
        'color': color,
        'macro_data': macro_data,
        'company_fundamentals': company_fundamentals
    }

# ============================================================
# FUNKCJE PROGNOZOWANIA
# ============================================================

sector_tech_weight = {
    'Technology': 0.70,          # więcej techniki
    'Communication Services': 0.65,
    'Consumer Cyclical': 0.60,
    'Financial Services': 0.55,
    'Healthcare': 0.50,          # mniej techniki
    'Consumer Defensive': 0.45,  # więcej fundamentów
    'Energy': 0.50,
    'Automotive': 0.55,
    'Index': 0.50,
    'Default': 0.55
}

def get_fundamental_impact_by_horizon(fundamental_score, horizon, sector=None):
    if fundamental_score is None:
        return 1.0
    if horizon == '1M':
        if fundamental_score >= 80: base = 1.03
        elif fundamental_score >= 70: base = 1.02
        elif fundamental_score >= 60: base = 1.01
        elif fundamental_score >= 50: base = 1.00
        elif fundamental_score >= 40: base = 0.99
        else: base = 0.98
    else:
        if fundamental_score >= 80: base = 1.08
        elif fundamental_score >= 70: base = 1.05
        elif fundamental_score >= 60: base = 1.02
        elif fundamental_score >= 50: base = 1.00
        elif fundamental_score >= 40: base = 0.97
        else: base = 0.94
    defensive = ['Healthcare', 'Consumer Defensive', 'Utilities']
    if sector in defensive:
        if base > 1.0:
            base = 1.0 + (base - 1.0) * 0.5
        else:
            base = 1.0 - (1.0 - base) * 0.5
        base = max(0.96, min(1.04, base))
    return base

def get_technical_score_with_sector(df, sector):
    if df is None or len(df) < 20:
        return 1.0
    last = df.iloc[-1]
    rsi = last.get('RSI', 50)
    macd = last.get('MACD', 0)
    macd_signal = last.get('MACD_Signal', 0)
    adx = last.get('ADX', 20)  # DODANE
    obv = last.get('OBV', 0)   # DODANE
    obv_slope = last.get('OBV_Slope', 0)  # DODANE
    
    rsi_shift = 0.0
    if rsi < 30: rsi_shift = 0.02
    elif rsi > 70: rsi_shift = -0.02
    
    macd_shift = 0.0
    if macd > macd_signal: macd_shift = 0.01
    elif macd < macd_signal: macd_shift = -0.01
    
    # DODANE: ADX – silny trend = +1%
    adx_shift = 0.0
    if adx > 25: adx_shift = 0.01
    elif adx < 20: adx_shift = -0.01
    
    # DODANE: OBV – rosnący wolumen = +0.5%
    obv_shift = 0.0
    if obv_slope > 0: obv_shift = 0.005
    
    # Nowe wagi sektorowe
    sector_weights = {
        'Technology': {'rsi': 1.2, 'macd': 1.5, 'adx': 1.0, 'obv': 0.8},
        'Energy': {'rsi': 1.5, 'macd': 0.8, 'adx': 1.2, 'obv': 0.5},
        'Default': {'rsi': 1.0, 'macd': 1.0, 'adx': 1.0, 'obv': 1.0},
    }
    weights = sector_weights.get(sector, sector_weights['Default'])
    
    total_shift = (
        rsi_shift * weights['rsi'] +
        macd_shift * weights['macd'] +
        adx_shift * weights['adx'] +
        obv_shift * weights['obv']
    )
    tech_mult = 1.0 + total_shift
    return max(0.85, min(1.15, tech_mult))

def get_max_historical_change(df, horizon_days, percentile=90):
    if df is None or len(df) < horizon_days + 5:
        return 15.0
    changes = df['Close'].pct_change(periods=horizon_days).dropna()
    if changes.empty:
        return 15.0
    abs_changes = changes.abs()
    cap = np.percentile(abs_changes, percentile)
    if np.isnan(cap) or cap == 0:
        return 15.0
    return float(cap * 100)

def predict_with_technical_influence(df, fundamental_analysis, days_forward, sector):
    print(f"🔍 FUNKCJA WYWOŁANA dla {sector}, dni: {days_forward}")
    """
    Prognozuje cenę na podstawie analizy fundamentalnej i technicznej.
    Uwzględnia: regresję liniową, RSI, MACD, SMA50, SMA200, momentum, wolumen, ATR.
    """
    if df is None or df.empty or len(df) < 5:
        return 0.0, "NEUTRALNY", 0.0
        
    df_clean = df.ffill().bfill().dropna()
    if len(df_clean) < 10:
        current_p = float(df['Close'].iloc[-1]) if not df.empty and 'Close' in df.columns else 0.0
        return current_p, "NEUTRALNY", 0.0

    # ========== WSKAŹNIKI TECHNICZNE ==========
    # 1. Regresja liniowa na cenach
    prices = df_clean["Close"].values.reshape(-1, 1)
    X = np.arange(len(prices)).reshape(-1, 1)
    model = LinearRegression()
    model.fit(X, prices)
    future_index = np.array([[len(prices) + days_forward]])
    base_pred = model.predict(future_index)[0][0]
    
    # 2. Średnie kroczące
    sma50 = df_clean['Close'].rolling(50).mean().iloc[-1] if len(df_clean) >= 50 else df_clean['Close'].iloc[-1]
    sma200 = df_clean['Close'].rolling(200).mean().iloc[-1] if len(df_clean) >= 200 else df_clean['Close'].iloc[-1]
    current_price = float(df_clean['Close'].iloc[-1])
    
    price_vs_sma50 = (current_price / sma50 - 1) * 100 if not np.isnan(sma50) else 0
    price_vs_sma200 = (current_price / sma200 - 1) * 100 if not np.isnan(sma200) else 0
    
    # 3. Momentum (zmiana ceny w ostatnich 20 dniach)
    momentum_20 = (current_price / df_clean['Close'].iloc[-20] - 1) * 100 if len(df_clean) >= 20 else 0
    
    # 4. Wolumen
    avg_volume = df_clean['Volume'].rolling(20).mean().iloc[-1] if len(df_clean) >= 20 else df_clean['Volume'].iloc[-1]
    last_volume = df_clean['Volume'].iloc[-1]
    volume_ratio = last_volume / avg_volume if avg_volume > 0 else 1.0
    
    # 5. ATR – zmienność
    atr = df_clean['ATR'].iloc[-1] if 'ATR' in df_clean.columns else 0
    atr_pct = (atr / current_price) * 100 if current_price > 0 else 0

    horizon = '1M' if days_forward <= 30 else '3M'
    fundamental_score = fundamental_analysis.get('combined_score', 50)
    if fundamental_score is None or np.isnan(fundamental_score):
        fundamental_score = 50
    fundamental_factor = get_fundamental_impact_by_horizon(fundamental_score, horizon, sector)
    tech_mult = get_technical_score_with_sector(df, sector)

    base_tech = sector_tech_weight.get(sector, sector_tech_weight.get('Default', 0.5))
    tech_weight = base_tech + 0.05 if horizon == '1M' else base_tech

    final_factor = (1 - tech_weight) * fundamental_factor + tech_weight * tech_mult
    adjusted_pred = float(base_pred) * final_factor
    
    if current_price <= 0:
        return 0.0, "NEUTRALNY", 0.0

    # ========== KOREKTA O DODATKOWE WSKAŹNIKI ==========
    # Korekta o SMA50 (jeśli cena daleko od SMA50)
    if price_vs_sma50 > 10:
        adjusted_pred *= 0.98
    elif price_vs_sma50 < -10:
        adjusted_pred *= 1.04
    
    # Korekta o SMA200 (jeśli cena daleko od SMA200)
    if price_vs_sma200 > 20:
        adjusted_pred *= 0.94
    elif price_vs_sma200 < -20:
        adjusted_pred *= 1.06
    
    # Korekta o momentum
    if momentum_20 > 10:
        adjusted_pred *= 0.97
    elif momentum_20 < -10:
        adjusted_pred *= 1.03
    
    # Korekta o wolumen (duży wolumen = potwierdzenie trendu)
    if volume_ratio > 1.8:
        adjusted_pred *= 1.03
    elif volume_ratio > 1.3:
        adjusted_pred *= 1.015
    
    # Korekta o ATR (wysoka zmienność = większy potencjał)
    if atr_pct > 5:
        adjusted_pred *= 1.04
    elif atr_pct > 3:
        adjusted_pred *= 1.02

    change_percent = ((adjusted_pred - current_price) / current_price) * 100

    # Ograniczenie zmiany (historyczne maksimum)
    try:
        hist_cap = get_max_historical_change(df, days_forward, percentile=90)
    except:
        hist_cap = 15.0

    sector_cap_mult = {
        'Healthcare': 0.8,
        'Consumer Defensive': 0.8,
        'Technology': 1.2,
        'Communication Services': 1.1,
        'Default': 1.0
    }
    mult = sector_cap_mult.get(sector, 1.0)
    max_change = hist_cap * mult
    max_change = max(max_change, 8.0)
    
    change_percent = max(-max_change, min(max_change, change_percent))
    adjusted_pred = current_price * (1 + change_percent / 100)

    if change_percent > 3:
        direction = "WZROSTOWY"
    elif change_percent < -3:
        direction = "SPADKOWY"
    else:
        direction = "NEUTRALNY"
        print(f"📊 PROGNOZA: {adjusted_pred:.2f} (zmiana: {change_percent:.2f}%)")
    
    return float(adjusted_pred), direction, float(change_percent)

# ============================================================
# SYGNAŁY TECHNICZNE
# ============================================================

def get_technical_signal(df):
    if len(df) < 1:
        return "Brak danych"

    try:
        valid_data = df.dropna()
        if len(valid_data) == 0:
            return "Brak danych"

        current = valid_data.iloc[-1]

        rsi_val = current['RSI'] if isinstance(current['RSI'], (int, float)) else 50
        macd_val = current['MACD'] if isinstance(current['MACD'], (int, float)) else 0
        macd_signal_val = current['MACD_Signal'] if isinstance(current['MACD_Signal'], (int, float)) else 0
        close_val = current['Close'] if isinstance(current['Close'], (int, float)) else 0
        bb_upper_val = current['BB_Upper'] if isinstance(current['BB_Upper'], (int, float)) else 0
        bb_lower_val = current['BB_Lower'] if isinstance(current['BB_Lower'], (int, float)) else 0
        stoch_k_val = current['Stoch_K'] if isinstance(current['Stoch_K'], (int, float)) else 50
        stoch_d_val = current['Stoch_D'] if isinstance(current['Stoch_D'], (int, float)) else 50
        williams_r_val = current['Williams_R'] if isinstance(current['Williams_R'], (int, float)) else -50
        cci_val = current['CCI'] if isinstance(current['CCI'], (int, float)) else 0
        vwap_val = current['VWAP'] if isinstance(current['VWAP'], (int, float)) else 0
        adx_val = current['ADX'] if isinstance(current['ADX'], (int, float)) else 0
        mfi_val = current['MFI'] if isinstance(current['MFI'], (int, float)) else 50
        cmf_val = current['CMF'] if isinstance(current['CMF'], (int, float)) else 0

        signals = []

        if rsi_val < 30:
            signals.append("RSI: WYPRZEDANIE")
        elif rsi_val > 70:
            signals.append("RSI: WYKUPIENIE")

        if macd_val > macd_signal_val:
            signals.append("MACD: SYGNAŁ KUPNA")
        elif macd_val < macd_signal_val:
            signals.append("MACD: SYGNAŁ SPRZEDAŻY")

        if close_val < bb_lower_val:
            signals.append("BB: CENA PONIŻEJ DOLNEGO PASMA")
        elif close_val > bb_upper_val:
            signals.append("BB: CENA POWYŻEJ GÓRNEGO PASMA")

        if stoch_k_val < 20 and stoch_d_val < 20:
            signals.append("STOCH: WYPRZEDANIE")
        elif stoch_k_val > 80 and stoch_d_val > 80:
            signals.append("STOCH: WYKUPIENIE")

        if williams_r_val < -80:
            signals.append("WILLIAMS %R: WYPRZEDANIE")
        elif williams_r_val > -20:
            signals.append("WILLIAMS %R: WYKUPIENIE")

        if cci_val < -100:
            signals.append("CCI: WYPRZEDANIE")
        elif cci_val > 100:
            signals.append("CCI: WYKUPIENIE")

        if close_val > vwap_val:
            signals.append("VWAP: CENA POWYŻEJ ŚREDNIEJ")
        elif close_val < vwap_val:
            signals.append("VWAP: CENA PONIŻEJ ŚREDNIEJ")

        if adx_val > 25:
            signals.append(f"ADX: SILNY TREND ({adx_val:.1f})")
        elif adx_val > 20:
            signals.append(f"ADX: UMIARKOWANY TREND ({adx_val:.1f})")
        else:
            signals.append(f"ADX: SŁABY TREND ({adx_val:.1f})")

        if mfi_val < 20:
            signals.append("MFI: WYPRZEDANIE")
        elif mfi_val > 80:
            signals.append("MFI: WYKUPIENIE")

        if cmf_val > 0.1:
            signals.append("CMF: DODATNI (akumulacja)")
        elif cmf_val < -0.1:
            signals.append("CMF: UJEMNY (dystrybucja)")

        if not signals:
            return "BRAK SYGNAŁU"

        return " | ".join(signals[:6])
    except Exception as e:
        return f"Błąd: {str(e)}"

# ============================================================
# PERSPEKTYWA 3-LETNIA
# ============================================================

def get_risk_and_potential(current_price, low_3y, high_3y, data_3y,
                           fundamental_score=None, is_index=False, trend="",
                           data_10y=None, crash_risk_score=None):
    
    if data_10y is not None and not data_10y.empty and len(data_10y) >= 200:
        low_ctx = data_10y['Low'].min()
        high_ctx = data_10y['High'].max()
        data_ctx = data_10y
        range_ctx = high_ctx - low_ctx
        position_pct = ((current_price - low_ctx) / range_ctx) * 100 if range_ctx > 0 else 50
    else:
        low_ctx = low_3y
        high_ctx = high_3y
        data_ctx = data_3y
        range_ctx = high_ctx - low_ctx
        position_pct = ((current_price - low_ctx) / range_ctx) * 100 if range_ctx > 0 else 50

    if data_ctx.empty or len(data_ctx) < 50:
        risk = min(60, max(5, position_pct * 0.40))
        upside = min(80, max(5, ((high_ctx - current_price) / current_price) * 100))
        return round(risk, 1), round(upside, 1)

    sma200 = data_ctx['Close'].rolling(200).mean().iloc[-1]
    if np.isnan(sma200):
        sma200 = (high_ctx + low_ctx) / 2

    delta = data_ctx['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    rsi_val = rsi.iloc[-1] if not np.isnan(rsi.iloc[-1]) else 50

    dist_to_sma = ((current_price - sma200) / sma200) * 100

    risk_base = 0.0
    if position_pct > 50:
        risk_base += (position_pct - 50) * 0.9
    if dist_to_sma > 5:
        risk_base += min(25, (dist_to_sma - 5) * 1.2)
    if rsi_val > 65:
        risk_base += (rsi_val - 65) * 1.2

    upside_base = 0.0
    if position_pct < 50:
        upside_base += (50 - position_pct) * 1.4
    if dist_to_sma < -5:
        upside_base += min(35, abs(dist_to_sma + 5) * 1.8)
    if rsi_val < 35:
        upside_base += (35 - rsi_val) * 1.8

    if fundamental_score is not None:
        fund_factor = 0.75 + (fundamental_score / 100) * 0.5
        risk_base = risk_base / fund_factor
        upside_base = upside_base * fund_factor

    if crash_risk_score is not None:
        crash_mult = 0.80 + (crash_risk_score / 100) * 0.50
        risk_base = risk_base * crash_mult
        upside_base = upside_base * (1.20 - (crash_risk_score / 100) * 0.40)

    momentum_upside = 0.0
    if "WZROSTOWY" in trend:
        if high_ctx > 0 and current_price < high_ctx:
            pct_to_high = ((high_ctx - current_price) / current_price) * 100
        else:
            pct_to_high = 0.0
        if "SILNIE" in trend:
            momentum_upside = max(5.0, pct_to_high * 0.4)
        else:
            momentum_upside = max(2.0, pct_to_high * 0.2)
    upside_base += momentum_upside

    risk = 5.0 + (risk_base / 150) * 55
    upside = 5.0 + (upside_base / 80) * 120

    risk = max(5.0, min(60.0, risk))
    upside = max(5.0, min(80.0, upside))

    if position_pct > 70:
        upside = min(upside, 45.0)
    elif position_pct > 50:
        upside = min(upside, 60.0)

    if position_pct < 30:
        risk = min(risk, 20.0)
    elif position_pct < 50:
        risk = min(risk, 35.0)

    if "WZROSTOWY" in trend:
        upside += 10.0 if "SILNIE" in trend else 5.0
    elif "SPADKOWY" in trend:
        risk += 10.0 if "SILNIE" in trend else 5.0

    risk = max(5.0, min(60.0, risk))
    upside = max(5.0, min(80.0, upside))

    if is_index:
        risk = max(5.0, risk * 0.7)
        upside = max(5.0, upside * 0.7)

    return round(risk, 1), round(upside, 1)

def get_volume_spike_multipliers(data_3y, data_10y=None):
    if data_10y is not None and not data_10y.empty and len(data_10y) >= 200:
        data = data_10y
    else:
        data = data_3y
    if data is None or len(data) < 50:
        return 1.20, 1.0

    window = min(30, len(data) - 1)
    if window < 10:
        return 1.20, 1.0

    avg_volume = data['Volume'].iloc[-window-1:-1].mean()
    if avg_volume == 0:
        return 1.20, 1.0

    last_volume = data['Volume'].iloc[-1]
    ratio = last_volume / avg_volume
    if ratio < 1.5:
        return 1.20, 1.0

    if len(data) < 6:
        return 1.20, 1.0
    price_change = (data['Close'].iloc[-1] - data['Close'].iloc[-5]) / data['Close'].iloc[-5]

    if len(data) > 200:
        sma50 = data['Close'].rolling(50).mean().iloc[-1]
        sma200 = data['Close'].rolling(200).mean().iloc[-1]
        trend_up = sma50 > sma200
    else:
        trend_up = price_change > 0

    boost = 1.0 + min(0.15, (ratio - 1.5) / 10.0 * 0.15)

    if price_change > 0.02 or (trend_up and price_change > -0.02):
        return boost, 1.0
    elif price_change < -0.02 or (not trend_up and price_change < 0.02):
        return 1.0, boost
    else:
        return 1.0, 1.0

def get_3year_perspective(ticker, fundamental_score=None):
    try:
        data_3y = get_historical_prices(ticker, days=3*365)
        if data_3y.empty:
            return None

        data_10y = pd.DataFrame()
        has_10y = False
        try:
            data_10y = get_historical_prices(ticker, days=10*365)
            if not data_10y.empty and len(data_10y) >= 200:
                has_10y = True
        except Exception as e:
            print(f"Ostrzeżenie 10y {ticker}: {e}")

        current_price = data_3y['Close'].iloc[-1]
        high_3y = data_3y['High'].max()
        low_3y = data_3y['Low'].min()
        range_3y = high_3y - low_3y
        position_in_3y_range = ((current_price - low_3y) / range_3y) * 100 if range_3y > 0 else 50

        is_index = ticker.startswith('^') or ticker in ['^GSPC', '^N225', '^NDX', '^DJI', '^FCHI', '^FTSE', '^GDAXI', '^STOXX50E']

        sma200 = data_3y['Close'].rolling(200).mean().iloc[-1]
        trend_3y = "NIEZNANY"
        if not np.isnan(sma200):
            if current_price > sma200 * 1.08:
                trend_3y = "SILNIE WZROSTOWY"
            elif current_price > sma200 * 1.03:
                trend_3y = "WZROSTOWY"
            elif current_price < sma200 * 0.92:
                trend_3y = "SILNIE SPADKOWY"
            elif current_price < sma200 * 0.97:
                trend_3y = "SPADKOWY"
            else:
                trend_3y = "BOCZNY"

        crash_risk_score = 50
        crash_details = {}
        if has_10y:
            try:
                high_10y = data_10y['High'].max()
                low_10y = data_10y['Low'].min()
                range_10y = high_10y - low_10y
                position_in_10y = ((current_price - low_10y) / range_10y) * 100 if range_10y > 0 else 50
                sma200_10y = data_10y['Close'].rolling(200).mean().iloc[-1]
                dist_sma200 = ((current_price - sma200_10y) / sma200_10y) * 100 if not np.isnan(sma200_10y) else 0
                returns_10y = data_10y['Close'].pct_change().dropna()
                vol_10y = returns_10y.std() * np.sqrt(252) * 100
                roll_max = data_10y['Close'].cummax()
                drawdown = (data_10y['Close'] - roll_max) / roll_max * 100
                max_dd_10y = drawdown.min()
                pos_score = max(0, (position_in_10y - 40) / 60 * 100)
                sma_score = max(0, min(100, (dist_sma200 - 10) * 3.0))
                vol_score = min(100, (vol_10y / 80) * 100)
                dd_score = min(100, (abs(max_dd_10y) / 70) * 100)
                crash_risk_score = int(pos_score * 0.30 + sma_score * 0.25 + vol_score * 0.10 + dd_score * 0.08)
                crash_risk_score = max(0, min(100, crash_risk_score))
                crash_details = {
                    'high_10y': high_10y, 'low_10y': low_10y,
                    'position_in_10y': round(position_in_10y, 1),
                    'dist_from_sma200_pct': round(dist_sma200, 1),
                    'annual_volatility_pct': round(vol_10y, 1),
                    'max_drawdown_10y_pct': round(max_dd_10y, 1),
                    'crash_risk_score': crash_risk_score,
                }
            except Exception as e:
                print(f"Błąd w crash-checker dla {ticker}: {e}")
                crash_details = {
                    'high_10y': high_3y, 'low_10y': low_3y,
                    'position_in_10y': round(position_in_3y_range, 1),
                    'dist_from_sma200_pct': 0.0, 'annual_volatility_pct': 0.0,
                    'max_drawdown_10y_pct': 0.0, 'crash_risk_score': 50,
                }
                crash_risk_score = 50
        else:
            crash_details = {
                'high_10y': high_3y, 'low_10y': low_3y,
                'position_in_10y': round(position_in_3y_range, 1),
                'dist_from_sma200_pct': 0.0, 'annual_volatility_pct': 0.0,
                'max_drawdown_10y_pct': 0.0, 'crash_risk_score': 50,
            }
            crash_risk_score = 50

        # Dynamiczne progi – oblicz percentyle z 3-letnich danych
        price_percentiles = np.percentile(data_3y['Close'], [10, 25, 75, 90])
        low_10 = price_percentiles[0]
        low_25 = price_percentiles[1]
        high_75 = price_percentiles[2]
        high_90 = price_percentiles[3]
        
        # Oblicz zmienność (odchylenie standardowe dziennych zwrotów)
        daily_returns = data_3y['Close'].pct_change().dropna()
        volatility = daily_returns.std() * np.sqrt(252) * 100  # roczna zmienność w %
        
        # Dynamiczne progi dla okazji/zagrożenia
        if volatility > 40:  # wysoka zmienność
            okazja_prog = 20
            zagrozenie_prog = 80
        elif volatility > 25:
            okazja_prog = 25
            zagrozenie_prog = 75
        else:
            okazja_prog = 30
            zagrozenie_prog = 70
        
        duza_okazja = "NIE"
        duze_zagrozenie = "NIE"
        
        # Sprawdź czy cena jest w dolnym percentylu (okazja)
        if current_price <= low_25 or pos_check < okazja_prog:
            duza_okazja = "TAK"
        # Sprawdź czy cena jest w górnym percentylu (zagrożenie)
        if current_price >= high_75 or pos_check > zagrozenie_prog:
            duze_zagrozenie = "TAK"

        upside_mult, downside_mult = get_volume_spike_multipliers(data_3y, data_10y if has_10y else None)
        
        risk_pct, upside_pct = get_risk_and_potential(
            current_price, low_3y, high_3y, data_3y,
            fundamental_score=fundamental_score,
            is_index=is_index,
            trend=trend_3y,
            data_10y=data_10y if has_10y else None,
            crash_risk_score=crash_risk_score,
        )
        
        risk_pct = round(min(60.0, risk_pct * downside_mult), 1)
        upside_pct = round(min(80.0, upside_pct * upside_mult), 1)

        return {
            'ticker': ticker,
            'current_price': current_price,
            'high_3y': high_3y,
            'low_3y': low_3y,
            'position_in_range': round(position_in_3y_range, 1),
            'trend_3y': trend_3y,
            'duza_okazja': duza_okazja,
            'duze_zagrozenie': duze_zagrozenie,
            'risk_of_drop_pct': risk_pct,
            'upside_potential_pct': upside_pct,
            'crash_risk_score': crash_risk_score,
            'crash_details': crash_details,
        }
    except Exception as e:
        print(f"Błąd analizy 3-letniej dla {ticker}: {e}")
        return None

# ============================================================
# PERSPEKTYWA 3-LETNIA - PEŁNA
# ============================================================

def get_risk_and_potential(current_price, low_3y, high_3y, data_3y,
                           fundamental_score=None, is_index=False, trend="",
                           data_10y=None, crash_risk_score=None):
    
    if data_10y is not None and not data_10y.empty and len(data_10y) >= 200:
        low_ctx = data_10y['Low'].min()
        high_ctx = data_10y['High'].max()
        data_ctx = data_10y
        range_ctx = high_ctx - low_ctx
        position_pct = ((current_price - low_ctx) / range_ctx) * 100 if range_ctx > 0 else 50
    else:
        low_ctx = low_3y
        high_ctx = high_3y
        data_ctx = data_3y
        range_ctx = high_ctx - low_ctx
        position_pct = ((current_price - low_ctx) / range_ctx) * 100 if range_ctx > 0 else 50

    if data_ctx.empty or len(data_ctx) < 50:
        risk = min(60, max(5, position_pct * 0.40))
        upside = min(80, max(5, ((high_ctx - current_price) / current_price) * 100))
        return round(risk, 1), round(upside, 1)

    sma200 = data_ctx['Close'].rolling(200).mean().iloc[-1]
    if np.isnan(sma200):
        sma200 = (high_ctx + low_ctx) / 2

    delta = data_ctx['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    rsi_val = rsi.iloc[-1] if not np.isnan(rsi.iloc[-1]) else 50

    dist_to_sma = ((current_price - sma200) / sma200) * 100

    risk_base = 0.0
    if position_pct > 50:
        risk_base += (position_pct - 50) * 0.9
    if dist_to_sma > 5:
        risk_base += min(25, (dist_to_sma - 5) * 1.2)
    if rsi_val > 65:
        risk_base += (rsi_val - 65) * 1.2

    upside_base = 0.0
    if position_pct < 50:
        upside_base += (50 - position_pct) * 1.4
    if dist_to_sma < -5:
        upside_base += min(35, abs(dist_to_sma + 5) * 1.8)
    if rsi_val < 35:
        upside_base += (35 - rsi_val) * 1.8

    if fundamental_score is not None:
        fund_factor = 0.75 + (fundamental_score / 100) * 0.5
        risk_base = risk_base / fund_factor
        upside_base = upside_base * fund_factor

    if crash_risk_score is not None:
        crash_mult = 0.80 + (crash_risk_score / 100) * 0.50
        risk_base = risk_base * crash_mult
        upside_base = upside_base * (1.20 - (crash_risk_score / 100) * 0.40)

    momentum_upside = 0.0
    if "WZROSTOWY" in trend:
        if high_ctx > 0 and current_price < high_ctx:
            pct_to_high = ((high_ctx - current_price) / current_price) * 100
        else:
            pct_to_high = 0.0
        if "SILNIE" in trend:
            momentum_upside = max(5.0, pct_to_high * 0.4)
        else:
            momentum_upside = max(2.0, pct_to_high * 0.2)
    upside_base += momentum_upside

    risk = 5.0 + (risk_base / 150) * 55
    upside = 5.0 + (upside_base / 80) * 120

    risk = max(5.0, min(60.0, risk))
    upside = max(5.0, min(80.0, upside))

    if position_pct > 70:
        upside = min(upside, 45.0)
    elif position_pct > 50:
        upside = min(upside, 60.0)

    if position_pct < 30:
        risk = min(risk, 20.0)
    elif position_pct < 50:
        risk = min(risk, 35.0)

    if "WZROSTOWY" in trend:
        upside += 10.0 if "SILNIE" in trend else 5.0
    elif "SPADKOWY" in trend:
        risk += 10.0 if "SILNIE" in trend else 5.0

    risk = max(5.0, min(60.0, risk))
    upside = max(5.0, min(80.0, upside))

    if is_index:
        risk = max(5.0, risk * 0.7)
        upside = max(5.0, upside * 0.7)

    return round(risk, 1), round(upside, 1)

def get_volume_spike_multipliers(data_3y, data_10y=None):
    if data_10y is not None and not data_10y.empty and len(data_10y) >= 200:
        data = data_10y
    else:
        data = data_3y
    if data is None or len(data) < 50:
        return 1.20, 1.0

    window = min(30, len(data) - 1)
    if window < 10:
        return 1.20, 1.0

    avg_volume = data['Volume'].iloc[-window-1:-1].mean()
    if avg_volume == 0:
        return 1.20, 1.0

    last_volume = data['Volume'].iloc[-1]
    ratio = last_volume / avg_volume
    if ratio < 1.5:
        return 1.20, 1.0

    if len(data) < 6:
        return 1.20, 1.0
    price_change = (data['Close'].iloc[-1] - data['Close'].iloc[-5]) / data['Close'].iloc[-5]

    if len(data) > 200:
        sma50 = data['Close'].rolling(50).mean().iloc[-1]
        sma200 = data['Close'].rolling(200).mean().iloc[-1]
        trend_up = sma50 > sma200
    else:
        trend_up = price_change > 0

    boost = 1.0 + min(0.15, (ratio - 1.5) / 10.0 * 0.15)

    if price_change > 0.02 or (trend_up and price_change > -0.02):
        return boost, 1.0
    elif price_change < -0.02 or (not trend_up and price_change < 0.02):
        return 1.0, boost
    else:
        return 1.0, 1.0

def get_3year_perspective(ticker, fundamental_score=None):
    try:
        data_3y = get_historical_prices(ticker, days=3*365)
        if data_3y.empty:
            return None

        data_10y = pd.DataFrame()
        has_10y = False
        try:
            data_10y = get_historical_prices(ticker, days=10*365)
            if not data_10y.empty and len(data_10y) >= 200:
                has_10y = True
        except Exception as e:
            print(f"Ostrzeżenie 10y {ticker}: {e}")

        current_price = data_3y['Close'].iloc[-1]
        high_3y = data_3y['High'].max()
        low_3y = data_3y['Low'].min()
        range_3y = high_3y - low_3y
        position_in_3y_range = ((current_price - low_3y) / range_3y) * 100 if range_3y > 0 else 50

        is_index = ticker.startswith('^') or ticker in ['^GSPC', '^N225', '^NDX', '^DJI', '^FCHI', '^FTSE', '^GDAXI', '^STOXX50E']

        sma200 = data_3y['Close'].rolling(200).mean().iloc[-1]
        trend_3y = "NIEZNANY"
        if not np.isnan(sma200):
            if current_price > sma200 * 1.08:
                trend_3y = "SILNIE WZROSTOWY"
            elif current_price > sma200 * 1.03:
                trend_3y = "WZROSTOWY"
            elif current_price < sma200 * 0.92:
                trend_3y = "SILNIE SPADKOWY"
            elif current_price < sma200 * 0.97:
                trend_3y = "SPADKOWY"
            else:
                trend_3y = "BOCZNY"

        crash_risk_score = 50
        crash_details = {}
        if has_10y:
            try:
                high_10y = data_10y['High'].max()
                low_10y = data_10y['Low'].min()
                range_10y = high_10y - low_10y
                position_in_10y = ((current_price - low_10y) / range_10y) * 100 if range_10y > 0 else 50
                sma200_10y = data_10y['Close'].rolling(200).mean().iloc[-1]
                dist_sma200 = ((current_price - sma200_10y) / sma200_10y) * 100 if not np.isnan(sma200_10y) else 0
                returns_10y = data_10y['Close'].pct_change().dropna()
                vol_10y = returns_10y.std() * np.sqrt(252) * 100
                roll_max = data_10y['Close'].cummax()
                drawdown = (data_10y['Close'] - roll_max) / roll_max * 100
                max_dd_10y = drawdown.min()
                pos_score = max(0, (position_in_10y - 40) / 60 * 100)
                sma_score = max(0, min(100, (dist_sma200 - 10) * 3.0))
                vol_score = min(100, (vol_10y / 80) * 100)
                dd_score = min(100, (abs(max_dd_10y) / 70) * 100)
                                # Oblicz trend (nachylenie SMA200)
                sma200_values = data_10y['Close'].rolling(200).mean().dropna()
                if len(sma200_values) > 50:
                    trend_slope = (sma200_values.iloc[-1] - sma200_values.iloc[-50]) / sma200_values.iloc[-50] * 100
                else:
                    trend_slope = 0
                # Jeśli trend jest wzrostowy, zmniejsz ryzyko, jeśli spadkowy – zwiększ
                trend_factor = max(0, min(20, -trend_slope * 2))  # -10% trendu daje +20 do score
                
                # Nowe wagi: większy nacisk na zmienność i drawdown
                crash_risk_score = int(
                    pos_score * 0.25 +      # pozycja w zakresie
                    sma_score * 0.20 +      # odchylenie od SMA200
                    vol_score * 0.20 +      # zmienność
                    dd_score * 0.20 +       # max drawdown
                    trend_factor * 0.15     # trend
                )
                crash_risk_score = max(0, min(100, crash_risk_score))                
                crash_details = {
                    'high_10y': high_10y, 'low_10y': low_10y,
                    'position_in_10y': round(position_in_10y, 1),
                    'dist_from_sma200_pct': round(dist_sma200, 1),
                    'annual_volatility_pct': round(vol_10y, 1),
                    'max_drawdown_10y_pct': round(max_dd_10y, 1),
                    'crash_risk_score': crash_risk_score,
                }
            except Exception as e:
                print(f"Błąd w crash-checker dla {ticker}: {e}")
                crash_details = {
                    'high_10y': high_3y, 'low_10y': low_3y,
                    'position_in_10y': round(position_in_3y_range, 1),
                    'dist_from_sma200_pct': 0.0, 'annual_volatility_pct': 0.0,
                    'max_drawdown_10y_pct': 0.0, 'crash_risk_score': 50,
                }
                crash_risk_score = 50
        else:
            crash_details = {
                'high_10y': high_3y, 'low_10y': low_3y,
                'position_in_10y': round(position_in_3y_range, 1),
                'dist_from_sma200_pct': 0.0, 'annual_volatility_pct': 0.0,
                'max_drawdown_10y_pct': 0.0, 'crash_risk_score': 50,
            }
            crash_risk_score = 50

        duza_okazja = "NIE"
        duze_zagrozenie = "NIE"
        pos_check = crash_details['position_in_10y'] if has_10y else position_in_3y_range
        dist_check = crash_details['dist_from_sma200_pct']
        if dist_check < -15 or pos_check < 25:
            duza_okazja = "TAK"
        if dist_check > 25 or pos_check > 75:
            duze_zagrozenie = "TAK"

        upside_mult, downside_mult = get_volume_spike_multipliers(data_3y, data_10y if has_10y else None)
        
        risk_pct, upside_pct = get_risk_and_potential(
            current_price, low_3y, high_3y, data_3y,
            fundamental_score=fundamental_score,
            is_index=is_index,
            trend=trend_3y,
            data_10y=data_10y if has_10y else None,
            crash_risk_score=crash_risk_score,
        )
        
        risk_pct = round(min(60.0, risk_pct * downside_mult), 1)
        upside_pct = round(min(80.0, upside_pct * upside_mult), 1)

        return {
            'ticker': ticker,
            'current_price': current_price,
            'high_3y': high_3y,
            'low_3y': low_3y,
            'position_in_range': round(position_in_3y_range, 1),
            'trend_3y': trend_3y,
            'duza_okazja': duza_okazja,
            'duze_zagrozenie': duze_zagrozenie,
            'risk_of_drop_pct': risk_pct,
            'upside_potential_pct': upside_pct,
            'crash_risk_score': crash_risk_score,
            'crash_details': crash_details,
        }
    except Exception as e:
        print(f"Błąd analizy 3-letniej dla {ticker}: {e}")
        return None

# ============================================================
# FUNKCJE PROGNOZOWANIA
# ============================================================

# ============================================================
# PROGNOZY 1M / 3M – ENSEMBLE + REGIME + FUNDAMENTY
# ============================================================

sector_tech_weight = {
    'Technology': 0.60,
    'Communication Services': 0.56,
    'Consumer Cyclical': 0.54,
    'Financial Services': 0.50,
    'Healthcare': 0.42,
    'Consumer Defensive': 0.40,
    'Energy': 0.55,
    'Automotive': 0.55,
    'Index': 0.48,
    'Default': 0.50,
}

REGIME_MODEL_PRIORS = {
    'TREND_UP':   {'ridge': 0.28, 'gb': 0.32, 'heuristic': 0.40},
    'TREND_DOWN': {'ridge': 0.28, 'gb': 0.32, 'heuristic': 0.40},
    'RANGE':      {'ridge': 0.35, 'gb': 0.25, 'heuristic': 0.40},
    'HIGH_VOL':   {'ridge': 0.40, 'gb': 0.20, 'heuristic': 0.40},
}


def get_max_historical_change(df, horizon_days, percentile=90):
    if df is None or len(df) < horizon_days + 5:
        return 15.0
    changes = df['Close'].pct_change(periods=horizon_days).dropna()
    if changes.empty:
        return 15.0
    abs_changes = changes.abs()
    cap = np.percentile(abs_changes, percentile)
    if np.isnan(cap) or cap == 0:
        return 15.0
    return float(cap * 100)


def _detect_market_regime(df):
    if df is None or len(df) < 50:
        return 'RANGE'
    close = df['Close']
    current = float(close.iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(df) >= 50 else current
    sma200 = float(close.rolling(200).mean().iloc[-1]) if len(df) >= 200 else sma50
    adx = float(df['ADX'].iloc[-1]) if 'ADX' in df.columns and not pd.isna(df['ADX'].iloc[-1]) else 20.0
    atr = float(df['ATR'].iloc[-1]) if 'ATR' in df.columns and not pd.isna(df['ATR'].iloc[-1]) else 0.0
    atr_pct = (atr / current * 100) if current > 0 else 0.0
    returns = close.pct_change().dropna()
    vol_ann = float(returns.tail(60).std() * np.sqrt(252) * 100) if len(returns) >= 20 else 20.0
    if atr_pct > 4.5 or vol_ann > 45:
        return 'HIGH_VOL'
    if adx >= 25:
        if current > sma50 and sma50 >= sma200 * 0.98:
            return 'TREND_UP'
        if current < sma50 and sma50 <= sma200 * 1.02:
            return 'TREND_DOWN'
    if abs(current / sma50 - 1) < 0.04 and adx < 22:
        return 'RANGE'
    if current > sma50:
        return 'TREND_UP'
    if current < sma50:
        return 'TREND_DOWN'
    return 'RANGE'


def _extract_features_row(df, i):
    row = df.iloc[i]
    close = float(row['Close'])
    if close <= 0:
        return None

    def _safe(col, default=0.0):
        if col not in df.columns:
            return default
        v = row[col]
        if pd.isna(v):
            return default
        return float(v)

    rsi = _safe('RSI', 50.0)
    macd = _safe('MACD', 0.0)
    macd_sig = _safe('MACD_Signal', 0.0)
    atr = _safe('ATR', 0.0)
    adx = _safe('ADX', 20.0)
    bb_u = _safe('BB_Upper', close)
    bb_l = _safe('BB_Lower', close)
    stoch_k = _safe('Stochastic_K', 50.0) if 'Stochastic_K' in df.columns else _safe('Stoch_K', 50.0)
    cci = _safe('CCI', 0.0)
    willr = _safe('Williams_R', -50.0) if 'Williams_R' in df.columns else _safe('Williams %R', -50.0)
    vol = _safe('Volume', 0.0)

    window = df['Close'].iloc[max(0, i - 199):i + 1]
    sma20 = float(window.tail(20).mean()) if len(window) >= 10 else close
    sma50 = float(window.tail(50).mean()) if len(window) >= 20 else close
    sma200 = float(window.mean()) if len(window) >= 50 else close

    def _ret(n):
        if i >= n:
            p0 = float(df['Close'].iloc[i - n])
            if p0 > 0:
                return (close / p0 - 1.0) * 100.0
        return 0.0

    ret5, ret10, ret20, ret60 = _ret(5), _ret(10), _ret(20), _ret(60)
    avg_vol20 = float(df['Volume'].iloc[max(0, i - 19):i + 1].mean()) if 'Volume' in df.columns else 1.0
    vol_ratio = min(vol / avg_vol20, 5.0) if avg_vol20 > 0 else 1.0
    bb_width = (bb_u - bb_l) / close * 100 if close > 0 else 0.0
    pct_b = (close - bb_l) / (bb_u - bb_l) if (bb_u - bb_l) > 0 else 0.5

    if i >= 20:
        prev_slice = df['Close'].iloc[max(0, i - 69):i - 19]
        sma50_prev = float(prev_slice.tail(50).mean()) if len(prev_slice) >= 10 else sma50
        sma_slope = (sma50 / sma50_prev - 1.0) * 100 if sma50_prev > 0 else 0.0
    else:
        sma_slope = 0.0

    signs = [np.sign(ret5), np.sign(ret10), np.sign(ret20)]
    mom_agree = 1.0 if (signs[0] == signs[1] == signs[2] and signs[0] != 0) else 0.0

    return {
        'rsi': rsi, 'macd_hist': macd - macd_sig,
        'atr_pct': atr / close * 100 if close > 0 else 0.0, 'adx': adx,
        'dist_sma20': (close / sma20 - 1) * 100 if sma20 > 0 else 0.0,
        'dist_sma50': (close / sma50 - 1) * 100 if sma50 > 0 else 0.0,
        'dist_sma200': (close / sma200 - 1) * 100 if sma200 > 0 else 0.0,
        'ret5': ret5, 'ret10': ret10, 'ret20': ret20, 'ret60': ret60,
        'vol_ratio': vol_ratio, 'bb_width': bb_width, 'pct_b': pct_b,
        'stoch_k': stoch_k, 'cci': max(-200.0, min(200.0, cci)),
        'willr': willr, 'sma_slope': sma_slope, 'mom_agree': mom_agree,
        'close': close,
    }


FEATURE_KEYS = [
    'rsi', 'macd_hist', 'atr_pct', 'adx',
    'dist_sma20', 'dist_sma50', 'dist_sma200',
    'ret5', 'ret10', 'ret20', 'ret60',
    'vol_ratio', 'bb_width', 'pct_b',
    'stoch_k', 'cci', 'willr', 'sma_slope', 'mom_agree',
]


def _build_training_set(df, horizon_days, max_samples=200):
    n = len(df)
    if n < horizon_days + 40:
        return None, None
    start = max(40, n - horizon_days - max_samples)
    X_list, y_list = [], []
    for i in range(start, n - horizon_days):
        feats = _extract_features_row(df, i)
        if feats is None:
            continue
        future = float(df['Close'].iloc[i + horizon_days])
        if future <= 0 or feats['close'] <= 0:
            continue
        fwd_ret = (future / feats['close'] - 1.0) * 100.0
        X_list.append([feats[k] for k in FEATURE_KEYS])
        y_list.append(fwd_ret)
    if len(X_list) < 30:
        return None, None
    return np.array(X_list, dtype=float), np.array(y_list, dtype=float)


def _heuristic_momentum_return(feats, regime, days_forward):
    scale = days_forward / 21.0
    mom = 0.25 * feats['ret5'] + 0.35 * feats['ret10'] + 0.25 * feats['ret20'] + 0.15 * feats.get('ret60', 0.0)
    if feats.get('mom_agree', 0) > 0:
        mom *= 1.12
    mr = 0.0
    if feats['rsi'] > 70:
        mr -= (feats['rsi'] - 70) * 0.18
    elif feats['rsi'] < 30:
        mr += (30 - feats['rsi']) * 0.18
    if feats['pct_b'] > 0.95:
        mr -= 1.8
    elif feats['pct_b'] < 0.05:
        mr += 1.8
    if feats.get('stoch_k', 50) > 80:
        mr -= 0.8
    elif feats.get('stoch_k', 50) < 20:
        mr += 0.8
    slope = feats.get('sma_slope', 0.0)
    if regime == 'TREND_UP':
        pred = mom * 0.50 * scale + mr * 0.12 * scale + slope * 0.15 * scale
        if feats['macd_hist'] > 0:
            pred += 0.5 * scale
    elif regime == 'TREND_DOWN':
        pred = mom * 0.50 * scale + mr * 0.12 * scale + slope * 0.15 * scale
        if feats['macd_hist'] < 0:
            pred -= 0.5 * scale
    elif regime == 'HIGH_VOL':
        pred = mom * 0.20 * scale + mr * 0.50 * scale
    else:
        pred = mom * 0.12 * scale + mr * 0.55 * scale
    if feats['adx'] > 30 and regime in ('TREND_UP', 'TREND_DOWN'):
        pred *= 1.12
    return float(np.clip(pred, -22, 22))


def _fundamental_expected_return_pct(fundamental_score, horizon, sector=None):
    if fundamental_score is None or (isinstance(fundamental_score, float) and np.isnan(fundamental_score)):
        fundamental_score = 50.0
    if horizon == '1M':
        base = (fundamental_score - 50.0) / 50.0 * 3.0
    else:
        base = (fundamental_score - 50.0) / 50.0 * 8.0
    if sector in {'Healthcare', 'Consumer Defensive', 'Utilities', 'Index'}:
        base *= 0.55
    if sector in {'Technology', 'Consumer Cyclical', 'Communication Services', 'Automotive'} and fundamental_score >= 70:
        base *= 1.12
    return float(np.clip(base, -9.0, 11.0))


def _historical_drift(df, days_forward):
    if df is None or len(df) < days_forward + 30:
        return 0.0
    chg = df['Close'].pct_change(periods=days_forward).dropna() * 100
    if chg.empty:
        return 0.0
    lo, hi = np.percentile(chg, 10), np.percentile(chg, 90)
    return float(chg.clip(lo, hi).median())


def _shrink_prediction(raw_pred, prior, strength=0.35):
    return (1.0 - strength) * raw_pred + strength * prior


def _calibrate_return_magnitude(pred_ret, df, days_forward, regime='RANGE'):
    """
    Kalibracja WIELKOŚCI prognozy bez zmiany kierunku (znak zostaje).

    Cel: obniżyć MAE, nie ruszając Hit%.
    - Znak = z modelu (kierunek).
    - |pred| zbliżamy do typowego historycznego ruchu w TYM samym kierunku
      (mediana |return| conditional + lekki blend z modelem).
    - Unikamy zarówno zbyt małych prognoz (główne źródło wysokiego MAE
      przy Hit 100%), jak i ekstremów.
    """
    try:
        if pred_ret is None or df is None or len(df) < days_forward + 40:
            return pred_ret
        pred_ret = float(pred_ret)
        if abs(pred_ret) < 1e-9:
            return pred_ret

        sign = 1.0 if pred_ret > 0 else -1.0
        pred_mag = abs(pred_ret)

        rets = (df['Close'].pct_change(periods=days_forward).dropna() * 100.0)
        if len(rets) < 20:
            return pred_ret

        # Typowa wielkość ruchu w tym samym kierunku
        same = rets[np.sign(rets.values) == sign]
        if len(same) >= 10:
            typical = float(np.median(np.abs(same.values)))
            p60 = float(np.percentile(np.abs(same.values), 60))
            p75 = float(np.percentile(np.abs(same.values), 75))
        else:
            abs_all = np.abs(rets.values)
            typical = float(np.median(abs_all))
            p60 = float(np.percentile(abs_all, 60))
            p75 = float(np.percentile(abs_all, 75))

        # Regime: w RANGE trzymaj bliżej mediany, w HIGH_VOL pozwól na więcej
        if regime == 'RANGE':
            target = 0.55 * typical + 0.45 * p60
            model_w = 0.40
        elif regime == 'HIGH_VOL':
            target = 0.40 * typical + 0.60 * p60
            model_w = 0.50
        else:  # TREND_UP / TREND_DOWN
            target = 0.45 * typical + 0.55 * p60
            model_w = 0.48

        # Gdy model mocno niedoszacowuje wielkości (częsty przypadek przy Hit 100% + MAE 30-50%)
        if pred_mag < 0.55 * target:
            model_w = min(model_w, 0.28)
        elif pred_mag > 1.35 * p75:
            # Model zbyt agresywny – ściągnij w dół
            model_w = min(model_w, 0.35)

        calibrated_mag = model_w * pred_mag + (1.0 - model_w) * target

        # Soft caps – nie wyjdź poza rozsądny percentyl historii
        hard_cap = max(p75 * 1.15, target * 1.25)
        if days_forward <= 30:
            hard_cap = min(hard_cap, 22.0)
        else:
            hard_cap = min(hard_cap, 40.0)
        calibrated_mag = float(np.clip(calibrated_mag, 0.0, hard_cap))

        # Minimalna wielkość gdy model ma wyraźny kierunek – żeby nie spłaszczyć sygnału
        if pred_mag >= 1.5:
            floor = min(pred_mag, max(1.2, 0.45 * typical))
            calibrated_mag = max(calibrated_mag, floor)

        return sign * calibrated_mag
    except Exception:
        return pred_ret


def _model_agreement_penalty(preds):
    vals = [preds.get('ridge'), preds.get('gb'), preds.get('heuristic')]
    vals = [v for v in vals if v is not None]
    if len(vals) < 2:
        return 1.0
    signs = [np.sign(v) if abs(v) >= 0.8 else 0 for v in vals]
    nonzero = [s for s in signs if s != 0]
    if len(nonzero) < 2:
        return 0.85
    if len(set(nonzero)) == 1:
        return 1.0
    return 0.60


def _calibrate_model_weights(X, y, horizon_days, regime):
    prior = REGIME_MODEL_PRIORS.get(regime, REGIME_MODEL_PRIORS['RANGE']).copy()
    if X is None or y is None or len(y) < 45:
        return prior
    split = int(len(y) * 0.8)
    if split < 30 or len(y) - split < 8:
        return prior
    X_tr, X_ho = X[:split], X[split:]
    y_tr, y_ho = y[:split], y[split:]
    errors = {}
    try:
        ridge = Ridge(alpha=1.2)
        ridge.fit(X_tr, y_tr)
        errors['ridge'] = float(np.mean(np.abs(ridge.predict(X_ho) - y_ho)))
    except Exception:
        errors['ridge'] = 999.0
    try:
        if len(X_tr) >= 40:
            gb = GradientBoostingRegressor(
                n_estimators=80, max_depth=3, learning_rate=0.06,
                min_samples_leaf=4, subsample=0.85, random_state=42
            )
            gb.fit(X_tr, y_tr)
            errors['gb'] = float(np.mean(np.abs(gb.predict(X_ho) - y_ho)))
        else:
            errors['gb'] = 999.0
    except Exception:
        errors['gb'] = 999.0
    try:
        scale = horizon_days / 21.0
        pred_h = X_ho[:, 9] * 0.35 * scale  # ret20
        errors['heuristic'] = float(np.mean(np.abs(pred_h - y_ho)))
    except Exception:
        errors['heuristic'] = 999.0
    inv = {k: 1.0 / max(v, 0.05) for k, v in errors.items()}
    total = sum(inv.values()) or 1.0
    data_w = {k: inv[k] / total for k in inv}
    keys = ['ridge', 'gb', 'heuristic']
    blended = {k: 0.60 * data_w.get(k, 0.33) + 0.40 * prior.get(k, 0.33) for k in keys}
    for k in blended:
        blended[k] = max(0.12, min(0.55, blended[k]))
    s = sum(blended.values())
    return {k: blended[k] / s for k in blended}


def _ensemble_expected_return(df, days_forward, sector, regime, feats):
    """Ensemble v2: Ridge + GradientBoosting + heurystyka + shrinkage + agreement."""
    X, y = _build_training_set(df, days_forward)
    weights = _calibrate_model_weights(X, y, days_forward, regime)
    preds = {}
    preds['heuristic'] = _heuristic_momentum_return(feats, regime, days_forward)
    x_now = np.array([[feats[k] for k in FEATURE_KEYS]], dtype=float)

    try:
        if X is not None and y is not None:
            ridge = Ridge(alpha=1.2)
            ridge.fit(X, y)
            preds['ridge'] = float(ridge.predict(x_now)[0])
        else:
            preds['ridge'] = preds['heuristic']
    except Exception:
        preds['ridge'] = preds['heuristic']

    try:
        if X is not None and y is not None and len(X) >= 40:
            gb = GradientBoostingRegressor(
                n_estimators=100, max_depth=3, learning_rate=0.05,
                min_samples_leaf=4, subsample=0.85, random_state=42
            )
            gb.fit(X, y)
            preds['gb'] = float(gb.predict(x_now)[0])
        else:
            preds['gb'] = preds['heuristic']
            weights['gb'] = 0.0
            s = weights['ridge'] + weights['heuristic']
            if s > 0:
                weights['ridge'] /= s
                weights['heuristic'] /= s
    except Exception:
        preds['gb'] = preds['heuristic']

    blended = (
        weights.get('ridge', 0.30) * preds['ridge']
        + weights.get('gb', 0.30) * preds['gb']
        + weights.get('heuristic', 0.40) * preds['heuristic']
    )
    blended *= _model_agreement_penalty(preds)
    prior = _historical_drift(df, days_forward)
    # Mniejszy shrink → mniej systematycznego niedoszacowania wielkości (MAE)
    shrink_s = 0.28 if days_forward <= 30 else 0.20
    if regime == 'HIGH_VOL':
        shrink_s += 0.08
    elif regime == 'RANGE':
        shrink_s += 0.04
    blended = _shrink_prediction(blended, prior, strength=shrink_s)
    if regime == 'HIGH_VOL':
        blended *= 0.88
    elif regime == 'RANGE':
        blended *= 0.93
    return float(blended), preds, weights



def get_fundamental_impact_by_horizon(fundamental_score, horizon, sector=None):
    ret = _fundamental_expected_return_pct(fundamental_score, horizon, sector)
    return 1.0 + ret / 100.0


def get_technical_score_with_sector(df, sector):
    if df is None or len(df) < 20:
        return 1.0
    regime = _detect_market_regime(df)
    feats = _extract_features_row(df, len(df) - 1)
    if feats is None:
        return 1.0
    h = _heuristic_momentum_return(feats, regime, 21)
    return float(np.clip(1.0 + h / 100.0, 0.85, 1.15))



def _local_direction_accuracy(df, days_forward, max_points=14, step=8):
    """
    Szybki test: jak często prosty momentum (ret20) + znak driftu
    zgadza się z realnym kierunkiem na tej spółce ostatnio.
    Zwraca hit 0–1 lub None.
    """
    try:
        if df is None or len(df) < days_forward + 80:
            return None
        n = len(df)
        end = n - days_forward - 1
        start = max(60, end - max_points * step)
        hits, total = 0, 0
        closes = df['Close'].values
        for i in range(start, end + 1, step):
            if i < 20:
                continue
            p0 = float(closes[i])
            p1 = float(closes[i + days_forward])
            if p0 <= 0:
                continue
            actual = p1 / p0 - 1.0
            # naiwna prognoza: ret20 + lekki drift
            p_past = float(closes[i - 20])
            if p_past <= 0:
                continue
            mom = p0 / p_past - 1.0
            # hist median proxy: średnia z kilku wcześniejszych okien
            pred = mom * 0.5
            if abs(actual) < 0.005 and abs(pred) < 0.01:
                hits += 1
            elif pred * actual > 0:
                hits += 1
            total += 1
        if total < 5:
            return None
        return hits / total
    except Exception:
        return None


def _vol_scale_for_ticker(df):
    """Wysoka zmienność → większa ostrożność kierunku."""
    try:
        rets = df['Close'].pct_change().dropna().tail(40)
        if len(rets) < 10:
            return 1.0
        vol = float(rets.std() * (252 ** 0.5))
        # typowe equity ~0.2–0.35; TSLA często >0.5
        if vol > 0.55:
            return 1.35
        if vol > 0.40:
            return 1.18
        if vol < 0.18:
            return 0.92
        return 1.0
    except Exception:
        return 1.0



def predict_with_technical_influence(df, fundamental_analysis, days_forward, sector, ticker=None, quiet=False):
    """Prognoza 1M/3M v2 klasyczna (bez wyjątków per ticker / bez mag-cal)."""
    def _log(*a, **k):
        if not quiet:
            print(*a, **k)
    _log(f"🔍 ENSEMBLE v2 | ticker={ticker} sektor={sector} | dni={days_forward}")
    if df is None or df.empty or len(df) < 5:
        return 0.0, "NEUTRALNY", 0.0
    df_clean = df.ffill().bfill()
    if 'Close' not in df_clean.columns or len(df_clean) < 15:
        current_p = float(df['Close'].iloc[-1]) if not df.empty else 0.0
        return current_p, "NEUTRALNY", 0.0
    current_price = float(df_clean['Close'].iloc[-1])
    if current_price <= 0:
        return 0.0, "NEUTRALNY", 0.0

    horizon = '1M' if days_forward <= 30 else '3M'
    regime = _detect_market_regime(df_clean)
    feats = _extract_features_row(df_clean, len(df_clean) - 1)
    if feats is None:
        return current_price, "NEUTRALNY", 0.0

    tech_ret, model_preds, model_weights = _ensemble_expected_return(
        df_clean, days_forward, sector, regime, feats
    )
    fa = fundamental_analysis or {}
    fund_score = fa.get('combined_score', 50)
    if fund_score is None or (isinstance(fund_score, float) and np.isnan(fund_score)):
        fund_score = 50
    fund_ret = _fundamental_expected_return_pct(fund_score, horizon, sector)

    base_tech = sector_tech_weight.get(sector, sector_tech_weight.get('Default', 0.50))
    if horizon == '1M':
        tech_w = min(0.72, base_tech + 0.10)
    else:
        tech_w = max(0.32, base_tech - 0.12)
    if regime == 'HIGH_VOL':
        tech_w *= 0.82
    if regime == 'RANGE':
        tech_w *= 0.88
    if abs(fund_score - 50) < 5:
        tech_w = min(0.85, tech_w + 0.08)

    blended_ret = tech_w * tech_ret + (1.0 - tech_w) * fund_ret
    if feats['vol_ratio'] > 1.8 and abs(blended_ret) > 1.0:
        blended_ret *= 1.06

    # --- Adaptacyjna kotwica kierunku (Hit% na trudnych spółkach jak TSLA/UNH) ---
    try:
        hist_med = _historical_drift(df_clean, days_forward)
    except Exception:
        hist_med = 0.0

    # --- Kotwica v2 (ta, która dawała AAPL ~61/61) ---
    drift_w = 0.22 if horizon == '1M' else 0.32
    blended_ret = (1.0 - drift_w) * blended_ret + drift_w * hist_med

    if regime == 'TREND_UP' and blended_ret < 0:
        blended_ret *= 0.45
        if hist_med > 0:
            blended_ret = 0.6 * blended_ret + 0.4 * max(hist_med * 0.5, 0.3)
    elif regime == 'TREND_DOWN' and blended_ret > 0:
        blended_ret *= 0.45
        if hist_med < 0:
            blended_ret = 0.6 * blended_ret + 0.4 * min(hist_med * 0.5, -0.3)

    if abs(blended_ret) < 1.2 and abs(hist_med) >= 0.8:
        blended_ret = 0.35 * blended_ret + 0.65 * np.sign(hist_med) * max(abs(hist_med), 1.0)

    _log(f"   regime={regime} | tech={tech_ret:+.2f}% fund={fund_ret:+.2f}% "
          f"tech_w={tech_w:.2f} drift_w={drift_w:.2f} "
          f"→ blend={blended_ret:+.2f}%")
    _log(f"   models: ridge={model_preds.get('ridge', 0):+.2f} "
          f"gb={model_preds.get('gb', 0):+.2f} heur={model_preds.get('heuristic', 0):+.2f} "
          f"| w={model_weights}")

    try:
        hist_cap = get_max_historical_change(df_clean, days_forward, percentile=88)
    except Exception:
        hist_cap = 15.0
    sector_cap_mult = {
        'Healthcare': 0.80, 'Consumer Defensive': 0.80,
        'Technology': 1.20, 'Communication Services': 1.12,
        'Energy': 1.15, 'Automotive': 1.12, 'Default': 1.0,
    }
    max_change = max(hist_cap * sector_cap_mult.get(sector, 1.0), 5.5)
    if regime == 'HIGH_VOL':
        max_change *= 1.10
    if regime == 'RANGE':
        max_change *= 0.80
    if horizon == '1M':
        max_change = min(max_change, 18.0)
    else:
        max_change = min(max_change, 35.0)

    change_percent = float(np.clip(blended_ret, -max_change, max_change))
    adjusted_pred = current_price * (1.0 + change_percent / 100.0)
    if change_percent > 2.5:
        direction = "WZROSTOWY"
    elif change_percent < -2.5:
        direction = "SPADKOWY"
    else:
        direction = "NEUTRALNY"
    _log(f"✅ PROGNOZA v2: {adjusted_pred:.2f} ({change_percent:+.2f}%) – {direction} | cap±{max_change:.1f}%")
    return float(adjusted_pred), direction, float(change_percent)



def backtest_forecast_quality(df, days_forward=21, sector='Default',
                              fund_score=50, step=None, max_points=30, ticker=None):
    """
    Walk-forward jakości prognoz 1M/3M – twardszy Hit% (mniej inflacji).

    Hit tylko gdy:
      1) |actual| >= min_move
      2) |pred|   >= min_pred   (prognoza nie jest „płaska”)
      3) ten sam znak actual i pred

    Bez soft_hit i bez fallbacku na łagodną definicję przy małej próbie.
    """
    if df is None or df.empty:
        return None

    min_len = days_forward + 60
    if len(df) < min_len:
        return None

    # Trochę ostrzejsze progi niż wcześniej (2.0 / 3.5)
    min_move = 2.5 if days_forward <= 30 else 4.0
    # Prognoza musi być „wyraźna” – inaczej nie liczymy hitu
    min_pred = 1.5 if days_forward <= 30 else 2.5

    df_clean = df.ffill().bfill()
    n = len(df_clean)
    end = n - days_forward - 1
    if end < 60:
        return None

    def _make_indices(step_val, max_pts):
        start_i = max(60, end - max_pts * step_val)
        return list(range(start_i, end + 1, step_val))

    if step is None:
        target_points = 12
        span = max(1, end - 60)
        auto_step = max(8, span // target_points)
        if days_forward <= 30:
            step = max(10, min(auto_step, max(10, days_forward // 2)))
        else:
            step = max(12, min(auto_step, max(15, days_forward // 3)))
    indices = _make_indices(step, max_points)

    if len(indices) < 6:
        step = max(8, step // 2)
        indices = _make_indices(step, max_points + 10)
    if len(indices) < 5:
        step = max(5, step // 2)
        indices = _make_indices(step, max_points + 20)
    if len(indices) < 4:
        return None

    errors = []
    dir_hits = 0
    significant = 0
    total = 0
    bias_sum = 0.0

    fa_neutral = {'combined_score': fund_score if fund_score is not None else 50}

    for i in indices:
        hist = df_clean.iloc[:i + 1].copy()
        if len(hist) < 50:
            continue
        try:
            _, _, pred_ret = predict_with_technical_influence(
                hist, fa_neutral, days_forward, sector, ticker=ticker, quiet=True
            )
            if pred_ret is None:
                continue

            p0 = float(df_clean['Close'].iloc[i])
            p1 = float(df_clean['Close'].iloc[i + days_forward])
            if p0 <= 0:
                continue
            actual_ret = (p1 / p0 - 1.0) * 100.0

            errors.append(abs(float(pred_ret) - actual_ret))
            bias_sum += float(pred_ret) - actual_ret
            total += 1

            # Twardy hit: istotny ruch RYNKU + istotna PROGNOZA + ten sam znak
            if abs(actual_ret) >= min_move and abs(pred_ret) >= min_pred:
                significant += 1
                if (pred_ret > 0 and actual_ret > 0) or (pred_ret < 0 and actual_ret < 0):
                    dir_hits += 1
        except Exception:
            continue

    min_total = 4 if days_forward > 30 else 5
    if total < min_total or not errors:
        return None

    # Brak soft-fallbacku: za mało istotnych prób → nie udawaj wysokiego Hit%
    if significant >= 5:
        dir_rate = 100.0 * dir_hits / significant
    elif significant >= 3:
        dir_rate = 100.0 * dir_hits / significant  # raportuj, ale UI i tak zobaczy n_sig
    else:
        return None  # za mało twardych przypadków → brak Hit% zamiast zawyżonego

    return {
        'hit_rate': round(float(dir_rate), 1),
        'soft_hit_rate': round(float(dir_rate), 1),  # świadomie = hard (bez soft)
        'dir_hit_rate': round(float(dir_rate), 1),
        'mae': round(float(np.mean(errors)), 2),
        'bias': round(bias_sum / total, 2),
        'n_samples': total,
        'n_significant': significant,
        'cover_rate': round(100.0 * significant / total, 1) if total else 0.0,
        'min_move': min_move,
    }
# ============================================================
# PERSPEKTYWA 3-LETNIA - PEŁNA
# ============================================================

def get_risk_and_potential(current_price, low_3y, high_3y, data_3y,
                           fundamental_score=None, is_index=False, trend="",
                           data_10y=None, crash_risk_score=None):
    
    if data_10y is not None and not data_10y.empty and len(data_10y) >= 200:
        low_ctx = data_10y['Low'].min()
        high_ctx = data_10y['High'].max()
        data_ctx = data_10y
        range_ctx = high_ctx - low_ctx
        position_pct = ((current_price - low_ctx) / range_ctx) * 100 if range_ctx > 0 else 50
    else:
        low_ctx = low_3y
        high_ctx = high_3y
        data_ctx = data_3y
        range_ctx = high_ctx - low_ctx
        position_pct = ((current_price - low_ctx) / range_ctx) * 100 if range_ctx > 0 else 50

    if data_ctx.empty or len(data_ctx) < 50:
        risk = min(60, max(5, position_pct * 0.40))
        upside = min(80, max(5, ((high_ctx - current_price) / current_price) * 100))
        return round(risk, 1), round(upside, 1)

    sma200 = data_ctx['Close'].rolling(200).mean().iloc[-1]
    if np.isnan(sma200):
        sma200 = (high_ctx + low_ctx) / 2

    delta = data_ctx['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    rsi_val = rsi.iloc[-1] if not np.isnan(rsi.iloc[-1]) else 50

    dist_to_sma = ((current_price - sma200) / sma200) * 100

    risk_base = 0.0
    if position_pct > 50:
        risk_base += (position_pct - 50) * 0.9
    if dist_to_sma > 5:
        risk_base += min(25, (dist_to_sma - 5) * 1.2)
    if rsi_val > 65:
        risk_base += (rsi_val - 65) * 1.2

    upside_base = 0.0
    if position_pct < 50:
        upside_base += (50 - position_pct) * 1.4
    if dist_to_sma < -5:
        upside_base += min(35, abs(dist_to_sma + 5) * 1.8)
    if rsi_val < 35:
        upside_base += (35 - rsi_val) * 1.8

    if fundamental_score is not None:
        fund_factor = 0.75 + (fundamental_score / 100) * 0.5
        risk_base = risk_base / fund_factor
        upside_base = upside_base * fund_factor

    if crash_risk_score is not None:
        crash_mult = 0.80 + (crash_risk_score / 100) * 0.50
        risk_base = risk_base * crash_mult
        upside_base = upside_base * (1.20 - (crash_risk_score / 100) * 0.40)

    momentum_upside = 0.0
    if "WZROSTOWY" in trend:
        if high_ctx > 0 and current_price < high_ctx:
            pct_to_high = ((high_ctx - current_price) / current_price) * 100
        else:
            pct_to_high = 0.0
        if "SILNIE" in trend:
            momentum_upside = max(5.0, pct_to_high * 0.4)
        else:
            momentum_upside = max(2.0, pct_to_high * 0.2)
    upside_base += momentum_upside

    risk = 5.0 + (risk_base / 150) * 55
    upside = 5.0 + (upside_base / 80) * 120

    risk = max(5.0, min(60.0, risk))
    upside = max(5.0, min(80.0, upside))

    if position_pct > 70:
        upside = min(upside, 45.0)
    elif position_pct > 50:
        upside = min(upside, 60.0)

    if position_pct < 30:
        risk = min(risk, 20.0)
    elif position_pct < 50:
        risk = min(risk, 35.0)

    if "WZROSTOWY" in trend:
        upside += 10.0 if "SILNIE" in trend else 5.0
    elif "SPADKOWY" in trend:
        risk += 10.0 if "SILNIE" in trend else 5.0

    risk = max(5.0, min(60.0, risk))
    upside = max(5.0, min(80.0, upside))

    if is_index:
        risk = max(5.0, risk * 0.7)
        upside = max(5.0, upside * 0.7)

    return round(risk, 1), round(upside, 1)

def get_volume_spike_multipliers(data_3y, data_10y=None):
    if data_10y is not None and not data_10y.empty and len(data_10y) >= 200:
        data = data_10y
    else:
        data = data_3y
    if data is None or len(data) < 50:
        return 1.20, 1.0

    window = min(30, len(data) - 1)
    if window < 10:
        return 1.20, 1.0

    avg_volume = data['Volume'].iloc[-window-1:-1].mean()
    if avg_volume == 0:
        return 1.20, 1.0

    last_volume = data['Volume'].iloc[-1]
    ratio = last_volume / avg_volume
    if ratio < 1.5:
        return 1.20, 1.0

    if len(data) < 6:
        return 1.20, 1.0
    price_change = (data['Close'].iloc[-1] - data['Close'].iloc[-5]) / data['Close'].iloc[-5]

    if len(data) > 200:
        sma50 = data['Close'].rolling(50).mean().iloc[-1]
        sma200 = data['Close'].rolling(200).mean().iloc[-1]
        trend_up = sma50 > sma200
    else:
        trend_up = price_change > 0

    boost = 1.0 + min(0.15, (ratio - 1.5) / 10.0 * 0.15)

    if price_change > 0.02 or (trend_up and price_change > -0.02):
        return boost, 1.0
    elif price_change < -0.02 or (not trend_up and price_change < 0.02):
        return 1.0, boost
    else:
        return 1.0, 1.0


def compute_risk_and_upside_3y(current_price, low_3y, high_3y, data_3y,
                               fundamental_score=None, is_index=False, trend="",
                               data_10y=None, crash_risk_score=None,
                               hist_dd_p50=None, hist_dd_p75=None, own_dd_p50=None):
    """
    Ryzyko + potencjał 3Y – kalibracja pod produkt:
    - ryzyko kotwiczone o historyczne DD (analogie + własna historia), nie tylko score
    - quality/trend obniża ekstremalne risk przy ATH (AAPL ≠ meme)
    - upside realistyczny, tłumiony blisko szczytu, ale nie zerowany
    """
    if data_10y is not None and not data_10y.empty and len(data_10y) >= 200:
        data_ctx = data_10y
        low_ctx = float(data_10y['Low'].min())
        high_ctx = float(data_10y['High'].max())
    else:
        data_ctx = data_3y
        low_ctx = float(low_3y)
        high_ctx = float(high_3y)
    range_ctx = high_ctx - low_ctx
    position_pct = ((current_price - low_ctx) / range_ctx) * 100 if range_ctx > 0 else 50.0

    if data_ctx is None or data_ctx.empty or len(data_ctx) < 50:
        risk = min(55.0, max(8.0, position_pct * 0.45))
        upside = max(12.0, ((high_ctx - current_price) / current_price) * 100 if current_price > 0 else 15)
        return round(risk, 1), round(min(90.0, upside), 1)

    close = data_ctx['Close']
    sma200 = close.rolling(200).mean().iloc[-1]
    if pd.isna(sma200):
        sma200 = (high_ctx + low_ctx) / 2.0
    dist_to_sma = ((current_price - float(sma200)) / float(sma200)) * 100 if sma200 else 0.0

    rets = close.pct_change().dropna()
    vol_ann = float(rets.std() * np.sqrt(252) * 100) if len(rets) > 20 else 25.0

    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi_s = 100 - (100 / (1 + rs))
    rsi_val = float(rsi_s.iloc[-1]) if not pd.isna(rsi_s.iloc[-1]) else 50.0

    # --- Kotwica ryzyka: historyczne DD ---
    # bierzemy |median/p75| z analogii i własnej historii
    dd_anchors = []
    if hist_dd_p50 is not None:
        dd_anchors.append(abs(float(hist_dd_p50)))
    if hist_dd_p75 is not None:
        dd_anchors.append(abs(float(hist_dd_p75)) * 0.85)
    if own_dd_p50 is not None:
        dd_anchors.append(abs(float(own_dd_p50)))
    # własny max DD z serii jako kontekst
    try:
        roll_max = close.cummax()
        max_dd_hist = float(((close - roll_max) / roll_max * 100).min())
        dd_anchors.append(abs(max_dd_hist) * 0.55)
    except Exception:
        max_dd_hist = -25.0

    if dd_anchors:
        risk_anchor = float(np.median(dd_anchors))
    else:
        risk_anchor = 22.0 + max(0.0, position_pct - 50) * 0.35

    # składowa pozycyjna (nie dominuje, tylko koryguje)
    pos_add = 0.0
    if position_pct > 70:
        pos_add += (position_pct - 70) * 0.35
    if position_pct > 90:
        pos_add += (position_pct - 90) * 0.8
    if dist_to_sma > 10:
        pos_add += min(8.0, (dist_to_sma - 10) * 0.35)
    if rsi_val > 70:
        pos_add += min(5.0, (rsi_val - 70) * 0.35)

    risk = risk_anchor * 0.70 + pos_add

    # jakość / trend: blue-chip w silnym trendzie ≠ max risk
    quality = 0.5
    if fundamental_score is not None:
        quality = float(np.clip(float(fundamental_score) / 100.0, 0.15, 0.95))
    trend_s = trend or ""
    if "SILNIE WZROSTOWY" in trend_s:
        risk *= 0.88
    elif "WZROSTOWY" in trend_s:
        risk *= 0.93
    elif "SILNIE SPADKOWY" in trend_s:
        risk *= 1.12
    # niska vol + wysoka jakość → mniej dramatycznego risk
    if vol_ann < 22 and quality > 0.55:
        risk *= 0.90
    elif vol_ann > 40:
        risk *= 1.08
    if quality > 0.65:
        risk *= 0.92
    elif quality < 0.35:
        risk *= 1.08

    if crash_risk_score is not None:
        # score lekko dokręca, nie dyktuje
        cs = float(crash_risk_score)
        risk *= (0.92 + cs / 100.0 * 0.18)

    # podłogi / sufity – realistyczne, nie zawsze 60
    if position_pct >= 92:
        risk = max(risk, 28.0 + (0 if quality > 0.6 else 5))
    elif position_pct >= 85:
        risk = max(risk, 24.0)
    elif position_pct >= 75:
        risk = max(risk, 20.0)
    if position_pct < 30:
        risk = min(risk, 18.0)
    elif position_pct < 50:
        risk = min(risk, 28.0)

    if is_index:
        risk *= 0.82

    risk = float(np.clip(risk, 8.0, 55.0))  # sufit 55 – zostawia bufor, mniej "wszystko na max"

    # --- UPSIDE ---
    hist_upside = 26.0
    try:
        if len(close) >= 800:
            fwd = (close.shift(-756) / close - 1.0).dropna() * 100
            if len(fwd) >= 30:
                # ostrożniej: bliżej mediany niż p75 (mniej rozczarowań)
                hist_upside = float(0.70 * np.percentile(fwd, 50) + 0.30 * np.percentile(fwd, 70))
                hist_upside = float(np.clip(hist_upside, 10.0, 100.0))
        elif len(close) >= 400:
            ann = float(rets.mean() * 252 * 100)
            hist_upside = float(np.clip(ann * 3 * 0.85, 10.0, 85.0))
    except Exception:
        hist_upside = 26.0

    room_to_high = max(0.0, (high_ctx - current_price) / current_price * 100) if current_price > 0 else 0.0
    mr_boost = 0.0
    if position_pct < 40:
        mr_boost += (40 - position_pct) * 0.7
    if dist_to_sma < -8:
        mr_boost += min(12.0, abs(dist_to_sma + 8) * 0.5)

    trend_boost = 0.0
    if "SILNIE WZROSTOWY" in trend_s:
        trend_boost = 8.0
    elif "WZROSTOWY" in trend_s:
        trend_boost = 5.0
    elif "SILNIE SPADKOWY" in trend_s:
        trend_boost = -6.0
    elif "SPADKOWY" in trend_s:
        trend_boost = -3.0

    fund_boost = 0.0
    if fundamental_score is not None:
        fund_boost = (float(fundamental_score) - 50.0) / 50.0 * 12.0

    damp = 1.0
    if position_pct > 92:
        damp = 0.58
    elif position_pct > 85:
        damp = 0.68
    elif position_pct > 75:
        damp = 0.80
    elif position_pct > 65:
        damp = 0.90

    upside = (hist_upside * 0.55 + room_to_high * 0.08 + mr_boost * 0.12 + trend_boost + fund_boost) * damp
    if vol_ann > 35:
        upside *= 1.05  # wyższa vol = szerszy zakres możliwe
    if is_index:
        upside = max(10.0, upside * 0.85)

    upside = float(np.clip(upside, 10.0, 95.0))

    # przy samym szczycie: upside nie powinien mocno przebijać ryzyka (uczciwy R/R)
    if position_pct >= 90 and upside > risk * 1.05:
        upside = risk * 1.05
    elif position_pct >= 80 and upside > risk * 1.25:
        upside = risk * 1.25

    return round(risk, 1), round(upside, 1)




# ============================================================
# HISTORYCZNE KRACHY / KOREKTY – PROFIL RYNKOWY (kalibracja)
# Wartości = typowy stan *przed* eventem + typowe skutki (indeks US).
# To NIE jest prognoza daty krachu – tylko mapa analogii.
# ============================================================

HISTORICAL_CRASH_EVENTS = [
    {
        'name': 'Dot-com 2000',
        'type': 'SYSTEMIC',
        'pre_position_pct': 92,
        'pre_dist_sma200': 28,
        'pre_vol_ann': 20,
        'max_dd_pct': -49,
        'dd_6m_p25': -18,
        'dd_6m_p50': -28,
        'dd_6m_p75': -40,
        'recovery_months': 30,
    },
    {
        'name': 'GFC 2008',
        'type': 'SYSTEMIC',
        'pre_position_pct': 88,
        'pre_dist_sma200': 18,
        'pre_vol_ann': 16,
        'max_dd_pct': -57,
        'dd_6m_p25': -22,
        'dd_6m_p50': -35,
        'dd_6m_p75': -48,
        'recovery_months': 48,
    },
    {
        'name': 'EU Debt 2011',
        'type': 'CORRECTION',
        'pre_position_pct': 75,
        'pre_dist_sma200': 8,
        'pre_vol_ann': 18,
        'max_dd_pct': -19,
        'dd_6m_p25': -8,
        'dd_6m_p50': -12,
        'dd_6m_p75': -17,
        'recovery_months': 6,
    },
    {
        'name': 'QT Scare 2018',
        'type': 'CORRECTION',
        'pre_position_pct': 85,
        'pre_dist_sma200': 12,
        'pre_vol_ann': 14,
        'max_dd_pct': -20,
        'dd_6m_p25': -9,
        'dd_6m_p50': -14,
        'dd_6m_p75': -19,
        'recovery_months': 4,
    },
    {
        'name': 'COVID 2020',
        'type': 'SYSTEMIC',
        'pre_position_pct': 90,
        'pre_dist_sma200': 15,
        'pre_vol_ann': 12,
        'max_dd_pct': -34,
        'dd_6m_p25': -15,
        'dd_6m_p50': -25,
        'dd_6m_p75': -33,
        'recovery_months': 5,
    },
    {
        'name': 'Bear 2022',
        'type': 'SYSTEMIC',
        'pre_position_pct': 95,
        'pre_dist_sma200': 22,
        'pre_vol_ann': 15,
        'max_dd_pct': -25,
        'dd_6m_p25': -12,
        'dd_6m_p50': -18,
        'dd_6m_p75': -24,
        'recovery_months': 14,
    },
]


def _crash_similarity(position_pct, dist_sma200, vol_ann, event):
    """Podobieństwo 0–100 obecnego stanu do profilu sprzed eventem."""
    # znormalizowane różnice
    d_pos = abs(position_pct - event['pre_position_pct']) / 50.0
    d_sma = abs(dist_sma200 - event['pre_dist_sma200']) / 30.0
    d_vol = abs(vol_ann - event['pre_vol_ann']) / 25.0
    dist = 0.45 * d_pos + 0.35 * d_sma + 0.20 * d_vol
    sim = max(0.0, 100.0 * (1.0 - min(dist, 1.5) / 1.5))
    return round(sim, 1)


def _analyze_crash_analogies(position_pct, dist_sma200, vol_ann):
    """
    Porównuje bieżący stan z biblioteką historycznych krachów/korekt.
    Zwraca najlepszą analogię + ważone historyczne DD.
    """
    scored = []
    for ev in HISTORICAL_CRASH_EVENTS:
        sim = _crash_similarity(position_pct, dist_sma200, vol_ann, ev)
        scored.append((sim, ev))
    scored.sort(key=lambda x: x[0], reverse=True)
    best_sim, best_ev = scored[0]

    # ważona mediana DD z top-3 analogii (waga = similarity)
    top = scored[:3]
    w_sum = sum(s for s, _ in top) or 1.0
    dd50 = sum(s * e['dd_6m_p50'] for s, e in top) / w_sum
    dd25 = sum(s * e['dd_6m_p25'] for s, e in top) / w_sum
    dd75 = sum(s * e['dd_6m_p75'] for s, e in top) / w_sum
    max_dd = sum(s * e['max_dd_pct'] for s, e in top) / w_sum

    # risk tier: pozycja + similarity (spójniej z crash score)
    if position_pct >= 90 or (position_pct >= 85 and best_sim >= 50):
        risk_tier = "WYSOKI"
    elif position_pct >= 75 or (position_pct >= 70 and best_sim >= 45):
        risk_tier = "PODWYŻSZONY"
    elif position_pct <= 30 and best_sim < 40:
        risk_tier = "NISKI"
    else:
        risk_tier = "UMIARKOWANY"

    return {
        'best_analogy': best_ev['name'],
        'best_analogy_type': best_ev['type'],
        'best_similarity': best_sim,
        'hist_dd_6m_p25': round(dd25, 1),
        'hist_dd_6m_p50': round(dd50, 1),
        'hist_dd_6m_p75': round(dd75, 1),
        'hist_max_dd': round(max_dd, 1),
        'hist_recovery_months': best_ev['recovery_months'],
        'risk_tier': risk_tier,
        'top_analogies': [
            {'name': e['name'], 'sim': s, 'type': e['type'], 'max_dd': e['max_dd_pct']}
            for s, e in scored[:3]
        ],
    }


def _own_history_conditional_dd(data, position_now, window_fwd=126, min_samples=8):
    """
    Z historii spółki: gdy pozycja w zakresie była podobna (±12 pp),
    jaki był późniejszy max drawdown w ~6 miesiącach.
    """
    if data is None or len(data) < window_fwd + 100:
        return None
    close = data['Close']
    roll_low = close.rolling(252, min_periods=60).min()
    roll_high = close.rolling(252, min_periods=60).max()
    rng = roll_high - roll_low
    pos = ((close - roll_low) / rng.replace(0, np.nan)) * 100

    dds = []
    step = 15
    for i in range(60, len(close) - window_fwd, step):
        p = pos.iloc[i]
        if pd.isna(p):
            continue
        if abs(p - position_now) > 12:
            continue
        future = close.iloc[i:i + window_fwd + 1]
        peak = float(future.iloc[0])
        if peak <= 0:
            continue
        min_p = float(future.min())
        dd = (min_p / peak - 1.0) * 100.0
        dds.append(dd)

    if len(dds) < min_samples:
        return None
    arr = np.array(dds)
    return {
        'n': len(dds),
        'p25': round(float(np.percentile(arr, 25)), 1),
        'p50': round(float(np.percentile(arr, 50)), 1),
        'p75': round(float(np.percentile(arr, 75)), 1),
    }


def get_3year_perspective(ticker, fundamental_score=None):
    """
    Perspektywa 3-letnia + analogie do historycznych krachów/korekt
    + conditional drawdown z własnej historii spółki.
    """
    try:
        data_3y = get_historical_prices(ticker, days=3 * 365)
        if data_3y.empty:
            return None

        data_10y = pd.DataFrame()
        has_10y = False
        try:
            data_10y = get_historical_prices(ticker, days=10 * 365)
            if not data_10y.empty and len(data_10y) >= 200:
                has_10y = True
        except Exception as e:
            print(f"Ostrzeżenie 10y {ticker}: {e}")

        current_price = float(data_3y['Close'].iloc[-1])
        high_3y = float(data_3y['High'].max())
        low_3y = float(data_3y['Low'].min())
        range_3y = high_3y - low_3y
        position_in_3y_range = ((current_price - low_3y) / range_3y) * 100 if range_3y > 0 else 50.0

        is_index = ticker.startswith('^') or ticker in [
            '^GSPC', '^N225', '^NDX', '^DJI', '^FCHI', '^FTSE', '^GDAXI', '^STOXX50E'
        ]

        daily_returns = data_3y['Close'].pct_change().dropna()
        volatility = float(daily_returns.std() * np.sqrt(252) * 100) if len(daily_returns) > 10 else 20.0

        if volatility > 40:
            okazja_prog, zagrozenie_prog = 20, 80
        elif volatility > 25:
            okazja_prog, zagrozenie_prog = 25, 75
        else:
            okazja_prog, zagrozenie_prog = 30, 70

        sma200 = data_3y['Close'].rolling(200).mean().iloc[-1]
        trend_3y = "NIEZNANY"
        if not np.isnan(sma200):
            if current_price > sma200 * 1.08:
                trend_3y = "SILNIE WZROSTOWY"
            elif current_price > sma200 * 1.03:
                trend_3y = "WZROSTOWY"
            elif current_price < sma200 * 0.92:
                trend_3y = "SILNIE SPADKOWY"
            elif current_price < sma200 * 0.97:
                trend_3y = "SPADKOWY"
            else:
                trend_3y = "BOCZNY"

        crash_risk_score = 50
        crash_details = {}
        position_in_10y = position_in_3y_range
        dist_sma200 = 0.0
        vol_10y = volatility
        max_dd_10y = 0.0

        ctx = data_10y if has_10y else data_3y
        try:
            high_ctx = float(ctx['High'].max())
            low_ctx = float(ctx['Low'].min())
            range_ctx = high_ctx - low_ctx
            position_in_10y = ((current_price - low_ctx) / range_ctx) * 100 if range_ctx > 0 else 50.0
            sma200_ctx = ctx['Close'].rolling(200).mean().iloc[-1]
            dist_sma200 = ((current_price - sma200_ctx) / sma200_ctx) * 100 if not np.isnan(sma200_ctx) else 0.0
            returns_ctx = ctx['Close'].pct_change().dropna()
            vol_10y = float(returns_ctx.std() * np.sqrt(252) * 100) if len(returns_ctx) > 20 else volatility
            roll_max = ctx['Close'].cummax()
            drawdown = (ctx['Close'] - roll_max) / roll_max * 100
            max_dd_10y = float(drawdown.min())

            sma200_values = ctx['Close'].rolling(200).mean().dropna()
            if len(sma200_values) > 50:
                trend_slope = (sma200_values.iloc[-1] - sma200_values.iloc[-50]) / sma200_values.iloc[-50] * 100
            else:
                trend_slope = 0.0
            trend_factor = max(0.0, min(20.0, -float(trend_slope) * 2))

            # pozycja: 50%→0, 100%→100
            pos_score = max(0.0, min(100.0, (position_in_10y - 40) / 60 * 100))
            # dystans od SMA200: 0%→0, 25%+ →100
            sma_score = max(0.0, min(100.0, dist_sma200 * 3.2))
            vol_score = min(100.0, (vol_10y / 55) * 100)  # ostrzej – vol 28% ≈ 51
            dd_score = min(100.0, (abs(max_dd_10y) / 55) * 100)

            crash_risk_score = int(
                pos_score * 0.35 + sma_score * 0.25 + vol_score * 0.15
                + dd_score * 0.15 + trend_factor * 0.10
            )
            # podłoga przy ekstremalnej pozycji
            if position_in_10y >= 90:
                crash_risk_score = max(crash_risk_score, 62)
            elif position_in_10y >= 80:
                crash_risk_score = max(crash_risk_score, 52)
            crash_risk_score = max(0, min(100, crash_risk_score))
            crash_details = {
                'high_10y': high_ctx, 'low_10y': low_ctx,
                'position_in_10y': round(position_in_10y, 1),
                'dist_from_sma200_pct': round(dist_sma200, 1),
                'annual_volatility_pct': round(vol_10y, 1),
                'max_drawdown_10y_pct': round(max_dd_10y, 1),
                'crash_risk_score': crash_risk_score,
                'trend_slope_pct': round(float(trend_slope), 2),
            }
        except Exception as e:
            print(f"Błąd crash-checker {ticker}: {e}")
            crash_details = {
                'high_10y': high_3y, 'low_10y': low_3y,
                'position_in_10y': round(position_in_3y_range, 1),
                'dist_from_sma200_pct': 0.0, 'annual_volatility_pct': round(volatility, 1),
                'max_drawdown_10y_pct': 0.0, 'crash_risk_score': 50,
                'trend_slope_pct': 0.0,
            }
            crash_risk_score = 50

        # --- Analogie historyczne (biblioteka krachów) ---
        analogies = _analyze_crash_analogies(position_in_10y, dist_sma200, vol_10y)
        if analogies['best_analogy_type'] == 'SYSTEMIC' and analogies['best_similarity'] >= 55:
            crash_risk_score = min(100, crash_risk_score + 10)
        elif analogies['best_analogy_type'] == 'CORRECTION' and analogies['best_similarity'] >= 60:
            crash_risk_score = min(100, crash_risk_score + 4)
        elif analogies['risk_tier'] == 'NISKI':
            crash_risk_score = max(0, crash_risk_score - 5)
        # zsynchronizuj tier z finalnym score
        if crash_risk_score >= 70 or position_in_10y >= 90:
            analogies['risk_tier'] = "WYSOKI"
        elif crash_risk_score >= 55 or position_in_10y >= 80:
            analogies['risk_tier'] = "PODWYŻSZONY"
        elif crash_risk_score <= 30 and position_in_10y <= 35:
            analogies['risk_tier'] = "NISKI"
        else:
            if analogies['risk_tier'] not in ("WYSOKI", "PODWYŻSZONY", "NISKI"):
                analogies['risk_tier'] = "UMIARKOWANY"
        crash_details['crash_risk_score'] = crash_risk_score

        # --- Conditional DD z własnej historii spółki ---
        own_dd = _own_history_conditional_dd(
            data_10y if has_10y else data_3y,
            position_in_10y,
        )

        duza_okazja = "NIE"
        duze_zagrozenie = "NIE"
        pos_check = position_in_10y
        price_percentiles = np.percentile(data_3y['Close'], [10, 25, 75, 90])
        low_25 = float(price_percentiles[1])
        high_75 = float(price_percentiles[2])
        if current_price <= low_25 or pos_check < okazja_prog:
            duza_okazja = "TAK"
        if current_price >= high_75 or pos_check > zagrozenie_prog:
            duze_zagrozenie = "TAK"

        returns_3y = data_3y['Close'].pct_change().dropna()
        if len(returns_3y) > 50:
            avg_return = float(returns_3y.mean() * 252)
            std_return = float(returns_3y.std() * np.sqrt(252))
            sharpe_ratio = avg_return / std_return if std_return > 0 else 0.0
        else:
            sharpe_ratio = 0.0

        atr = calculate_atr(data_3y, window=14)
        if atr is not None and not atr.empty and not pd.isna(atr.iloc[-1]):
            stop_loss = current_price - 2 * float(atr.iloc[-1])
        else:
            stop_loss = current_price * 0.85

        upside_mult, downside_mult = get_volume_spike_multipliers(
            data_3y, data_10y if has_10y else None
        )
        own_p50 = None
        if own_dd and isinstance(own_dd, dict):
            own_p50 = own_dd.get('p50')
        risk_pct, upside_pct = compute_risk_and_upside_3y(
            current_price, low_3y, high_3y, data_3y,
            fundamental_score=fundamental_score,
            is_index=is_index,
            trend=trend_3y,
            data_10y=data_10y if has_10y else None,
            crash_risk_score=crash_risk_score,
            hist_dd_p50=analogies.get('hist_dd_6m_p50'),
            hist_dd_p75=analogies.get('hist_dd_6m_p75'),
            own_dd_p50=own_p50,
        )
        # volume spike: lekkie, nie wywraca skali
        risk_pct = round(float(np.clip(risk_pct * min(downside_mult, 1.15), 8.0, 55.0)), 1)
        upside_pct = round(float(np.clip(upside_pct * min(upside_mult, 1.15), 10.0, 95.0)), 1)

        return {
            'ticker': ticker,
            'current_price': current_price,
            'high_3y': high_3y,
            'low_3y': low_3y,
            'position_in_range': round(position_in_3y_range, 1),
            'trend_3y': trend_3y,
            'duza_okazja': duza_okazja,
            'duze_zagrozenie': duze_zagrozenie,
            'risk_of_drop_pct': risk_pct,
            'upside_potential_pct': upside_pct,
            'crash_risk_score': crash_risk_score,
            'sharpe_ratio': round(sharpe_ratio, 2),
            'stop_loss': round(stop_loss, 2),
            'volatility': round(volatility, 1),
            'crash_details': crash_details,
            # nowe pola – analogie / conditional DD
            'best_analogy': analogies['best_analogy'],
            'best_similarity': analogies['best_similarity'],
            'risk_tier': analogies['risk_tier'],
            'hist_dd_p50': analogies['hist_dd_6m_p50'],
            'hist_dd_p75': analogies['hist_dd_6m_p75'],
            'hist_max_dd': analogies['hist_max_dd'],
            'hist_recovery_months': analogies['hist_recovery_months'],
            'analogy_details': analogies,
            'own_conditional_dd': own_dd,
        }
    except Exception as e:
        print(f"Błąd analizy 3-letniej dla {ticker}: {e}")
        import traceback
        traceback.print_exc()
        return None
    
# ============================================================
# KLASA HYBRYDOWEGO ANALIZATORA
# ============================================================



# ============================================================
# LISTA TICKERÓW DOMYŚLNA (API / rankings)
# ============================================================
tickers = [
    "NVDA", "INTC", "AMD", "CSCO", "XOM", "AMZN",
    "AAPL", "MSFT", "META", "GOOGL", "JPM", "TSLA",
]
all_data = {}
stock_analysis_data_1m = []
stock_analysis_data_3m = []
fundamental_data = {}
company_fundamentals_data = {}
three_year_data = {}

def init_macro_for_api():
    """Opcjonalne dociągnięcie makro przy starcie API."""
    try:
        ensure_macro_data_up_to_date()
        load_macro_csv()
    except Exception as e:
        print("Makro init:", e)

print("core_analysis loaded (headless, ready for FastAPI)")
