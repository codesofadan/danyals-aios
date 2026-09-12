"""Form intelligence: what leaves the browser, and what is trusted coming back.

NO network - the summarizer is a scripted stub.

**THE TWO MOST IMPORTANT TESTS IN THIS FILE** are
``test_a_credential_shaped_field_never_leaves_the_browser`` and
``test_a_mapping_for_a_field_that_was_never_sent_is_discarded``.

The first is the privacy boundary. This feature exists to send form STRUCTURE to a
model; the moment it sends a password field's context, or an operator's typed value,
a convenience becomes an exfiltration path through a directory nobody audited. The
sanitizer is a WHITELIST for exactly that reason - an unknown field kind is dropped,
not passed through.

The second is the trust boundary. The model proposes what to type into somebody's
live business listing. An index it invented, a key outside the vocabulary, a
confidence that is not a number - all of it is discarded rather than believed. The
model is a suggestion engine here, not an authority.

Also pinned: IGNORE is a real answer (a honeypot that gets filled makes the directory
discard the submission silently, and the operator is told it worked); a low-confidence
mapping is OFFERED, never typed; and a failure degrades to copy buttons instead of
fabricating a plan.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.services.form_intelligence import (
    APPLY_THRESHOLD,
    CANONICAL_KEYS,
    IGNORE,
    FieldDigest,
    apply_values,
    build_prompt,
    fingerprint,
    parse_response,
    plan_form,
    sanitize,
)
from integrations.llm import LLMResult

pytestmark = pytest.mark.unit


def raw(**kw: Any) -> dict[str, Any]:
    base = {"kind": "text", "selector": "#x", "name": "", "label": ""}
    base.update(kw)
    return base


class ScriptedSummarizer:
    """Returns a fixed body; records what it was asked."""

    def __init__(self, body: str) -> None:
        self._body = body
        self.prompts: list[str] = []
        self.systems: list[Any] = []

    def summarize(self, prompt: str, *, model: str, max_tokens: int,
                  system: Any = None, cache: Any = None) -> LLMResult:
        self.prompts.append(prompt)
        self.systems.append(system)
        return LLMResult(text=self._body, input_tokens=100, output_tokens=50)


class ExplodingSummarizer:
    def summarize(self, *a: Any, **kw: Any) -> LLMResult:
        raise RuntimeError("provider down")


# --------------------------------------------------------------------------- #
# 1. THE PRIVACY BOUNDARY
# --------------------------------------------------------------------------- #
class TestWhatLeavesTheBrowser:
    @pytest.mark.parametrize("name", [
        "password", "user_password", "passwd", "pwd",
        "cc_number", "card-number", "cvv", "cvc", "ssn",
        "csrf_token", "xsrf", "authenticity_token", "api_key", "secret",
    ])
    def test_a_credential_shaped_field_never_leaves_the_browser(self, name: str) -> None:
        """Matched on name, id OR label - a field called one thing and labelled
        another must still be caught."""
        digest, notes = sanitize([
            raw(name="company", label="Business name"),
            raw(name=name, label="x"),
            raw(name="z", label=name),
        ])
        sent = " ".join(json.dumps(f.prompt_view()) for f in digest)
        assert name not in sent
        assert len(digest) == 1, "only the business-name field may travel"
        assert any("credential-shaped" in n for n in notes)

    def test_the_field_kind_list_is_a_whitelist_not_a_blacklist(self) -> None:
        """An unknown control is DROPPED. A blacklist would let a future browser
        control start travelling the day it ships."""
        digest, notes = sanitize([
            raw(kind="text", name="company"),
            raw(kind="password", name="p"),
            raw(kind="file", name="upload"),
            raw(kind="hidden", name="h"),
            raw(kind="some-future-control", name="f"),
        ])
        assert [f.name for f in digest] == ["company"]
        assert any("unsupported kind" in n for n in notes)

    def test_the_digest_carries_no_typed_value(self) -> None:
        """The extension may send a value by mistake; it must not survive. The digest
        dataclass has no value field at all, which is the strongest form of this."""
        digest, _ = sanitize([raw(name="phone", label="Phone", value="+1 555 0199")])
        view = digest[0].prompt_view()
        assert "value" not in view
        assert "555" not in json.dumps(view)

    def test_the_selector_is_not_sent_to_the_model(self) -> None:
        """Selectors can embed generated class names and page content, and the model
        cannot reason about them anyway. The index is the join key."""
        digest, _ = sanitize([
            raw(name="company", label="Name", selector="#form > .row-7f3a[data-client='acme']")
        ])
        assert "acme" not in build_prompt(digest)
        assert "7f3a" not in build_prompt(digest)

    def test_long_text_is_truncated_before_it_travels(self) -> None:
        digest, _ = sanitize([raw(name="d", label="L" * 5000, near="N" * 5000)])
        assert len(digest[0].label) <= 160 and len(digest[0].near_text) <= 160

    def test_an_oversized_form_is_bounded_and_says_so(self) -> None:
        digest, notes = sanitize([raw(name=f"f{i}", label=f"Field {i}") for i in range(200)])
        assert len(digest) == 60
        assert any("200" in n for n in notes), "the operator must know it was truncated"


# --------------------------------------------------------------------------- #
# 2. THE TRUST BOUNDARY
# --------------------------------------------------------------------------- #
class TestWhatIsTrustedComingBack:
    def test_a_mapping_for_a_field_that_was_never_sent_is_discarded(self) -> None:
        """An invented index would attach a value to whatever field happened to sit at
        that position - or to nothing. Either way the model made it up."""
        digest, _ = sanitize([raw(name="company", label="Business name")])
        out, notes = parse_response(
            json.dumps([{"i": 0, "key": "business_name", "confidence": 0.9},
                        {"i": 7, "key": "phone", "confidence": 0.9}]),
            digest,
        )
        assert [m.index for m in out] == [0]
        assert any("not sent" in n for n in notes)

    def test_a_key_outside_the_vocabulary_is_discarded(self) -> None:
        digest, _ = sanitize([raw(name="a", label="A"), raw(name="b", label="B")])
        out, notes = parse_response(
            json.dumps([{"i": 0, "key": "business_name", "confidence": 0.9},
                        {"i": 1, "key": "bank_account", "confidence": 0.99}]),
            digest,
        )
        assert [m.key for m in out] == ["business_name"]
        assert any("outside the vocabulary" in n for n in notes)

    def test_a_duplicate_index_is_taken_once(self) -> None:
        digest, _ = sanitize([raw(name="a", label="A")])
        out, _ = parse_response(
            json.dumps([{"i": 0, "key": "business_name", "confidence": 0.9},
                        {"i": 0, "key": "phone", "confidence": 0.9}]),
            digest,
        )
        assert len(out) == 1 and out[0].key == "business_name"

    def test_a_non_numeric_confidence_becomes_zero_not_certainty(self) -> None:
        """The safe direction. A confidence that failed to parse must not read as 1.0
        and get typed into a live form."""
        digest, _ = sanitize([raw(name="a", label="A")])
        out, _ = parse_response(
            json.dumps([{"i": 0, "key": "business_name", "confidence": "very sure"}]), digest
        )
        assert out[0].confidence == 0.0
        assert out[0].fillable is False

    def test_confidence_is_clamped_into_range(self) -> None:
        digest, _ = sanitize([raw(name="a", label="A"), raw(name="b", label="B")])
        out, _ = parse_response(
            json.dumps([{"i": 0, "key": "phone", "confidence": 5.0},
                        {"i": 1, "key": "phone", "confidence": -3.0}]), digest
        )
        assert [m.confidence for m in out] == [1.0, 0.0]

    @pytest.mark.parametrize("body", ["not json at all", "{}", "[", "", "```", "[1,2,3]"])
    def test_a_malformed_response_maps_nothing(self, body: str) -> None:
        digest, _ = sanitize([raw(name="a", label="A")])
        out, notes = parse_response(body, digest)
        assert out == []
        assert notes, "a failure must explain itself"

    def test_unmapped_fields_are_reported_not_hidden(self) -> None:
        """A form where only half the fields came back must not look complete."""
        digest, _ = sanitize([raw(name=f"f{i}", label=f"F{i}") for i in range(4)])
        _, notes = parse_response(
            json.dumps([{"i": 0, "key": "business_name", "confidence": 0.9}]), digest
        )
        assert any("unmapped" in n for n in notes)


# --------------------------------------------------------------------------- #
# 3. WHAT ACTUALLY GETS TYPED
# --------------------------------------------------------------------------- #
class TestWhatGetsTyped:
    def test_ignore_is_never_filled(self) -> None:
        """A honeypot that gets filled makes the directory discard the submission
        silently, and the operator is told it worked."""
        digest, _ = sanitize([raw(name="hp", label="Leave empty")])
        out, _ = parse_response(
            json.dumps([{"i": 0, "key": IGNORE, "confidence": 1.0}]), digest
        )
        assert out[0].fillable is False

    def test_a_low_confidence_mapping_is_offered_not_typed(self) -> None:
        digest, _ = sanitize([raw(name="a", label="A"), raw(name="b", label="B")])
        out, _ = parse_response(
            json.dumps([{"i": 0, "key": "phone", "confidence": APPLY_THRESHOLD},
                        {"i": 1, "key": "phone", "confidence": APPLY_THRESHOLD - 0.01}]),
            digest,
        )
        assert out[0].fillable is True
        assert out[1].fillable is False

    def test_apply_values_emits_exactly_the_fillers_shape(self) -> None:
        """The semantic lane and the earned-spec lane must produce the SAME
        instruction, so the read-back honesty layer in filler.ts is untouched."""
        plan = plan_form(
            ScriptedSummarizer(json.dumps([{"i": 0, "key": "phone", "confidence": 0.95}])),
            [raw(name="a", label="A", selector="#a")],
            host="example.com", model="m",
        )
        out = apply_values(plan, {"phone": "+1 555 0199"})
        assert out == [{"selector": "#a", "valueKey": "phone", "value": "+1 555 0199"}]
        assert set(out[0]) == {"selector", "valueKey", "value"}

    def test_a_mapped_field_with_no_client_value_is_skipped(self) -> None:
        """Typing an empty string is not neutral - it can clear a pre-filled default."""
        plan = plan_form(
            ScriptedSummarizer(json.dumps([{"i": 0, "key": "phone", "confidence": 0.95}])),
            [raw(name="a", label="A", selector="#a")],
            host="example.com", model="m",
        )
        assert apply_values(plan, {"phone": "   "}) == []
        assert apply_values(plan, {}) == []


# --------------------------------------------------------------------------- #
# 4. THE CACHE KEY
# --------------------------------------------------------------------------- #
class TestFingerprint:
    def _digest(self, labels: list[str], selectors: list[str] | None = None) -> list[FieldDigest]:
        sel = selectors or [f"#f{i}" for i in range(len(labels))]
        d, _ = sanitize([raw(name=f"n{i}", label=labels[i], selector=sel[i])
                         for i in range(len(labels))])
        return d

    def test_the_same_form_fingerprints_the_same(self) -> None:
        a = self._digest(["Name", "Phone"])
        b = self._digest(["Name", "Phone"])
        assert fingerprint(a, host="x.com") == fingerprint(b, host="x.com")

    def test_generated_selectors_do_not_break_the_cache(self) -> None:
        """Selectors can carry per-load class names. If they fed the fingerprint, the
        cache would miss on every single visit and the feature would be billed per
        click - which is the whole cost model."""
        a = self._digest(["Name"], ["#form .css-1a2b3c input"])
        b = self._digest(["Name"], ["#form .css-9z8y7x input"])
        assert fingerprint(a, host="x.com") == fingerprint(b, host="x.com")

    def test_a_changed_form_fingerprints_differently(self) -> None:
        """A form that gained a field must MISS the cache - that is exactly when the
        stored mapping is stale and would fill the wrong boxes."""
        assert fingerprint(self._digest(["Name"]), host="x.com") != fingerprint(
            self._digest(["Name", "Phone"]), host="x.com"
        )

    def test_field_order_alone_does_not_change_the_fingerprint(self) -> None:
        """The SAME fields in a different DOM order are the same form. Note the fields
        must carry their own name with them - an earlier version of this test moved the
        labels while leaving the names pinned to position, which is a different form and
        correctly fingerprints differently."""
        fields = [raw(name="nm", label="Name", selector="#a"),
                  raw(name="ph", label="Phone", selector="#b")]
        a, _ = sanitize(fields)
        b, _ = sanitize(list(reversed(fields)))
        assert fingerprint(a, host="x.com") == fingerprint(b, host="x.com")

    def test_the_host_is_part_of_the_key(self) -> None:
        """Two directories can ship the same boilerplate form and want different
        mappings; sharing one cache row across hosts would leak one into the other."""
        d = self._digest(["Name"])
        assert fingerprint(d, host="a.com") != fingerprint(d, host="b.com")


# --------------------------------------------------------------------------- #
# 5. DEGRADING HONESTLY
# --------------------------------------------------------------------------- #
class TestDegrading:
    def test_a_provider_failure_returns_a_reason_and_no_mappings(self) -> None:
        """The operator must land back on copy buttons, not on a fabricated plan."""
        plan = plan_form(ExplodingSummarizer(), [raw(name="a", label="A", selector="#a")],
                         host="x.com", model="m")
        assert plan.ok is False
        assert plan.mappings == ()
        assert plan.error

    def test_a_page_with_no_fillable_fields_says_so(self) -> None:
        plan = plan_form(ScriptedSummarizer("[]"), [raw(kind="file", name="u")],
                         host="x.com", model="m")
        assert plan.ok is False and "no fillable fields" in plan.error

    def test_an_unmappable_form_is_an_error_not_an_empty_success(self) -> None:
        """An empty plan reported as OK renders as "analysed, nothing to fill" - which
        is indistinguishable from a form that genuinely needs nothing."""
        plan = plan_form(ScriptedSummarizer("sorry, I cannot help with that"),
                         [raw(name="a", label="A", selector="#a")], host="x.com", model="m")
        assert plan.ok is False

    def test_the_system_prompt_is_sent_separately_for_cache_reuse(self) -> None:
        """A stable system prefix across every form is what makes prompt caching
        possible; folding it into the user turn would defeat it."""
        stub = ScriptedSummarizer(json.dumps([{"i": 0, "key": "phone", "confidence": 0.9}]))
        plan_form(stub, [raw(name="a", label="A", selector="#a")], host="x.com", model="m")
        assert stub.systems[0] and "canonical business-listing" in str(stub.systems[0])
        assert "canonical business-listing" not in stub.prompts[0]


def test_the_vocabulary_has_no_duplicates_and_excludes_the_sentinel() -> None:
    assert len(set(CANONICAL_KEYS)) == len(CANONICAL_KEYS)
    assert IGNORE not in CANONICAL_KEYS, "IGNORE is a sentinel, not a fillable key"
