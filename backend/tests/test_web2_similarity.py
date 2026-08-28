"""The cross-property similarity gate (WEB2-007 / R2-09..R2-11).

The load-bearing test is
``test_entity_masking_makes_the_templated_verdict_threshold_independent``. It encodes the
measurement that shapes the whole design: shingling RAW text leaves a templated pair's
score wherever the entity-token ratio happens to put it, so the verdict hangs on exactly
where the block line is drawn - and on real generator output measured in this repo it
landed under the ceiling entirely. Masking the client entity first pins the templated
case at ~1.0, which is what makes the threshold robust rather than delicate. Everything
else here is guard-rails around that one property.

The second thing this file has to prove is the opposite error: two genuinely distinct
articles for two different clients in the same trade MUST pass. A gate that cries wolf
gets switched off or routed around, and then nothing is checked at all.
"""

from __future__ import annotations

import pytest

from app.services.content_lint import shingle_hashes
from app.services.web2_similarity import (
    BODY_SHINGLE_SIZE,
    SAMPLE_MODULUS,
    Candidate,
    error_code,
    evaluate,
    fingerprint,
    headings_of,
    normalize,
    resemblance,
)

pytestmark = pytest.mark.unit


# A real templating shape: one skeleton, the city and brand swapped. This is what the
# generator produces for two clients in the same trade, and it is the case the gate exists
# for - not a copy-paste duplicate, which is trivially caught by the hash.
def _article(brand: str, city: str) -> str:
    return f"""# Emergency Drain Unblocking in {city}

## Why {city} Homes Get Blocked Drains
Older properties across {city} were built with narrow clay pipework that roots find
easily, and {brand} sees the same three causes again and again through the winter.

## How {brand} Clears a Blockage
A camera survey first, then high-pressure jetting, then a second survey so the customer
sees the pipe is actually clear rather than taking our word for it.

## What It Costs in {city}
Most {city} jobs are a single visit. {brand} quotes before starting, and the price does
not change once the van is on the drive.

## Booking {brand}
Call or use the form; {brand} covers {city} and the surrounding villages daily.
"""


def _fp(brand: str, city: str, anchor: str = ""):
    return fingerprint(
        body_md=_article(brand, city), client_name=brand, geo=city, anchor=anchor
    )


def _cand(fp, web2_id: str = "w2-other", scope: str = "platform") -> Candidate:
    return Candidate(
        web2_id=web2_id, scope=scope, body_sha256=fp.body_sha256,
        body_hashes=fp.body_hashes, heading_hashes=fp.heading_hashes,
        anchor_norm=fp.anchor_norm,
    )


# --------------------------------------------------------------------------- #
# THE test.
# --------------------------------------------------------------------------- #
def test_entity_masking_makes_the_templated_verdict_threshold_independent() -> None:
    """Two articles off one skeleton, differing only in brand + city.

    What this actually demonstrates, stated precisely: on this fixture the RAW score is
    ~0.39 while the MASKED score is ~1.00. Both happen to clear R2's 0.25 block line, so
    this pair alone does NOT prove a raw gate would let templating through - the honest
    claim is narrower and more useful. Raw resemblance lands wherever the ratio of
    entity tokens to prose puts it, so the verdict depends on exactly where the line is
    drawn; masked resemblance pins a templated pair at ~1.0, so EVERY threshold below 1
    catches it and the block line stops being a delicate judgement.

    That the delicacy is real, not hypothetical, is the repo's own measurement on real
    generator output (content_pipeline/outline.py:11-23): raw 27.6% at w=5 against that
    gate's 70% duplicate ceiling - i.e. raw PASSED templated pages outright there, and
    got worse as the window grew. The lesson transfers even though the ceiling differs.
    """
    a_raw = shingle_hashes(normalize(_article("Leeds Drainage", "Leeds")), size=BODY_SHINGLE_SIZE)
    b_raw = shingle_hashes(normalize(_article("Bristol Drains", "Bristol")), size=BODY_SHINGLE_SIZE)
    raw_score = resemblance(a_raw, b_raw)
    masked_score = resemblance(
        _fp("Leeds Drainage", "Leeds").body_hashes,
        _fp("Bristol Drains", "Bristol").body_hashes,
    )

    # The property that matters: masking moves a templated pair to effectively total
    # overlap, well clear of any plausible threshold, and strictly above the raw score.
    assert masked_score > raw_score
    assert masked_score >= 0.95, f"masked templating should be ~total, got {masked_score:.3f}"
    assert raw_score < 0.95, (
        "raw scored ~total on this fixture, so it no longer demonstrates the gap "
        "masking closes - rewrite the fixture with more distinct prose"
    )
    assert evaluate(
        _fp("Leeds Drainage", "Leeds"), [_cand(_fp("Bristol Drains", "Bristol"))]
    ).blocked


def test_two_genuinely_distinct_articles_in_one_trade_pass() -> None:
    """The false-positive case, which matters as much as the true positive: a gate that
    blocks legitimately independent work gets overridden by habit, and then it protects
    nothing."""
    other = """# Choosing a Drainage Contractor

## Questions Worth Asking Before You Book
Ask whether the quote covers a post-job survey, whether the engineer is insured for
work on shared drains, and how quickly a follow-up visit is scheduled if the problem
returns within a fortnight.

## Reading a Camera Survey
The footage should show the full run, not a still frame. Ask for the recording.
"""
    fp_other = fingerprint(body_md=other, client_name="Bristol Drains", geo="Bristol")
    verdict = evaluate(_fp("Leeds Drainage", "Leeds"), [_cand(fp_other)])
    assert verdict.verdict == "pass", f"distinct articles must pass, got {verdict.check}"


# --------------------------------------------------------------------------- #
# Exact duplicates and the heading skeleton.
# --------------------------------------------------------------------------- #
def test_an_identical_body_is_an_unconditional_block() -> None:
    fp = _fp("Leeds Drainage", "Leeds")
    verdict = evaluate(fp, [_cand(fp)])
    assert verdict.blocked
    assert verdict.check == "body_sha256"


def test_the_same_outline_with_different_words_blocks_on_the_heading_skeleton() -> None:
    """The case body resemblance alone misses: rewritten prose under a reused outline."""
    reworded = """# Emergency Drain Unblocking in Leeds

## Why Leeds Homes Get Blocked Drains
Victorian clay runs beneath much of the city; tree roots exploit every hairline crack
once temperatures drop below freezing for a sustained spell.

## How Leeds Drainage Clears a Blockage
Survey, jet, survey again. The second survey is the proof, not a formality.

## What It Costs in Leeds
One visit covers most jobs. The quote is fixed before any work begins on site.

## Booking Leeds Drainage
Phone the office or submit the online form for same-day attendance where available.
"""
    fp_reworded = fingerprint(
        body_md=reworded, client_name="Leeds Drainage", geo="Leeds"
    )
    verdict = evaluate(fp_reworded, [_cand(_fp("Leeds Drainage", "Leeds"))])
    assert verdict.blocked
    assert verdict.check in {"heading_skeleton", "body_resemblance"}


# --------------------------------------------------------------------------- #
# Anchors (R2-14.2) and scoping.
# --------------------------------------------------------------------------- #
def test_a_repeated_anchor_within_a_client_blocks() -> None:
    fp = _fp("Leeds Drainage", "Leeds", anchor="Leeds Drainage")
    other = fingerprint(
        body_md="# Something Else\n\nEntirely different prose about gutters and soffits.\n",
        client_name="Leeds Drainage", geo="Leeds", anchor="Leeds Drainage",
    )
    verdict = evaluate(fp, [_cand(other, scope="client")])
    assert verdict.blocked
    assert verdict.check == "anchor_reuse"


def test_a_repeated_anchor_on_an_unrelated_platform_scope_does_not_block() -> None:
    """Anchor uniqueness is scoped to the client and the shared house account. Two
    unrelated clients may legitimately use their own brand names, and those can collide
    by coincidence - blocking on that would be a false positive with no safety value."""
    fp = _fp("Leeds Drainage", "Leeds", anchor="drain unblocking")
    other = fingerprint(
        body_md="# Unrelated\n\nDifferent prose entirely, about roofing work.\n",
        client_name="Bristol Drains", geo="Bristol", anchor="drain unblocking",
    )
    verdict = evaluate(fp, [_cand(other, scope="platform")])
    assert verdict.verdict == "pass"


def test_the_verdict_reports_the_scope_and_the_colliding_id() -> None:
    fp = _fp("Leeds Drainage", "Leeds")
    verdict = evaluate(fp, [_cand(fp, web2_id="w2-42", scope="account")])
    assert verdict.scope == "account"
    assert verdict.colliding_web2_id == "w2-42"
    assert error_code(verdict) == "sim_block:body_sha256:account:w2-42"


def test_a_passing_verdict_has_no_error_code() -> None:
    assert error_code(evaluate(_fp("Leeds Drainage", "Leeds"), [])) == ""


# --------------------------------------------------------------------------- #
# Mechanics.
# --------------------------------------------------------------------------- #
def test_no_candidates_is_a_pass_not_an_error() -> None:
    """The first property for a client has nothing to collide with."""
    assert evaluate(_fp("Leeds Drainage", "Leeds"), []).verdict == "pass"


def test_headings_are_extracted_in_order() -> None:
    assert headings_of("# One\n\ntext\n\n## Two\n\n### Three\n") == ["One", "Two", "Three"]


def test_the_sampled_subset_is_the_mod_16_slice_and_is_a_real_subset() -> None:
    fp = _fp("Leeds Drainage", "Leeds")
    assert fp.sampled <= fp.body_hashes
    assert all(h % SAMPLE_MODULUS == 0 for h in fp.sampled)


def test_hashes_are_stable_across_calls() -> None:
    """blake2b, not the builtin hash(): PYTHONHASHSEED randomises the latter per
    process, so two workers would index different values for the same article and the
    gate would silently stop matching."""
    assert _fp("Leeds Drainage", "Leeds").body_hashes == _fp("Leeds Drainage", "Leeds").body_hashes


def test_resemblance_of_empty_sets_is_zero_not_a_crash() -> None:
    assert resemblance(frozenset(), frozenset()) == 0.0
    assert resemblance({1, 2}, frozenset()) == 0.0


def test_normalize_keeps_stopwords() -> None:
    """Stopwords carry the template - two documents off one skeleton differ mostly in
    their content words, so the function words are the signal, not noise."""
    assert "the" in normalize("The quick brown fox and the lazy dog")
