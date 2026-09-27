"""Does the key actually WORK, not just exist.

WHY THIS EXISTS. Every readiness check in this platform asks whether a credential is
configured, and a configured credential is not a working one. MEASURED on 2026-09-26: the
Anthropic key was present and valid and the account had no credit, so the capability board
reported the content pipeline READY while every page died at the compose stage with
``400 invalid_request_error - Your credit balance is too low``. An operator reading that
board would have demoed the product to a client on the strength of it.

Configuration and funding are different questions and only one of them can be answered
without asking the provider. So this asks - once, cheaply, and with the answer cached -
and the board reports the truth either way.

The probe is deliberately the smallest possible request (one token, no system prompt), and
its result is cached for :data:`_TTL_SECONDS` so a dashboard that polls readiness does not
turn a health check into a spend. It NEVER raises: a probe that cannot run returns
``unknown``, which reads as "not verified" rather than as either good news or bad.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from app.config import Settings
from app.logging_setup import get_logger

logger = get_logger("services.provider_health")

#: How long a probe result stands. Long enough that polling a dashboard costs nothing,
#: short enough that topping the account up is reflected while the operator is still
#: looking at the screen.
_TTL_SECONDS = 600.0

#: What the probe found. `unknown` is a real answer and NOT a synonym for either of the
#: others: it means nobody asked, so nobody should claim.
Verdict = Literal["ok", "no_credit", "bad_key", "unreachable", "unknown"]


@dataclass(frozen=True)
class ProviderVerdict:
    """A probe result and the one sentence an operator needs from it."""

    verdict: Verdict
    detail: str = ""

    @property
    def usable(self) -> bool:
        """Whether work depending on this provider can be expected to run.

        `unknown` counts as usable on purpose: a probe that could not run is not evidence
        of a problem, and blocking the product on an unanswered question would make a
        network hiccup look like an outage.
        """
        return self.verdict in ("ok", "unknown")


_cache: dict[str, tuple[float, ProviderVerdict]] = {}


def _classify(exc: Exception) -> ProviderVerdict:
    """Turn a provider error into the one thing the operator can act on.

    The distinction that matters is FUNDING versus CREDENTIAL, because the fixes are
    unrelated: one is a billing page and the other is a key rotation. Anthropic reports
    an exhausted balance as a 400 whose message names it, which is the only reliable
    signal - the status code alone says "bad request" and would be read as our bug.
    """
    text = str(exc)
    lowered = text.lower()
    if "credit balance is too low" in lowered or "insufficient_quota" in lowered:
        return ProviderVerdict(
            "no_credit",
            "the key is valid and the account has no credit - every AI feature will fail",
        )
    if "authentication" in lowered or "invalid x-api-key" in lowered or "401" in lowered:
        return ProviderVerdict("bad_key", "the key was rejected - it is wrong or revoked")
    return ProviderVerdict("unreachable", f"the provider could not be reached ({type(exc).__name__})")


def anthropic_health(settings: Settings, *, force: bool = False) -> ProviderVerdict:
    """Whether the Anthropic key can actually be spent. Cached; never raises.

    ``force`` skips the cache, for the operator pressing "check again" after topping up.
    """
    key = settings.anthropic_api_key
    if not key or not key.get_secret_value().strip():
        return ProviderVerdict("bad_key", "no Anthropic key is configured")

    # Cached per KEY, not globally: rotating the key must invalidate the verdict, and
    # the key itself never leaves this function.
    fingerprint = key.get_secret_value()[-8:]
    now = time.monotonic()
    if not force:
        hit = _cache.get(fingerprint)
        if hit is not None and now - hit[0] < _TTL_SECONDS:
            return hit[1]

    try:
        from integrations.llm import AnthropicSummarizer

        client = AnthropicSummarizer(
            api_key=key.get_secret_value(),
            model_summary=settings.anthropic_model_summary,
            model_heavy=settings.anthropic_model_heavy,
        )
        # The smallest request the API accepts. One output token is enough to prove the
        # account can be billed, which is the entire question being asked.
        client.summarize("hi", model=settings.anthropic_model_summary, max_tokens=1)
        verdict = ProviderVerdict("ok", "")
    except Exception as exc:
        verdict = _classify(exc)
        # The KEY is never logged; the verdict and the reason are.
        logger.warning("anthropic_probe_failed", verdict=verdict.verdict)

    _cache[fingerprint] = (now, verdict)
    return verdict


def reset_cache() -> None:
    """Forget every cached verdict (tests, and the operator's explicit re-check)."""
    _cache.clear()
