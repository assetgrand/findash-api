# FinDash – rejestracja, Demo, Standard, Pro

## Plany

| Plan | Limit | Funkcje |
|------|-------|---------|
| **Demo** | 2× `/analyze` (1M lub 3M) / miesiąc UTC | tylko analyze |
| **Standard** | bez limitu analyze | 1M/3M, fundamenty, tech, raporty, backtest strategii, 3Y, rankings |
| **Pro** | bez limitu | Standard + Hybrid + signals (+ portfolio gdy będzie) |

Egzekucja limitów: **API (Render)**, nie tylko UI.

---

## 1. Supabase

1. Projekt na https://supabase.com
2. SQL Editor – wklej:

```sql
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  plan text not null default 'demo',
  analyze_count int not null default 0,
  analyze_month text not null default to_char(now() at time zone 'utc', 'YYYY-MM'),
  created_at timestamptz default now()
);

alter table public.profiles enable row level security;

create policy "Users read own profile"
  on public.profiles for select
  using (auth.uid() = id);

create or replace function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, email, plan, analyze_count, analyze_month)
  values (
    new.id,
    new.email,
    'demo',
    0,
    to_char(now() at time zone 'utc', 'YYYY-MM')
  )
  on conflict (id) do nothing;
  return new;
end;
$$ language plpgsql security definer;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();
```

3. Authentication → Providers → Email ON  
4. Settings → API skopiuj:
   - Project URL → `SUPABASE_URL`
   - `anon` `public` → do **Lovable** (front)
   - `service_role` → **tylko Render** `SUPABASE_SERVICE_ROLE_KEY`
   - JWT Secret (Settings → API → JWT Settings) → `SUPABASE_JWT_SECRET`

---

## 2. Render – Environment

```
POLYGON_API_KEY=...
AUTH_REQUIRED=1
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_ROLE_KEY=eyJ...
SUPABASE_JWT_SECRET=super-secret-jwt...
PRECOMPUTE_ENABLED=1
```

Opcjonalnie Stripe później:
```
STRIPE_WEBHOOK_SECRET=whsec_...
```

Deploy (push `auth_plans.py` + `api_server.py` + requirements).

---

## 3. Lovable (UI – ręcznie / mały prompt)

- Supabase client: signUp / signInWithPassword / signOut  
- Po loginie: `session.access_token`  
- Każdy request do API:

```js
headers: {
  Authorization: `Bearer ${access_token}`,
  "Content-Type": "application/json",
}
```

- `GET /me` → pokaż plan + `analyze_remaining`  
- `GET /analyze/NVDA?horizon=1M` z Bearer  
- 401 → przekieruj do logowania  
- 402 → „Limit Demo wyczerpany – upgrade”  
- 403 → „Wymaga Standard/Pro”

Publiczne bez tokena: `/health`, `/plans`, `/tickers` (tickers opcjonalnie później zamknąć).

---

## 4. Stripe (później)

1. Products: Standard, Pro  
2. Checkout Session z metadata:
   - `supabase_user_id` = user.id  
   - `plan` = `standard` | `pro`  
3. Webhook → `POST https://TWOJ-API.onrender.com/billing/stripe-webhook`  
   Event: `checkout.session.completed`

---

## 5. Test lokalny bez Supabase

```bash
export AUTH_REQUIRED=1
export DEV_AUTH_BYPASS=1
# bez JWT – użyj nagłówka:
curl -H "X-Dev-Email: test@example.com" http://127.0.0.1:8000/me
curl -H "X-Dev-Email: test@example.com" http://127.0.0.1:8000/analyze/AAPL?horizon=1M
```

`POST /billing/set-plan-dev?plan=pro` z tym samym nagłówkiem.

---

## Pliki

- `auth_plans.py` – macierz planów, Supabase, limity  
- `api_server.py` – Depends(get_profile) na chronionych trasach  
