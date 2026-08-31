"""The thresholds must sit where the MEASUREMENT put them, not where they feel right.

THE GOLDEN SET (15 real generator articles, 105 pairs, measured 2026-08-30). Every number
below came from running the real content generator and scoring the real fingerprints:

    distinct, different framework   n=91  median 0.314  max 0.388
    distinct, SAME framework        n=5   median 0.648  max 0.656
    same topic redrafted            n=3   1.000
    same topic, different client    n=6   1.000

The finding that decides the threshold: heading resemblance is dominated by WHICH
FRAMEWORK was used, not by content - `_FRAMEWORK_MOVES` is a fixed heading table, so two
genuinely distinct articles sharing a framework already share ~0.65 of their skeleton.
A block at 0.60 therefore sat INSIDE the distinct band and falsely blocked 5 of 96
legitimate pairs, while a block at 0.80 catches every duplicate (all at 1.000) and none
of them.

BODY resemblance separates NOTHING here (every class 0.003-0.067) because the writer
rephrases; it stays as a backstop for genuinely copied prose, which this corpus has none
of. Anyone tempted to "tighten" the body threshold toward these numbers would block the
entire corpus.
"""

from __future__ import annotations

import pytest

from app.services.web2_similarity import (
    BODY_BLOCK,
    BODY_WARN,
    HEADING_BLOCK,
    HEADING_WARN,
)

pytestmark = pytest.mark.unit

#: The widest DISTINCT pair in the golden set (two real articles, same framework).
MEASURED_DISTINCT_MAX = 0.656
#: Where every duplicate and every templated pair landed.
MEASURED_DUPLICATE = 1.000


def test_the_heading_block_sits_above_every_genuinely_distinct_pair() -> None:
    """Below this and the gate blocks real work: 5 of 96 distinct pairs, all of them
    merely sharing a writing framework."""
    assert HEADING_BLOCK > MEASURED_DISTINCT_MAX, (
        f"a block at {HEADING_BLOCK} falsely blocks distinct articles that reach "
        f"{MEASURED_DISTINCT_MAX}"
    )


def test_the_heading_block_still_catches_every_duplicate() -> None:
    assert HEADING_BLOCK < MEASURED_DUPLICATE, "a duplicate must still be blocked"
    # Real headroom on both sides, so the verdict is not balanced on a hair.
    assert HEADING_BLOCK - MEASURED_DISTINCT_MAX >= 0.10
    assert MEASURED_DUPLICATE - HEADING_BLOCK >= 0.10


def test_the_warn_flags_a_reused_framework_without_blocking_it() -> None:
    """Two articles sharing a heading skeleton is worth telling an operator about - the
    fix is to rotate the framework - but it is not grounds to refuse the work."""
    assert HEADING_WARN <= MEASURED_DISTINCT_MAX < HEADING_BLOCK


def test_the_body_threshold_is_not_tightened_toward_the_measured_noise() -> None:
    """Every class scored 0.003-0.067 on body resemblance. A threshold anywhere near
    that blocks the whole corpus; it is a backstop for copied prose, not the live signal."""
    assert BODY_BLOCK > 0.10, "a body block near the measured range blocks everything"
    assert BODY_WARN > 0.067, "the warn must sit above the widest measured distinct pair"


def test_the_config_defaults_match_the_calibrated_module_constants() -> None:
    """THE TRAP THIS CLOSES. `web2_gate` passes `settings.web2_similarity_*` into the
    scorer, so the CONFIG values are what actually run - the module constants are only
    defaults. Calibrating one and not the other leaves the measurement decorative and the
    live gate on its old, wrong numbers, with every test still green.
    """
    from app.config import Settings

    s = Settings(_env_file=None)
    assert s.web2_similarity_heading_block == HEADING_BLOCK
    assert s.web2_similarity_heading_warn == HEADING_WARN
    assert s.web2_similarity_body_block == BODY_BLOCK
    assert s.web2_similarity_body_warn == BODY_WARN
