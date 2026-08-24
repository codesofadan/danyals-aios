"""P1A': calibrate the backend's QA scorers against the corpus's own validators.

The backend and the SEO-CONTENT-OS corpus contain TWO independent implementations of
several of the same deterministic checks. `content_qa.PROVISIONAL` is True and its
thresholds are self-declared "NOT yet validated against real ranking outcomes or a
human SEO grade", so before either is trusted the cheapest available evidence is to
run both over the corpus's own shipped sample pages and diff them.

This file is that diff, executable and pinned. It is not a pass/fail quality gate - it
is the ACCEPTANCE TARGET for the P1B port: when `readability_scorer` is ported
in-process, these deltas must go to zero, and this file is what proves it.

Findings recorded here (2026-08-24):

  1. The two Flesch implementations disagree by 1.4-2.1 points on the corpus's own
     samples, from IDENTICAL formulas. The whole difference is tokenization.

  2. `content_qa` counts NUMERIC tokens as words - `555`, `tel`, `90403`, `1234`,
     `2026`, `3d` - and each contributes >=1 syllable via the `max(1, ...)` floor.
     Numerals are short, so they drag syllables-per-word DOWN and push Flesch UP.
     For LOCAL SEO pages this is not an edge case: every page carries NAP data,
     prices, dimensions and years in business.

  3. `content_qa` splits SENTENCES on periods inside numbers ("555.1234", "3.5"),
     reading 101 sentences where the corpus reads 96. That one is unambiguously a bug
     in the backend, not a difference of opinion.

  4. IMPACT IS BOUNDED, and saying so matters more than the finding. The score bands
     are wide (55-75 -> 100), so on BOTH samples the disagreement changes the emitted
     `structure_readability` score by exactly ZERO. It would flip 100 -> 88 only for a
     page whose true Flesch sits near a band edge (~75). This is a real defect with a
     narrow blast radius - not a reason to distrust every score already emitted.

RESOLVED 2026-08-24 (P1B). The scoring path now calls the ported corpus scorer, so
the disagreement no longer reaches an emitted score. `content_qa.flesch_reading_ease`
survives as a DEPRECATED published name that nothing in the scoring path calls, and
`on_page` was switched over with it - its module docstring claims "exactly ONE content
rubric", and leaving two divergent implementations would have made that false.

These tests are kept rather than deleted: they still pin the legacy function's
behaviour, so if anyone routes scoring back through it the delta reappears here with
an explanation attached rather than as an unexplained score shift.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
_SCRIPTS = _BACKEND / "seo-content-os" / "scripts"
_FIXTURES = _BACKEND / "tests" / "fixtures" / "content_golden"

_SAMPLES = {
    "dental": _FIXTURES / "sample-dental" / "dental-implants" / "page.md",
    "storage": _FIXTURES / "sample-storage" / "climate-controlled-storage-round-rock" / "page.md",
}


@pytest.fixture(scope="module")
def corpus_readability():
    """Import the corpus validator directly. It is stdlib-only (asserted by
    test_doctrine_corpus), so this adds no dependency."""
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import readability_scorer

        return readability_scorer
    finally:
        sys.path.remove(str(_SCRIPTS))


def _body(path: pathlib.Path) -> str:
    """The page body, minus YAML frontmatter."""
    return path.read_text().split("---", 2)[-1]


@pytest.mark.parametrize("name", sorted(_SAMPLES))
def test_flesch_delta_between_the_two_implementations_is_known(
    name: str, corpus_readability
) -> None:
    """Pin the LEGACY function's disagreement with the corpus.

    The scoring path no longer uses it (see the module docstring). This remains as a
    tripwire: if scoring is ever routed back through `flesch_reading_ease`, the delta
    returns and this test explains why.
    """
    from app.services import content_qa as cq

    body = _body(_SAMPLES[name])
    backend = cq.flesch_reading_ease(cq._prose(body))
    corpus = corpus_readability.analyse(body)["flesch_reading_ease"]

    assert backend > corpus, (
        "the backend has always read EASIER than the corpus because it counts numeric "
        "tokens as short words. If this flipped, the tokenizer changed."
    )
    assert 1.0 < backend - corpus < 3.0, (
        f"{name}: flesch delta moved to {backend - corpus:.2f} (was 1.4-2.1). Either "
        "the scorer or the fixture changed - find out which before re-pinning."
    )


@pytest.mark.parametrize("name", sorted(_SAMPLES))
def test_the_disagreement_does_not_change_the_emitted_score(
    name: str, corpus_readability
) -> None:
    """The honest half of the finding: on these samples the delta changes NOTHING the
    reviewer sees. Recorded so the defect is not overstated - and so that if a future
    change to the bands DOES make it bite, this test says so."""
    from app.services import content_qa as cq

    def band(flesch: float) -> int:
        if 55 <= flesch <= 75:
            return 100
        if 45 <= flesch <= 85:
            return 88
        if 35 <= flesch <= 95:
            return 74
        return 55

    body = _body(_SAMPLES[name])
    backend = cq.flesch_reading_ease(cq._prose(body))
    corpus = corpus_readability.analyse(body)["flesch_reading_ease"]
    assert band(backend) == band(corpus)


def test_backend_counts_numerals_and_url_debris_as_prose_words() -> None:
    """The mechanism behind the delta, isolated so it cannot be argued away.

    `_prose` strips URLs but leaves image debris, and `_words` keeps bare numerals.
    """
    from app.services import content_qa as cq

    words = cq._words(cq._prose("Call 555.1234 or visit ![roof photo](img/roof.png)."))
    assert "555" in words and "1234" in words, "numerals are counted as prose words"
    assert "png" in words or "img" in words, "image debris survives _prose"


def test_backend_splits_sentences_inside_numbers() -> None:
    """Unambiguously a bug rather than a difference of opinion: a decimal point or a
    phone number ends a 'sentence', inflating the sentence count and the score."""
    from app.services import content_qa as cq

    one_sentence = "Call us on 555.1234 today."
    assert len(cq._SENTENCE_RE.findall(one_sentence)) > 1, (
        "if this now reads 1 sentence the bug is FIXED - delete this test and tighten "
        "the delta bound in test_flesch_delta_between_the_two_implementations_is_known"
    )


def test_the_scoring_path_now_agrees_with_the_corpus(corpus_readability) -> None:
    """The acceptance criterion for the port, now met.

    `_score_structure_readability` calls the ported scorer, so the number the reviewer
    sees is the corpus's number - not the legacy tokenizer's, which read every page
    with a phone number or a price as easier than it is.
    """
    from app.services.content_lint import analyse_readability

    for path in _SAMPLES.values():
        body = _body(path)
        assert analyse_readability(body).flesch_reading_ease == pytest.approx(
            corpus_readability.analyse(body)["flesch_reading_ease"]
        )


def test_one_readability_rubric_across_the_platform() -> None:
    """on_page and content QA must not diverge. on_page's docstring claims "exactly
    ONE content rubric in this system"; P1B briefly made that false by switching only
    content_qa, so this pins both onto the same function."""
    import inspect

    from app.modules.on_page import service as onpage

    source = inspect.getsource(onpage)
    assert "analyse_readability(page.body_text)" in source
    assert "flesch_reading_ease(page.body_text)" not in source
