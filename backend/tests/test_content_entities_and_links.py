"""Two QA-signal defects found by reading a real generated page (CJ-4346, 2026-09-25).

1. THE ENTITY LIST WAS CAPITALISED STOPWORDS. ``_PROPER_NOUN_RE`` matches any capitalised
   word, so every word that happens to open a sentence was harvested as a named entity.
   The teardown's table-stakes list - the thing the whole ``entity_coverage`` dimension is
   scored against - came out of a live run as ``['Physical', 'Regular', 'The', 'This',
   'You']``, with differentiators including ``But``, ``Can`` and ``Copyright``. Those pass
   the "covered by near-all competitors" test by construction, and any draft written in
   English trivially contains them, so the dimension scored **100** while measuring
   nothing - and that 100 lifted the weighted total that decides whether a page is worth
   a human's review.

2. INTERNAL LINKS WERE OFF-TOPIC. The link planner's second tier took ANY published
   sibling page, justified in its own comment as "real pages, off-topic, better than a
   dead end" - directly contradicting the paragraph above it, which says an off-topic
   internal link "is not a weaker version of the right answer, it is a different and
   worse one". The live article about physical fitness shipped links reading "SEO in 2026"
   and "skincare routine for pakistani skin", because those were the client's most
   recently published pages.

Re-inject either and the matching test fails.
"""

from __future__ import annotations

import pytest

from app.services.content_pipeline.schema_links import _topic_tokens, _topically_related
from app.services.content_research import proper_nouns

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# 1. Entity extraction.
# --------------------------------------------------------------------------- #
#: Prose shaped like the competitor pages the live teardown actually read: sentences
#: opening on ordinary words, footer furniture, and genuine names mixed in.
_SAMPLE = (
    "The importance of physical fitness. This is regular movement. You should move more. "
    "But can you find the time? Physical activity matters. Regular exercise helps. "
    "Copyright 2026. Find out more. Help and support. Call us today. About us. "
    "The World Health Organization recommends 150 minutes a week. "
    "Smart Healthcare Pharmacy in Lahore stocks Centrum and Panadol. "
    "the physical world, this regular thing, you and your body, about our team"
)

_JUNK = (
    "The", "This", "You", "But", "Can", "Physical", "Regular",
    "Copyright", "Find", "Help", "Call", "About",
)


@pytest.mark.parametrize("word", _JUNK)
def test_a_sentence_opener_is_not_an_entity(word: str) -> None:
    """THE defect, one word at a time. Every one of these was in the live run's
    table-stakes or differentiator list."""
    assert word not in proper_nouns(_SAMPLE)


@pytest.mark.parametrize(
    "name", ["Lahore", "Centrum", "Panadol", "Smart Healthcare Pharmacy",
             "World Health Organization"],
)
def test_a_real_name_survives_the_filter(name: str) -> None:
    """The guard against over-correcting: a filter that also drops real entities would
    make the dimension measure nothing in the other direction."""
    assert name in proper_nouns(_SAMPLE)


def test_the_lowercase_test_is_what_does_the_work() -> None:
    """A capitalised token whose lowercase form appears in the same text is a common
    word, not a name - no word list needed. "Fitness" appears both ways here."""
    text = "Fitness is a habit. Real fitness takes time."
    assert "Fitness" not in proper_nouns(text)


def test_a_name_that_never_appears_lowercased_is_kept() -> None:
    """The other side of the same test: "Novartis" is never lowercased, so it stays."""
    text = "Novartis published the trial. The trial was large."
    assert "Novartis" in proper_nouns(text)


def test_a_leading_article_is_stripped_from_a_multi_word_name() -> None:
    """A sentence opening on a name chains the opener into the match, and storing "The
    World Health Organization" makes the entity miss a draft that writes it without the
    article - so coverage would under-report on a page that genuinely covers it."""
    got = proper_nouns("The World Health Organization said so.")
    assert "World Health Organization" in got
    assert "The World Health Organization" not in got


def test_a_multi_word_phrase_is_trusted_without_the_lowercase_test() -> None:
    """Consecutive capitalised words are not how English opens a sentence, so the
    strongest signal the teardown has is not subjected to the weakest test."""
    text = "Smart Healthcare Pharmacy sells smart healthcare products."
    assert "Smart Healthcare Pharmacy" in proper_nouns(text)


def test_empty_and_junk_input_is_safe() -> None:
    assert proper_nouns("") == set()
    assert proper_nouns("!!! ??? 123 456") == set()
    assert proper_nouns("all lowercase words only here") == set()


def test_the_live_defect_shape_no_longer_reaches_table_stakes() -> None:
    """End to end over the teardown aggregator: the same prose on several competitor
    pages must not yield stopwords as table-stakes entities.

    This is the assertion that would have caught the live defect: the aggregator keeps
    whatever is on >=70% of pages, so junk that appears on every page is exactly what
    survives to the scored list.
    """
    from app.services.content_research import TeardownPage, analyze_teardown

    pages = [
        TeardownPage(
            url=f"https://competitor{i}.example/fitness",
            position=i + 1,
            headings=["Why fitness matters"],
            word_count=900,
            entities=sorted(proper_nouns(_SAMPLE)),
            schema_types=["Article"],
            media_count=3,
            has_freshness=True,
        )
        for i in range(5)
    ]
    teardown = analyze_teardown(pages, refused=[])
    assert teardown.table_stakes_entities, "a real teardown should still find entities"
    for junk in _JUNK:
        assert junk not in teardown.table_stakes_entities
        assert junk not in teardown.differentiator_entities
    # ...and the real names ARE the table stakes, which is the point.
    assert "Lahore" in teardown.table_stakes_entities


# --------------------------------------------------------------------------- #
# 2. Internal-link relevance.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sibling",
    [
        "SEO in 2026",
        "skincare routine for pakistani skin",
        "home cleaning services lahore",
        "best laptop deals",
    ],
)
def test_an_unrelated_sibling_is_not_linked(sibling: str) -> None:
    """THE defect, using the two anchors the live page actually shipped."""
    assert not _topically_related(sibling.lower(), "importance of physical fitness in life")


@pytest.mark.parametrize(
    "sibling",
    [
        "physical fitness for beginners",
        "best fitness equipment",
        "fitness tips for busy adults",
    ],
)
def test_a_related_sibling_is_linked(sibling: str) -> None:
    """The guard against over-filtering: a genuinely related page must still be offered,
    or the fix trades a misleading link list for an empty one."""
    assert _topically_related(sibling.lower(), "importance of physical fitness in life")


def test_relatedness_tolerates_word_endings() -> None:
    """"training" should relate to "train"; crude stemming by prefix, deliberately
    erring toward the shorter link list."""
    assert _topically_related("strength training guide", "strength train for runners")


def test_a_shared_stopword_is_not_relatedness() -> None:
    """Without a stopword list, "best X" and "best Y" would look related to each other
    and every page would link to every other page."""
    assert not _topically_related("best seo tools", "best fitness equipment")
    assert not _topically_related("how to file taxes", "how to stretch")


def test_topic_tokens_drops_glue_and_short_words() -> None:
    """Only meaning-bearing words survive. "tips" and "guide" are stopwords here on
    purpose: "fitness tips" and "seo tips" must not read as related to each other."""
    assert _topic_tokens("the best tips for your fitness") == {"fitness"}
    assert _topic_tokens("strength training for older adults") == {
        "strength", "training", "older", "adults",
    }


def test_an_empty_phrase_is_never_related() -> None:
    assert not _topically_related("", "fitness")
    assert not _topically_related("fitness", "")


def test_the_planner_drops_an_unrelated_sibling_but_keeps_a_related_one() -> None:
    """The planner itself, not just the predicate. A page with one related and two
    unrelated siblings must carry exactly the related one - a SHORTER list than before,
    which is the intended outcome."""
    from app.services.content_pipeline.context import PipelineContext
    from app.services.content_pipeline.schema_links import plan_internal_links

    ctx = PipelineContext(
        job_code="CJ-1", page_type="blog",
        primary_keyword="importance of physical fitness in life",
    )
    registry = {
        "SEO in 2026": "https://spotino.org/?page_id=200",
        "skincare routine for pakistani skin": "https://spotino.org/?page_id=196",
        "physical fitness for beginners": "https://spotino.org/fitness-beginners",
    }
    links = plan_internal_links(ctx, internal_urls=registry)
    resolved = [x.anchor for x in links if x.url]
    assert resolved == ["physical fitness for beginners"]
    assert "SEO in 2026" not in resolved
