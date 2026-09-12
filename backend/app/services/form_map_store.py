"""Persistence for the semantic form-mapping cache (``0140``).

Split from ``form_intelligence`` on purpose: that module is PURE (no DB, no network,
no clock) so the privacy boundary and the response validation are unit-tested against
hand-built digests. This one is the only part that touches Postgres.

Reads and writes go through ``rls_connection`` on the CALLER's identity - there is no
service_role path here. An operator-token request therefore writes the cache as the
staff user the token belongs to, so a cache write can never escape the tenant boundary
or be attributed to nobody.
"""

from __future__ import annotations

from psycopg.types.json import Jsonb

from app.db.database import rls_connection
from app.services.form_intelligence import FieldMapping, FormPlan

#: A cache row older than this is recomputed even on a fingerprint hit. A form can
#: change in ways the fingerprint cannot see - a field that kept its name and label but
#: changed meaning, or a selector the site rewrote - and a cache with no ceiling turns a
#: one-off bad mapping into a permanent one.
MAX_AGE_DAYS = 90


class FormMapStore:
    """RLS-scoped access to ``public.form_field_maps``."""

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def get(self, fingerprint: str) -> list[FieldMapping] | None:
        """The cached mapping for this form, or ``None``.

        A row past ``MAX_AGE_DAYS`` is treated as a MISS rather than deleted here: the
        recompute writes over it, and deleting on a read path would make a read fail
        for a lead-only permission it does not need.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select mappings from public.form_field_maps "
                "where fingerprint = %s "
                "  and created_at > now() - make_interval(days => %s) "
                "limit 1",
                (fingerprint, MAX_AGE_DAYS),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return [
            FieldMapping(
                index=int(m.get("index", 0) or 0),
                selector=str(m.get("selector") or ""),
                key=str(m.get("key") or ""),
                confidence=float(m.get("confidence") or 0.0),
            )
            for m in (row["mappings"] or [])
            if isinstance(m, dict) and m.get("selector")
        ] or None

    def touch(self, fingerprint: str) -> None:
        """Record a cache HIT. Best-effort accounting, never the point of the request."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "update public.form_field_maps "
                "set use_count = use_count + 1, last_used_at = now() "
                "where fingerprint = %s",
                (fingerprint,),
            )

    def put(
        self,
        plan: FormPlan,
        *,
        host: str,
        model: str,
        directory_id: str | None = None,
    ) -> None:
        """Store a freshly computed plan.

        Upserts on the fingerprint so a recompute REPLACES a stale row rather than
        colliding with it. ``use_count`` is reset because the counter describes the
        stored mapping, and this is a different one.

        An empty plan is not stored: ``0140``'s CHECK refuses it anyway, and a cached
        "nothing maps here" would suppress the retry that might succeed.
        """
        if not plan.mappings:
            return
        payload = [
            {"index": m.index, "selector": m.selector, "key": m.key,
             "confidence": round(m.confidence, 3)}
            for m in plan.mappings
        ]
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "insert into public.form_field_maps "
                "(fingerprint, host, directory_id, mappings, model, "
                " fields_fillable, fields_total, created_by) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s) "
                "on conflict (fingerprint) do update set "
                "  host = excluded.host, "
                "  directory_id = excluded.directory_id, "
                "  mappings = excluded.mappings, "
                "  model = excluded.model, "
                "  fields_fillable = excluded.fields_fillable, "
                "  fields_total = excluded.fields_total, "
                "  use_count = 0, "
                "  created_at = now()",
                (plan.fingerprint, host[:255], directory_id, Jsonb(payload), model[:120],
                 len(plan.to_fill), len(plan.mappings), self._user_id),
            )

    def purge_host(self, host: str) -> int:
        """Drop every cached mapping for one host (lead-only, per ``0140``'s policy).

        The escape hatch for a directory that redesigned its form in a way the
        fingerprint did not catch - a field that kept its name and label but changed
        meaning. Recomputing costs one inference per form; being wrong costs listings.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "delete from public.form_field_maps where host = %s", (host.strip().lower(),)
            )
            return int(cur.rowcount or 0)


def cached_plan(store: FormMapStore, fingerprint: str) -> FormPlan | None:
    """A ``FormPlan`` rebuilt from the cache, marked ``cached`` so the caller can
    report an honest $0 run."""
    mappings = store.get(fingerprint)
    if not mappings:
        return None
    return FormPlan(fingerprint=fingerprint, mappings=tuple(mappings), cached=True)


def store_for(user_id: str) -> FormMapStore:
    return FormMapStore(user_id)


__all__: list[str] = [
    "MAX_AGE_DAYS",
    "FormMapStore",
    "cached_plan",
    "store_for",
]

