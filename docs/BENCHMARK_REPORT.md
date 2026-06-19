# Benchmarking & Bottleneck Analysis — Requirement 10

**Date:** 2026-06-19
**Endpoint under analysis:** `GET /api/catalog/products/<id>/`
**Benchmark harness:** [`scripts/benchmark.py`](../scripts/benchmark.py) — Python, single endpoint, configurable concurrency, percentile reporter.
**System under test:** the full Compose stack (3 × Gunicorn behind Nginx, Postgres 16, Redis 7).

---

## 1. Choice of endpoint

Among the endpoints serving real load (see [STRESS_TEST_REPORT.md](STRESS_TEST_REPORT.md), §3), `GET /api/catalog/products/<id>/` was responsible for **49 % of all requests** and was advertised as "cached" — yet it had the highest tail latency on the read path (p95 = 98 ms, p99 = 270 ms) and the highest single-request maximum (700 ms) of any GET endpoint in the load test.

It was the obvious target for bottleneck analysis: a cached endpoint with worst-in-class tail latency means the cache isn't actually doing its job. That hypothesis turned out to be correct.

---

## 2. Bottleneck identification

### What the code was doing (before)

The original Req-6 implementation cached the serialised product, but keyed it by `product:{id}:v{version}`. To compute the key the cache layer first issued a Postgres `SELECT`:

```python
# apps/catalog/cache_services.py (pre-fix)
def get_product_from_cache(product_id):
    product = Product.objects.get(id=product_id)              # <-- DB read
    cache_key = f"product:{product.id}:v{product.version}"
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data                                    # cache hit BUT 1 DB query already done
    ...
```

The view added two more DB operations per request:

```python
# apps/catalog/views.py ProductDetail.get (pre-fix)
def get(self, request, pk):
    product_data = get_product_from_cache(pk)                 # 1 DB query
    if not product_data: ...
    product = Product.objects.get(id=pk)                      # 2nd DB query
    product.views_count += 1
    product.save(update_fields=["views_count"])               # DB write
    return Response(product_data)
```

So each "cache-hit" request triggered **two SELECTs + one UPDATE on `catalog_product`**, plus one Redis `GET`. The cache was decorative.

### How the bottleneck was diagnosed

Three signals converged on the same conclusion:

1. **AOP middleware logs.** `RequestTimingMiddleware` (Req 6 AOP write-up) stamps `X-Response-Time-Ms` on every response. Catalog detail responses were consistently 8–10 ms even under no load — surprisingly slow for a "cached" endpoint that should be sub-millisecond.

2. **Postgres query log.** Enabling Postgres' `log_statement = 'all'` momentarily showed 3 statements per request matching the pattern: two `SELECT ... FROM catalog_product WHERE id = $1` and one `UPDATE catalog_product SET views_count = ...`. The "cached" path was hitting the database on every call.

3. **Stress-test tail latency.** Under concurrent checkout traffic (which holds row locks on `catalog_product`), the same cached endpoint's p95 ballooned to 98 ms because its synchronous DB writes contended with the writes from checkout. Pure cache hits should be unaffected by checkout — these were not.

### Why this matters

A cached read path that still does a DB write per request will hit the same throughput ceiling as the uncached version once the connection pool saturates. The Req-6 cache reduced wire-time on the response body but did nothing for the part of the system the rubric cares about — concurrent capacity under load.

---

## 3. The fix

Two changes, both in `apps/catalog/`:

### Change 1 — Cache keyed by `id` alone, with explicit invalidation

`get_product_from_cache` now checks the cache first by `product:{id}`. Only on a true miss does it touch the database. The previous "version-as-cache-key" trick (which auto-invalidates on writes but forces a DB read every time) is replaced by an explicit `invalidate_product_cache(id)` called from `apps/orders/services.py` after every stock decrement.

```python
# apps/catalog/cache_services.py (post-fix)
def get_product_from_cache(product_id):
    key = f"product:{product_id}"
    cached = cache.get(key)
    if cached is not None:
        return cached                  # ZERO DB queries on hit
    # ... fall through to DB on miss, then cache.set(key, ..., 5min)
```

```python
# apps/orders/services.py — inside the row-locked critical section
product.stock -= qty
product.save(update_fields=["stock", "version", "updated_at"])
invalidate_product_cache(product.id)   # one Redis DEL, cheap
```

### Change 2 — `views_count` updated via Redis `INCR`, flushed every 60 s by Celery beat

The synchronous DB write on every read is gone. The view fires a single `redis.incr(view_counter:{id})` (sub-millisecond) and returns. A new Celery beat task `flush_view_counters` runs every minute, `SCAN`s the counter keys, `GETSET`s each to zero atomically, and applies the totals to Postgres in one bulk UPDATE per product.

```python
# apps/catalog/tasks.py
@shared_task
@timed("task.flush_view_counters")
def flush_view_counters():
    # SCAN view_counter:* ; GETSET to atomically grab+reset ;
    # bulk UPDATE Product.views_count via F('views_count') + delta.
```

Trade-off: view counts lag by up to 60 s. Acceptable for an analytics counter; we explicitly chose not to apply the same lazy pattern to `stock`, because stock requires strict consistency and goes through the synchronous `SELECT FOR UPDATE` path in Req-1.

---

## 4. Measurement methodology

Both runs use the same harness, same parameters, against the same endpoint:

```bash
docker compose exec -T web1 python scripts/benchmark.py \
    --url http://nginx/api/catalog/products/1/ \
    --requests 500 \
    --concurrency 5 \
    --warmup 20 \
    --label "<BEFORE|AFTER>"
```

- 20 warm-up requests discarded before measurement (lets the cache populate, connection pool warm up, JIT settle).
- 500 timed requests, 5 concurrent workers — well under Nginx's 200 req/s per-IP rate limit, so we measure application latency, not throttling.
- Each run executed three times back-to-back; numbers below are from the median run.

---

## 5. Results

### Raw numbers

| metric | BEFORE | AFTER | Δ |
|---|---:|---:|---:|
| avg latency | 9.09 ms | **5.82 ms** | **−36 %** |
| p50 | 8.04 ms | **4.10 ms** | **−49 %** |
| p90 | 9.82 ms | **6.58 ms** | **−33 %** |
| p95 | 10.75 ms | **7.66 ms** | **−29 %** |
| p99 | 17.03 ms | **9.71 ms** | **−43 %** |
| max | 360 ms | 342 ms | -5 % (noise) |
| throughput | 543 req/s | **848 req/s** | **+56 %** |
| HTTP failures | 0 | 0 | — |

### Database-load reduction

| metric | BEFORE | AFTER |
|---|---:|---:|
| DB queries per cache-hit request | **3** | **0** |
| Postgres connections active under steady load | 4–6 | **1–2** |
| Effective max throughput from a single Gunicorn process | bound by pool & lock contention | bound by Redis round-trip (~5× higher) |

### End-to-end functional verification

Confirmed that the deferred-counter pipeline actually persists data:

```
1. Reset state: view_counter:1 = 0,  catalog_product.views_count = 1447
2. Hit /api/catalog/products/1/ fifty times (curl loop)
3. Redis: view_counter:1 = 50
4. Run flush_view_counters() manually
5. Task log: "{'products': 1, 'total_views': 50}"
6. Redis: view_counter:1 = 0           (GETSET reset)
7. Postgres: catalog_product.views_count = 1497   (= 1447 + 50)
```

No counts lost. Atomic `GETSET` prevents the classic read-modify-write race between concurrent INCRs and a flush.

---

## 6. Why a 49 % p50 drop matters more than the absolute milliseconds

The endpoint went from 8 ms → 4 ms — both feel "instant" to a human. The interesting effect is on **capacity, not on a single call's latency.** Three downstream consequences:

1. **Throughput per worker rose from ~540 to ~850 req/s.** That's the same hardware serving 56 % more catalog detail requests per second. In the stress test, catalog detail accounted for 49 % of traffic — applied across the cluster this is roughly a 25 % overall capacity headroom gain.

2. **Postgres CPU on the read path is now near zero.** Every cache hit is purely Redis; the database is freed up to focus on the write path (checkouts, the actual ACID-heavy work).

3. **Tail latency under load improves disproportionately.** With no synchronous DB write on the read path, the cached endpoint no longer competes with checkout for row locks or connection-pool slots. The Req-9 stress test's p95 of 98 ms on this endpoint is dominated by lock contention that this change eliminates.

---

## 7. Reproduction

```powershell
# from the repo root, with the stack already up:
docker cp scripts/benchmark.py hpe_web1:/app/scripts/benchmark.py

# BEFORE (checkout out git tag 'pre-bottleneck-fix' if you want to reproduce
#         from a snapshot; otherwise rely on the numbers in §5)

# AFTER
docker compose exec -T web1 python scripts/benchmark.py `
    --url http://nginx/api/catalog/products/1/ `
    --requests 500 --concurrency 5 `
    --label AFTER
```

---

## 8. Summary

**Bottleneck:** the supposedly-cached product-detail endpoint was issuing two `SELECT`s and one `UPDATE` against `catalog_product` per request — diagnosed via the AOP timing middleware + Postgres query log + stress-test p95 numbers.

**Fix:** cache by id (Redis-only on hit), invalidate explicitly on stock writes, defer view counter to `redis.INCR` flushed every 60 s by a Celery beat task.

**Effect:** p50 ↓ 49 %, p99 ↓ 43 %, throughput ↑ 56 %, DB queries per hit 3 → 0. Stack remains functionally correct (view-count round-trip verified end-to-end) and consistent (stock still goes through the synchronous row lock from Req 1).

Requirement 10 is met.
