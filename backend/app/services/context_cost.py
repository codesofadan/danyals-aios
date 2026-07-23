"""P6B-4: cost-gated wrappers over the context module's AI provider seams.

Every context-module LLM (summarize) and embedding call MUST flow through the
existing per-call cost gate (``app/services/cost_gate.py``) so no context AI spend
can bypass the money-dial, per-client budget caps, or the org daily spend-stop.
These wrappers are the ONLY way the compaction engine (P6B-5) touches a provider:
it receives a ``Summarizer`` / ``Embedder`` (the Protocol), and because that is a
``GatedSummarizer`` / ``GatedEmbedder`` it CANNOT reach the raw provider -- every
invocation is preceded by a ``gate.evaluate`` decision.

The three-step gate contract is reused verbatim (mirrors ``workers/tasks/audit.py``):

    build GateContext -> gate.evaluate(ctx) -> if allowed: provider call + gate.commit

* ``off`` / ``byhand`` / ``blocked_cap`` / ``blocked_daily`` -> the inner provider
  is NEVER called and a typed ``ContextSpendBlocked(outcome)`` is raised. The
  compaction worker catches it and HOLDS the freshness watermark (degrade), it
  does not crash.
* Embeddings cache on the **content checksum** (sha256 of the text): a re-embed of
  UNCHANGED text is a gate ``cached`` hit -> cost 0, and the previously stored
  vector is returned from the cache instead of paying the provider again.

This is a pure seam: it never reimplements budget logic and never calls a provider
except through the wrapped ``inner``.
"""

from __future__ import annotations

import hashlib

from app.config import Settings
from app.db.database import privileged_connection
from app.services import pricing
from app.services.cost_gate import CostGate, GateContext, GateOutcome
from integrations.embeddings import Embedder
from integrations.llm import LLMResult, Summarizer

# Provider labels stamped onto the cost_log rows (match the dial features).
_LLM_PROVIDER = "Anthropic"
_EMBED_PROVIDER = "Voyage"
# Dial feature keys these wrappers gate against (see app/schemas/cost.py).
_LLM_FEATURE = "context"
_EMBED_FEATURE = "context_embed"
_JOB_TYPE = "context"

# An (entity_type, entity_id) pair, used only to group the cost-log rows.
Entity = tuple[str, str]


class ContextSpendBlocked(RuntimeError):  # noqa: N818 - a control-flow signal (caught by the worker to degrade), deliberately not an *Error
    """Raised when the gate denies a context AI call (no provider call happened).

    ``outcome`` is the gate's verdict: ``skip`` (dial off), ``manual`` (dial
    by-hand), ``blocked_cap`` (client budget cap), or ``blocked_daily`` (org daily
    spend-stop / manual halt). The compaction worker catches this and degrades
    (holds the watermark) instead of crashing.
    """

    def __init__(self, outcome: GateOutcome) -> None:
        super().__init__(f"context AI spend blocked by the cost gate: {outcome}")
        self.outcome: GateOutcome = outcome


def content_checksum(text: str) -> str:
    """The sha256 hex digest of ``text`` -- the embedding cache key.

    Unchanged text has an identical checksum, so its embedding is a gate ``cached``
    hit ($0) that returns the stored vector rather than re-paying the provider.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _job_id(entity: Entity | None) -> str:
    """Group a run's cost-log rows under the entity (``type:id``) or ``""``."""
    return f"{entity[0]}:{entity[1]}" if entity else ""


class GatedSummarizer:
    """A ``Summarizer`` that meters every summarize call through the cost gate.

    Satisfies the ``Summarizer`` Protocol, so the compaction engine treats it as
    an ordinary summarizer and can never reach ``inner`` (the raw provider)
    directly. Summarize is not cached (each fold is unique), so ``cache_key`` is
    ``None`` and every allowed call is a fresh, committed spend.
    """

    def __init__(
        self,
        inner: Summarizer,
        gate: CostGate,
        *,
        settings: Settings,
        client_id: str | None,
        entity: Entity | None = None,
    ) -> None:
        self._inner = inner
        self._gate = gate
        self._settings = settings
        self._client_id = client_id
        self._entity = entity

    def _ctx(self) -> GateContext:
        return GateContext(
            feature_key=_LLM_FEATURE,
            client_id=self._client_id,
            provider=_LLM_PROVIDER,
            estimated_cost=self._settings.context_summarize_cost_estimate,
            job_id=_job_id(self._entity),
            job_type=_JOB_TYPE,
            cache_key=None,
        )

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        ctx = self._ctx()
        decision = self._gate.evaluate(ctx)
        if not decision.allowed:
            raise ContextSpendBlocked(decision.outcome)
        result = self._inner.summarize(prompt, model=model, max_tokens=max_tokens)
        # Commit the ACTUAL spend computed at RUNTIME from the call's real token
        # usage x the model's unit price (pricing.py) -- NOT the flat estimate. The
        # estimate stays only as the upfront pre-check number the evaluate() above
        # needed before usage was known.
        actual = pricing.anthropic_cost(
            self._settings,
            model=model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        self._gate.commit(ctx, actual)
        return result


class GatedEmbedder:
    """An ``Embedder`` that meters every embedding through the cost gate.

    Satisfies the ``Embedder`` Protocol (including ``dim``). The cache key is the
    per-text **content checksum**, so unchanged text re-embeds for $0 (a gate
    ``cached`` hit) and its stored vector is reused. A batch is split into cached
    hits (served from the cache) and misses (embedded once, each committed and
    cached); order is preserved.
    """

    def __init__(
        self,
        inner: Embedder,
        gate: CostGate,
        *,
        settings: Settings,
        client_id: str | None,
        entity: Entity | None = None,
    ) -> None:
        self._inner = inner
        self._gate = gate
        self._settings = settings
        self._client_id = client_id
        self._entity = entity
        # Same dimension as the wrapped embedder so vectors round-trip unchanged.
        self.dim: int = inner.dim

    def _ctx(self, checksum: str) -> GateContext:
        return GateContext(
            feature_key=_EMBED_FEATURE,
            client_id=self._client_id,
            provider=_EMBED_PROVIDER,
            estimated_cost=self._settings.context_embed_cost_estimate,
            job_id=_job_id(self._entity),
            job_type=_JOB_TYPE,
            cache_key=checksum,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        results: list[list[float] | None] = [None] * len(texts)
        # Unique misses in first-seen order: identical text within one batch is
        # embedded (and paid for) exactly once, not per occurrence.
        miss_order: list[str] = []
        miss_positions: dict[str, list[int]] = {}
        miss_ctx: dict[str, GateContext] = {}

        for i, text in enumerate(texts):
            checksum = content_checksum(text)
            if checksum in miss_positions:
                miss_positions[checksum].append(i)
                continue
            ctx = self._ctx(checksum)
            decision = self._gate.evaluate(ctx)
            if decision.outcome == "cached":
                # Unchanged text: $0 hit, reuse the stored vector (evaluate already
                # logged the cached row at cost 0). ``cached_value`` is non-None
                # here -- the gate only returns ``cached`` when the cache held a value.
                hit = decision.cached_value
                results[i] = list(hit) if hit is not None else []
            elif decision.allowed:
                miss_order.append(checksum)
                miss_positions[checksum] = [i]
                miss_ctx[checksum] = ctx
            else:
                raise ContextSpendBlocked(decision.outcome)

        if miss_order:
            miss_texts = [_first_text(texts, miss_positions[c]) for c in miss_order]
            vectors = self._inner.embed(miss_texts)
            for checksum, text, vector in zip(miss_order, miss_texts, vectors, strict=True):
                # Commit the ACTUAL embedding spend from the real text's token count
                # x the Voyage per-token price (the Embedder seam surfaces no token
                # count, so it is approximated from the embedded text) -- NOT the flat
                # estimate. Warm the cache so an unchanged re-embed is a $0 hit.
                actual = pricing.voyage_embed_cost(
                    self._settings, tokens=pricing.approx_tokens(text)
                )
                self._gate.commit(miss_ctx[checksum], actual, cache_value=vector)
                for pos in miss_positions[checksum]:
                    results[pos] = vector

        # Every slot is filled (cached hit or freshly embedded); assert for mypy.
        return [vector for vector in results if vector is not None]


def _first_text(texts: list[str], positions: list[int]) -> str:
    """The text at the first position of a checksum group (all are identical)."""
    return texts[positions[0]]


def resolve_budget_client(entity_type: str, entity_id: str) -> str | None:
    """Resolve an entity to the client whose budget/spend-stop the gate applies.

    * ``client`` -> itself (the client id IS the budget client).
    * ``site``   -> its owning ``client_id``.
    * ``user``   -> that user's ``client_id`` IFF it is a portal client (per
      migration 0010 ``client_id`` is set iff role='client'); a staff user has a
      NULL ``client_id`` -> ``None`` (org-level, still under the daily spend-stop).

    Feeds ``GateContext.client_id``. ``None`` means org-level: no per-client cap
    applies, but the org daily spend-stop still does. Uses the privileged
    connection (workers hold no user JWT); all values are bound params.
    """
    if entity_type == "client":
        return entity_id
    if entity_type == "site":
        return _client_id_of(_SITE_CLIENT_SQL, entity_id)
    if entity_type == "user":
        return _client_id_of(_USER_CLIENT_SQL, entity_id)
    return None


# Static, parameterized lookups (no dynamic SQL): id is always a bound param.
_SITE_CLIENT_SQL = "select client_id from public.sites where id = %s limit 1"
_USER_CLIENT_SQL = "select client_id from public.users where id = %s limit 1"


def _client_id_of(query: str, entity_id: str) -> str | None:
    """Read the ``client_id`` column for ``entity_id`` on the privileged connection."""
    with privileged_connection() as cur:
        cur.execute(query, (entity_id,))
        row = cur.fetchone()
    if not row or not row.get("client_id"):
        return None
    return str(row["client_id"])
