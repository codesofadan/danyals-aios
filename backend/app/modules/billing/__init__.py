"""Billing module (Part 8 Phase 2H): the staff-only invoice ledger. RECORDS ONLY -
there is no payment gateway in v1.

Public surface is the router; the module owns its schemas / repo / service / tasks.
See ``router.py`` for the endpoint map, the tables/migration it owns, and the
load-bearing scope rule (MRR is subscription-derived, never invoice-derived).
"""

from __future__ import annotations

from app.modules.billing.router import router

__all__ = ["router"]
