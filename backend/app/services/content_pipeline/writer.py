"""The doctrine-carrying writer - the seam every generating stage calls.

This is the abstraction the v1 generator lacked. There, a stage sent a bare user
prompt and inherited whatever system prompt the transport happened to default to
(which for the whole module's life was the context-COMPACTION contract). Here a stage
names itself, and the writer assembles the doctrine that governs that stage, sends it
as ordered cache blocks, and records what it used.

THREE THINGS IT DOES THAT A RAW `summarize` CALL CANNOT:

  1. ASSEMBLES THE RIGHT DOCTRINE. `doctrine_routes.assemble` turns
     (stage, page_type, vertical, framework) into three blocks ordered most-stable
     first, because the API caches on a PREFIX.
  2. CACHES ONLY WHERE IT PAYS. A cache write costs 1.25x and a read 0.1x, so a block
     used ONCE is 25% more expensive cached than plain. `expected_calls` is passed
     through to `cache_flags`, which is why single-call stages send their variable
     blocks uncached.
  3. RECORDS PROVENANCE AS IT GOES. Which chunks governed the call, which were dropped
     for not fitting, the real cache accounting, and the cost. This cannot be
     reconstructed afterwards - the routing table will have moved on - so it is
     written per call or not at all.

The writer it wraps is the COST-GATED one, never a raw provider. A spend block raises
out of `summarize` and the stage degrades; nothing here catches it, because a stage
that swallowed a spend block would keep writing on a halted budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from app.services.doctrine_routes import assemble
from integrations.llm import EmptyCompletionError, SystemSummarizer

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.config import Settings


# Ceiling for the adaptive retry.
#
# 20k, not higher, and the limit is the SDK's not ours: a non-streaming request whose
# `max_tokens` implies it could run past 10 minutes is refused outright with
# "Streaming is required for operations that may take longer than 10 minutes". Found
# by a retry doubling into that wall and surfacing as an opaque BadRequestError on the
# second batch of a page.
#
# 20k still clears the deepest reasoning measured (~10k) plus a long answer. Going
# beyond it means moving this seam to streaming, which is a bigger change than any
# stage currently needs.
MAX_ADAPTIVE_TOKENS = 20_000


class UsageRecorder(Protocol):
    """The provenance sink. `ContentPlanningStore` satisfies this."""

    def record_doctrine_usage(self, **kwargs: object) -> None: ...


@dataclass
class WriteAccounting:
    """Running totals for one stage, folded into its StageResult."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    cost: float = 0.0
    chunk_ids: list[str] = field(default_factory=list)
    dropped_chunk_ids: list[str] = field(default_factory=list)


class DoctrineWriter:
    """Wraps a cost-gated writer and gives it the doctrine for a stage."""

    def __init__(
        self,
        inner: SystemSummarizer,
        *,
        settings: Settings,
        model: str,
        recorder: UsageRecorder | None = None,
        job_id: str | None = None,
        engagement_id: str | None = None,
    ) -> None:
        self._inner = inner
        self._settings = settings
        self._model = model
        self._recorder = recorder
        self._job_id = job_id
        self._engagement_id = engagement_id

    def write(
        self,
        stage: str,
        prompt: str,
        *,
        page_type: str = "service",
        vertical: str | None = None,
        framework: str | None = None,
        max_tokens: int = 1024,
        expected_calls: int = 1,
        model: str | None = None,
        accounting: WriteAccounting | None = None,
    ) -> str:
        """Send one prompt under this stage's doctrine and return the text.

        ``expected_calls`` is how many calls THIS STAGE will make, not the page's
        total. It decides whether the variable blocks are worth a cache breakpoint,
        and passing 1 for a stage that makes six is a real (if small) waste.
        """
        blocks = assemble(
            stage, page_type=page_type, vertical=vertical, framework=framework
        )
        used_model = model or self._model

        # ADAPTIVE BUDGET. This model reasons before it writes, and how much reasoning
        # a prompt provokes is not knowable in advance - measured on real calls it
        # ranged from a few hundred tokens to ~10,000 for the SAME stage on different
        # inputs. A fixed allowance is therefore either wasteful or occasionally too
        # small, and too small means `EmptyCompletionError`: the whole budget spent
        # thinking, no text, a blank section.
        #
        # So: try the stage's budget, and if reasoning consumed it, retry ONCE with
        # double. Normal calls stay cheap; the rare deep-reasoning one still lands.
        # The failed attempt's tokens are real spend and are counted, because
        # pretending a paid-for failure was free is how a cost model drifts.
        cost = 0.0
        result = None
        budget = max_tokens
        for attempt in range(2):
            try:
                result = self._inner.summarize(
                    prompt,
                    model=used_model,
                    max_tokens=budget,
                    system=blocks.as_system(),
                    cache=blocks.cache_flags(expected_calls=expected_calls),
                )
                break
            except EmptyCompletionError:
                if accounting is not None:
                    # The spend happened even though no text came back.
                    accounting.calls += 1
                if attempt == 1:
                    raise
                budget = min(budget * 2, MAX_ADAPTIVE_TOKENS)
        assert result is not None

        cost = self._cost(used_model, result)
        if accounting is not None:
            accounting.calls += 1
            accounting.input_tokens += result.input_tokens
            accounting.output_tokens += result.output_tokens
            accounting.cache_write_tokens += result.cache_write_tokens
            accounting.cache_read_tokens += result.cache_read_tokens
            accounting.cost += cost
            accounting.chunk_ids.extend(blocks.chunk_ids)
            accounting.dropped_chunk_ids.extend(blocks.dropped_chunk_ids)

        if self._recorder is not None:
            self._recorder.record_doctrine_usage(
                stage=stage,
                model=used_model,
                chunk_ids=list(blocks.chunk_ids),
                dropped_chunk_ids=list(blocks.dropped_chunk_ids),
                job_id=self._job_id,
                engagement_id=self._engagement_id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cache_write_tokens=result.cache_write_tokens,
                cache_read_tokens=result.cache_read_tokens,
                cost=cost,
            )
        return result.text

    def _cost(self, model: str, result: object) -> float:
        """Real cost including the cache multipliers.

        A cost computed from `input_tokens` alone is wrong in BOTH directions: it
        over-charges a cached read (billed at 0.1x) and under-charges the write that
        created it (1.25x). Since the doctrine prefix dwarfs the user turn, getting
        this wrong would make the per-page figure meaningless.
        """
        from app.services import pricing

        base = pricing.anthropic_cost(
            self._settings,
            model=model,
            input_tokens=getattr(result, "input_tokens", 0),
            output_tokens=getattr(result, "output_tokens", 0),
        )
        write_tokens = getattr(result, "cache_write_tokens", 0)
        read_tokens = getattr(result, "cache_read_tokens", 0)
        if not (write_tokens or read_tokens):
            return base
        tier = pricing.anthropic_tier(model)
        price_in, _price_out = pricing.anthropic_prices(self._settings, tier)
        cache_cost = (write_tokens * 1.25 + read_tokens * 0.10) * price_in / 1_000_000.0
        return base + cache_cost
