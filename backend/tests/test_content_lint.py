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


# =========================================================================== #
# information_gain_scorer - Law 15: gain over coverage
# =========================================================================== #
from app.services.content_lint import (  # noqa: E402
    MIN_GAIN,
    extract_items,
    residual_ratio,
    score_information_gain,
)

_CONSENSUS = (
    "Dental implants replace missing teeth. A titanium post is placed in the jaw "
    "and a crown is attached. The process takes several months."
)
_GAIN_PROBES = [
    ("rehash", _CONSENSUS, _CONSENSUS),
    ("disjoint", "Round Rock crews charge $189 for the after-hours call in 78664.", _CONSENSUS),
    ("empty-draft", "", _CONSENSUS),
    ("quotes", 'Our tech said "we found the leak in twenty minutes" on site.', _CONSENSUS),
    ("entities", "Sunbridge Dental Group serves Santa Monica and Glendale.", _CONSENSUS),
    ("numbers", "We charge $89 and arrive in 47 minutes, since 2011, across 1,284 calls.", _CONSENSUS),
]


@pytest.fixture(scope="module")
def original_gain():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import information_gain_scorer

        return information_gain_scorer
    finally:
        sys.path.remove(str(_SCRIPTS))


@pytest.mark.parametrize("label,draft,consensus", _GAIN_PROBES, ids=[p[0] for p in _GAIN_PROBES])
def test_gain_port_matches_the_original(label, draft, consensus, original_gain) -> None:
    theirs = original_gain.score(draft, consensus)
    mine = score_information_gain(draft, consensus)

    assert mine.residual == pytest.approx(theirs["residual"])
    assert mine.matched_tokens == theirs["matched_tokens"]
    assert mine.total_tokens == theirs["total_tokens"]
    assert mine.item_count == theirs["item_count"]
    assert mine.net_new_count == theirs["net_new_count"]
    for cat in ("NUMBERS", "QUOTES", "ENTITIES"):
        assert list(mine.items[cat]) == list(theirs["items"][cat])
        assert list(mine.net_new[cat]) == list(theirs["net_new"][cat])


@pytest.mark.parametrize("label,draft,_c", _GAIN_PROBES, ids=[p[0] for p in _GAIN_PROBES])
def test_gain_port_matches_the_original_without_a_baseline(label, draft, _c, original_gain) -> None:
    theirs = original_gain.score(draft, None)
    mine = score_information_gain(draft, None)
    assert mine.residual is theirs["residual"] is None
    assert mine.item_count == theirs["item_count"]
    assert mine.has_consensus is theirs["has_consensus"] is False


def test_a_verbatim_rehash_scores_zero_gain() -> None:
    """The defining case. A page that says exactly what the consensus already says
    adds nothing, however fluent it is."""
    r = score_information_gain(_CONSENSUS, _CONSENSUS)
    assert r.residual == pytest.approx(0.0)
    assert not r.passed
    assert "rehash" in r.issues()[0]


def test_first_party_specifics_are_what_creates_gain() -> None:
    """Gain lives in numbers, quotes and local entities - the SME-sourced material -
    not in more paragraphs about the same thing."""
    r = score_information_gain(
        "Our crew charges $189 in 78664. Jane Doe said \"we sealed it in an hour\".",
        _CONSENSUS,
    )
    assert r.residual > MIN_GAIN and r.passed
    assert r.net_new["NUMBERS"] and r.net_new["QUOTES"]


def test_it_abstains_rather_than_passing_when_there_is_no_baseline() -> None:
    """A residual against nothing is meaningless. Reporting `pass` for an unmeasurable
    page would be worse than reporting nothing, so callers must check has_consensus."""
    r = score_information_gain("anything at all", None)
    assert r.residual is None and r.has_consensus is False
    assert r.issues() == []


def test_sentence_initial_stopwords_are_not_read_as_entities() -> None:
    """A capitalisation-based finder would otherwise report "The Round Rock" and
    inflate the local-specificity inventory with grammar."""
    items = extract_items("The Round Rock crew arrived. Our Santa Monica office called.")
    assert "The Round Rock crew" not in items["ENTITIES"]
    assert any("Round Rock" in e for e in items["ENTITIES"])


def test_alignment_does_not_discard_common_words() -> None:
    """`difflib`'s autojunk heuristic drops tokens appearing in >1% of a long
    sequence - on prose that is the common words, which would inflate the apparent
    residual exactly where it must not. The port pins autojunk=False."""
    base = "the quick brown fox jumps over the lazy dog " * 40
    residual, matched, total = residual_ratio(base, base)
    assert residual == pytest.approx(0.0)
    assert matched == total


# =========================================================================== #
# conversion_linter - the deterministic half of quality gate G13
# =========================================================================== #
from app.services.content_lint import is_strong_cta, lint_conversion  # noqa: E402

_CTA_PROBES = [
    ("bare-prose", "Just some prose about air conditioning with no ask at all."),
    ("full", "## Reviews\nGreat work.\n\n[Call us now](tel:+15551234567) - $89 flat, satisfaction guaranteed.\n"),
    ("mechanical-only", "[Submit your details](https://x.com/form) and we will be in touch."),
    ("no-cta-after-proof", "[Call us now](tel:+15551234567)\n\n## Frequently asked questions\nQ and A here.\n"),
    ("off-goal", "[Call us today](tel:+15551234567)\n\nSubscribe to our newsletter and download our guide.\n"),
    ("priced", "[Book your estimate](tel:+15551234567) starting at $199 with a money-back guarantee."),
    ("empty", ""),
]


@pytest.fixture(scope="module")
def original_conversion():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import conversion_linter

        return conversion_linter
    finally:
        sys.path.remove(str(_SCRIPTS))


@pytest.mark.parametrize("label,text", _CTA_PROBES, ids=[p[0] for p in _CTA_PROBES])
def test_conversion_port_matches_the_original(label, text, original_conversion) -> None:
    theirs = original_conversion.lint(text)
    mine = lint_conversion(text)
    assert [(i.severity, i.code, i.line) for i in mine.issues] == [
        (sev, code, line) for sev, code, line, _msg in theirs
    ]


@pytest.mark.parametrize("page", _PAGES, ids=lambda p: p.parent.name)
def test_conversion_port_matches_on_the_corpus_samples(page, original_conversion) -> None:
    text = page.read_text()
    theirs = original_conversion.lint(text)
    mine = lint_conversion(text)
    assert [(i.severity, i.code, i.line) for i in mine.issues] == [
        (sev, code, line) for sev, code, line, _m in theirs
    ]


def test_the_reader_who_finished_the_faq_must_meet_an_ask() -> None:
    """The most under-appreciated check. Someone who read the reviews AND the FAQ is
    the most qualified visitor on the page, and they reach the bottom with nothing to
    do. A CTA at the top does not serve them."""
    text = "[Call us now](tel:+15551234567)\n\n## Frequently asked questions\nQ and A.\n"
    r = lint_conversion(text)
    assert not r.passed
    assert any(i.code == "NO_CTA_AFTER_PROOF_FAQ" for i in r.errors)

    fixed = text + "\n[Call us today](tel:+15551234567)\n"
    assert lint_conversion(fixed).passed


def test_a_call_and_form_pair_is_not_treated_as_a_competing_cta() -> None:
    """Deliberate: those two serve URGENT vs CONSIDERED intent and belong together. A
    newsletter or a download is what actually splits the goal."""
    pair = "[Call us now](tel:+15551234567) or [book your estimate](https://x.com/book)."
    assert not any(i.code == "OFF_GOAL_CTA" for i in lint_conversion(pair).issues)

    split = pair + "\n\nSubscribe to our newsletter."
    assert any(i.code == "OFF_GOAL_CTA" for i in lint_conversion(split).warnings)


def test_severity_is_load_bearing_warnings_do_not_block() -> None:
    """Unlike the earlier gates, ERROR and WARN mean different things here: ERROR fails
    G13, WARN asks a human to look. A page missing only a price signal still passes."""
    r = lint_conversion("[Call us now](tel:+15551234567) - satisfaction guaranteed.")
    assert r.warnings and not r.errors and r.passed


def test_a_direct_call_action_counts_as_a_strong_cta() -> None:
    assert is_strong_cta("Call us now on 555-1234")
    assert is_strong_cta("Get my free estimate")
    assert not is_strong_cta("Submit the form below")


# =========================================================================== #
# blocklist_lint - quality gate G9, voice fidelity
# =========================================================================== #
from app.services.content_lint import lint_blocklist, term_to_regex  # noqa: E402
from app.services.content_lint.blocklist import _default_terms  # noqa: E402

_VOICE_PROBES = [
    "",
    "We pride ourselves on fast, reliable, and affordable service.",
    "In the ever-evolving landscape of home services, we delve into solutions.",
    "Our affordable repairs start at $89.",              # conditional + a real specific
    "Our affordable repairs are competitively priced.",  # conditional, no specific
    "Reliable service you can trust.",                   # one near-synonym, not stacked
    "Reliable, dependable, trustworthy service.",        # stacked
    "```\ndelve into the code fence\n```\nClean prose here.",
]


@pytest.fixture(scope="module")
def original_blocklist():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import blocklist_lint

        return blocklist_lint
    finally:
        sys.path.remove(str(_SCRIPTS))


@pytest.mark.parametrize("text", _VOICE_PROBES)
def test_blocklist_port_matches_the_original(text: str, original_blocklist) -> None:
    path = str(_BACKEND / "seo-content-os" / "knowledge" / "voice" / "vocabulary-blocklist.md")
    terms, groups = original_blocklist.parse_blocklist(path)
    theirs = original_blocklist.scan(text, terms, groups)
    mine = lint_blocklist(text)

    assert [(h.line, h.col, h.match) for h in mine.hits] == [
        (h["line"], h["col"], h["match"]) for h in theirs
    ]


def test_the_corpus_blocklist_is_actually_loaded() -> None:
    """The terms come from the doctrine file, not from a list re-typed into Python -
    so editing the doctrine changes the check, which is the point."""
    terms = _default_terms()
    assert len(terms) > 100, f"only {len(terms)} terms parsed; the blocklist may have moved"
    displays = {t.display.lower() for t in terms}
    assert {"delve", "leverage"} <= displays


def test_a_tricolon_is_one_hit_not_three() -> None:
    """The report should reflect one bad sentence, not three bad words."""
    hits = lint_blocklist("We offer fast, reliable, and affordable service.").hits
    assert any(h.match.lower() == "fast, reliable, and affordable" for h in hits)


def test_a_lone_near_synonym_is_fine_but_stacking_is_the_tell() -> None:
    """Any one of these is ordinary English. Three in a row is filler."""
    lone = lint_blocklist("Reliable service, every time.").hits
    stacked = lint_blocklist("Reliable, dependable, trustworthy service.").hits
    assert len(stacked) > len(lone)


def test_a_conditional_term_is_allowed_beside_a_real_specific() -> None:
    """The objection was never the word "affordable" - it was the vagueness. With a
    price on the line the term carries real information."""
    vague = lint_blocklist("Our affordable repairs are competitively priced.")
    specific = lint_blocklist("Our affordable repairs start at $89.")
    assert any(h.match.lower() == "affordable" for h in vague.hits)
    assert not any(h.match.lower() == "affordable" for h in specific.hits)


def test_a_generic_placeholder_term_is_dropped_rather_than_flooding_the_report() -> None:
    """"at [Brand]" would wildcard-match "at our practice", "at once", "at the
    consult". A placeholder term needs 2+ literal anchors of 3+ characters."""
    assert term_to_regex("at [Brand]") is None
    assert term_to_regex("here at [Brand] we understand") is not None


def test_fenced_code_is_not_linted_for_voice() -> None:
    assert lint_blocklist("```\ndelve into this\n```").passed


def test_client_banned_phrases_layer_on_top_of_doctrine() -> None:
    r = lint_blocklist("We are better than Competitor Corp.", extra_banned=["Competitor Corp"])
    assert any(h.tier == "Client" for h in r.hits)


# =========================================================================== #
# link_graph - hub-and-spoke equity routing across the whole client site
# =========================================================================== #
from app.services.content_lint import (  # noqa: E402
    analyze_links,
    build_graph,
    build_page,
)

_GRAPH_FIXTURE = [
    ("/hvac", "hub", "hvac", ["/hvac/ac-repair", "/hvac/furnace"]),
    ("/hvac/ac-repair", "spoke", "hvac", ["/hvac"]),
    ("/hvac/furnace", "spoke", "hvac", ["/plumbing/leak"]),
    ("/plumbing/leak", "spoke", "plumbing", ["/gone"]),
]


@pytest.fixture(scope="module")
def original_links():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import link_graph

        return link_graph
    finally:
        sys.path.remove(str(_SCRIPTS))


def test_link_graph_port_matches_the_original(original_links) -> None:
    theirs_graph = original_links.new_graph("acme")
    for url, role, silo, links in _GRAPH_FIXTURE:
        original_links.add_page(theirs_graph, url, role, silo, links=links)
    theirs, theirs_total, theirs_inbound = original_links.analyze(theirs_graph)

    mine = analyze_links(build_graph(
        [build_page(u, r, s, links=ls) for u, r, s, ls in _GRAPH_FIXTURE], client="acme"
    ))

    assert mine.total_issues == theirs_total
    assert dict(mine.inbound) == theirs_inbound
    assert list(mine.orphans) == theirs["orphans"]
    assert [list(x) for x in mine.over_linked] == [list(x) for x in theirs["over_linked"]]
    assert [list(x) for x in mine.missing_spoke_to_hub] == [list(x) for x in theirs["missing_spoke_to_hub"]]
    assert [list(x) for x in mine.cross_silo_spoke] == [list(x) for x in theirs["cross_silo_spoke"]]
    assert [list(x) for x in mine.dangling] == [list(x) for x in theirs["dangling"]]
    assert list(mine.silo_no_hub) == theirs["silo_no_hub"]


def test_an_orphan_is_invisible_however_good_the_page_is() -> None:
    """Zero inbound internal links means the page cannot accrue or pass equity. No
    per-page check can see this, which is why content_qa's stub cannot."""
    g = build_graph([
        build_page("/hub", "hub", "s", links=["/a"]),
        build_page("/a", "spoke", "s", links=["/hub"]),
        build_page("/lonely", "spoke", "s", links=["/hub"]),
    ])
    assert "/lonely" in analyze_links(g).orphans


def test_every_spoke_must_link_up_to_its_hub() -> None:
    """Equity landing on a spoke has to flow back to the hub or the cluster never
    lifts. A spoke that does not link up is a dead end for authority."""
    g = build_graph([
        build_page("/hub", "hub", "s", links=["/a"]),
        build_page("/a", "spoke", "s", links=[]),
    ])
    assert [u for u, _ in analyze_links(g).missing_spoke_to_hub] == ["/a"]


def test_the_spoke_to_hub_rule_is_only_enforced_when_a_hub_exists() -> None:
    """Otherwise a silo mid-build would report a violation for every page in it, for
    a structural reason the writer cannot fix from the page."""
    g = build_graph([build_page("/a", "spoke", "s", links=[])])
    r = analyze_links(g)
    assert r.missing_spoke_to_hub == ()
    assert r.silo_no_hub == ("s",)   # the real problem is reported instead


def test_two_hubs_in_one_silo_split_the_authority() -> None:
    g = build_graph([
        build_page("/h1", "hub", "s", links=["/h2"]),
        build_page("/h2", "hub", "s", links=["/h1"]),
    ])
    assert analyze_links(g).silo_multi_hub == (("s", ("/h1", "/h2")),)


def test_self_links_and_duplicates_are_dropped_at_build_time() -> None:
    page = build_page("/a", "spoke", "s", links=["/a", "/b", "/b", "  /c  ", ""])
    assert page.links == ("/b", "/c")


def test_role_is_validated_rather_than_silently_accepted() -> None:
    with pytest.raises(ValueError, match="role must be"):
        build_page("/a", "pillar", "s")


# =========================================================================== #
# geo_page_linter - AI-search citability (Law 17 / the Local AI-Citation Stack)
# =========================================================================== #
from app.services.content_lint import (  # noqa: E402
    analyse_geo,
    opens_with_direct_answer,
    split_h2_sections,
)

_GEO_PROBES = [
    "",
    "## How much does it cost?\n\n$1,400 on average in Tempe.\n",
    "## How much does it cost?\n\nWhen it comes to pricing, every home is different.\n",
    "## Is it worth it?\n\nYes. A new unit pays back in 4 years.\n",
    "## Overview\n\nWe understand that you have questions.\n\n## Cost\n\n$99 flat.\n",
    "Intro prose with no heading at all, which should not be scored as an answer block.",
    ("## A\n\nac repair phoenix is the best ac repair phoenix option because ac repair "
     "phoenix works. ac repair phoenix again and ac repair phoenix once more.\n"),
    "## Q\n\nPer the state board, 42% of units fail. Last updated: 2026-01-02\n",
]


@pytest.fixture(scope="module")
def original_geo():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import geo_page_linter

        return geo_page_linter
    finally:
        sys.path.remove(str(_SCRIPTS))


@pytest.mark.parametrize("text", _GEO_PROBES)
def test_geo_port_matches_the_original(text: str, original_geo) -> None:
    theirs = original_geo.analyse(text)
    mine = analyse_geo(text)

    assert mine.total_words == theirs["total_words"]
    assert mine.n_h2 == theirs["n_h2"] and mine.n_h2_ok == theirs["n_h2_ok"]
    assert mine.stat_count == theirs["stat_count"]
    assert mine.stat_density == pytest.approx(theirs["stat_density"])
    assert mine.source_count == theirs["source_count"]
    assert mine.quote_count == theirs["quote_count"]
    assert mine.stuffed == theirs["stuffed"]
    assert mine.stuff_phrase == theirs["stuff_phrase"]
    assert mine.has_freshness == theirs["has_freshness"]
    assert mine.issues() == original_geo.evaluate(theirs)


@pytest.mark.parametrize("page", _PAGES, ids=lambda p: p.parent.name)
def test_geo_port_matches_on_the_corpus_samples(page, original_geo) -> None:
    text = page.read_text()
    assert analyse_geo(text).issues() == original_geo.evaluate(original_geo.analyse(text))


def test_a_filler_opener_makes_a_block_unextractable() -> None:
    """An answer engine extracts passages. A block that opens with "When it comes
    to..." has no answer to lift, however good the paragraph below it is."""
    ok, _ = opens_with_direct_answer("When it comes to pricing, every home is different.")
    assert not ok
    ok, _ = opens_with_direct_answer("$1,400 on average in Tempe.")
    assert ok


def test_a_yes_no_opener_counts_as_a_direct_answer() -> None:
    assert opens_with_direct_answer("Yes. A new unit pays back in about 4 years.")[0]


def test_the_intro_is_not_scored_as_an_answer_block() -> None:
    """Content before the first H2 is the page opening, not a passage. Scoring it
    would penalise every normally-written page."""
    sections = split_h2_sections("Intro prose here.\n\n## Real block\n\n$5 flat.\n")
    assert [h for h, _ in sections] == ["Real block"]
    assert "Intro prose" not in sections[0][1]


def test_stuffing_is_detected_without_being_told_the_keyword() -> None:
    """Self-contained: it finds the most-repeated meaningful phrase, so it catches
    stuffing of a term nobody declared as a target. Keyword stuffing was the ONLY
    tactic in the GEO study that made citation LESS likely."""
    r = analyse_geo("## A\n\n" + "ac repair phoenix is great. " * 8)
    assert r.stuffed and r.stuff_phrase and "ac repair" in r.stuff_phrase


def test_ordinary_connective_phrasing_is_not_reported_as_stuffing() -> None:
    """Needs 3+ occurrences AND a non-stopword, so "of the" repeated does not fire."""
    r = analyse_geo("## A\n\n" + "One of the things. Some of the others. Most of the rest. " * 3)
    assert not r.stuffed or (r.stuff_phrase and r.stuff_phrase not in ("of the", "the"))


def test_sources_are_counted_on_raw_markdown_not_stripped_text() -> None:
    """Stripping markdown removes the links, which would zero the Cite Sources lever."""
    assert analyse_geo("## A\n\nSee [the board](https://example.com/x). $5.\n").source_count >= 1


# =========================================================================== #
# schema_validator - JSON-LD structured data
# =========================================================================== #
import json  # noqa: E402

from app.services.content_lint import validate_schema, walk_nodes  # noqa: E402

_SCHEMA_PROBES = [
    {},
    {"@type": "LocalBusiness"},
    {"@type": "Plumber", "name": "X", "telephone": "1", "address": {}},
    {"@graph": [{"@type": "Person", "name": "Jane"}, {"@type": "Organization"}]},
    {"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": "Q?"}]},
    {"@type": "BreadcrumbList", "itemListElement": [{"position": 1}]},
    {"@type": "SomethingUnknown", "whatever": 1},
]


@pytest.fixture(scope="module")
def original_schema():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import schema_validator

        return schema_validator
    finally:
        sys.path.remove(str(_SCRIPTS))


@pytest.mark.parametrize("data", _SCHEMA_PROBES)
def test_schema_port_matches_the_original(data, original_schema) -> None:
    theirs, their_count = original_schema.validate(data)
    mine = validate_schema(data)
    assert mine.node_count == their_count
    assert [(i.path, i.message) for i in mine.issues] == list(theirs)


def test_schema_port_matches_on_the_corpus_samples(original_schema) -> None:
    for name in ("sample-dental/dental-implants", "sample-storage/climate-controlled-storage-round-rock"):
        data = json.loads((_FIXTURES / name / "schema.json").read_text())
        theirs, count = original_schema.validate(data)
        mine = validate_schema(data)
        assert mine.node_count == count
        assert [(i.path, i.message) for i in mine.issues] == list(theirs)


# --- the cross-check that makes this port worth having --------------------- #
def test_the_backends_own_json_ld_passes_the_corpus_validator() -> None:
    """Two independently written implementations agreeing is real evidence.

    `content_schema.build_json_ld` was written for this repo; the validator came from
    the corpus. Neither was built against the other, so a clean pass here is a genuine
    cross-check rather than a rule grading itself.
    """
    from app.services import content_schema as cs

    biz = cs.Business(
        name="Valley Air", url="https://valleyair.example", telephone="+1-555-123-4567",
        business_type="HVACBusiness",
        address=cs.PostalAddress(
            street_address="12 Main St", address_locality="San Jose",
            address_region="CA", postal_code="95112", address_country="US",
        ),
    )
    page = cs.Page(
        url="https://valleyair.example/ac-repair", title="AC Repair San Jose",
        description="Emergency AC repair.", service_type="AC Repair",
        area_served=("San Jose",),
        faqs=(cs.FaqItem(question="How much?", answer="A flat $89 diagnostic."),),
    )
    doc = cs.build_json_ld(
        "service", biz, page,
        breadcrumbs=(cs.Breadcrumb("Home", "https://valleyair.example"), cs.Breadcrumb("AC Repair")),
    )
    report = validate_schema(doc)
    assert report.node_count > 0
    assert report.passed, report.messages()


# --- the two checks that are not shape validation -------------------------- #
def test_self_serving_review_markup_is_flagged() -> None:
    """Compliance spine D3, and the corpus names it the most common local
    manual-action cause. The markup that looks like it earns stars is exactly what
    makes the page ineligible for them."""
    doc = {"@type": "Plumber", "name": "X", "telephone": "1",
           "address": {"streetAddress": "1", "addressLocality": "a", "addressRegion": "b",
                       "postalCode": "c", "addressCountry": "d"},
           "aggregateRating": {"ratingValue": 4.9}}
    assert any("D3" in i.message for i in validate_schema(doc).issues)


def test_a_monthly_rental_offer_must_declare_lease_out() -> None:
    """A storage unit is leased, not sold (SS-SCHEMA2)."""
    offer = {"@type": "Offer",
             "priceSpecification": {"@type": "UnitPriceSpecification", "unitCode": "MON"}}
    assert any("LeaseOut" in i.message for i in validate_schema(offer).issues)

    leased = dict(offer, businessFunction="http://purl.org/goodrelations/v1#LeaseOut")
    assert not any("LeaseOut" in i.message for i in validate_schema(leased).issues)


def test_an_ordinary_offer_is_not_forced_to_declare_lease_out() -> None:
    """Scoped to monthly price specs so it never fires on a normal discount Offer -
    a validator that cried wolf on every Offer would be switched off."""
    assert not any("LeaseOut" in i.message
                   for i in validate_schema({"@type": "Offer", "price": "20"}).issues)


def test_an_unrecognised_type_is_not_an_error() -> None:
    """No rule to apply is not the same as a violation. Treating unknown types as
    failures makes a validator hostile to legitimate schema it was not taught."""
    assert validate_schema({"@type": "SomethingUnknown", "x": 1}).passed


def test_nested_and_graph_nodes_are_walked() -> None:
    doc = {"@graph": [{"@type": "A", "inner": {"@type": "Person", "name": "n"}}]}
    assert len(list(walk_nodes(doc))) == 2


# =========================================================================== #
# compliance_lint - over-optimisation, thin content, NAP consistency
# =========================================================================== #
from app.services.content_lint import extract_schema_nap, lint_compliance  # noqa: E402

_COMPLIANCE_PROBES = [
    ("empty", "", []),
    ("no-h1", "## Section\n\n" + "word " * 60, []),
    ("two-h1", "# One\n\ntext\n\n# Two\n\ntext", []),
    ("dupe-heading", "# T\n\n## A\n\nx\n\n## A\n\ny", []),
    ("thin-section", "# T\n\n## Short\n\nonly three words\n", []),
    ("em-dash", "# T\n\nA sentence — with a dash.\n", []),
    ("stuffed", "# T\n\n" + "roof repair austin " * 30, ["roof repair austin"]),
    ("over-exact-heading",
     "# roof repair austin\n\n## roof repair austin cost\n\nx\n\n## roof repair austin time\n\ny",
     ["roof repair austin"]),
    ("missing-target", "# T\n\nUnrelated prose entirely.\n", ["roof repair austin"]),
]


@pytest.fixture(scope="module")
def original_compliance():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import compliance_lint

        return compliance_lint
    finally:
        sys.path.remove(str(_SCRIPTS))


@pytest.mark.parametrize(
    "label,text,keywords", _COMPLIANCE_PROBES, ids=[p[0] for p in _COMPLIANCE_PROBES]
)
def test_compliance_port_matches_the_original(label, text, keywords, original_compliance) -> None:
    theirs = original_compliance.lint(text, keywords=keywords)
    mine = lint_compliance(text, keywords=keywords)
    assert [(i.severity, i.code, i.line) for i in mine.issues] == [
        (sev, code, line) for sev, code, line, _msg in theirs
    ]


@pytest.mark.parametrize("page", _PAGES, ids=lambda p: p.parent.name)
def test_compliance_port_matches_on_the_corpus_samples(page, original_compliance) -> None:
    text = page.read_text()
    theirs = original_compliance.lint(text)
    mine = lint_compliance(text)
    assert [(i.severity, i.code, i.line) for i in mine.issues] == [
        (sev, code, line) for sev, code, line, _m in theirs
    ]


def test_schema_nap_check_matches_the_original(tmp_path, original_compliance) -> None:
    """The port takes PARSED schema; the original reads a path. Same verdicts."""
    schema = {
        "@type": "Plumber", "name": "Valley Air", "telephone": "(555) 123-4567",
        "address": {"streetAddress": "12 Main St", "addressLocality": "San Jose",
                    "addressRegion": "CA", "postalCode": "95112"},
    }
    page = "# T\n\nmeta title: x\ndescription: y\n\nValley Air, 12 Main St, San Jose CA 95112.\n"
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(schema))

    theirs: list = []
    original_compliance.check_schema_nap(page, str(path), theirs)
    mine = lint_compliance(page, schema=schema)
    nap_issues = [i for i in mine.issues if i.code.startswith("SCHEMA_")]
    assert [(i.severity, i.code) for i in nap_issues] == [(sev, code) for sev, code, _l, _m in theirs]


def test_schema_that_disagrees_with_the_page_is_an_error() -> None:
    """Schema contradicting the visible copy is worse than absent schema: it asserts a
    second, competing identity for the same business."""
    schema = {"@type": "Plumber", "name": "Valley Air", "telephone": "555-000-0000",
              "address": {"addressLocality": "Oakland"}}
    page = "# T\n\ntitle: a\ndescription: b\n\nValley Air in San Jose.\n"
    codes = {i.code for i in lint_compliance(page, schema=schema).errors}
    assert "SCHEMA_NAP_MISMATCH" in codes


def test_a_phone_formatting_difference_is_a_warning_not_an_error() -> None:
    """"(555) 123-4567" vs "+1-555-123-4567" is a display choice, not a different
    business. Treating it as a hard failure trains operators to ignore the check."""
    schema = {"@type": "Plumber", "name": "Valley Air", "telephone": "(555) 123-4567"}
    page = "# T\n\ntitle: a\ndescription: b\n\nValley Air on +1-555-123-4567.\n"
    r = lint_compliance(page, schema=schema)
    assert any(i.code == "SCHEMA_NAP_FORMAT" for i in r.warnings)
    assert not any(i.code == "SCHEMA_NAP_MISMATCH" for i in r.errors)


def test_a_page_of_stubs_is_flagged_even_when_the_total_word_count_looks_fine() -> None:
    """Thin SECTIONS are the scaled-low-value signature; a healthy total hides it."""
    text = "# T\n\ntitle: a\ndescription: b\n\n" + "".join(
        f"## Section {i}\n\nonly a handful of words here\n\n" for i in range(8)
    )
    assert len(text.split()) > 60
    assert sum(1 for i in lint_compliance(text).issues if i.code == "THIN_SECTION") == 8


def test_extract_schema_nap_picks_the_business_node() -> None:
    doc = {"@graph": [{"@type": "WebPage", "name": "A page"},
                      {"@type": "Plumber", "name": "Valley Air", "telephone": "1"}]}
    assert extract_schema_nap(doc)["name"] == "Valley Air"


# =========================================================================== #
# nap_checker - Name / Address / Phone consistency
# =========================================================================== #
from app.services.content_lint import (  # noqa: E402
    CanonicalNap,
    check_nap,
    normalise_tokens,
    same_number,
)

_NAP = CanonicalNap(name="Valley Air", phone="+1-512-555-0100", street="12 Main Street",
                    city="San Jose", region="CA", postal="95112")
_NAP_DICT = {"name": "Valley Air", "phone": "+1-512-555-0100", "street": "12 Main Street",
             "city": "San Jose", "region": "CA", "postal": "95112"}

_NAP_PROBES = [
    ("exact", "Valley Air, 12 Main Street, San Jose, CA 95112. Call +1-512-555-0100."),
    ("abbreviated", "Valley Air, 12 Main St, San Jose, CA 95112. Call (512) 555-0100."),
    ("wrong-phone", "Valley Air, 12 Main Street, San Jose, CA 95112. Call 999-999-9999."),
    ("case-variant", "valley air, 12 main street, san jose, ca 95112. +1-512-555-0100"),
    ("absent", "A page about air conditioning with no business details at all."),
]


@pytest.fixture(scope="module")
def original_nap():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import nap_checker

        return nap_checker
    finally:
        sys.path.remove(str(_SCRIPTS))


@pytest.mark.parametrize("label,text", _NAP_PROBES, ids=[p[0] for p in _NAP_PROBES])
def test_nap_port_matches_the_original(label, text, original_nap) -> None:
    theirs = (original_nap.check_name(text, _NAP_DICT["name"])
              + original_nap.check_phone(text, _NAP_DICT["phone"])
              + original_nap.check_address(text, _NAP_DICT))
    mine = check_nap(text, _NAP)
    assert [(i.field, i.kind) for i in mine.issues] == [(f, k) for f, k, _m in theirs]


def test_a_variant_is_not_a_miss() -> None:
    """The distinction the whole check rests on. "12 Main St" is the right address in
    a different shape; a miss is the wrong address. Conflating them either buries real
    misses in noise or lets genuine inconsistencies pass as cosmetic."""
    r = check_nap("Valley Air, 12 Main St, San Jose, CA 95112. Call (512) 555-0100.", _NAP)
    assert r.passed          # no misses -> not a failure
    assert not r.exact       # but not byte-perfect either
    assert {i.field for i in r.variants} == {"PHONE", "ADDRESS.street"}


def test_a_wrong_number_is_a_miss_not_a_variant() -> None:
    r = check_nap("Valley Air, 12 Main Street, San Jose, CA 95112. Call 999-999-9999.", _NAP)
    assert not r.passed
    assert [i.field for i in r.misses] == ["PHONE"]


def test_a_country_code_prefix_is_the_same_number() -> None:
    assert same_number("+1 512 555 0100", "5125550100")
    assert same_number("(512) 555-0100", "512-555-0100")
    assert not same_number("5125550100", "5125550101")


def test_street_abbreviations_normalise_in_both_directions() -> None:
    assert normalise_tokens("12 Main St.") == normalise_tokens("12 Main Street")
    assert normalise_tokens("400 N Ave") == normalise_tokens("400 North Avenue")


def test_a_blank_canonical_field_is_skipped_not_failed() -> None:
    """A client without a public address (a service-area business) must not fail every
    page for a field they deliberately do not publish."""
    partial = CanonicalNap(name="Valley Air", phone="+1-512-555-0100")
    assert check_nap("Valley Air on +1-512-555-0100.", partial).exact


# =========================================================================== #
# voice_fingerprint - measurable idiolect, with a slop guardrail
# =========================================================================== #
from app.services.content_lint import fingerprint_voice, is_imperative  # noqa: E402

_VOICE_CORPUS_PROBES = [
    "",
    "Short. A somewhat longer sentence follows it here. Then another short one.",
    "Call us today. Book your estimate. Get my free inspection now.",
    "Is this worth it? Do you need a permit? What does it cost?",
    ("We are your trusted partner offering seamless solutions and peace of mind. "
     "Our dedicated professionals are committed to providing world class quality. "
     "We pride ourselves on customer satisfaction and exceed your expectations."),
    "We'll be there. You're covered. Don't wait, it's simple.",
]


@pytest.fixture(scope="module")
def original_voice():
    sys.path.insert(0, str(_SCRIPTS))
    try:
        import voice_fingerprint

        return voice_fingerprint
    finally:
        sys.path.remove(str(_SCRIPTS))


@pytest.mark.parametrize("text", _VOICE_CORPUS_PROBES)
def test_voice_port_matches_the_original(text: str, original_voice) -> None:
    theirs = original_voice.analyse(text)
    mine = fingerprint_voice(text)

    for field in (
        "sentences", "words", "avg_sentence_len", "sentence_len_variance",
        "sentence_len_stdev", "min_sentence_len", "max_sentence_len",
        "short_sentences", "medium_sentences", "long_sentences",
        "syllables_per_word", "contraction_rate_per_100w", "question_rate",
        "imperative_rate", "filler_ratio", "filler_word_hits", "filler_phrase_hits",
    ):
        assert getattr(mine, field) == pytest.approx(theirs[field]), field
    for n, attr in ((1, "distinctive_unigrams"), (2, "distinctive_bigrams"), (3, "distinctive_trigrams")):
        assert [list(g) for g in getattr(mine, attr)] == [list(g) for g in theirs[f"distinctive_{['uni','bi','tri'][n-1]}grams"]]


@pytest.mark.parametrize("page", _PAGES, ids=lambda p: p.parent.name)
def test_voice_port_matches_on_the_corpus_samples(page, original_voice) -> None:
    text = page.read_text()
    theirs, mine = original_voice.analyse(text), fingerprint_voice(text)
    assert mine.filler_ratio == pytest.approx(theirs["filler_ratio"])
    assert mine.sentence_len_stdev == pytest.approx(theirs["sentence_len_stdev"])
    assert [list(g) for g in mine.distinctive_bigrams] == [list(g) for g in theirs["distinctive_bigrams"]]


# --- the guardrail: refuse to learn a voice from slop ----------------------- #
def test_a_generic_source_is_flagged_as_unlearnable() -> None:
    """The clever part. A client site can itself be generic, and a naive tool would
    faithfully learn "trusted partner" and reproduce it forever. A high filler ratio
    means the source must not be learned from at all."""
    slop = fingerprint_voice(_VOICE_CORPUS_PROBES[4])
    assert slop.filler_ratio > slop.max_filler_ratio
    assert not slop.learnable


def test_filler_never_surfaces_as_a_characteristic_phrase() -> None:
    """Belt and braces: even below the ratio threshold, a filler gram is excluded from
    the distinctive ranking, so slop cannot be adopted as "how this client sounds"."""
    f = fingerprint_voice(
        "We fix roofs in Round Rock. We fix roofs in Round Rock fast. "
        "Peace of mind matters. Peace of mind matters here. We fix roofs in Round Rock."
    )
    phrases = {g[0] for g in f.distinctive_bigrams + f.distinctive_trigrams}
    assert "peace of mind" not in phrases
    assert any("round rock" in p for p in phrases)


def test_flat_sentence_variance_is_the_machine_tell() -> None:
    """Human writing is bursty. This quantifies it rather than asserting it."""
    flat = fingerprint_voice("We fix roofs today. We fix pipes today. We fix vents today. " * 4)
    assert not flat.is_bursty


def test_imperative_detection_ignores_questions() -> None:
    assert is_imperative("Call us before 4pm.")
    assert not is_imperative("Call us before 4pm?")
    assert not is_imperative("The roof was replaced.")
