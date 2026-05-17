# High-Performance E-Commerce Backend Engine

Django 5 + PostgreSQL 16 + Redis 7 + Celery + Nginx, packaged with Docker
Compose. Covers the first five non-functional requirements of the
Parallel Programming 2026 project:

1. Concurrent Access & Data Integrity (pessimistic row locks)
2. Resource Management & Capacity Control (bounded semaphore + Gunicorn)
3. Asynchronous Queues (Celery on Redis)
4. Batch Processing (chunked streaming via Celery Beat)
5. Load Distribution (Nginx `least_conn` across 3 Django app servers)

See **[ARCHITECTURE.md](ARCHITECTURE.md)** for the why and where of every
design decision, including the synchronization points and the AOP wiring
the rubric asks about.

---

## Prerequisites

- Docker Desktop (already detected on your machine: 29.x).
- Nothing else. PostgreSQL, Redis, Python 3.12 — all of them live inside
  the compose stack.

## Bring it up

From the repo root (PowerShell):

```powershell
docker compose build
docker compose up -d
```

First boot takes a minute (image pull + pip install + migrations). When
the `hpe_migrator` container exits with status 0 and the three web
containers are healthy you are ready.

Verify the load balancer:

```powershell
for ($i = 0; $i -lt 6; $i++) { curl.exe -s -D - -o $null http://localhost:8080/api/health/ | Select-String "X-Instance|X-Served-By" }
```

You should see `X-Instance` rotating across `web1` / `web2` / `web3`.

## Seed data

```powershell
docker compose exec web1 python scripts/seed.py
```

Creates a demo superuser `demo / demo12345` and four products including
`RACE-001` (the race-condition demo target).

## Endpoints

| Method | Path                                  | Purpose                                            |
|--------|---------------------------------------|----------------------------------------------------|
| GET    | `/api/health/`                        | Liveness probe + worker tag                        |
| POST   | `/api/accounts/register/`             | Register + return token                            |
| POST   | `/api/accounts/login/`                | Token login                                        |
| GET    | `/api/accounts/me/`                   | Current user                                       |
| GET    | `/api/catalog/products/`              | List products                                      |
| GET/PATCH/DELETE | `/api/catalog/products/<id>/`   | Detail / admin update                              |
| GET    | `/api/cart/`                          | View cart                                          |
| POST   | `/api/cart/add/`                      | Add item                                           |
| DELETE | `/api/cart/items/<id>/`               | Remove item                                        |
| POST   | `/api/orders/checkout/`               | **Req #1** safe checkout (locks + ACID)            |
| POST   | `/api/orders/checkout-direct/`        | Direct buy; takes `unsafe: bool` for the demo      |
| GET    | `/api/orders/mine/`                   | My orders                                          |
| POST   | `/api/orders/reports/trigger/`        | **Req #4** kick the batch job on demand            |
| GET    | `/api/orders/reports/daily/`          | **Req #4** output: daily rollups                   |

All write endpoints require the `Authorization: Token <key>` header.

## Demonstrate Req #1 — the race condition

```powershell
docker compose exec web1 python scripts/race_condition_demo.py
```

What it does, in one paragraph: log in as `demo`, reset `RACE-001` stock
to 50, fire 100 concurrent single-unit checkouts on the deliberately
broken `unsafe=True` path, count successes and final stock; reset, fire
the same 100 against the real `unsafe=False` path, count again. Phase 1
oversells, Phase 2 sells exactly 50. The pessimistic row lock did its
job.

## Demonstrate Req #3 — async dispatch

```powershell
docker compose logs -f celery_worker
```

Then trigger a checkout from a second terminal. You will see the worker
pick up `send_invoice_email` and `send_order_notifications` *after* the
HTTP response has already returned to the client.

## Demonstrate Req #4 — chunked batch rollup

```powershell
curl.exe -X POST http://localhost:8080/api/orders/reports/trigger/
docker compose logs -f celery_worker | findstr rollup
curl.exe http://localhost:8080/api/orders/reports/daily/
```

`celery_beat` will fire the same job automatically at 00:05 UTC every day.

## Demonstrate Req #5 — load distribution

```powershell
for ($i = 0; $i -lt 12; $i++) { curl.exe -s -D - -o $null http://localhost:8080/api/health/ | Select-String "X-Instance" }
```

You should see the responses fan out across web1 / web2 / web3. Hit it
with a real burst to see `least_conn` favour idle workers:

```powershell
1..200 | ForEach-Object -Parallel { curl.exe -s -D - -o $null http://localhost:8080/api/health/ } -ThrottleLimit 50
```

## Demonstrate Req #2 — capacity ceiling

Lower the cap to make it observable:

```powershell
# In .env, set MAX_CONCURRENT_HEAVY_REQUESTS=2 and:
docker compose up -d --force-recreate web1 web2 web3
```

then run the race-condition demo. You will see a sprinkling of `503`
responses in the Phase 1 / Phase 2 output — the system shedding load
rather than thrashing.

## Tear down

```powershell
docker compose down -v
```

(`-v` also wipes the Postgres + Redis volumes; drop it if you want to
keep the seeded data.)

---

## File map

```
config/                Django project (settings, urls, celery)
apps/core/             Cross-cutting concerns (middleware, AOP decorator, health)
apps/accounts/         Register / login / me  (Token auth)
apps/catalog/          Product model + REST endpoints
apps/cart/             Per-user cart with atomic add
apps/orders/           Checkout, async tasks, batch rollup, DailySalesReport
nginx/nginx.conf       least_conn upstream + X-Served-By header
scripts/seed.py        Seed users + products
scripts/race_condition_demo.py   Empirical Req #1 proof
docker-compose.yml     postgres + redis + 3xweb + nginx + celery + beat
```
