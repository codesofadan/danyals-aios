"""The planning layer above content_jobs (migrations 0084-0092).

Engagements, keyword plans, topical maps, SME dossiers, versions, brand kits and the
provenance ledger - the decisions around a page, which `content_jobs` has never had
anywhere to record.

No router yet: the pipeline (P3) is the first consumer, and exposing an API before the
shape has been exercised by a real caller would freeze a contract that is still moving.
"""
