# Połączenie dashboardu Python ↔ Lovable

## Co jest w tym folderze

| Plik | Rola |
|------|------|
| `core_analysis.py` | Logika analizy **bez okien Tk** (Polygon, 1M/3M, fundamenty, 3Y) |
| `api_server.py` | FastAPI – endpointy pod frontend |
| `requirements.txt` | Zależności Pythona |
| `Procfile` | Start na Render / Railway |

---

## Krok 1 – klucz Polygon

1. Weź klucz z [polygon.io](https://polygon.io/).
2. **Nie commituj klucza do GitHub** – tylko zmienna środowiskowa:

```bash
export POLYGON_API_KEY="twoj_klucz_tutaj"
```

Na hostingu (Render/Railway) dodaj tę samą zmienną w panelu **Environment**.

---

## Krok 2 – test lokalny (komputer)

W terminalu, w folderze `lovable_backend`:

```bash
cd lovable_backend
python -m venv .venv

# Windows:
.venv\Scripts\activate
# Mac/Linux:
source .venv/bin/activate

pip install -r requirements.txt
export POLYGON_API_KEY="twoj_klucz"
uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
```

Otwórz w przeglądarce:

- http://127.0.0.1:8000/docs – interaktywna dokumentacja  
- http://127.0.0.1:8000/health  
- http://127.0.0.1:8000/analyze/NVDA?horizon=1M  

Jeśli `/health` pokazuje `"polygon_key_configured": true` i `/analyze/NVDA` zwraca JSON – backend działa.

> Lovable w chmurze **nie zobaczy** `localhost`. Do połączenia ze stroną potrzebny jest **publiczny URL** (krok 3).

---

## Krok 3 – hosting API (publiczny URL)

### Opcja A – Render (prosto, jest free tier)

1. Załóż konto: https://render.com  
2. New → **Web Service**  
3. Podłącz repo GitHub z folderem `lovable_backend` (albo cały projekt, ustaw Root Directory = `lovable_backend`)  
4. Ustawienia:
   - **Runtime:** Python  
   - **Build Command:** `pip install -r requirements.txt`  
   - **Start Command:** `uvicorn api_server:app --host 0.0.0.0 --port $PORT`  
5. Environment:
   - `POLYGON_API_KEY` = twój klucz  
   - `CORS_ALLOW_ALL` = `1`  
6. Deploy → dostaniesz URL np. `https://findash-api.onrender.com`

### Opcja B – Railway

1. https://railway.app → New Project → Deploy from repo  
2. Root: `lovable_backend`  
3. Variables: `POLYGON_API_KEY`, `CORS_ALLOW_ALL=1`  
4. Start: jak w Procfile  

Po deploym sprawdź: `https://TWOJ-URL/health` i `https://TWOJ-URL/analyze/AAPL?horizon=1M`

---

## Krok 4 – podłączenie Lovable

1. Otwórz swój projekt na Lovable (strona główna już masz).  
2. Wklej **prompt** (podmień URL):

```
Zintegruj zewnętrzne API analityczne FinDash.

Base URL: https://TWOJ-URL-Z-RENDER.onrender.com

Endpointy (JSON):
1) GET /health → { status, polygon_key_configured }
2) GET /analyze/{ticker}?horizon=1M lub 3M →
   {
     ticker, horizon, current_price, predicted_price,
     predicted_change_pct, direction, rsi, sector,
     fundamental_rating, combined_score, hit_rate, mae,
     disclaimer
   }
3) GET /rankings?horizon=1M&limit=10 → { horizon, items: [ { ticker, current_price, predicted_change_pct, direction, sector, fundamental_rating, hit_rate } ] }
4) GET /fundamentals/{ticker} → rating + wskaźniki
5) GET /perspective-3y/{ticker} → ryzyko / potencjał 3 lata

Zrób stronę /app lub sekcję "Analiza":
- pole tekstowe na ticker (np. NVDA)
- wybór horyzontu 1M / 3M
- przycisk "Analizuj" wywołujący GET /analyze/{ticker}
- czytelna karta wyniku (cena, prognoza %, kierunek, rating, Hit%, MAE)
- krótki disclaimer z pola "disclaimer"
- sekcja "Ranking" ładująca GET /rankings

Wywołuj API przez fetch. Obsłuż loading i błędy (np. 404 brak danych).
Nie hardcoduj kluczy API – backend jest publiczny bez auth na start.
```

3. Jeśli Lovable pyta o Cloud / secrets – **klucza Polygon nie dodawaj do Lovable** (jest tylko na backendzie).  
4. Po wygenerowaniu UI przetestuj analizę NVDA / AAPL.

Opcjonalnie w Secrets Lovable (jeśli używasz zmiennej):

- `VITE_API_BASE_URL` = `https://TWOJ-URL-Z-RENDER.onrender.com`

---

## Krok 5 – CORS / domena Lovable

W `api_server.py` domyślnie `CORS_ALLOW_ALL=1` (działa z każdą domeną Lovable).

Na produkcji możesz ustawić:

```bash
CORS_ALLOW_ALL=0
CORS_ORIGINS=https://twoj-projekt.lovable.app,https://twoja-domena.pl
```

---

## Endpointy – ściąga

| Metoda | Ścieżka | Opis |
|--------|---------|------|
| GET | `/health` | Status + czy jest klucz |
| GET | `/tickers` | Lista domyślnych tickerów |
| GET | `/analyze/{ticker}?horizon=1M` | Pełna prognoza 1M/3M |
| GET | `/rankings?horizon=1M&limit=12` | Ranking spółek |
| GET | `/fundamentals/{ticker}` | Fundamenty + makro |
| GET | `/perspective-3y/{ticker}` | Perspektywa 3 lat |
| GET | `/docs` | Swagger UI |

---

## Częste problemy

| Problem | Rozwiązanie |
|---------|-------------|
| Lovable: Failed to fetch | API niepubliczne / zły URL / CORS – sprawdź `/health` w przeglądarce |
| `polygon_key_configured: false` | Brak `POLYGON_API_KEY` na hostingu |
| 404 przy analyze | Zły ticker albo Polygon nie zwraca danych |
| Timeout na rankings | Free Render „usypia” – pierwsze wywołanie 30–60 s; zmniejsz `limit` |
| Import error core_analysis | Uruchamiaj z katalogu `lovable_backend` |

---

## Bezpieczeństwo (MVP vs później)

**MVP (to co masz teraz):** API publiczne, bez logowania – OK do testów i demo.

**Później:** API key / JWT dla frontu, rate limit, tylko zalogowani userzy, monitoring kosztów Polygon.

**Disclaimer** jest w odpowiedzi API – wyświetlaj go zawsze na stronie (tool analityczny, nie doradztwo).

---

## Desktop vs API

- Stary plik z Tkinterem = program na komputer.  
- `core_analysis.py` + `api_server.py` = wersja pod stronę.  
Możesz dalej używać desktopu lokalnie; strona korzysta z API.

