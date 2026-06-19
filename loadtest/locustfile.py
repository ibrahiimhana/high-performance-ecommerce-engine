"""
Locust scenario for Req #9 — Stress Testing.

User mix (weights are realistic for an e-commerce store: lots of browsing,
some carting, few checkouts):

    weight=20   GET  /api/catalog/products/<id>/   (cache-hit path, Req 6)
    weight=10   GET  /api/catalog/products/        (catalog list)
    weight=5    GET  /api/catalog/top-products/    (top-N, Req 6 cache)
    weight=3    POST /api/orders/checkout-direct/  (heavy path, Reqs 1/7/8)
    weight=2    GET  /api/orders/mine/             (read after write)

A 503 on the checkout endpoint is NOT counted as a failure: it is
intentional capacity-control backpressure from Req #2 doing its job.
We flag it as a success with a distinct name so the report shows the
shed-load rate separately.

Run from the repo root:
    docker compose --profile loadtest run --rm locust
"""
from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, events, task


class EcommerceUser(HttpUser):
    # Each "user" thinks for 0.5–2 s between actions — produces a realistic
    # request stream when scaled to 100 concurrent users.
    wait_time = between(0.5, 2.0)

    def on_start(self):
        """Register a unique account and remember the token."""
        self.username = f"stress_{uuid.uuid4().hex[:10]}"
        self.password = "stress_pass_123"

        r = self.client.post(
            "/api/accounts/register/",
            json={
                "username": self.username,
                "password": self.password,
                "email": f"{self.username}@stress.test",
            },
            name="setup: register",
        )
        if r.status_code in (200, 201):
            self.token = r.json()["token"]
        else:
            # Fall back to login if the username collided.
            r = self.client.post(
                "/api/accounts/login/",
                json={"username": self.username, "password": self.password},
                name="setup: login",
            )
            self.token = (r.json() or {}).get("token", "")

        self.auth_headers = {"Authorization": f"Token {self.token}"}

    # ---- read-heavy traffic ----
    @task(10)
    def list_products(self):
        self.client.get("/api/catalog/products/", name="GET catalog list")

    @task(20)
    def product_detail(self):
        pid = random.randint(1, 4)  # we have 4 seeded products
        self.client.get(
            f"/api/catalog/products/{pid}/",
            name="GET product detail (Req 6 cache)",
        )

    @task(5)
    def top_products(self):
        self.client.get("/api/catalog/top-products/",
                        name="GET top-products (Req 6 cache)")

    # ---- write traffic ----
    @task(3)
    def checkout(self):
        # BOOK-001 has stock 200 — high enough that 100 concurrent users
        # don't quickly drain it. RACE-001 (stock 50) is reserved for the
        # focused Req-1 / Req-7 demos.
        with self.client.post(
            "/api/orders/checkout-direct/",
            headers=self.auth_headers,
            json={
                "items": [{"product_id": 4, "quantity": 1}],
                "lock": "pessimistic",
            },
            name="POST checkout (heavy, Reqs 1/2/7/8)",
            catch_response=True,
        ) as resp:
            if resp.status_code in (201, 200):
                resp.success()
            elif resp.status_code == 503:
                # Req-2 backpressure firing. Mark as success in the
                # stats and track separately under a clearer name.
                resp.success()
                events.request.fire(
                    request_type="POST",
                    name="POST checkout (Req-2 backpressure 503)",
                    response_time=resp.elapsed.total_seconds() * 1000,
                    response_length=len(resp.content or b""),
                    exception=None,
                    context={},
                )
            elif resp.status_code == 409:
                # Out of stock or optimistic conflict — also a normal
                # outcome under load, not a system failure.
                resp.success()
            else:
                resp.failure(f"unexpected {resp.status_code}")

    @task(2)
    def my_orders(self):
        self.client.get(
            "/api/orders/mine/?limit=20",
            headers=self.auth_headers,
            name="GET my orders",
        )
