"""Simulated payment gateway. Replace with Stripe/PayPal in production."""
from __future__ import annotations

import logging
import random
import time

logger = logging.getLogger("apps.orders.payments")


class PaymentDeclined(Exception):
    """Gateway returned a clean 'no'."""


class PaymentGatewayError(Exception):
    """Gateway timed out / 5xx'd — we don't know if the charge happened."""


VALID_OUTCOMES = ("approved", "declined", "error")


def simulate_charge(
    order_id: int,
    amount,
    *,
    force_outcome: str | None = None,
    simulate_latency: bool = True,
) -> str:
    if force_outcome is not None and force_outcome not in VALID_OUTCOMES:
        raise ValueError(f"force_outcome must be one of {VALID_OUTCOMES}")

    if simulate_latency:
        time.sleep(random.uniform(0.05, 0.15))

    outcome = force_outcome or "approved"

    if outcome == "approved":
        ref = f"txn_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        logger.info("charge approved order=%s amount=%s ref=%s",
                    order_id, amount, ref)
        return ref
    if outcome == "declined":
        logger.warning("charge declined order=%s amount=%s", order_id, amount)
        raise PaymentDeclined(f"Payment declined for order {order_id}")
    logger.error("charge gateway-error order=%s amount=%s", order_id, amount)
    raise PaymentGatewayError(f"Gateway error for order {order_id}")
