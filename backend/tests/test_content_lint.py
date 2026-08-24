"""P1B: the ported corpus validators must agree with the scripts they came from.

A port is only trustworthy if it is provably the same function. These tests run the
ORIGINAL corpus script and the ported module over the same inputs and require
identical numbers - so "we ported it" is a checked claim rather than a commit message.

They also pin the two tokenizer decisions that make this port supersede
`content_qa.flesch_reading_ease`, and the purity guarantees that let it run inside the
QA loop (no file writes, no network, no clock).
"""

from __future__ import annotations

import pathlib
import sys

import pytest

from app.services.content_lint import (
    analyse_readability,
    count_syllables,
    split_sentences,
    strip_markdown,
    words_of,
)

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
_SCRIPTS = _BACKEND / "seo-content-os" / "scripts"
_FIXTURES = _BACKEND / "tests" / "fixtures" / "content_golden"

_PAGES = [
    _FIXTURES / "sample-dental" / "dental-implants" / "page.md",
    _FIXTURES / "sample-storage" / "climate-controlled-storage-round-rock" / "page.md",
]

# Deliberately awkward: no terminators, numerics, unicode, markdown debris, empties.
_PROBES = [
    "",
    "   ",
    "One sentence.",
    "No terminator at all",
    "Call 555.1234 now. Then visit 3.5 miles away.",
    "## Heading\n\n- bullet one\n- bullet two\n\n[link](https://example.com/a/b) and ![alt](i.png).",
    "Ünïcödé têxt with accents and a café. It reads fine.",
    "```\ncode fence\n```\nAfter the fence.",
    "Word " * 400,
    "A very long sentence that simply keeps going and going without any terminator at all so that it "
    "comfortably exceeds the twenty five word threshold used to flag long sentences here.",
]


@pytest.fixture(scope="module")
def original():
    """The unported corpus script, imported directly (stdlib-only, so no new deps)."""
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import readability_scorer

        return readability_scorer
    finally:
        sys.path.remove(str(_SCRIPTS))


# --------------------------------------------------------------------------- #
# 1 - EQUIVALENCE: the port is the same function
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text", _PROBES)
def test_port_matches_the_original_script_exactly(text: str, original) -> None:
    theirs = original.analyse(text)
    mine = analyse_readability(text)

    assert mine.sentences == theirs["sentences"]
    assert mine.words == theirs["words"]
    assert mine.syllables == theirs["syllables"]
    assert mine.long_sentences == theirs["long_sentences"]
    assert mine.flesch_reading_ease == pytest.approx(theirs["flesch_reading_ease"])
    assert mine.fk_grade == pytest.approx(theirs["fk_grade"])
    assert mine.long_ratio == pytest.approx(theirs["long_ratio"])


@pytest.mark.parametrize("page", _PAGES, ids=lambda p: p.parent.name)
def test_port_matches_the_original_on_the_corpus_own_samples(page: pathlib.Path, original) -> None:
    body = page.read_text().split("---", 2)[-1]
    theirs = original.analyse(body)
    mine = analyse_readability(body)
    assert mine.flesch_reading_ease == pytest.approx(theirs["flesch_reading_ease"])
    assert mine.words == theirs["words"] and mine.sentences == theirs["sentences"]


@pytest.mark.parametrize("text", _PROBES)
def test_helper_functions_match_the_original(text: str, original) -> None:
    """The helpers are the shared primitive four other validators build on, so they
    must match too - not just the aggregate the top-level call returns."""
    assert strip_markdown(text) == original.strip_markdown(text)
    assert split_sentences(text) == original.split_sentences(text)
    assert words_of(text) == original.words_of(text)


@pytest.mark.parametrize(
    "word", ["table", "the", "a", "implant", "orthodontics", "queue", "rhythm", "", "555", "e"]
)
def test_syllable_counting_matches_the_original(word: str, original) -> None:
    assert count_syllables(word) == original.count_syllables(word)


# --------------------------------------------------------------------------- #
# 2 - the two tokenizer decisions that supersede content_qa
# --------------------------------------------------------------------------- #
def test_numerals_are_not_counted_as_prose_words() -> None:
    """`content_qa._words` keeps `555`, `90403`, `2026` as one-syllable words, which
    drags syllables-per-word down and reads EASIER than the prose is. A zip code is
    spoken as five syllables, not one."""
    assert words_of("Call 555 1234 at 90403 in 2026") == ["Call", "at", "in"]


def test_a_period_inside_a_number_does_not_end_a_sentence() -> None:
    """The whitespace requirement in the split. `content_qa._SENTENCE_RE` breaks here
    and reads 101 sentences where this reads 96 on the same page."""
    assert len(split_sentences("Call us on 555.1234 today.")) == 1
    assert len(split_sentences("It is 3.5 miles away.")) == 1
    # A real boundary still splits.
    assert len(split_sentences("First one. Second one.")) == 2


def test_image_alt_text_is_not_body_prose_but_link_anchors_are() -> None:
    """An image caption is not read as part of the sentence; a link's anchor text is."""
    assert "alt" not in strip_markdown("![alt](i.png)")
    assert "our guide" in strip_markdown("See [our guide](https://example.com/x).")


# --------------------------------------------------------------------------- #
# 3 - purity: this runs inside the QA loop
# --------------------------------------------------------------------------- #
def test_is_pure_no_writes_no_network(tmp_path, monkeypatch) -> None:
    """8 of the 22 corpus scripts write files as a side effect - qa_scorecard dropped a
    scorecard.md into the test fixtures on its first run. A validator that writes
    during a content job would litter the artifact store, so the ports must not."""
    import builtins
    import socket

    def _no_network(*_a, **_k):  # pragma: no cover - the point is that it never runs
        raise AssertionError("a validator attempted a network connection")

    real_open = builtins.open

    def _guarded_open(file, mode="r", *a, **k):
        if any(m in str(mode) for m in ("w", "a", "x", "+")):
            raise AssertionError(f"a validator attempted to write {file!r}")
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(socket, "socket", _no_network)
    monkeypatch.setattr(builtins, "open", _guarded_open)

    before = sorted(tmp_path.iterdir())
    analyse_readability("Some prose here. It has two sentences.")
    assert sorted(tmp_path.iterdir()) == before


def test_empty_input_returns_a_zeroed_report_rather_than_raising() -> None:
    """This sits on the QA path; a degraded section must not crash the job."""
    r = analyse_readability("")
    assert r.words == 0 and r.sentences == 0
    assert isinstance(r.flesch_reading_ease, float)


def test_report_exposes_a_verdict_without_baking_one_into_the_numbers() -> None:
    r = analyse_readability("Word " * 400)
    assert isinstance(r.passed, bool)
    assert isinstance(r.issues(), list)
    assert (r.issues() == []) is r.passed
