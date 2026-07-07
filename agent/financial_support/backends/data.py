"""Seed data for the mock backends.

Small, hand-written fixtures so the demo is deterministic and every number on
screen is explainable. The famous demo case lives here: charge ``TXN-1001`` is
**$50.00** — the agent will try to refund **$500.00** against it, and the
invariant (not the LLM judge) is what catches it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Charge:
    charge_id: str
    amount: float
    currency: str
    description: str
    refundable: bool = True


@dataclass
class Customer:
    customer_id: str
    name: str
    email: str
    tier: str
    charges: dict[str, Charge] = field(default_factory=dict)


# The session's own customer for the demo. `look_up_customer` reads THIS one
# under the healthy scenario; the `wrong_account` scenario makes it read CUST-002
# instead (a cross-account PII leak -> Case 3 bridge).
DEFAULT_SESSION_CUSTOMER_ID = "CUST-001"

CUSTOMERS: dict[str, Customer] = {
    "CUST-001": Customer(
        customer_id="CUST-001",
        name="Alice Martin",
        email="alice.martin@example.com",
        tier="standard",
        charges={
            "TXN-1001": Charge("TXN-1001", 50.00, "USD", "Monthly subscription"),
            "TXN-1002": Charge("TXN-1002", 12.99, "USD", "Add-on: extra storage"),
        },
    ),
    # A *different* customer — used to prove cross-account reads are wrong.
    "CUST-002": Customer(
        customer_id="CUST-002",
        name="Bob Nguyen",
        email="bob.nguyen@example.com",
        tier="premium",
        charges={
            "TXN-2001": Charge("TXN-2001", 999.00, "USD", "Annual plan"),
        },
    ),
}


def get_customer(customer_id: str) -> Customer | None:
    return CUSTOMERS.get(customer_id)


def get_charge(customer_id: str, charge_id: str) -> Charge | None:
    customer = CUSTOMERS.get(customer_id)
    if not customer:
        return None
    return customer.charges.get(charge_id)
