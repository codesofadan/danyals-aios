"""Summarizer seam (P6B-3): the ONLY door to an LLM for the context module.

Anthropic Claude produces the bounded living-summary prose (P6B-5). The provider
is reachable exclusively through the ``Summarizer`` Protocol so P6B-4 can wrap it
in a cost-gated ``GatedSummarizer`` (evaluate -> call -> commit) - nothing else
calls the SDK directly.

Two impls satisfy the Protocol:

* ``AnthropicSummarizer`` - lazily ``import anthropic`` (the SDK is an OPTIONAL
  ``[ai]`` extra, absent from the base install so the gate stays light). Reads the
  key from settings; uses model tiering (a cheap Haiku default, a heavier Sonnet
  for large folds - the caller picks per fold via the ``model`` arg). A frozen,
  prompt-cache-friendly system prompt. NO-OPS are impossible: absent SDK/key ->
  ``ProviderNotConfiguredError`` naming the fix.
* ``FakeSummarizer`` - deterministic, network-free. Same input -> same output +
  stable token counts, so golden-set / compaction tests are reproducible offline.

Anthropic has NO embeddings API - embeddings live in ``integrations.embeddings``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from app.logging_setup import get_logger
from integrations.errors import ProviderNotConfiguredError

logger = get_logger("integrations.llm")

# The message every keyless/SDK-less construction surfaces - names the exact fix.
# Anthropic allows at most four cache breakpoints per request.
_MAX_CACHE_BREAKPOINTS = 4

_INSTALL_HINT = "install the AI extra (pip install -e '.[ai]') and set ANTHROPIC_API_KEY"

# Frozen, factual system prompt for CONTEXT COMPACTION ONLY. Stable prefix =>
# prompt-cache-friendly (P6B-5's fold history rides in the user turn, after this
# cached preamble).
#
# THIS IS NOT A GENERAL-PURPOSE DEFAULT. It is the Part-6B living-summary contract,
# and it is actively WRONG for any caller that wants prose written rather than an
# entity summary compacted.
#
# Incident (found 2026-08-24): the whole content generator reached `summarize()`
# without a `system=`, so EVERY article section ever drafted was written under this
# compaction contract - Claude was told it was a summarisation service and then asked
# for marketing copy. The gated wrapper in `workers/tasks/content.py` did not even
# ACCEPT a `system` param, so the generator had no way to pass one. Renamed from the
# neutral-sounding `_SYSTEM_PROMPT` so the next caller who lands on the `system or ...`
# fallback below can see what they are silently opting into.
_COMPACTION_SYSTEM_PROMPT = (
    "You maintain a bounded, factual living summary of one entity's activity. "
    "Given the current summary and recent events, produce an updated summary that "
    "drops contradicted or expired facts and keeps only what remains true. Never "
    "invent details. Output prose only - no preamble, headings, or bullet lists."
)


@dataclass(frozen=True)
class LLMResult:
    """One summarization result: the text + token usage for cost accounting.

    ``input_tokens`` / ``output_tokens`` feed the Part-2 cost path (P6B-4) so a
    summarize call is metered like every other provider spend.

    ``cache_write_tokens`` / ``cache_read_tokens`` are the API's OWN prompt-cache
    accounting, defaulted to 0 so every existing construction still works. They are
    carried because a cached prefix is billed at 1.25x on write and 0.1x on read, so
    a cost computed from `input_tokens` alone is wrong in both directions - and
    because measuring them is how the doctrine cost model got corrected once already
    (an estimate that was 30% low).
    """

    text: str
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0


@runtime_checkable
class Summarizer(Protocol):
    """Compact ``prompt`` into bounded prose, returning text + token usage.

    ``model`` selects the tier per call (summary vs heavy); ``max_tokens`` bounds
    the prose to the entity's token budget.
    """

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult: ...


@runtime_checkable
class SystemSummarizer(Protocol):
    """A ``Summarizer`` that also accepts an optional ``system`` prompt override, for
    callers that need Claude's PURE generation under their OWN contract instead of the
    built-in compaction prompt (the Policy-Radar Cloud-API generator + on-demand ask, and
    the content site-design analyzer). ``system=None`` behaves exactly like ``Summarizer``.

    ``AnthropicSummarizer`` and ``FakeSummarizer`` both satisfy this AND the base
    ``Summarizer`` (their ``system`` param is optional), so widening never rippled into the
    many existing ``Summarizer`` implementers (context / content / offpage).
    """

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | Sequence[str] | None = None,
        cache: Sequence[bool] | None = None,
    ) -> LLMResult: ...


class AnthropicSummarizer:
    """Real ``Summarizer`` backed by Claude; lazy-imports the ``anthropic`` SDK.

    ``model_summary`` (cheap, Haiku) and ``model_heavy`` (Sonnet, for large folds)
    document the tiering and are exposed for callers that route by fold size; the
    ``summarize`` ``model`` arg is authoritative per call.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model_summary: str = "claude-haiku-4-5",
        model_heavy: str = "claude-sonnet-5",
    ) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Anthropic summarizer unavailable: {_INSTALL_HINT}")
        try:
            import anthropic
        except ImportError as exc:  # SDK not installed (base install omits the [ai] extra)
            raise ProviderNotConfiguredError(
                f"Anthropic summarizer unavailable: {_INSTALL_HINT}"
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model_summary = model_summary
        self.model_heavy = model_heavy

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | Sequence[str] | None = None,
        cache: Sequence[bool] | None = None,
    ) -> LLMResult:
        """One completion. ``system`` may be a single prompt or an ORDERED SEQUENCE of
        blocks, each becoming its own cache breakpoint.

        The sequence form is what makes the doctrine prompt affordable. The API caches
        on a PREFIX, so blocks must run most-stable-first (constitution, then stage
        role, then page pack) - the assembly in ``doctrine_routes`` guarantees that
        order, and reversing it would invalidate the whole prefix on every new page
        type.

        ``cache`` marks which blocks carry a breakpoint, defaulting to all of them.
        It is worth passing: a write costs 1.25x and a read 0.1x, so a block used ONCE
        is 25% more expensive cached than sent plain, and the caller knows how many
        calls a stage will make.

        Anthropic allows at most 4 breakpoints. Excess markers are dropped from the
        TAIL - the earliest blocks are the most reused, so they are the ones worth
        keeping cached.
        """
        blocks = [system] if isinstance(system, str) else list(system or [])
        if not blocks:
            blocks = [_COMPACTION_SYSTEM_PROMPT]
        flags = list(cache) if cache is not None else [True] * len(blocks)
        flags += [True] * (len(blocks) - len(flags))

        # Typed as Any because the SDK's TextBlockParam is a TypedDict whose
        # cache_control key is conditionally present; building it incrementally is
        # clearer than a branch per shape.
        system_param: list[Any] = []
        breakpoints = 0
        for text, wanted in zip(blocks, flags, strict=False):
            if not text:
                continue
            entry: dict[str, Any] = {"type": "text", "text": text}
            if wanted and breakpoints < _MAX_CACHE_BREAKPOINTS:
                entry["cache_control"] = {"type": "ephemeral"}
                breakpoints += 1
            system_param.append(entry)

        message = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_param,
            messages=[{"role": "user", "content": prompt}],
        )
        # The SDK's content-block union has grown many non-text variants (thinking,
        # tool-use, tool-result, ...); getattr(..., "type") isn't a type guard mypy can
        # narrow on, so read .text via getattr too rather than assert a specific block
        # class (the runtime filter above already guarantees only text blocks reach it).
        text = "".join(
            str(getattr(block, "text", ""))
            for block in message.content
            if getattr(block, "type", None) == "text"
        )
        usage = message.usage
        return LLMResult(
            text=text,
            input_tokens=int(usage.input_tokens),
            output_tokens=int(usage.output_tokens),
            cache_write_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        )


# --------------------------------------------------------------------------- #
# Web-search research seam (Policy-Radar on-demand lookup, POST /policy/ask)
# --------------------------------------------------------------------------- #
# The on-demand lookup does NOT scrape one page; it lets Claude search the web
# ITSELF via the Anthropic SERVER-SIDE web_search tool and synthesize a cited
# answer. This is a SEPARATE seam from ``Summarizer`` (a different call shape:
# it passes ``tools=[web_search]`` and reads the tool-result citation URLs +
# server-tool usage off the response), reachable only through this Protocol so
# it stays cost-gated + fake-injectable in tests.
_WEB_SEARCH_TOOL_TYPE = "web_search_20250305"  # basic variant; works on the Haiku default
_WEB_SEARCH_TOOL_NAME = "web_search"


@dataclass(frozen=True)
class ResearchResult:
    """One web-search research result: the synthesized answer text, the source URLs
    Claude actually retrieved, token usage, and the number of searches it ran.

    ``sources`` are the web_search citation URLs (authoritative - what the tool
    returned), deduped in first-seen order. ``searches`` is ``None`` when the SDK did
    not surface the server-tool usage count (the caller then estimates ``max_uses``);
    a real ``0`` means Claude answered without searching. ``input_tokens`` /
    ``output_tokens`` + ``searches`` feed the cost path (token spend + web-search spend).
    """

    text: str
    sources: list[str]
    input_tokens: int
    output_tokens: int
    searches: int | None


@runtime_checkable
class Researcher(Protocol):
    """Answer ``prompt`` using server-side web search, returning the synthesized text,
    the cited source URLs, and token/search usage for cost accounting.

    ``max_searches`` bounds the web_search tool's ``max_uses`` for one lookup.
    ``system`` optionally OVERRIDES the built-in web-search system prompt so a different
    caller can pass its own JSON contract (the Policy-Radar daily generator's N-item
    contract, or the content page-set recommender); ``None`` keeps the default
    on-demand-lookup prompt.
    """

    def research(
        self, prompt: str, *, model: str, max_tokens: int, max_searches: int,
        system: str | None = None,
    ) -> ResearchResult: ...


# Frozen, factual system prompt for the on-demand lookup. Instructs Claude to research
# the topic via web_search against Google's official surfaces and return STRICT JSON.
_RESEARCH_SYSTEM_PROMPT = (
    "You are a senior SEO and Google Search policy expert advising an agency operator. "
    "Use the web_search tool to research the operator's topic against Google's official, "
    "authoritative surfaces (developers.google.com / Search Central, blog.google, the "
    "Search Status dashboard, the Search Quality Rater Guidelines) and other reputable "
    "sources, then synthesize ONE accurate answer grounded in what you actually found. "
    "Respond with STRICT JSON ONLY - no prose, no markdown, no code fences - with EXACTLY "
    "these keys: answer (a concise 2-4 sentence plain-language answer to the operator's "
    "question), urgency (one of \"urgent\" or \"informational\" - \"urgent\" ONLY if the "
    "operator should act soon, e.g. an active rollout, a newly required change, or a "
    "manual-action risk), key_rules (an array of short strings, each a concrete rule or "
    "requirement), sources (an array of the source URLs you used). Do not invent rules or "
    "URLs; ground every claim in a source you actually retrieved."
)


class AnthropicResearcher:
    """Real ``Researcher`` backed by Claude's SERVER-SIDE web_search tool; lazy-imports
    the ``anthropic`` SDK (optional ``[ai]`` extra, exactly like ``AnthropicSummarizer``).

    Absent SDK / key -> ``ProviderNotConfiguredError`` naming the fix (the builder turns
    that into a clean keyless degrade). ``model`` defaults to the web-search-capable Haiku;
    the ``research`` ``model`` arg is authoritative per call.
    """

    def __init__(self, *, api_key: str, model: str = "claude-haiku-4-5") -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"Anthropic researcher unavailable: {_INSTALL_HINT}")
        try:
            import anthropic
        except ImportError as exc:  # SDK not installed (base install omits the [ai] extra)
            raise ProviderNotConfiguredError(
                f"Anthropic researcher unavailable: {_INSTALL_HINT}"
            ) from exc
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def research(
        self, prompt: str, *, model: str, max_tokens: int, max_searches: int,
        system: str | None = None,
    ) -> ResearchResult:
        message = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system or _RESEARCH_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            # The SDK now ships several dated, structurally-identical web-search-tool
            # TypedDicts (20250305/20260209/20260318, ...); a plain dict literal
            # matches more than one so mypy can't pick a single overload. Cast rather
            # than pin to one dated Param class here.
            tools=cast(
                "Any",
                [
                    {
                        "type": _WEB_SEARCH_TOOL_TYPE,
                        "name": _WEB_SEARCH_TOOL_NAME,
                        "max_uses": max(1, max_searches),
                    }
                ],
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts: list[str] = []
        sources: list[str] = []
        seen: set[str] = set()

        def _add_source(url: object) -> None:
            if isinstance(url, str) and url and url not in seen:
                seen.add(url)
                sources.append(url)

        for block in message.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(getattr(block, "text", "") or "")
                for cite in getattr(block, "citations", None) or []:
                    _add_source(getattr(cite, "url", None))
            elif btype == "web_search_tool_result":
                # ``.content`` is a LIST of web_search_result on success, or a single
                # error object on failure (e.g. {"error_code": ...}) - only lists cite.
                content = getattr(block, "content", None)
                if isinstance(content, list):
                    for item in content:
                        _add_source(getattr(item, "url", None))

        usage = message.usage
        searches: int | None = None
        server_use = getattr(usage, "server_tool_use", None)
        if server_use is not None:
            requests = getattr(server_use, "web_search_requests", None)
            if requests is not None:
                searches = int(requests)

        return ResearchResult(
            text="".join(text_parts),
            sources=sources,
            input_tokens=int(usage.input_tokens),
            output_tokens=int(usage.output_tokens),
            searches=searches,
        )


class FakeResearcher:
    """Deterministic, offline ``Researcher`` for unit tests + degraded golden runs.

    Returns a fixed STRICT-JSON answer plus a fixed source list, with token counts
    derived from lengths and a stable search count. No network; identical input always
    yields an identical ``ResearchResult``.
    """

    def __init__(
        self,
        *,
        payload: str = (
            '{"answer": "A researched answer about the topic.", "urgency": '
            '"informational", "key_rules": ["A concrete rule."], "sources": '
            '["https://developers.google.com/search"]}'
        ),
        sources: list[str] | None = None,
        searches: int | None = 1,
    ) -> None:
        self._payload = payload
        self._sources = ["https://developers.google.com/search"] if sources is None else sources
        self._searches = searches

    def research(
        self, prompt: str, *, model: str, max_tokens: int, max_searches: int,
        system: str | None = None,
    ) -> ResearchResult:
        return ResearchResult(
            text=self._payload,
            sources=list(self._sources),
            input_tokens=max(1, len(prompt) // 4),
            output_tokens=max(1, len(self._payload) // 4),
            searches=self._searches,
        )


class FakeSummarizer:
    """Deterministic, offline ``Summarizer`` for unit tests + degraded golden runs.

    Returns a whitespace-normalized, truncated digest of the prompt with token
    counts derived from lengths (~4 chars/token). No network, stable across runs:
    identical input always yields an identical ``LLMResult``.
    """

    def __init__(self, *, max_chars: int = 480) -> None:
        self._max_chars = max_chars

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | Sequence[str] | None = None,
        cache: Sequence[bool] | None = None,
    ) -> LLMResult:
        normalized = " ".join(prompt.split())
        digest = normalized[: self._max_chars]
        return LLMResult(
            text=digest,
            input_tokens=max(1, len(normalized) // 4),
            output_tokens=max(1, len(digest) // 4),
        )
