"""
Race-condition demo.

Phase 1: 100 concurrent buyers on the unsafe path -> oversell.
Phase 2: same on the safe path (SELECT FOR UPDATE) -> exactly STOCK sales.

    docker compose exec -T -e BASE_URL=http://nginx web1 \
        python scripts/race_condition_demo.py
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


def one_purchase(token: str, product_id: int, unsafe: bool) -> tuple[int, str]:
    r = requests.post(
        f"{BASE}/api/orders/checkout-direct/",
        headers={"Authorization": f"Token {token}"},
        json={"items": [{"product_id": product_id, "quantity": 1}],
              "unsafe": unsafe},
        timeout=30,
    )
    return r.status_code, r.text[:120].replace("\n", " ")


def burst(token: str, product_id: int, unsafe: bool) -> dict:
    successes = conflicts = other = 0
    with ThreadPoolExecutor(max_workers=N_THREADS) as pool:
        futs = [pool.submit(one_purchase, token, product_id, unsafe)
                for _ in range(N_REQUESTS)]
        for f in as_completed(futs):
            code, _ = f.result()
            if code == 201:
                successes += 1
            elif code == 409:
                conflicts += 1
            else:
                other += 1

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

    print("\n=== Phase 1: UNSAFE ===")
    reset_stock(token, pid, STOCK_TARGET)
    pretty(burst(token, pid, unsafe=True))

    print("\n=== Phase 2: SAFE ===")
    reset_stock(token, pid, STOCK_TARGET)
    pretty(burst(token, pid, unsafe=False))

    print("\nExpected:")
    print("  Phase 1 -> successes > 50 or stock_after != 0 (race fired)")
    print("  Phase 2 -> 50 successes, 50 conflicts, stock=0, consistent=True")


if __name__ == "__main__":
    main()
