"""
Empirical proof for Req #1 (Concurrent Access & Data Integrity).

What this script does:
    1. Logs in as the seeded "demo" user against the load balancer.
    2. Resets the demo product to a known stock (50 units).
    3. Fires N concurrent purchase requests for 1 unit each, with
       `unsafe=True` — the no-lock code path. The classic Race Condition
       symptom should appear: more successful "sales" than units we had,
       or negative final stock.
    4. Resets the same product back to 50 units.
    5. Repeats the burst with `unsafe=False` — the SELECT FOR UPDATE path.
       Exactly STOCK sales should succeed, the rest should fail with 409.

Run it from the host:
    pip install requests   # if you don't have it in your venv
    python scripts/race_condition_demo.py

Or, inside a container with everything already installed:
    docker compose exec web1 python scripts/race_condition_demo.py
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE = os.environ.get("BASE_URL", "http://localhost:8080")
USERNAME = os.environ.get("DEMO_USERNAME", "demo")
PASSWORD = os.environ.get("DEMO_PASSWORD", "demo12345")
PRODUCT_SKU = "RACE-001"
STOCK_TARGET = 50
N_REQUESTS = 100
N_THREADS = 50


def login() -> str:
    r = requests.post(f"{BASE}/api/accounts/login/",
                      json={"username": USERNAME, "password": PASSWORD},
                      timeout=10)
    r.raise_for_status()
    return r.json()["token"]


def find_product(token: str) -> dict:
    r = requests.get(f"{BASE}/api/catalog/products/",
                     headers={"Authorization": f"Token {token}"}, timeout=10)
    r.raise_for_status()
    for p in r.json():
        if p["sku"] == PRODUCT_SKU:
            return p
    raise RuntimeError("seed first: scripts/seed.py")


def reset_stock(token: str, product_id: int, value: int) -> None:
    """Reset stock via admin DRF endpoint. The seeded demo user is not staff;
    we use the Django admin via a superuser instead — or just call the
    product PATCH endpoint as a staff user.

    Simpler: use the admin we create out-of-band. For this demo we hit the
    catalog detail endpoint with a staff token. If you don't have a staff
    token configured, run scripts/seed.py once and set DJANGO_SUPERUSER_*
    env vars on the migrator container; alternatively shell into the db:

        docker compose exec postgres psql -U ecommerce -d ecommerce \\
            -c "UPDATE catalog_product SET stock=50, version=version+1 \\
                WHERE sku='RACE-001';"
    """
    # Try the API path; fall back to a clear instruction.
    r = requests.patch(
        f"{BASE}/api/catalog/products/{product_id}/",
        headers={"Authorization": f"Token {token}"},
        json={"stock": value},
        timeout=10,
    )
    if r.status_code in (200, 202):
        return
    print(f"[reset_stock] API refused ({r.status_code}). Run:")
    print('  docker compose exec postgres psql -U ecommerce -d ecommerce '
          f'-c "UPDATE catalog_product SET stock={value}, version=version+1 '
          f"WHERE sku='{PRODUCT_SKU}';\"")
    sys.exit(2)


def one_purchase(token: str, product_id: int, unsafe: bool) -> tuple[int, str]:
    r = requests.post(
        f"{BASE}/api/orders/checkout-direct/",
        headers={"Authorization": f"Token {token}"},
        json={"items": [{"product_id": product_id, "quantity": 1}],
              "unsafe": unsafe},
        timeout=30,
    )
    body = r.text[:120].replace("\n", " ")
    return r.status_code, body


def burst(token: str, product_id: int, unsafe: bool) -> dict:
    successes = 0
    conflicts = 0
    other = 0
    served_by_counter: dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=N_THREADS) as pool:
        futs = [pool.submit(one_purchase, token, product_id, unsafe)
                for _ in range(N_REQUESTS)]
        for f in as_completed(futs):
            code, _body = f.result()
            if code == 201:
                successes += 1
            elif code == 409:
                conflicts += 1
            else:
                other += 1

    # Read final stock.
    r = requests.get(f"{BASE}/api/catalog/products/{product_id}/",
                     headers={"Authorization": f"Token {token}"})
    stock_after = r.json()["stock"]

    return {
        "mode": "UNSAFE (no lock)" if unsafe else "SAFE (SELECT FOR UPDATE)",
        "requests_fired": N_REQUESTS,
        "successful_sales (HTTP 201)": successes,
        "out_of_stock_rejected (HTTP 409)": conflicts,
        "other_errors": other,
        "stock_before": STOCK_TARGET,
        "stock_after": stock_after,
        "consistent": (successes + stock_after == STOCK_TARGET),
    }


def pretty(d: dict) -> None:
    width = max(len(k) for k in d) + 2
    for k, v in d.items():
        print(f"  {k:<{width}}{v}")


def main():
    print(f"-> logging in as {USERNAME!r} on {BASE}")
    token = login()
    product = find_product(token)
    pid = product["id"]
    print(f"-> product {PRODUCT_SKU} id={pid} starting_stock={product['stock']}")

    print("\n=== Phase 1: UNSAFE checkout (proving the race exists) ===")
    reset_stock(token, pid, STOCK_TARGET)
    pretty(burst(token, pid, unsafe=True))

    print("\n=== Phase 2: SAFE checkout (with row lock) ===")
    reset_stock(token, pid, STOCK_TARGET)
    pretty(burst(token, pid, unsafe=False))

    print("\nInterpretation:")
    print("  * Phase 1 should show successes != 50 OR stock_after != 0")
    print("    (oversell or inconsistent state -> classic race condition).")
    print("  * Phase 2 should show exactly 50 successes, 50 conflicts,")
    print("    stock_after = 0, consistent = True.")


if __name__ == "__main__":
    main()
