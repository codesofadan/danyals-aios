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


# =========================================================================== #
# experience_gate - Law 16: Experience must be SHOWN, not asserted
# =========================================================================== #
from app.services.content_lint import (  # noqa: E402
    evaluate_experience,
    find_claims,
    find_markers,
    signals_from_manifest_text,
)

_EXPERIENCE_PROBES = [
    "",
    "We are licensed and insured.",                       # claim, no proof
    "Licensed contractor, license #1043382.",             # claim + its proof
    "Serving Austin since 2009.",                         # claim, no proof
    "Serving Austin since 2009. See [our record](https://example.com/about).",
    "Over 1,200 roofs replaced.",
    "Rated 4.9 out of 5 across 312 reviews.",
    "Meet our founder Jane Doe.",
    "![our crew on a roof](https://cdn.example.com/crew.jpg)",
    "15 years of experience serving the metro area.",
    "A page with no experience language at all, purely descriptive prose about a service.",
]


@pytest.fixture(scope="module")
def original_experience():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import experience_gate

        return experience_gate
    finally:
        sys.path.remove(str(_SCRIPTS))


@pytest.mark.parametrize("text", _EXPERIENCE_PROBES)
@pytest.mark.parametrize("manifest", [None, "year_founded: 2009\nreviews: 312\nlicense_no: X"])
def test_experience_port_matches_the_original(text, manifest, original_experience) -> None:
    theirs = original_experience.evaluate(text, manifest)
    mine = evaluate_experience(text, proof_signals=signals_from_manifest_text(manifest))

    assert mine.signals == theirs["signals"]
    assert len(mine.claims) == len(theirs["claims"])
    # Same issue codes on the same lines, in the same order.
    assert [(i.code, i.line) for i in mine.issues] == [
        (code, line) for _sev, code, line, _msg in theirs["issues"]
    ]
    assert len(mine.markers) == theirs["marker_total"]


@pytest.mark.parametrize("page", _PAGES, ids=lambda p: p.parent.name)
def test_experience_port_matches_on_the_corpus_samples(page, original_experience) -> None:
    text = page.read_text()
    theirs = original_experience.evaluate(text, None)
    mine = evaluate_experience(text)
    assert [(i.code, i.line) for i in mine.issues] == [
        (code, line) for _s, code, line, _m in theirs["issues"]
    ]


# --- the distinctions that make this gate real ----------------------------- #
def test_a_bare_number_never_proves_itself() -> None:
    """The circularity the gate exists to prevent: if "since 2009" counted as its own
    evidence, every fabricated claim would self-certify and the gate would be
    decorative."""
    r = evaluate_experience("Serving Austin since 2009.")
    assert not r.passed
    assert [c.kind for c in r.unproven] == ["YEARS_IN_BUSINESS"]


def test_the_word_licensed_is_a_claim_but_a_license_number_is_proof() -> None:
    assert not evaluate_experience("We are licensed and insured.").passed
    proved = evaluate_experience("We are licensed and insured. License #1043382.")
    assert proved.passed, [i.message for i in proved.issues]


def test_client_supplied_signals_can_satisfy_a_claim_the_draft_cannot() -> None:
    """The P2 path: proof lives in `sme_slots`, not inline in the prose. A page may
    legitimately claim what the client can back without printing the artifact."""
    # A RELATIVE image path deliberately: an image whose src is an http URL also
    # registers as `cited_source` (the corpus regex matches any `](https://...)`),
    # which would satisfy the claim on its own and hide what this test is checking.
    text = "Serving Austin since 2009. ![crew](/img/crew.jpg)"
    assert not evaluate_experience(text).passed
    assert evaluate_experience(text, proof_signals=frozenset({"founding_date"})).passed


def test_it_names_exactly_which_artifacts_the_sme_interview_must_collect() -> None:
    """The hard-halt payoff: ask the operator three specific questions, not hand them
    a generic intake form."""
    r = evaluate_experience("Licensed and insured. Serving Austin since 2009. Rated 4.9 out of 5.")
    assert r.missing_proof_categories() >= {"founding_date", "review_source"}
    assert "photo" not in r.missing_proof_categories(), "only categories that resolve a CLAIM"


def test_a_draft_with_no_experience_markers_fails_even_with_no_claims() -> None:
    """Asserting nothing is not the same as proving something. A page that shows no
    first-hand artifact at all has no Experience to rank on."""
    r = evaluate_experience("Purely descriptive prose about a service, making no claims.")
    assert [i.code for i in r.issues] == ["NO_EXPERIENCE_MARKERS"]


def test_markers_and_claims_are_reported_in_document_order() -> None:
    text = "Line one.\n![a](b.png)\nSince 2009.\nLicense #1043382."
    assert [m.line for m in find_markers(text)] == sorted(m.line for m in find_markers(text))
    assert [c.line for c in find_claims(text)] == sorted(c.line for c in find_claims(text))


def test_an_http_image_url_also_registers_as_a_cited_source() -> None:
    """Faithful to the corpus regex, which matches any `](https://...)` including an
    image src. Pinned rather than silently inherited: it means an externally hosted
    photo can satisfy a claim that wanted a citation. Tighten it in the dimension
    rewrite if that proves too generous - but change it deliberately, not by accident."""
    r = evaluate_experience("Since 2009. ![crew](https://cdn.example.com/c.jpg)")
    assert "cited_source" in r.signals
    assert r.passed


# =========================================================================== #
# keyword_density - anti-stuffing by page COVERAGE, not by tally
# =========================================================================== #
from app.services.content_lint import analyse_density, count_phrase, tokenize  # noqa: E402

_DENSITY_PROBES = [
    ("", ["ac repair"]),
    ("ac repair " * 50, ["ac repair"]),
    ("A page about heating and cooling in San Jose.", ["ac repair"]),
    ("emergency ac repair san jose " * 3 + "filler " * 200, ["emergency ac repair san jose", "ac"]),
    ("24 hour plumber near me", ["24 hour plumber"]),          # numerals belong in keywords
    ("## Heading\n[anchor](https://x.com) ac repair", ["ac repair"]),
]


@pytest.fixture(scope="module")
def original_density():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import keyword_density

        return keyword_density
    finally:
        sys.path.remove(str(_SCRIPTS))


@pytest.mark.parametrize("text,keywords", _DENSITY_PROBES)
def test_density_port_matches_the_original(text, keywords, original_density) -> None:
    theirs = original_density.analyse(text, keywords)
    mine = analyse_density(text, keywords)

    assert mine.total_words == theirs["total_words"]
    assert len(mine.rows) == len(theirs["rows"])
    for row, ref in zip(mine.rows, theirs["rows"], strict=True):
        assert row.keyword == ref["keyword"]
        assert row.occurrences == ref["occurrences"]
        assert row.words_in_phrase == ref["words_in_phrase"]
        assert row.density == pytest.approx(ref["density"])
        assert row.over == ref["over"]


def test_density_measures_page_coverage_not_occurrence_count() -> None:
    """The distinction the whole check rests on. A five-word phrase occupies five
    times the page a one-word term does at the same occurrence count, and saturation
    is what the stuffing systems react to."""
    text = "one two three four five " * 20                       # 100 tokens
    short = analyse_density(text, ["one"]).rows[0]
    longer = analyse_density(text, ["one two three four five"]).rows[0]
    assert short.occurrences == longer.occurrences == 20
    assert longer.density == pytest.approx(short.density * 5)


def test_phrase_matching_is_contiguous_not_bag_of_words() -> None:
    """"ac repair" must not be credited to a page that merely contains "ac" and
    "repair" in unrelated sentences."""
    assert analyse_density("The ac unit needed a repair.", ["ac repair"]).rows[0].occurrences == 0
    assert analyse_density("Book an ac repair today.", ["ac repair"]).rows[0].occurrences == 1


def test_numerals_are_kept_here_unlike_the_readability_tokenizer() -> None:
    """Not an inconsistency: a keyword can legitimately contain a number ("24 hour
    plumber"), whereas a zip code is not a readability word."""
    assert tokenize("24 hour plumber") == ["24", "hour", "plumber"]
    assert count_phrase(tokenize("call a 24 hour plumber"), tokenize("24 hour plumber")) == 1


def test_markdown_is_stripped_before_counting() -> None:
    """Shares the readability tokenizer's strip step, so a URL cannot inflate the
    denominator and dilute a real stuffing signal."""
    plain = analyse_density("ac repair " * 10, ["ac repair"]).rows[0].density
    marked = analyse_density(
        "## H\n[a](https://example.com/very/long/path) " + "ac repair " * 10, ["ac repair"]
    ).rows[0].density
    assert marked == pytest.approx(plain, rel=0.15)


def test_empty_and_blank_keywords_are_skipped_not_counted_as_zero() -> None:
    r = analyse_density("some prose here", ["", "   ", "prose"])
    assert [row.keyword for row in r.rows] == ["prose"]


# =========================================================================== #
# duplication_gate - the anti-doorway / scaled-content gate
# =========================================================================== #
import re  # noqa: E402

from app.services.content_lint import (  # noqa: E402
    compare_documents,
    jaccard,
    shingle_hashes,
    shingle_set,
)

_DUP_PROBES = [
    ("identical", "the same words repeated here", "the same words repeated here"),
    ("disjoint", "alpha beta gamma delta epsilon", "one two three four five six"),
    ("templated", "We fix roofs in Austin fast and well.", "We fix roofs in Dallas fast and well."),
    ("short", "tiny", "tiny"),
    ("empty-one-side", "", "some words here at all"),
]


@pytest.fixture(scope="module")
def original_duplication():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import duplication_gate

        return duplication_gate
    finally:
        sys.path.remove(str(_SCRIPTS))


@pytest.mark.parametrize("label,a,b", _DUP_PROBES, ids=[p[0] for p in _DUP_PROBES])
def test_duplication_port_matches_the_original(label, a, b, original_duplication) -> None:
    theirs = original_duplication.jaccard(
        original_duplication.shingles(original_duplication.tokenize(a), 5),
        original_duplication.shingles(original_duplication.tokenize(b), 5),
    )
    mine = compare_documents({"a": a, "b": b}).pairs[0].similarity
    assert mine == pytest.approx(theirs)


def test_a_single_document_passes_rather_than_erroring() -> None:
    """The CLI refuses fewer than two files. On the QA path a lone page genuinely has
    no sibling to duplicate, so it must pass, not raise."""
    r = compare_documents({"only": "some prose"})
    assert r.pairs == () and r.passed


def test_shingling_is_order_sensitive_unlike_bag_of_words() -> None:
    """The reason shingles are used at all: reordered text is not duplicate text."""
    a, b = "alpha beta gamma delta epsilon", "epsilon delta gamma beta alpha"
    assert jaccard(shingle_set(a), shingle_set(b)) == 0.0


def test_hashes_are_stable_across_processes() -> None:
    """`content_outline_shingles` (P2) indexes these, so they must not depend on
    PYTHONHASHSEED - the builtin hash() would differ between workers and the index
    would silently stop matching."""
    import subprocess

    text = "a stable phrase used to check the digest is reproducible everywhere"
    code = (
        "import sys; sys.path.insert(0, '.');"
        "from app.services.content_lint import shingle_hashes;"
        f"print(sorted(shingle_hashes({text!r}))[:3])"
    )
    runs = {
        subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            cwd=str(_BACKEND), env={"PYTHONHASHSEED": seed, "PATH": ""},
        ).stdout.strip()
        for seed in ("0", "1", "12345")
    }
    assert len(runs) == 1, f"hashes vary with PYTHONHASHSEED: {runs}"
    assert runs != {""}, "subprocess produced no output"


def test_hashes_fit_a_postgres_bigint() -> None:
    for h in shingle_hashes("some prose to hash into the signed 64 bit range"):
        assert -(2**63) <= h < 2**63


# --- THE FINDING: raw shingling misses the template this platform produces --- #
def test_the_entity_token_hides_template_duplication_and_must_be_masked() -> None:
    """P3 DESIGN CONSTRAINT, measured rather than assumed.

    `content_generator._FRAMEWORK_MOVES` is a fixed heading table, so two competing
    clients in two cities get heading skeletons identical except for the city token.
    That is the scaled-content fingerprint the platform itself manufactures.

    But shingling those headings RAW does not catch it: the city appears in most
    headings, so most shingles differ. Measured on real generator output, Austin vs
    Round Rock scores 58% at w=3 and only 28% at w=5 - both UNDER the 70% ceiling, and
    getting WORSE as the window grows, which is the opposite of the intuition.

    Masking the target entity first exposes it completely: 100% at both widths.

    So the P3 uniqueness gate must normalise the target query out of the text before
    shingling. Without this the gate would have shipped, passed its own tests, and
    silently approved every templated page.
    """
    from app.services.content_generator import generate
    from tests.test_content_generator import FakeWriter, _brief, _context, _source_pack

    def headings_for(city: str) -> tuple[str, str]:
        result = generate(
            _brief(keyword=f"roof repair {city}"), _source_pack(), _context(),
            page_type="service", framework="AIDA", writer=FakeWriter(),
        )
        return "\n".join(h.text for h in result.headings), f"roof repair {city}"

    def mask(text: str, primary: str) -> str:
        out = re.sub(re.escape(primary), "<TARGET>", text, flags=re.I)
        city = primary.split("repair", 1)[-1].strip()
        return re.sub(re.escape(city), "<CITY>", out, flags=re.I)

    (head_a, key_a), (head_b, key_b) = headings_for("austin"), headings_for("round rock")

    for width in (3, 5):
        raw = compare_documents({"a": head_a, "b": head_b}, size=width).pairs[0]
        assert not raw.duplicate, (
            f"w={width}: raw shingling scored {raw.similarity:.0%} and DID flag the "
            "template. If this now passes, the finding is obsolete - delete this test."
        )
        masked = compare_documents(
            {"a": mask(head_a, key_a), "b": mask(head_b, key_b)}, size=width
        ).pairs[0]
        assert masked.similarity == pytest.approx(1.0), (
            f"w={width}: entity-masked skeletons should be identical, got "
            f"{masked.similarity:.0%}"
        )
        assert masked.duplicate
