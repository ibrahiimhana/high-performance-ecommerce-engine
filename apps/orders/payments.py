"""
Payment gateway simulator — supports Req #8 (Transaction Integrity / ACID).

In a real system this module would talk to Stripe / PayPal / a bank API.
For the course project we simulate the external gateway in-process so
that:

  * Failure modes are deterministic and reproducible — the rubric asks
    us to *prove* all-or-nothing rollback, which requires the ability to
    force a failure on demand.
  * The demo is fully self-contained — no external accounts, no
    secrets, no network egress from the grader's machine.

A real gateway lands in one of three terminal states; we model all three
because they have different implications for ACID:

  APPROVED — money moved, return a reference.
  DECLINED — caller's fault (insufficient funds, fraud filter, ...).
             A clean, knowable failure.
  ERROR    — gateway's fault (timeout, 5xx, network drop).
             The DANGEROUS case for ACID: the bank may or may not have
             charged the customer. Real systems defend with idempotency
             keys + later reconciliation. For the project we treat both
             failure modes the same way at the transaction layer: raise
             an exception, let the surrounding @transaction.atomic block
             roll the whole thing back, never leave the system in a
             half-charged / half-shipped state.
"""
from __future__ import annotations

import logging
import random
import time

logger = logging.getLogger("apps.orders.payments")


class PaymentDeclined(Exception):
    """Gateway returned a clean 'no' — known failure mode."""


class PaymentGatewayError(Exception):
    """Gateway timed out or 5xx'd — outcome is unknown."""


VALID_OUTCOMES = ("approved", "declined", "error")


def simulate_charge(
    order_id: int,
    amount,
    *,
    force_outcome: str | None = None,
    simulate_latency: bool = True,
) -> str:
    """
    Pretend to charge `amount` for `order_id`. Returns a provider
    reference string on approval; raises PaymentDeclined or
    PaymentGatewayError otherwise.

    ``force_outcome`` is the lever the demo script pulls to make a given
    checkout fail at the payment step:

        None        -> defaults to 'approved' (production-like path)
        'approved'  -> always succeed
        'declined'  -> raise PaymentDeclined
        'error'     -> raise PaymentGatewayError
    """
    if force_outcome is not None and force_outcome not in VALID_OUTCOMES:
        raise ValueError(f"force_outcome must be one of {VALID_OUTCOMES}")

    if simulate_latency:
        # Real gateways take 50–250 ms. Latency matters because the
        # surrounding transaction holds row locks while we wait.
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
    # error
    logger.error("charge gateway-error order=%s amount=%s", order_id, amount)
    raise PaymentGatewayError(f"Gateway error for order {order_id}")
