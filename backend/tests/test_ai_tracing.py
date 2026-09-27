"""Tracing, and the redaction that makes turning it on safe.

06-AI-STACK.md §6 states the condition plainly: traces contain client page content, NAP
data and business descriptions. So the tests here are less about whether a span is
emitted and more about what CANNOT leave the process:

* content-bearing fields are replaced by a digest, by NAME, not by sniffing values;
* the default is redaction ON and tracing OFF - a trace destination is chosen, never
  inherited from a package being installed;
* nothing in this module may raise into the caller. An unreachable trace store must not
  take a client's campaign down with it.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.platform.ai import tracing

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_tracing_state() -> Any:
    """Disarm tracing after every test.

    Not hygiene - a correctness requirement, and the reason ``tracing.reset()`` exists.
    ``configure()`` arms a PROCESS-GLOBAL SDK through environment variables, and the
    LangSmith client then batches runs from a BACKGROUND THREAD. Without this, a test
    that configures an (unreachable) endpoint leaves that thread trying to POST for the
    rest of the session: the unit suite starts making network calls, which it is defined
    not to do, and the failures surface as unattributable noise from a thread nobody
    awaited.
    """
    tracing.reset()
    yield
    tracing.reset()


def _settings(**overrides: Any) -> Settings:
    return Settings(app_env="dev", **overrides)


# --------------------------------------------------------------------------- #
# Defaults
# --------------------------------------------------------------------------- #
def test_tracing_is_off_until_an_endpoint_is_chosen() -> None:
    state = tracing.configure(_settings())
    assert state.enabled is False
    assert "ENDPOINT" in state.reason
    assert state.redact_content is True, "redaction must default on even with tracing off"


def test_redaction_is_on_by_default_when_tracing_is_configured() -> None:
    state = tracing.configure(_settings(langsmith_endpoint="http://langsmith.internal:1984"))
    # `enabled` depends on whether the optional extra is installed; `redact_content` and
    # `self_hosted` are decided from configuration alone and must hold either way.
    assert state.redact_content is True
    assert state.self_hosted is True


def test_a_hosted_saas_endpoint_is_recognised_as_such() -> None:
    """§6 attaches an ADR, a PII-redaction requirement and a DPA note to hosted LangSmith.
    The first step is knowing which one you pointed at."""
    state = tracing.configure(
        _settings(langsmith_endpoint="https://api.smith.langchain.com")
    )
    assert state.self_hosted is False
    assert "HOSTED SaaS" in state.describe or not state.enabled


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #
def test_content_fields_are_replaced_by_a_digest_and_a_length() -> None:
    tracing.configure(_settings(langsmith_endpoint="http://ls.internal"))
    scrubbed = tracing.scrub(
        {
            "prompt": "Acme Drains, 14 Kirkstall Road, Leeds LS3 1HF",
            "module": "web2",
            "client_id": "c-1",
            "input_tokens": 120,
        }
    )
    assert "prompt" not in scrubbed
    assert scrubbed["prompt_digest"] == tracing.digest(
        "Acme Drains, 14 Kirkstall Road, Leeds LS3 1HF"
    )
    assert scrubbed["prompt_chars"] == 45
    # Non-content metadata is the part worth querying, and survives untouched.
    assert scrubbed["module"] == "web2"
    assert scrubbed["client_id"] == "c-1"
    assert scrubbed["input_tokens"] == 120


def test_no_content_value_survives_scrubbing_in_any_form() -> None:
    """The guarantee stated as a whole-payload property rather than field by field."""
    tracing.configure(_settings(langsmith_endpoint="http://ls.internal"))
    secret = "the client's private business description"
    scrubbed = tracing.scrub(
        {"prompt": secret, "system": [secret], "body_md": secret, "completion": secret}
    )
    assert secret not in repr(scrubbed)


def test_an_unrecognised_content_field_fails_the_safe_way() -> None:
    """Redaction keys off NAME, not value - a value-based rule cannot tell a business
    description from a model id and would eventually let one through. The cost of the
    name-based rule is that a field nobody listed keeps its value, so the list is the
    thing under test."""
    tracing.configure(_settings(langsmith_endpoint="http://ls.internal"))
    for key in ("prompt", "system", "body_md", "draft_md", "completion", "title", "messages"):
        assert f"{key}_digest" in tracing.scrub({key: "content"})


def test_turning_redaction_off_passes_content_through_verbatim() -> None:
    """The deliberate act, behaving as declared - and logged at warning level when it is
    configured (see ``configure``), so the decision leaves a trace of its own."""
    tracing.configure(
        _settings(langsmith_endpoint="http://ls.internal", langsmith_redact_content=False)
    )
    assert tracing.scrub({"prompt": "raw"}) == {"prompt": "raw"}


def test_a_digest_is_stable_and_short() -> None:
    """Stability is the whole feature: it answers "was this the same prompt?" across
    runs and clients without carrying the prompt."""
    assert tracing.digest("same") == tracing.digest("same")
    assert tracing.digest("same") != tracing.digest("different")
    assert len(tracing.digest("x")) == 16


# --------------------------------------------------------------------------- #
# Never raise into the caller
# --------------------------------------------------------------------------- #
def test_a_span_is_a_working_context_manager_when_tracing_is_off() -> None:
    tracing.configure(_settings())
    with tracing.span("node.draft", module="web2") as sp:
        sp.update(cost_cents=3)
    assert sp.metadata["cost_cents"] == 3


def test_an_exception_inside_a_span_propagates_unchanged() -> None:
    """Tracing observes; it must never swallow. A node that fails has to reach the job
    engine, which is the only layer with a retry budget and a dead letter."""
    tracing.configure(_settings())
    with pytest.raises(ZeroDivisionError), tracing.span("node.draft"):
        _ = 1 / 0


def test_the_traced_decorator_returns_the_wrapped_value_and_keeps_its_identity() -> None:
    tracing.configure(_settings())

    @tracing.traced("model.call", module="web2")
    def draft(word: str) -> str:
        """Draft it."""
        return word.upper()

    assert draft("ok") == "OK"
    assert draft.__name__ == "draft"
    assert draft.__doc__ == "Draft it."
