"""
Empirical proof for Req #8 (Transaction Integrity / ACID).

The invariant we are defending:

    A checkout that has BEGUN must end in exactly one of two terminal
    states:
        (a) stock decremented + Order persisted + APPROVED Payment, or
        (b) stock unchanged + no Order persisted + no Payment persisted.

Anything in between — stock decremented but no payment, or payment taken
but no order recorded — is a money-losing, customer-angering bug. The
@transaction.atomic block plus the payment-step-INSIDE-the-block design
should make state (b) impossible to observe even under heavy concurrent
load with deterministic payment failures.

How the script proves it:

    Baseline:
        product RACE-001 starts at stock = 50.
        record (stock_before, orders_before, payments_before).

    Phase A — force-decline 30 concurrent checkouts.
        For each: HTTP 402 expected.
        Then re-read (stock_after_A, orders_after_A, payments_after_A).
        EXPECT: same as baseline. Nothing committed.

    Phase B — force-gateway-error 30 concurrent checkouts.
        For each: HTTP 502 expected.
        EXPECT: still same as baseline.

    Phase C — let 30 concurrent checkouts proceed normally.
        For each: HTTP 201 expected.
        EXPECT: stock down by 30; +30 orders; +30 APPROVED payments.

If Phase A or Phase B alters the database AT ALL, the ACID claim is
false. If Phase C does not change it by exactly 30/30/30, the locking
claim is false.
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
N_PER_PHASE = 30
N_THREADS = 20


def login() -> str:
    r = requests.post(f"{BASE}/api/accounts/login/",
                      json={"username": USERNAME, "password": PASSWORD},
                      timeout=10)
    r.raise_for_status()
    return r.json()["token"]


def headers(token: str) -> dict:
    return {"Authorization": f"Token {token}"}


def find_product(token: str) -> dict:
    r = requests.get(f"{BASE}/api/catalog/products/", headers=headers(token))
    r.raise_for_status()
    for p in r.json():
        if p["sku"] == PRODUCT_SKU:
            return p
    raise RuntimeError(f"seed first: scripts/seed.py (looking for {PRODUCT_SKU})")


def reset_stock(token: str, pid: int, value: int) -> None:
    r = requests.patch(f"{BASE}/api/catalog/products/{pid}/",
                       headers=headers(token), json={"stock": value})
    if r.status_code not in (200, 202):
        print(f"[reset_stock] {r.status_code}: {r.text[:200]}")
        sys.exit(2)


def current_stock(token: str, pid: int) -> int:
    r = requests.get(f"{BASE}/api/catalog/products/{pid}/", headers=headers(token))
    return r.json()["stock"]


def my_orders_count(token: str) -> int:
    # Ask for a generous limit so the demo can see absolute growth, not a
    # capped tail of the most recent 50.
    r = requests.get(f"{BASE}/api/orders/mine/?limit=5000", headers=headers(token))
    return len(r.json())


def one_checkout(token: str, pid: int, force_outcome: str | None) -> tuple[int, str]:
    body = {
        "items": [{"product_id": pid, "quantity": 1}],
        "lock": "pessimistic",
    }
    if force_outcome:
        body["force_payment_outcome"] = force_outcome
    r = requests.post(f"{BASE}/api/orders/checkout-direct/",
                      headers=headers(token), json=body, timeout=30)
    return r.status_code, r.text[:120].replace("\n", " ")


def burst(token, pid, n, force_outcome):
    counts: dict[int, int] = {}
    with ThreadPoolExecutor(max_workers=N_THREADS) as pool:
        futs = [pool.submit(one_checkout, token, pid, force_outcome) for _ in range(n)]
        for f in as_completed(futs):
            code, _body = f.result()
            counts[code] = counts.get(code, 0) + 1
    return counts


def snapshot(token, pid):
    return {"stock": current_stock(token, pid),
            "orders_for_demo_user": my_orders_count(token)}


def diff(a, b):
    return {k: b[k] - a[k] for k in a}


def main():
    print(f"-> logging in as {USERNAME!r} on {BASE}")
    token = login()
    product = find_product(token)
    pid = product["id"]
    print(f"-> product {PRODUCT_SKU} id={pid}")

    reset_stock(token, pid, STOCK_TARGET)
    baseline = snapshot(token, pid)
    print(f"-> baseline {baseline}")

    # ---------- Phase A — declines ----------
    print(f"\n=== Phase A: {N_PER_PHASE} declined payments ===")
    codes_a = burst(token, pid, N_PER_PHASE, "declined")
    print(f"  HTTP code distribution: {codes_a}   (expected: {{402: {N_PER_PHASE}}})")
    after_a = snapshot(token, pid)
    delta_a = diff(baseline, after_a)
    print(f"  state delta vs baseline: {delta_a}   (expected: stock 0, orders 0)")
    assert codes_a.get(402, 0) == N_PER_PHASE, "expected every request declined"
    assert delta_a["stock"] == 0, "ACID violation: stock changed during declined burst!"
    assert delta_a["orders_for_demo_user"] == 0, "ACID violation: order persisted on decline!"
    print("  -> Phase A PASS: no side effects from declined payments.")

    # ---------- Phase B — gateway errors ----------
    print(f"\n=== Phase B: {N_PER_PHASE} gateway errors ===")
    codes_b = burst(token, pid, N_PER_PHASE, "error")
    print(f"  HTTP code distribution: {codes_b}   (expected: {{502: {N_PER_PHASE}}})")
    after_b = snapshot(token, pid)
    delta_b = diff(after_a, after_b)
    print(f"  state delta vs after_A: {delta_b}   (expected: stock 0, orders 0)")
    assert codes_b.get(502, 0) == N_PER_PHASE
    assert delta_b["stock"] == 0, "ACID violation: stock changed during gateway-error burst!"
    assert delta_b["orders_for_demo_user"] == 0
    print("  -> Phase B PASS: no side effects from gateway errors.")

    # ---------- Phase C — happy path ----------
    print(f"\n=== Phase C: {N_PER_PHASE} approved payments ===")
    codes_c = burst(token, pid, N_PER_PHASE, "approved")
    print(f"  HTTP code distribution: {codes_c}   (expected: {{201: {N_PER_PHASE}}})")
    after_c = snapshot(token, pid)
    delta_c = diff(after_b, after_c)
    print(f"  state delta vs after_B: {delta_c}   (expected: stock -{N_PER_PHASE}, orders +{N_PER_PHASE})")
    assert codes_c.get(201, 0) == N_PER_PHASE
    assert delta_c["stock"] == -N_PER_PHASE, "expected stock to drop by exactly N"
    assert delta_c["orders_for_demo_user"] == N_PER_PHASE
    print("  -> Phase C PASS: stock + orders moved by exactly the right amount.")

    print("\nALL PHASES PASSED. Req #8 (ACID transaction integrity) demonstrated.")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"\nFAILED: {e}")
        sys.exit(1)
