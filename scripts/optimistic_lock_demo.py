"""
Optimistic-locking demo (conditional UPDATE + retry).

100 concurrent buyers against 50 stock. Expect 50 sales, 50 rejects,
version bumped exactly 50 times.

    docker compose exec -T -e BASE_URL=http://nginx web1 \
        python scripts/optimistic_lock_demo.py
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
    raise RuntimeError(f"seed first: scripts/seed.py (looking for {PRODUCT_SKU})")


def reset_stock(token: str, product_id: int, value: int) -> None:
    r = requests.put(
        f"{BASE}/api/catalog/products/{product_id}/",
        headers={"Authorization": f"Token {token}"},
        json={"stock": value},
        timeout=10,
    )
    if r.status_code not in (200, 202):
        print(f"[reset_stock] {r.status_code}: {r.text[:200]}")
        sys.exit(2)


def one_purchase(token: str, product_id: int) -> tuple[int, str]:
    r = requests.post(
        f"{BASE}/api/orders/checkout-direct/",
        headers={"Authorization": f"Token {token}"},
        json={
            "items": [{"product_id": product_id, "quantity": 1}],
            "lock": "optimistic",
        },
        timeout=30,
    )
    return r.status_code, r.text[:160].replace("\n", " ")


def main():
    print(f"-> logging in as {USERNAME!r} on {BASE}")
    token = login()
    product = find_product(token)
    pid = product["id"]
    print(f"-> product {PRODUCT_SKU} id={pid} starting_stock={product['stock']}")
    reset_stock(token, pid, STOCK_TARGET)
    print(f"-> firing {N_REQUESTS} optimistic checkouts on {N_THREADS} threads")

    success = oos = conflict = other = 0
    with ThreadPoolExecutor(max_workers=N_THREADS) as pool:
        futs = [pool.submit(one_purchase, token, pid) for _ in range(N_REQUESTS)]
        for f in as_completed(futs):
            code, body = f.result()
            if code == 201:
                success += 1
            elif code == 409 and "Concurrent update" in body:
                conflict += 1
            elif code == 409:
                oos += 1
            else:
                other += 1
                print(f"  unexpected {code}: {body}")

    r = requests.get(f"{BASE}/api/catalog/products/{pid}/",
                     headers={"Authorization": f"Token {token}"})
    stock_after = r.json()["stock"]
    version_after = r.json()["version"]

    rows = {
        "mode": "OPTIMISTIC (CAS + retry)",
        "requests_fired": N_REQUESTS,
        "successful_sales (HTTP 201)": success,
        "out_of_stock (HTTP 409)": oos,
        "optimistic_conflicts (HTTP 409)": conflict,
        "other_errors": other,
        "stock_before": STOCK_TARGET,
        "stock_after": stock_after,
        "version_after": version_after,
        "consistent": (success + stock_after == STOCK_TARGET),
        "saw_real_contention": version_after >= success,
    }
    width = max(len(k) for k in rows) + 2
    for k, v in rows.items():
        print(f"  {k:<{width}}{v}")

    print("\nExpected: 50 sales, stock 0, version_after >= 50.")


if __name__ == "__main__":
    main()
