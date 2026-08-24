"""P1B: the doctrine index and the three-block prompt assembly.

The corpus is 428k tokens across 1,436 chunks. No stage can be handed all of it - a
stage that receives everything has no priorities, and the doctrine would drown the
brief. These tests pin the routing that decides what each stage actually sees, and the
CACHE-PREFIX ORDER that makes sending 50k tokens per call affordable.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from app.services.doctrine import (
    chunk_index,
    chunks_by_id,
    estimate_tokens,
    fit,
    resolve,
    slugify,
    total_tokens,
)
from app.services.doctrine_routes import (
    CONSTITUTION_REFS,
    PAGE_PLAYBOOK,
    STAGE_AGENT,
    assemble,
    known_stages,
)

_PAGE_TYPES = ("service", "blog", "local", "gbp_post")
_VERTICALS = (None, "home-services", "legal", "medical-dental", "self-storage", "financial")


# --------------------------------------------------------------------------- #
# 1 - the index
# --------------------------------------------------------------------------- #
def test_the_index_covers_the_corpus() -> None:
    index = chunk_index()
    assert len(index) > 1_000, f"only {len(index)} chunks - did an area stop being indexed?"
    areas = {c.area for c in index}
    assert {"knowledge", "agents", "commands"} <= areas


def test_research_is_deliberately_not_indexed() -> None:
    """`research/` is provenance for WHY the doctrine says what it says, not
    instruction. Indexing it would roughly double the index while never being routed
    to."""
    assert not any(c.area == "research" for c in chunk_index())


def test_chunk_ids_are_stable_and_greppable() -> None:
    """An id is what lands in the provenance ledger, so it has to survive being read
    by a person a year later and grepped back to a file."""
    for chunk in chunk_index():
        assert "#" in chunk.id
        _path, slug = chunk.id.split("#", 1)
        assert chunk.id.startswith(chunk.path)
        assert (slug and slug == slugify(chunk.heading)) or slug.startswith(("preamble", slugify(chunk.heading)))


def test_ids_are_unique_even_when_headings_repeat() -> None:
    """An id mapping to two different texts would make the provenance ledger lie."""
    ids = [c.id for c in chunk_index()]
    assert len(ids) == len(set(ids))
    assert len(chunks_by_id()) == len(ids)


def test_a_file_preamble_is_kept_not_dropped() -> None:
    """In this corpus the text before the first heading is frequently the thesis of
    the file; dropping it would silently remove what a stage most needs."""
    preambles = [c for c in chunk_index() if c.level == 0]
    assert preambles, "no preamble chunks - content before the first heading is being lost"


def test_resolve_accepts_both_whole_files_and_single_chunks() -> None:
    whole = resolve("knowledge/quality-gates/gates.md")
    assert len(whole) > 1
    one = resolve(whole[0].id)
    assert len(one) == 1 and one[0].id == whole[0].id


def test_resolve_deduplicates_while_preserving_order() -> None:
    a, b = "CLAUDE.md", "knowledge/voice/vocabulary-blocklist.md"
    assert resolve(a, b, a) == resolve(a, b)


def test_fit_drops_whole_chunks_and_reports_them() -> None:
    """Half a rule is worse than no rule - a model follows the half it was given. And
    a block that silently loses a third of its doctrine looks identical to one that
    fits, so what was dropped must be reported."""
    chunks = resolve("knowledge/doctrine/google-compliance-spine.md")
    kept, dropped = fit(chunks, max_tokens=500)
    assert kept and dropped
    assert total_tokens(kept) <= max(500, kept[0].tokens)
    assert {k.id for k in kept}.isdisjoint({d.id for d in dropped})
    assert len(kept) + len(dropped) == len(chunks)


def test_fit_never_returns_nothing() -> None:
    """A ceiling smaller than the first chunk still yields that chunk. Returning an
    empty block would send a stage with NO doctrine, which is worse than over budget."""
    kept, _ = fit(resolve("CLAUDE.md"), max_tokens=1)
    assert len(kept) == 1


# --------------------------------------------------------------------------- #
# 2 - the routing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("stage", known_stages())
@pytest.mark.parametrize("page_type", _PAGE_TYPES)
def test_every_stage_and_page_type_resolves(stage: str, page_type: str) -> None:
    blocks = assemble(stage, page_type=page_type)
    assert blocks.constitution, "no constitution - the laws must reach every stage"
    assert blocks.stage_role, f"{stage} has no role block"
    assert blocks.page_pack, f"{stage}/{page_type} has no page pack"
    assert blocks.chunk_ids


@pytest.mark.parametrize("vertical", _VERTICALS)
def test_every_vertical_resolves(vertical: str | None) -> None:
    assert assemble("draft", page_type="service", vertical=vertical).page_pack


@pytest.mark.parametrize("stage", known_stages())
def test_nothing_is_dropped_on_the_normal_routes(stage: str) -> None:
    """If a real route starts truncating, the ceiling was set wrong - and the failure
    would otherwise be invisible."""
    blocks = assemble(stage, page_type="service", vertical="home-services", framework="PAS")
    assert blocks.complete, f"{stage} dropped: {blocks.dropped_chunk_ids}"


def test_no_stage_receives_the_whole_corpus() -> None:
    """428k tokens of doctrine would drown the brief. A stage with everything has no
    priorities."""
    whole = total_tokens(chunk_index())
    for stage in known_stages():
        blocks = assemble(stage, page_type="service", vertical="home-services")
        assert blocks.tokens < whole * 0.2, f"{stage} pulls {blocks.tokens:,} of {whole:,}"


def test_an_unknown_stage_degrades_to_the_laws_rather_than_to_nothing() -> None:
    """Better "governed by the laws without a specialist role" than an exception at
    the call site, which would mean no doctrine at all."""
    blocks = assemble("no-such-stage", page_type="service")
    assert blocks.constitution and not blocks.stage_role


def test_blog_is_not_given_a_service_page_playbook() -> None:
    """A blog post is not a local money page. Handing it the service-page playbook
    would import the wrong structure wholesale; the passage-block protocol carries the
    extractability rules that actually apply."""
    assert "passage-block" in PAGE_PLAYBOOK["blog"]
    assert PAGE_PLAYBOOK["blog"] != PAGE_PLAYBOOK["service"]


def test_every_routed_file_exists_in_the_index() -> None:
    """A typo in the table would otherwise surface as a KeyError inside a paid run."""
    from app.services.doctrine_routes import (
        FRAMEWORK_REF,
        STAGE_FOUNDATIONS,
        VERTICAL_OVERLAY,
    )

    refs = {*CONSTITUTION_REFS, *STAGE_AGENT.values(), *PAGE_PLAYBOOK.values(),
            *VERTICAL_OVERLAY.values(), *FRAMEWORK_REF.values()}
    for foundations in STAGE_FOUNDATIONS.values():
        refs.update(foundations)
    for ref in sorted(refs):
        assert resolve(ref), f"routed file missing from the index: {ref}"


# --------------------------------------------------------------------------- #
# 3 - cache mechanics (this is what makes 50k tokens per call affordable)
# --------------------------------------------------------------------------- #
def test_blocks_are_ordered_most_stable_first() -> None:
    """The cache matches on a PREFIX. Putting the page pack ahead of the constitution
    would invalidate the whole prefix on every new page type and forfeit the entire
    saving."""
    blocks = assemble("draft", page_type="service")
    system = blocks.as_system()
    assert system[0] == blocks.constitution
    assert system[-1] == blocks.page_pack


def test_the_constitution_is_byte_identical_across_stages_and_page_types() -> None:
    """It is the shared cache prefix. Any variation - even whitespace - breaks the
    cache for every call that follows."""
    reference = assemble("draft", page_type="service").constitution
    for stage in known_stages():
        for page_type in _PAGE_TYPES:
            assert assemble(stage, page_type=page_type).constitution == reference


def test_single_call_stages_are_not_told_to_cache_their_variable_blocks() -> None:
    """A cache write costs 1.25x and a read 0.1x, so a block used ONCE is 25% more
    expensive cached than plain. Blindly caching everything costs about $0.04/page -
    small, but the exact opposite of what caching is for."""
    blocks = assemble("convert", page_type="service")
    once = blocks.cache_flags(expected_calls=1)
    many = blocks.cache_flags(expected_calls=6)
    assert once[0] is True, "the constitution always pays - it spans every stage"
    assert not any(once[1:]), "B and C must not be cached for a single-call stage"
    assert all(many), "with 6 calls every block pays"


def test_token_estimate_is_monotonic_and_positive() -> None:
    """It only ever bounds a block; exactness comes from the API's own usage numbers."""
    assert estimate_tokens("") >= 1
    assert estimate_tokens("a" * 4000) > estimate_tokens("a" * 400)


# --------------------------------------------------------------------------- #
# 4 - the writer actually sends the blocks as separate cache breakpoints
# --------------------------------------------------------------------------- #
def test_the_writer_accepts_ordered_blocks_and_marks_breakpoints() -> None:
    """The assembly is worthless if the transport flattens it back into one block."""
    from integrations.llm import _MAX_CACHE_BREAKPOINTS, AnthropicSummarizer

    captured: dict[str, object] = {}

    class _Messages:
        def create(self, **kw):
            captured.update(kw)

            class _R:
                content: ClassVar[list] = []
                usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()

            return _R()

    writer = AnthropicSummarizer.__new__(AnthropicSummarizer)
    writer._client = type("C", (), {"messages": _Messages()})()
    blocks = assemble("draft", page_type="service")

    writer.summarize(
        "hello", model="m", max_tokens=10,
        system=blocks.as_system(), cache=blocks.cache_flags(expected_calls=6),
    )
    sent = captured["system"]
    assert isinstance(sent, list) and len(sent) == 3, "blocks were flattened"
    assert sent[0]["text"] == blocks.constitution, "most-stable block must come first"
    assert all("cache_control" in b for b in sent)
    assert sum("cache_control" in b for b in sent) <= _MAX_CACHE_BREAKPOINTS


def test_a_single_call_stage_sends_its_variable_blocks_uncached() -> None:
    from integrations.llm import AnthropicSummarizer

    captured: dict[str, object] = {}

    class _Messages:
        def create(self, **kw):
            captured.update(kw)

            class _R:
                content: ClassVar[list] = []
                usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()

            return _R()

    writer = AnthropicSummarizer.__new__(AnthropicSummarizer)
    writer._client = type("C", (), {"messages": _Messages()})()
    blocks = assemble("convert", page_type="service")
    writer.summarize("hi", model="m", max_tokens=10,
                     system=blocks.as_system(), cache=blocks.cache_flags(expected_calls=1))
    sent = captured["system"]
    assert "cache_control" in sent[0], "the constitution always pays"
    assert not any("cache_control" in b for b in sent[1:]), "B/C cached for a one-shot stage"


def test_a_plain_string_system_still_works() -> None:
    """Every existing caller passes a single string; widening must not break them."""
    from integrations.llm import FakeSummarizer

    result = FakeSummarizer().summarize("x", model="m", max_tokens=5, system="one block")
    assert result.text
