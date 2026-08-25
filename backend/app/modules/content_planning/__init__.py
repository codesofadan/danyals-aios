"""The planning layer above content_jobs (migrations 0084-0092).

Engagements, keyword plans, topical maps, SME dossiers, versions, brand kits and the
provenance ledger - the decisions around a page, which `content_jobs` has never had
anywhere to record.

The router is READ-ONLY. Every write path runs in the pipeline, where the SME halt, the
uniqueness gate and the engagement budget live; an endpoint that enqueued production
would sit in FRONT of those checks rather than behind them.
"""

from app.modules.content_planning.router import router

__all__ = ["router"]
