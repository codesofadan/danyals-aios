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
