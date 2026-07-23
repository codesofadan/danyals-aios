"""Pure cores + provider wiring for the LIVE Policy-Radar change-detection WATCHER.

Everything here is deliberately DB-free and Celery-free, and (for the pure parts)
network-free, so the watcher's logic is unit-testable with fakes - no external
service, no store, no queue. The worker (``workers/tasks/policy.py``) owns the DB
writes + the Celery entry point and composes what lives here:

* ``detect_change`` - a pure sha256 diff of the fetched content against the stored
  anchor (mirrors ``context_cost.content_checksum``).
* ``SsrfGuardedPolicyFetcher`` - the ONLY I/O: a tiny SSRF-safe sync fetcher that
  validates the host on EVERY redirect hop (the ``app/core/security`` caller contract
  is explicit that one-shot validation is insufficient). It is injected into the
  worker as a ``PolicyFetcher``, so tests pass a fake fetcher instead.
* ``analyze_change`` - the cost-gated Claude Haiku call + a defensive JSON parse. It
  is gated EXACTLY like the context module's ``GatedSummarizer.summarize`` (evaluate
  -> call -> commit). An absent key, an unbuildable summarizer, or a dial-off / cap /
  daily-stop block all DEGRADE to ``None`` (the change_event still stands, no KB entry
  is written) - never a crash. A reply that does not parse degrades to a MINIMAL
  analysis distilled from the change summary rather than losing the finding.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urljoin

from app.config import Settings
from app.core.security import PrivateAddressError, validate_public_host
from app.logging_setup import get_logger
from app.services.cost_gate import CostGate, GateContext
from integrations.llm import AnthropicSummarizer, Summarizer

logger = get_logger("services.policy_watch")

# The Policy-Radar money-dial feature (schemas/cost.py) + the cost-log labels.
_FEATURE = "policy"
_PROVIDER = "Anthropic"
_JOB_TYPE = "policy"

# Bound the Haiku reply + the content we feed it (a fetched page can be large).
_ANALYSIS_MAX_TOKENS = 900
_PROMPT_MAX_CHARS = 12_000

# Fetcher redirect handling: follow MANUALLY so every hop is re-validated (a 30x can
# point at 169.254.169.254 - see app/core/security's caller contract). Bounded so a
# redirect loop cannot spin the worker.
_MAX_REDIRECT_HOPS = 5
_MAX_BODY_CHARS = 400_000

# Enum vocabularies (0019). Haiku output is clamped to these; an out-of-set value
# falls back to the column default rather than erroring the insert.
_SEVERITIES = frozenset({"critical", "major", "minor", "info"})
_CATEGORIES = frozenset({"algorithm", "policy", "technical", "content", "local", "geo"})
_REGIONS = frozenset({"global", "national"})
_TARGET_MODULES = frozenset({"audit", "content", "portal"})


# --------------------------------------------------------------------------- #
# 1. Pure change detection
# --------------------------------------------------------------------------- #
def detect_change(text: str, last_hash: str) -> tuple[bool, str]:
    """Return ``(changed, new_hash)`` for ``text`` vs the stored ``last_hash``.

    ``new_hash`` is the sha256 hex digest of ``text`` (mirrors
    ``context_cost.content_checksum``); ``changed`` is ``new_hash != last_hash``. The
    caller treats an empty ``last_hash`` as "no prior anchor" (baseline) rather than a
    change - see the worker's baseline path."""
    new_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return new_hash != last_hash, new_hash


def finding_hash(source_url: str, title: str, summary: str) -> str:
    """The dedupe anchor for a KB entry: sha256 of the distilled FINDING.

    Keyed on the finding (source + title + summary), not the raw page, so a source
    that re-states the same finding hashes identically and bumps the KB version instead
    of duplicating (``policy_watch_repo.insert_kb_entry``)."""
    return hashlib.sha256(f"{source_url}\n{title}\n{summary}".encode()).hexdigest()


# --------------------------------------------------------------------------- #
# 2. The SSRF-guarded fetcher (the only I/O; injected into the worker)
# --------------------------------------------------------------------------- #
class PolicyFetcher(Protocol):
    """Fetch one source URL's content (SSRF-guarded internally), or ``None`` on any
    transport failure / non-200."""

    def fetch(self, url: str) -> str | None: ...


class SsrfGuardedPolicyFetcher:
    """Fetch a policy source, re-validating the host at EVERY redirect hop.

    ``app/core/security``'s caller contract is explicit that one-shot validation is
    insufficient (httpx re-resolves DNS; a 30x can bounce to 169.254.169.254), so
    automatic redirects are DISABLED and each ``Location`` is re-validated through
    ``validate_public_host`` before we follow it. ``validate_public_host`` BLOCKS on
    DNS, which is fine in a Celery worker (no event loop). Non-raising for transport
    errors: they return ``None`` (the poll retries next tick); an SSRF hit RE-RAISES
    so the worker's per-source guard logs the guard doing its job."""

    def __init__(self, *, user_agent: str = "AIOSPolicyRadar/1.0", timeout: float = 15.0) -> None:
        self._ua = user_agent
        self._timeout = timeout

    def fetch(self, url: str) -> str | None:
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx is a base dep
            logger.warning("policy_fetch_no_httpx")
            return None
        current = url
        try:
            with httpx.Client(
                follow_redirects=False,  # we follow MANUALLY so every hop is re-checked
                timeout=httpx.Timeout(self._timeout),
                headers={"User-Agent": self._ua},
            ) as client:
                for _hop in range(_MAX_REDIRECT_HOPS):
                    validate_public_host(current)  # re-validated EVERY hop, not just once
                    resp = client.get(current)
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location", "")
                        if not location:
                            return None
                        current = urljoin(current, location)
                        continue
                    if resp.status_code != 200:
                        return None
                    return resp.text[:_MAX_BODY_CHARS]
        except PrivateAddressError:
            logger.warning("policy_fetch_ssrf_blocked", url=str(url).split("?", 1)[0])
            raise
        except Exception:  # any transport error degrades to "unreachable", never a crash
            logger.info("policy_fetch_failed", url=str(url).split("?", 1)[0])
            return None
        logger.info("policy_fetch_redirect_loop", url=str(url).split("?", 1)[0])
        return None


# --------------------------------------------------------------------------- #
# 3. Provider wiring: the Haiku summarizer (or None = degrade)
# --------------------------------------------------------------------------- #
def summarizer_from_settings(settings: Settings) -> Summarizer | None:
    """Build the Claude Haiku summarizer, or ``None`` when the key is absent / the SDK
    is not installed. ``None`` DEGRADES analysis (the change_event still stands),
    exactly mirroring every other key-gated provider seam in the codebase."""
    key = settings.anthropic_api_key
    if not key:
        return None
    try:
        return AnthropicSummarizer(
            api_key=key.get_secret_value(),
            model_summary=settings.anthropic_model_summary,
        )
    except Exception:  # ProviderNotConfiguredError (no [ai] extra) -> degrade, never crash
        logger.info("policy_summarizer_unavailable")
        return None


# --------------------------------------------------------------------------- #
# 4. The parsed analysis + the cost-gated Haiku call
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PolicyAnalysis:
    """One distilled finding: a KB entry's fields + a recommendation's fields."""

    title: str
    summary: str
    severity: str
    category: str
    region: str
    region_label: str
    rec_title: str
    rec_why: str
    rec_action: str
    target_module: str


def build_prompt(name: str, url: str, text: str) -> str:
    """The strict-JSON instruction fed to Haiku for one changed source."""
    body = " ".join(text.split())[:_PROMPT_MAX_CHARS]
    return (
        "A monitored Google Search policy/algorithm source has changed. Distil the "
        "change into ONE actionable SEO knowledge-base entry for an agency.\n\n"
        f"SOURCE: {name}\nURL: {url}\n\nCONTENT:\n{body}\n\n"
        "Respond with STRICT JSON only (no prose, no code fences), with EXACTLY these "
        "keys: title (string), summary (string), severity (one of critical|major|"
        "minor|info), category (one of algorithm|policy|technical|content|local|geo), "
        "region (one of global|national), region_label (string), rec_title (string), "
        "rec_why (string), rec_action (string), target_module (one of audit|content|"
        "portal)."
    )


def _clamp(value: object, allowed: frozenset[str], default: str) -> str:
    """Lower-case + validate ``value`` against ``allowed``; ``default`` on a miss."""
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _extract_json(raw: str) -> dict[str, Any] | None:
    """Best-effort parse of a JSON object from a model reply. Tolerates surrounding
    prose / code fences by slicing the outermost ``{...}``. ``None`` on failure."""
    text = raw.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def parse_analysis(raw: str, *, fallback_title: str, fallback_summary: str) -> PolicyAnalysis:
    """Parse Haiku's reply into a ``PolicyAnalysis``, DEGRADING defensively.

    On any parse failure (empty / non-JSON / missing keys) the finding is NOT lost: a
    minimal analysis is built from the change fallbacks (title + summary), with neutral
    enum defaults and a generic 'review this change' recommendation. Every enum is
    clamped to its 0019 vocabulary, so a hallucinated label can never break the insert.
    """
    data = _extract_json(raw) or {}
    title = str(data.get("title") or "").strip() or fallback_title
    summary = str(data.get("summary") or "").strip() or fallback_summary
    rec_title = str(data.get("rec_title") or "").strip() or f"Review: {title}"
    return PolicyAnalysis(
        title=title,
        summary=summary,
        severity=_clamp(data.get("severity"), _SEVERITIES, "info"),
        category=_clamp(data.get("category"), _CATEGORIES, "algorithm"),
        region=_clamp(data.get("region"), _REGIONS, "global"),
        region_label=str(data.get("region_label") or "").strip() or "Global",
        rec_title=rec_title,
        rec_why=str(data.get("rec_why") or "").strip() or summary,
        rec_action=str(data.get("rec_action") or "").strip()
        or "Review this change and assess client exposure.",
        target_module=_clamp(data.get("target_module"), _TARGET_MODULES, "audit"),
    )


def analyze_change(
    summarizer: Summarizer | None,
    gate: CostGate,
    *,
    settings: Settings,
    source_id: str,
    source_name: str,
    source_url: str,
    text: str,
    fallback_summary: str,
) -> PolicyAnalysis | None:
    """Cost-gated Haiku analysis of a changed source. ``None`` == DEGRADE (skip).

    Gated exactly like ``context_cost.GatedSummarizer.summarize``: the gate is
    consulted BEFORE any spend, the provider is called only if allowed, then the
    estimated cost is committed. Returns ``None`` (degrade, no KB entry) when the
    summarizer is absent (no key) OR the gate blocks (dial off / by-hand / client cap /
    daily spend-stop). The paid call is committed even if the reply does not parse -
    ``parse_analysis`` degrades to a minimal finding rather than dropping it."""
    if summarizer is None:
        return None
    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=None,
        provider=_PROVIDER,
        estimated_cost=float(settings.policy_analysis_cost_estimate),
        job_id=source_id,
        job_type=_JOB_TYPE,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        logger.info("policy_analysis_blocked", source=source_name, outcome=decision.outcome)
        return None
    result = summarizer.summarize(
        build_prompt(source_name, source_url, text),
        model=settings.anthropic_model_summary,
        max_tokens=_ANALYSIS_MAX_TOKENS,
    )
    gate.commit(ctx, ctx.estimated_cost)
    return parse_analysis(
        result.text,
        fallback_title=f"Update to {source_name}",
        fallback_summary=fallback_summary,
    )
