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

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.logging_setup import get_logger
from integrations.errors import ProviderNotConfiguredError

logger = get_logger("integrations.llm")

# The message every keyless/SDK-less construction surfaces - names the exact fix.
_INSTALL_HINT = "install the AI extra (pip install -e '.[ai]') and set ANTHROPIC_API_KEY"

# Frozen, factual system prompt. Stable prefix => prompt-cache-friendly (P6B-5's
# fold history rides in the user turn, after this cached preamble).
_SYSTEM_PROMPT = (
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
    """

    text: str
    input_tokens: int
    output_tokens: int


@runtime_checkable
class Summarizer(Protocol):
    """Compact ``prompt`` into bounded prose, returning text + token usage.

    ``model`` selects the tier per call (summary vs heavy); ``max_tokens`` bounds
    the prose to the entity's token budget.
    """

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult: ...


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

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        message = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=[
                {"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
            ],
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
        usage = message.usage
        return LLMResult(
            text=text,
            input_tokens=int(usage.input_tokens),
            output_tokens=int(usage.output_tokens),
        )


class FakeSummarizer:
    """Deterministic, offline ``Summarizer`` for unit tests + degraded golden runs.

    Returns a whitespace-normalized, truncated digest of the prompt with token
    counts derived from lengths (~4 chars/token). No network, stable across runs:
    identical input always yields an identical ``LLMResult``.
    """

    def __init__(self, *, max_chars: int = 480) -> None:
        self._max_chars = max_chars

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        normalized = " ".join(prompt.split())
        digest = normalized[: self._max_chars]
        return LLMResult(
            text=digest,
            input_tokens=max(1, len(normalized) // 4),
            output_tokens=max(1, len(digest) // 4),
        )
