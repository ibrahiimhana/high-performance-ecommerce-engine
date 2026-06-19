"""
Locust user scenario for the stress test.

Weights are roughly e-commerce-shaped: lots of browsing, few checkouts.
503 on checkout is treated as success — that's capacity backpressure, not
a real failure.

Run:
    docker compose --profile loadtest run --rm locust
"""
from __future__ import annotations

import random
import uuid

from locust import HttpUser, between, events, task


class EcommerceUser(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self):
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
            r = self.client.post(
                "/api/accounts/login/",
                json={"username": self.username, "password": self.password},
                name="setup: login",
            )
            self.token = (r.json() or {}).get("token", "")

        self.auth_headers = {"Authorization": f"Token {self.token}"}

    @task(10)
    def list_products(self):
        self.client.get("/api/catalog/products/", name="GET catalog list")

    @task(20)
    def product_detail(self):
        pid = random.randint(1, 4)
        self.client.get(f"/api/catalog/products/{pid}/", name="GET product detail")

    @task(5)
    def top_products(self):
        self.client.get("/api/catalog/top-products/", name="GET top-products")

    @task(3)
    def checkout(self):
        # BOOK-001 (stock 200) — won't drain in 60s under this load mix.
        with self.client.post(
            "/api/orders/checkout-direct/",
            headers=self.auth_headers,
            json={
                "items": [{"product_id": 4, "quantity": 1}],
                "lock": "pessimistic",
            },
            name="POST checkout",
            catch_response=True,
        ) as resp:
            if resp.status_code in (201, 200):
                resp.success()
            elif resp.status_code == 503:
                # Capacity middleware shed the load on purpose.
                resp.success()
                events.request.fire(
                    request_type="POST",
                    name="POST checkout (503 backpressure)",
                    response_time=resp.elapsed.total_seconds() * 1000,
                    response_length=len(resp.content or b""),
                    exception=None,
                    context={},
                )
            elif resp.status_code == 409:
                # Out of stock or optimistic conflict — both fine under load.
                resp.success()
            else:
                resp.failure(f"unexpected {resp.status_code}")

    @task(2)
    def my_orders(self):
        self.client.get("/api/orders/mine/?limit=20",
                        headers=self.auth_headers, name="GET my orders")
