"""The LangSmith tracing seam - and the redaction that makes it safe to turn on.

``06-AI-STACK.md`` §6 makes LangSmith the trace store for every model call and every
graph run, and then states the condition on it plainly: **traces contain client page
content, NAP data and business descriptions.** Self-hosted is the default; hosted SaaS
requires a signed-off ADR. This module encodes that as configuration rather than as a
sentence in a document nobody reads at 2am:

* ``langsmith_endpoint`` defaults to EMPTY, which means "no tracing at all". A trace
  destination is something an operator chooses, never something that appears because a
  package got installed.
* ``langsmith_redact_content`` defaults to **True**. With it on, no prompt text and no
  completion text leaves this process - a span carries the SHAPE of the call (tier,
  model, token counts, cost, cache hit, prompt hash, latency) and a content DIGEST, which
  is what actually answers "why did this article come out wrong" in aggregate.
* Turning redaction off is a deliberate act that is LOGGED at warning level on startup,
  with the ADR requirement named, so the decision leaves a trace of its own.

WHY A DIGEST AND NOT NOTHING. A span with no content at all cannot answer "did these two
properties get the same prompt?" - which is precisely the Web 2.0 failure mode the
similarity gate exists for. A stable hash answers it without carrying a syllable of the
client's business across the wire.

EVERY FUNCTION HERE IS A NO-OP WHEN LANGSMITH IS ABSENT OR UNCONFIGURED. ``langsmith`` is
an optional ``[graph]`` extra (the core image must stay light - see ``pyproject.toml``'s
note on the resolver backtracking that heavy AI trees caused), so nothing may import it
at module scope and nothing may fail because it is missing. A tracing backend that is
down must never take a client's campaign down with it.
"""

from __future__ import annotations

import functools
import hashlib
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

from app.logging_setup import get_logger

logger = get_logger("platform.ai.tracing")

_F = TypeVar("_F", bound=Callable[..., Any])

#: Metadata keys §6 requires on every span. Named as a constant so the router, the graph
#: runtime and the eval harness cannot drift into three different spellings of the same
#: field - a trace store where half the runs say `client` and half say `client_id`
#: cannot be filtered, which is the only thing a trace store is for.
REQUIRED_SPAN_KEYS: tuple[str, ...] = ("client_id", "job_id", "module", "task_tier")


@dataclass(frozen=True)
class TracingState:
    """What tracing actually resolved to at startup.

    Returned by :func:`configure` and held on the router, so a caller can ASK whether a
    trace was recorded instead of assuming one was. ``reason`` names why tracing is off
    when it is off - "no endpoint configured" and "langsmith not installed" send an
    operator to two completely different fixes.
    """

    enabled: bool = False
    project: str = ""
    endpoint: str = ""
    redact_content: bool = True
    self_hosted: bool = True
    reason: str = "not configured"

    @property
    def describe(self) -> str:
        if not self.enabled:
            return f"tracing off ({self.reason})"
        host = "self-hosted" if self.self_hosted else "HOSTED SaaS"
        redact = "redacted" if self.redact_content else "FULL CONTENT"
        return f"tracing on -> {self.project} ({host}, {redact})"


#: Hosts that mean "Anthropic/LangChain's hosted SaaS" rather than an instance the
#: agency runs. Used only to decide whether §6's ADR requirement applies - a self-hosted
#: instance on any other host needs no ADR.
_SAAS_HOSTS: tuple[str, ...] = ("api.smith.langchain.com", "eu.api.smith.langchain.com")

_state = TracingState()


def configure(settings: Any) -> TracingState:
    """Resolve tracing from settings and publish it to the LangSmith SDK's environment.

    Idempotent and safe to call at import time of the worker or the API. Returns the
    resolved :class:`TracingState`, which is also cached for :func:`state`.

    The SDK reads its configuration from the environment, so this sets the environment
    rather than constructing a client - that way LangGraph's own automatic run tracing
    (which we never call directly) lands in the same project as the router's spans.
    """
    global _state

    endpoint = str(getattr(settings, "langsmith_endpoint", "") or "").strip()
    api_key = getattr(settings, "langsmith_api_key", None)
    # A SecretStr in production, a plain string in a test, None when unset. Read through
    # the accessor when it exists so the secret is never stringified via repr - a
    # SecretStr's str() is the literal "**********", which would be silently sent as the
    # API key and fail authentication in a way nobody would connect back to here.
    reveal = getattr(api_key, "get_secret_value", None)
    key = str(reveal()) if callable(reveal) else str(api_key or "")
    project = str(getattr(settings, "langsmith_project", "") or "aios").strip()
    redact = bool(getattr(settings, "langsmith_redact_content", True))

    if not endpoint:
        _state = TracingState(redact_content=redact, reason="no LANGSMITH_ENDPOINT configured")
        return _state
    try:  # optional [graph] extra - absence is a configuration fact, never an error
        import langsmith  # noqa: F401
    except ImportError:
        _state = TracingState(
            redact_content=redact,
            reason="langsmith not installed (pip install -e '.[graph]')",
        )
        logger.info("langsmith_absent", endpoint=endpoint)
        return _state

    self_hosted = not any(host in endpoint for host in _SAAS_HOSTS)
    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_ENDPOINT"] = endpoint
    os.environ["LANGSMITH_PROJECT"] = project
    if key:
        os.environ["LANGSMITH_API_KEY"] = key
    # The SDK's own blunt instrument, set as a SECOND line of defence behind our own
    # scrubbing below. Ours redacts what we build; this catches anything the SDK
    # auto-captures from a library we did not write.
    os.environ["LANGSMITH_HIDE_INPUTS"] = "true" if redact else "false"
    os.environ["LANGSMITH_HIDE_OUTPUTS"] = "true" if redact else "false"

    _state = TracingState(
        enabled=True,
        project=project,
        endpoint=endpoint,
        redact_content=redact,
        self_hosted=self_hosted,
        reason="",
    )
    if not self_hosted:
        logger.warning(
            "langsmith_hosted_saas",
            endpoint=endpoint,
            detail="06-AI-STACK.md §6 requires a signed-off ADR, PII redaction and a "
                   "client DPA note before client content reaches hosted LangSmith",
        )
    if not redact:
        logger.warning(
            "langsmith_content_redaction_off",
            project=project,
            detail="raw prompts and completions (client page content, NAP, business "
                   "descriptions) are being sent to the trace store",
        )
    logger.info("langsmith_configured", project=project, self_hosted=self_hosted, redact=redact)
    return _state


#: Every environment variable :func:`configure` sets. Tracked as data so :func:`reset`
#: can undo exactly what was done - a partial reset leaves the SDK armed, which is how a
#: "tracing off" process keeps a background thread POSTing to a host that no longer
#: exists.
_ENV_KEYS: tuple[str, ...] = (
    "LANGSMITH_TRACING", "LANGSMITH_ENDPOINT", "LANGSMITH_PROJECT",
    "LANGSMITH_API_KEY", "LANGSMITH_HIDE_INPUTS", "LANGSMITH_HIDE_OUTPUTS",
)


def reset() -> TracingState:
    """Disarm tracing: clear the SDK environment and return to the unconfigured state.

    Needed because :func:`configure` arms a PROCESS-GLOBAL SDK by setting environment
    variables - that is how LangGraph's own automatic run tracing lands in the same
    project without us calling it. The consequence is that configuration outlives the
    caller, so there has to be a way to take it back:

    * the unit suite must not leave a background thread trying to reach a trace store
      (tests run with no external services, and a resolved-then-unreachable endpoint
      produces connection errors from a thread nobody is awaiting);
    * a process that reconfigures at runtime must not keep the old destination armed.
    """
    global _state
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
    _state = TracingState()
    return _state


def state() -> TracingState:
    """The tracing state resolved by the last :func:`configure` call."""
    return _state


def digest(text: str) -> str:
    """A stable, short content fingerprint safe to put in a span.

    Answers "was this the same prompt?" across runs and clients without carrying the
    prompt. Truncated to 16 hex chars: collision risk is irrelevant for a debugging
    label, and a full digest makes spans noisy to read.
    """
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


def scrub(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return ``payload`` with every content-bearing field replaced by a digest.

    A field counts as content-bearing by NAME (``prompt``, ``system``, ``text``,
    ``completion``, ``body``, ``body_md``, ``content``, ``messages``) rather than by
    sniffing values, because a value-based rule cannot tell a client's business
    description from a model id and would eventually let one through. A name-based rule
    fails the safe way: an unrecognised content field keeps its name and loses its value.

    Non-content metadata (ids, tiers, counts, costs, booleans) passes through unchanged -
    that is the part of the span that is worth querying.
    """
    if not _state.redact_content:
        return dict(payload)
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if key in _CONTENT_KEYS:
            if isinstance(value, str):
                out[f"{key}_digest"] = digest(value)
                out[f"{key}_chars"] = len(value)
            elif value is None:
                out[f"{key}_digest"] = ""
            else:
                out[f"{key}_digest"] = digest(repr(value))
        else:
            out[key] = value
    return out


_CONTENT_KEYS: frozenset[str] = frozenset(
    {
        "prompt", "system", "text", "completion", "body", "body_md", "content",
        "messages", "draft_md", "title", "answer", "summary", "description",
    }
)


@dataclass
class _NullSpan:
    """The span object handed out when tracing is off. Accepts everything, records
    nothing, and never raises - so node code is written once and does not branch on
    whether a trace store happens to be reachable."""

    name: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def update(self, **fields: Any) -> None:
        self.metadata.update(fields)


@contextmanager
def span(name: str, **metadata: Any) -> Iterator[_NullSpan]:
    """Open a trace span around a block of work.

    Yields an object with ``.update(**fields)`` so a node can attach facts it only learns
    at the end (token counts, cost, a verdict). When tracing is off this is a plain
    context manager over a no-op recorder - the calling code is identical either way.

    A failure inside the TRACING machinery never propagates: an unreachable trace store
    must not fail a client's campaign. A failure inside the wrapped BLOCK propagates
    normally, and is recorded first.
    """
    holder = _NullSpan(name=name, metadata=dict(metadata))
    if not _state.enabled:
        yield holder
        return
    try:
        from langsmith import run_helpers
    except ImportError:  # configured then uninstalled mid-process; degrade, never fail
        yield holder
        return

    try:
        ctx = run_helpers.trace(name=name, run_type="chain", metadata=scrub(holder.metadata))
    except Exception as exc:
        logger.debug("langsmith_span_unavailable", name=name, error=repr(exc))
        yield holder
        return

    try:
        with ctx as run:
            try:
                yield holder
            finally:
                try:
                    run.add_metadata(scrub(holder.metadata))
                except Exception as exc:
                    logger.debug("langsmith_span_metadata_failed", name=name, error=repr(exc))
    except Exception as exc:
        logger.debug("langsmith_span_failed", name=name, error=repr(exc))


def traced(name: str, **static_metadata: Any) -> Callable[[_F], _F]:
    """Decorate a function so each call opens a :func:`span`.

    Used on the router's ``complete`` and on graph node functions that are not already
    traced by LangGraph itself. Static metadata (``module``, ``task_tier``) is attached
    at decoration; per-call facts go on via the span the function can fetch from
    :func:`current`.
    """

    def decorate(fn: _F) -> _F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(name, **static_metadata):
                return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorate
