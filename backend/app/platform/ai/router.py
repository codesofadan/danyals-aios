"""``ModelRouter`` - the ONE door to a model call.

``06-AI-STACK.md`` §3. Every model call in the system goes through here, and this module
is responsible for the six things that were previously done differently at each of the
~15 call sites that construct their own SDK client or their own gated wrapper:

1. choose the model from the TASK TIER, never from a string a caller typed;
2. apply the prompt-cache breakpoints in stable-prefix-first order;
3. pass the cost gate BEFORE the provider is contacted;
4. commit the ACTUAL cost from real token usage, cache reads and writes included;
5. emit the trace span with ``client_id``, ``job_id``, ``module``, ``task_tier``,
   ``cost_cents``, ``cache_hit`` and the PROMPT HASH;
6. translate provider errors into our taxonomy.

WHAT THIS IS BUILT ON, AND WHY THAT IS THE DESIGN AND NOT A SHORTCUT.
The backend seam is :class:`integrations.llm.SystemSummarizer` - the Protocol this repo
already routes every Anthropic call through. Re-implementing the SDK call here would
have produced a SECOND place that knows about cache breakpoints, the reasoning token
floor and ``EmptyCompletionError``, and the two would have drifted. Reusing the seam
also means every existing ``FakeSummarizer`` satisfies this router unchanged, so the
whole suite still runs offline with zero keys - which is the property that makes a graph
testable at all.

THE CAPABILITY RULE (§3, "Backends").
A backend that cannot do adaptive thinking or effort control is *feature-degraded by
definition*, and the doc's rule is that a change of backend must never change output
quality SILENTLY. Silence is the thing being forbidden, so this router does two
different things depending on whether the missing feature IS the quality contract:

* ``reasoning`` and ``judge`` tiers **block** (:class:`CapabilityMissingError`). A judge
  that does not think is not a cheaper judge, it is a different grader - and an eval
  calibrated against one says nothing about the other.
* ``drafting`` / ``structured`` / ``bulk`` **proceed and record the degradation** on
  :class:`ModelResult.degraded`, in the log line and in the trace span. This matters for
  this deployment specifically: the live backend is an OpenAI-compatible proxy
  (``anthropic_base_url``), so blocking every drafting call on a missing ``effort``
  parameter would stop all work to enforce a preference.

``settings.ai_router_strict_tiers`` moves the line if an operator wants it moved.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.config import Settings
from app.logging_setup import get_logger
from app.platform.ai import prompts as prompt_registry
from app.platform.ai import tiers as tiers_module
from app.platform.ai import tracing
from app.platform.ai.tiers import TaskTier, TierSpec, spec_for
from app.services import pricing
from app.services.cost_gate import CostGate, GateContext, GateDecision, GateOutcome
from integrations.llm import LLMResult, SystemSummarizer

logger = get_logger("platform.ai.router")

#: The estimate-vs-actual variance §5 step 4 says raises a task. A module that is
#: consistently past this has a broken estimator, and the gate it feeds is therefore
#: making decisions on a number that does not describe the call it is about to allow.
VARIANCE_ALERT_RATIO = 0.25

#: The output size the estimator assumes when a caller does not declare one.
#:
#: NOT ``max_tokens // 2``, which was the first thing written here and was wrong in a way
#: that matters. ``max_tokens`` is a RUNAWAY GUARD, not a purchase - ``integrations/llm.py``
#: says so in as many words where it applies an 8192 reasoning floor ("a ceiling the model
#: does not reach costs nothing"), and the drafting tier's ceiling is 16000. Estimating
#: half of that prices a 900-word Web 2.0 article at ~$0.20 when it actually costs ~$0.03,
#: and the estimate is what the COST GATE decides on: a client on a $5 daily budget would
#: have been refused after 25 articles it could comfortably afford.
#:
#: 1500 output tokens is roughly a 1000-word answer - the size of the work this system
#: actually asks for. A caller that knows better passes ``expected_output_tokens``, and
#: the variance check above is the feedback loop that says when this default is wrong.
DEFAULT_EXPECTED_OUTPUT_TOKENS = 1500


class Capability(str):
    """A feature a backend either has or does not. Plain strings, compared by value."""


CAP_SYSTEM_BLOCKS = "system_blocks"
CAP_PROMPT_CACHE = "prompt_cache"
CAP_ADAPTIVE_THINKING = "adaptive_thinking"
CAP_EFFORT = "effort"
CAP_COUNT_TOKENS = "count_tokens"

#: Tiers whose declared configuration IS their quality contract - see the module header.
STRICT_TIERS: frozenset[TaskTier] = frozenset({TaskTier.REASONING, TaskTier.JUDGE})


class ModelRouterError(RuntimeError):
    """Base of the router's error taxonomy."""


class CapabilityMissingError(ModelRouterError):
    """The configured backend cannot honour a feature this call's tier requires.

    Raised, never worked around. The caller is a job, and a job that blocks with this
    reason is visible in the ledger; a job that quietly produced a lower-grade answer is
    not, and the difference only surfaces as a client complaint weeks later.
    """


class CostBlockedError(ModelRouterError):
    """The cost gate refused this call. Nothing was spent and no provider was contacted.

    Carries the gate's machine-readable ``outcome`` so a job's reason code can be derived
    from it rather than parsed out of prose.
    """

    def __init__(self, outcome: GateOutcome, message: str = "") -> None:
        super().__init__(message or f"spend_blocked:{outcome}")
        #: Typed as the gate's own verdict rather than `str`, because callers translate
        #: it into other gate-shaped exceptions (`ContentSpendBlocked`) and into job
        #: reason codes. A plain `str` here compiles and then fails at the first
        #: translation that expects the real vocabulary.
        self.outcome: GateOutcome = outcome


@dataclass(frozen=True)
class ModelRequest:
    """One prospective model call, fully described before anything is spent."""

    task: TaskTier
    prompt: str
    system: str | Sequence[str] | None = None
    #: Which system blocks carry a cache breakpoint. Defaults to all of them; pass it
    #: when a stage makes ONE call, where a cached block costs 1.25x and saves nothing.
    cache: Sequence[bool] | None = None
    max_tokens: int | None = None
    #: What the caller EXPECTS this call to produce, for the pre-call estimate. Distinct
    #: from ``max_tokens``, which is the runaway ceiling - see
    #: :data:`DEFAULT_EXPECTED_OUTPUT_TOKENS` for why conflating the two makes the cost
    #: gate refuse work a client can afford.
    expected_output_tokens: int | None = None
    module: str = ""
    client_id: str | None = None
    client_name: str = ""
    job_id: str = ""
    job_type: str = ""
    #: The money dial this call is metered against (``content``, ``backlinks``, ...).
    feature_key: str = ""
    #: Set when the system/prompt came from the registry, so the hash reaches the trace.
    prompt_id: str = ""


@dataclass(frozen=True)
class ModelResult:
    """What one routed call produced, and everything needed to audit it afterwards."""

    text: str
    model: str
    task: TaskTier
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    estimated_usd: float = 0.0
    #: Capabilities the tier asked for that the backend could not honour. EMPTY is the
    #: normal case; anything in here means this output is not what the tier specifies.
    degraded: tuple[str, ...] = ()
    prompt_id: str = ""
    prompt_sha: str = ""
    backend: str = ""
    traced: bool = False

    @property
    def cache_hit(self) -> bool:
        return self.cache_read_tokens > 0

    @property
    def variance(self) -> float:
        """Signed (actual - estimate) / estimate. 0.0 when there was no estimate."""
        if self.estimated_usd <= 0:
            return 0.0
        return (self.cost_usd - self.estimated_usd) / self.estimated_usd

    @property
    def trace_fields(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "task_tier": str(self.task),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_hit": self.cache_hit,
            "cost_cents": round(self.cost_usd * 100, 4),
            "degraded": list(self.degraded),
            "prompt_id": self.prompt_id,
            "prompt_sha": self.prompt_sha,
            "backend": self.backend,
        }


@runtime_checkable
class ModelBackend(Protocol):
    """What the router needs from whatever actually talks to a provider.

    ``capabilities`` is declared by the backend rather than inferred by the router,
    because only the backend knows what its endpoint accepts. A backend that lies here
    produces the exact silent-quality-change the capability rule exists to prevent, so
    it is the one field a backend must get right.
    """

    name: str
    capabilities: frozenset[str]

    def complete(
        self,
        *,
        model: str,
        prompt: str,
        system: str | Sequence[str] | None,
        cache: Sequence[bool] | None,
        max_tokens: int,
        effort: str | None,
        adaptive_thinking: bool,
    ) -> LLMResult: ...


class SummarizerBackend:
    """Adapts any :class:`integrations.llm.SystemSummarizer` into a :class:`ModelBackend`.

    This is the backend the whole system runs on today. It covers both real cases with
    one class because the difference between them is CONFIGURATION, not code:

    * ``anthropic_base_url`` unset -> the official Anthropic API, and the summarizer's
      system-block + cache-breakpoint handling is honoured end to end;
    * ``anthropic_base_url`` set -> the OpenAI-compatible proxy this deployment actually
      uses, which accepts the same call shape but guarantees nothing about caching.

    Hence ``supports_cache``: an operator running through a proxy declares it, and the
    router stops claiming cache hits it cannot verify. Neither path can do ``effort`` or
    adaptive thinking through this seam, so neither is advertised - which is what makes
    the strict tiers block honestly instead of pretending.
    """

    def __init__(
        self,
        summarizer: SystemSummarizer,
        *,
        name: str = "summarizer",
        supports_cache: bool = True,
    ) -> None:
        self._inner = summarizer
        self.name = name
        caps = {CAP_SYSTEM_BLOCKS}
        if supports_cache:
            caps.add(CAP_PROMPT_CACHE)
        self.capabilities = frozenset(caps)

    def complete(
        self,
        *,
        model: str,
        prompt: str,
        system: str | Sequence[str] | None,
        cache: Sequence[bool] | None,
        max_tokens: int,
        effort: str | None,
        adaptive_thinking: bool,
    ) -> LLMResult:
        # `effort` / `adaptive_thinking` are accepted and DROPPED here deliberately: the
        # router has already decided what a missing capability means for this tier
        # (block, or proceed and record), so silently ignoring them at this level is the
        # honest behaviour rather than a second, hidden policy.
        return self._inner.summarize(
            prompt, model=model, max_tokens=max_tokens, system=system, cache=cache
        )


class ModelRouter:
    """The single door. Construct once per process and hand it to graphs and services."""

    def __init__(
        self,
        backend: ModelBackend | None,
        gate: CostGate,
        settings: Settings,
        *,
        default_feature_key: str = "content",
        models: dict[TaskTier, str] | None = None,
    ) -> None:
        self._backend = backend
        self._gate = gate
        self._settings = settings
        self._default_feature = default_feature_key
        #: Per-tier model overrides. The TIER stays the contract a caller states; WHICH
        #: model serves it is deployment configuration, because a gateway publishes its
        #: own catalog - this one answers an id it does not carry with a 503, not a
        #: fallback. Empty means "use the table in `tiers.py`".
        self._models = dict(models or {})
        #: Running totals for the caller that wants to report what a run cost without
        #: re-reading the ledger. Never used for a gate decision - the ledger decides.
        self.calls = 0
        self.spent: float = 0.0

    @property
    def configured(self) -> bool:
        """Whether a backend exists at all. False means every call degrades upstream."""
        return self._backend is not None

    @property
    def backend_name(self) -> str:
        return self._backend.name if self._backend else ""

    def complete(self, request: ModelRequest) -> ModelResult:
        """Route one call: tier -> model -> gate -> backend -> commit actual -> trace.

        Raises :class:`CapabilityMissingError` when a strict tier cannot be honoured and
        :class:`CostBlockedError` when the gate refuses. Both leave nothing spent, and
        both are meant to reach the job engine as a BLOCK rather than a failure.
        """
        if self._backend is None:
            raise CapabilityMissingError(
                "no model backend configured: set anthropic_api_key (and install the "
                "[ai] extra) before routing a model call"
            )
        spec = spec_for(request.task)
        # The TIER is the contract; the model id that serves it is deployment
        # configuration - a gateway exposes its own catalog and answers an id it does not
        # carry with a 503, not a fallback. See `tier_models`.
        model = self._models.get(request.task, spec.model)
        degraded = self._resolve_capabilities(spec, request.task)
        max_tokens = int(request.max_tokens or spec.max_tokens)
        prompt = prompt_registry.get(request.prompt_id) if request.prompt_id else None

        estimate = self._estimate(request, spec, max_tokens, model)
        ctx = self._gate_context(request, estimate)
        decision: GateDecision = self._gate.evaluate(ctx)
        if not decision.allowed:
            logger.info(
                "model_call_blocked",
                module=request.module, tier=str(request.task), outcome=decision.outcome,
                estimate=estimate, client_id=request.client_id or "-",
            )
            raise CostBlockedError(decision.outcome)

        fields: dict[str, Any] = {
            "module": request.module,
            "task_tier": str(request.task),
            "client_id": request.client_id or "",
            "job_id": request.job_id,
            "model": model,
            "backend": self._backend.name,
            "prompt": request.prompt,
            "system": request.system,
        }
        if prompt is not None:
            fields.update(prompt.trace_fields)

        with tracing.span(f"model.{request.module or 'call'}.{request.task}", **fields) as sp:
            result = self._backend.complete(
                model=model,
                prompt=request.prompt,
                system=request.system,
                cache=request.cache if CAP_PROMPT_CACHE in self._backend.capabilities else None,
                max_tokens=max_tokens,
                effort=spec.effort,
                adaptive_thinking=spec.adaptive_thinking,
            )
            actual = pricing.anthropic_cost_cached(
                self._settings,
                model=model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cache_write_tokens=result.cache_write_tokens,
                cache_read_tokens=result.cache_read_tokens,
            )
            self._gate.commit(ctx, actual)
            self.calls += 1
            self.spent += actual

            out = ModelResult(
                text=result.text,
                model=model,
                task=request.task,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                cache_read_tokens=result.cache_read_tokens,
                cache_write_tokens=result.cache_write_tokens,
                cost_usd=actual,
                estimated_usd=estimate,
                degraded=degraded,
                prompt_id=prompt.id if prompt else "",
                prompt_sha=prompt.sha if prompt else "",
                backend=self._backend.name,
                traced=tracing.state().enabled,
            )
            sp.update(**out.trace_fields, completion=result.text)

        if abs(out.variance) > VARIANCE_ALERT_RATIO and estimate > 0:
            # §5 step 4: a persistently wrong estimator makes every gate decision it
            # feeds wrong too, so this is logged as a signal rather than swallowed.
            logger.warning(
                "model_cost_variance",
                module=request.module, tier=str(request.task),
                estimate=estimate, actual=actual, variance=round(out.variance, 3),
            )
        logger.info(
            "model_call",
            module=request.module, tier=str(request.task), model=model,
            cost=actual, cache_hit=out.cache_hit, degraded=list(degraded),
            client_id=request.client_id or "-",
        )
        return out

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _resolve_capabilities(self, spec: TierSpec, task: TaskTier) -> tuple[str, ...]:
        """Which of this tier's declared features the backend cannot honour.

        Blocks for a strict tier; returns the list (for the result and the trace) for
        the rest. See the module header for why the line is drawn there.
        """
        assert self._backend is not None  # guarded by the caller
        missing: list[str] = []
        if spec.adaptive_thinking and CAP_ADAPTIVE_THINKING not in self._backend.capabilities:
            missing.append(CAP_ADAPTIVE_THINKING)
        if spec.effort and CAP_EFFORT not in self._backend.capabilities:
            missing.append(CAP_EFFORT)
        if not missing:
            return ()
        strict = task in STRICT_TIERS and bool(
            getattr(self._settings, "ai_router_strict_tiers", True)
        )
        if strict:
            raise CapabilityMissingError(
                f"backend {self._backend.name!r} cannot honour {missing} which the "
                f"{task} tier requires. A {task} call run without them is a different "
                "grader, not a cheaper one - configure a direct Anthropic backend or "
                "route this work to a tier that does not require them."
            )
        return tuple(missing)

    def _estimate(
        self, request: ModelRequest, spec: TierSpec, max_tokens: int, model: str = ""
    ) -> float:
        """Price the call BEFORE making it, so the gate decides on a real number.

        §5 says estimate with ``messages.count_tokens``, never a character heuristic.
        This seam does not expose a token counter, so the estimate falls back to
        ``pricing.approx_tokens`` - and the fallback is DECLARED rather than hidden:
        the backend does not advertise ``count_tokens``, the variance check above
        measures how wrong the estimate is, and a persistently high variance is exactly
        the signal that says "wire the real counter".
        """
        system_text = ""
        if isinstance(request.system, str):
            system_text = request.system
        elif request.system:
            system_text = "\n".join(str(block) for block in request.system)
        input_tokens = pricing.approx_tokens(request.prompt, system_text)
        expected = request.expected_output_tokens or DEFAULT_EXPECTED_OUTPUT_TOKENS
        return pricing.anthropic_cost_cached(
            self._settings,
            # Price the model that will ACTUALLY run, not the tier's default: an
            # override can move a tier onto a differently-priced gateway model, and an
            # estimate against the wrong one misinforms the gate in both directions.
            model=model or spec.model,
            input_tokens=input_tokens,
            output_tokens=min(int(expected), max_tokens),
        )

    def _gate_context(self, request: ModelRequest, estimate: float) -> GateContext:
        return GateContext(
            feature_key=request.feature_key or self._default_feature,
            client_id=request.client_id,
            provider="Anthropic",
            estimated_cost=estimate,
            job_id=request.job_id,
            job_type=request.job_type or request.module,
            client_name=request.client_name,
        )


class RouterSummarizer:
    """The REVERSE adapter: a :class:`SystemSummarizer` that routes through the router.

    :class:`SummarizerBackend` lets the router stand on the existing provider seam. This
    lets the existing CALLERS stand on the router - and that asymmetry is what makes the
    migration incremental instead of a rewrite.

    ``content_generator.generate()`` makes a dozen separate ``writer.summarize()`` calls
    per article (one per section, one for the direct-answer block, one per photo brief).
    Handing it one of these instead of a raw summarizer puts every one of those calls
    through tier selection, the cost gate, cache-aware actual-cost commitment and a
    traced span - **without changing a line of the generator**, which is a 1,000-line
    module whose output is the product.

    It also retires the duplicated gated-writer wrappers: ``_Web2GatedWriter`` and
    ``_ContentGatedWriter`` are the same class written twice, in two modules, each
    re-deriving cost from ``pricing.anthropic_cost`` - which, reading ``input_tokens``
    alone, prices every cached call wrong. This does it once, correctly.

    The ``model`` argument callers pass is DELIBERATELY IGNORED in favour of the tier.
    That is the point of a router: a caller states what kind of work it is, and the model
    table answers. The ignored value is recorded on ``requested_models`` so a caller
    passing something surprising is visible rather than silently overridden.
    """

    def __init__(
        self,
        router: ModelRouter,
        *,
        task: TaskTier = TaskTier.DRAFTING,
        module: str = "",
        feature_key: str = "",
        client_id: str | None = None,
        client_name: str = "",
        job_id: str = "",
        job_type: str = "",
    ) -> None:
        self._router = router
        self._task = task
        self._module = module
        self._feature_key = feature_key
        self._client_id = client_id
        self._client_name = client_name
        self._job_id = job_id
        self._job_type = job_type
        self.calls = 0
        self.spent: float = 0.0
        self.degraded: set[str] = set()
        self.requested_models: set[str] = set()

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | Sequence[str] | None = None,
        cache: Sequence[bool] | None = None,
    ) -> LLMResult:
        """Route one call and return it in the seam's own ``LLMResult`` shape.

        :class:`CostBlockedError` is translated back to the exception the content
        pipeline already handles (``ContentSpendBlocked``), so a gate block mid-article
        still HOLDS the placement exactly as it does today rather than becoming a new,
        unhandled failure mode at every existing call site.
        """
        self.requested_models.add(model)
        try:
            result = self._router.complete(
                ModelRequest(
                    task=self._task,
                    prompt=prompt,
                    system=system,
                    cache=cache,
                    max_tokens=max_tokens,
                    expected_output_tokens=max_tokens,
                    module=self._module,
                    client_id=self._client_id,
                    client_name=self._client_name,
                    job_id=self._job_id,
                    job_type=self._job_type,
                    feature_key=self._feature_key,
                )
            )
        except CostBlockedError as blocked:
            from app.services.content_research import ContentSpendBlocked

            raise ContentSpendBlocked(blocked.outcome) from blocked

        self.calls += 1
        self.spent += result.cost_usd
        self.degraded.update(result.degraded)
        return LLMResult(
            text=result.text,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_write_tokens=result.cache_write_tokens,
            cache_read_tokens=result.cache_read_tokens,
        )


@dataclass
class RouterDeps:
    """What a caller needs to build a router, resolved once and passed down.

    A dataclass rather than four positional arguments because graph nodes receive this
    whole bundle through the graph's config, and a bundle that grows a field should not
    ripple through every node signature.
    """

    router: ModelRouter
    settings: Settings
    tracing: tracing.TracingState = field(default_factory=tracing.state)


def build_router(
    settings: Settings,
    gate: CostGate,
    *,
    summarizer: SystemSummarizer | None = None,
    default_feature_key: str = "content",
) -> ModelRouter:
    """Construct the router for this process.

    ``summarizer`` is injected in tests (a ``FakeSummarizer``); in production it is
    resolved from settings through the existing provider factory, so key handling,
    base-URL routing and the reasoning token floor all stay in the one module that
    already owns them. A missing key yields a router whose ``configured`` is False -
    callers degrade, exactly as every other provider seam in this repo does.
    """
    backend: ModelBackend | None = None
    inner = summarizer
    if inner is None:
        inner = _summarizer_from_settings(settings)
    if inner is not None:
        # A proxy base URL makes prompt-cache behaviour unverifiable, so the backend
        # stops advertising it rather than reporting cache hits it cannot substantiate.
        via_proxy = bool(str(getattr(settings, "anthropic_base_url", "") or "").strip())
        backend = SummarizerBackend(
            inner,
            name="agentrouter" if via_proxy else "anthropic",
            supports_cache=not via_proxy,
        )
    return ModelRouter(
        backend, gate, settings, default_feature_key=default_feature_key,
        models=tier_models(settings),
    )


def tier_models(settings: Settings) -> dict[TaskTier, str]:
    """The per-tier model overrides this deployment configures, validated.

    ``06-AI-STACK.md`` §3 fixes the tier -> model table AND states the thing that makes it
    insufficient on its own: *"Model IDs are gateway-specific: a router exposes its OWN
    catalog"*. This deployment proves it - the configured gateway answered a request for
    the table's bulk model with::

        503 no available channel for model claude-haiku-4-5

    So the tier stays the contract a caller states, and the model that serves it becomes
    configuration. Without this, changing gateway is a code change - the coupling the
    router exists to remove.

    This is also where §8's judge-independence rule is checked, because an override is
    the only thing that can break it: the default table already gives the judge a
    different configuration from every generator tier, but a deployment whose gateway
    carries one usable model collapses them onto each other, and an eval graded by the
    model that wrote the draft measures agreement rather than quality. A WARNING rather
    than a refusal - a single-model gateway is a real operating state, and stopping all
    work over it would be the worse failure - but a loud one.
    """
    raw = str(getattr(settings, "ai_tier_models", "") or "").strip()
    if not raw:
        return {}
    models = tiers_module.resolve_models(raw)
    judge = models.get(TaskTier.JUDGE, spec_for(TaskTier.JUDGE).model)
    for generator in (TaskTier.DRAFTING, TaskTier.REASONING):
        if models.get(generator, spec_for(generator).model) == judge:
            logger.warning(
                "judge_model_not_independent",
                tier=str(generator), model=judge,
                detail="06-AI-STACK.md §8 requires the grader never share the "
                       "generator's configuration; an eval graded by the model that "
                       "wrote the draft measures agreement, not quality",
            )
            break
    logger.info("tier_models_configured", overrides={str(k): v for k, v in models.items()})
    return models


def _summarizer_from_settings(settings: Settings) -> SystemSummarizer | None:
    """The configured Anthropic summarizer, or None when no key/SDK is present."""
    key = getattr(settings, "anthropic_api_key", None)
    if key is None:
        return None
    try:
        from app.config import apply_provider_env
        from integrations.llm import AnthropicSummarizer

        apply_provider_env(settings)
        return AnthropicSummarizer(
            api_key=key.get_secret_value(),
            model_summary=settings.anthropic_model_summary,
            model_heavy=settings.anthropic_model_heavy,
        )
    except Exception as exc:
        logger.info("model_backend_unconfigured", error=repr(exc))
        return None
