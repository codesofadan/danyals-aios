"""The 0135 Web 2.0 capability matrix: columns, seed classification, idempotence.

Three claims the migration makes, each pinned here so an edit cannot silently break
them:

* EVERY catalogue row leaves 0135 classified (mechanism != '') - an unclassified row
  would be invisible to placement routing. Verified by SIMULATING the seed's guarded
  updates, in file order, over the exact 90 names the seed migrations insert.
* The classification derives from VERIFIED reality: every 'api' row resolves to the
  publishing enum (a real ``Web2Publisher`` exists for every enum value), and every
  'unsupported' row records WHY in ``adapter_status`` - a do-not-use verdict with no
  reason is folklore.
* RE-APPLY NEVER CLOBBERS: every seed update is guarded ``where mechanism = ''``, so
  a later manual reclassification (mechanism != '') is left alone by a re-apply.

The simulation parses the migration's own SQL rather than duplicating its lists: a
typo'd platform name in 0135 would update zero rows in production and exactly zero
names here, which the "every name resolves" assertions turn into a failure instead of
a silent no-op.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from integrations.web2_publishers import WEB2_PLATFORMS

pytestmark = pytest.mark.unit

# Repo root: backend/tests/ -> backend/ -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS = _REPO_ROOT / "db" / "migrations"
_MATRIX = _MIGRATIONS / "0135_web2_capability_matrix.sql"

# Every migration that inserts/upserts public.web2_platforms rows. Together they seed
# the full 90-name catalogue the 0135 classification must cover.
_SEED_FILES = (
    "0063_web2_platforms_seed.sql",
    "0066_web2_platforms_more.sql",
    "0068_web2_platforms_new_adapters.sql",
    "0070_web2_platforms_batch3.sql",
    "0072_web2_platforms_batch4.sql",
    "0076_web2_platforms_batch5.sql",
    "0077_web2_platforms_batch6.sql",
)

# 0103's instance-qualified prefix mappings: catalogue names that resolve to a
# platform_enum WITHOUT equalling an enum label. Kept verbatim from that migration.
_ENUM_PREFIXES = ("Misskey", "Lemmy", "WhiteWind", "Pixelfed", "Mastodon (")

_LANES = ("api", "extension", "human", "unsupported")


def _catalogue_names() -> set[str]:
    names: set[str] = set()
    for fname in _SEED_FILES:
        text = (_MIGRATIONS / fname).read_text(encoding="utf-8")
        for line in text.splitlines():
            m = re.match(r"\s*\('([^']+)'", line)
            if m:
                names.add(m.group(1))
    return names


def _enum_mapped(names: set[str]) -> set[str]:
    """The catalogue names 0103 resolves to a platform_enum value."""
    return {
        n
        for n in names
        if n in WEB2_PLATFORMS or any(n.startswith(p) for p in _ENUM_PREFIXES)
    }


def _statements() -> list[str]:
    """The migration's statements, comment lines stripped, in file order."""
    text = _MATRIX.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("--")
    )
    return [s.strip() for s in code.split(";") if s.strip()]


def _seed_updates() -> list[str]:
    return [
        s for s in _statements() if s.lower().startswith("update public.web2_platforms")
    ]


def _lane_of(stmt: str) -> str | None:
    set_part = re.split(r"\bwhere\b", stmt, maxsplit=1)[0]
    m = re.search(r"mechanism = '(\w*)'", set_part)
    return m.group(1) if m else None


def _where_of(stmt: str) -> str:
    parts = re.split(r"\bwhere\b", stmt, maxsplit=1)
    assert len(parts) == 2, f"seed update without a where clause: {stmt[:80]}"
    return parts[1]


def _named_targets(where: str, names: set[str]) -> set[str] | None:
    """The catalogue names a where clause targets, or None if it names none
    (a structural sweep). Every literal must RESOLVE - a name that matches nothing
    is a production no-op wearing a classification."""
    eq = re.findall(r"name = '([^']+)'", where)
    in_lists = [
        re.findall(r"'([^']+)'", body)
        for body in re.findall(r"name in \(([^)]*)\)", where)
    ]
    likes = re.findall(r"name like '([^']+)'", where)
    literals = set(eq)
    for body in in_lists:
        literals.update(body)
    if not literals and not likes:
        return None
    for literal in literals:
        assert literal in names, f"0135 names '{literal}' but no seed inserts it"
    targets = set(literals)
    for pattern in likes:
        prefix = pattern.rstrip("%")
        matched = {n for n in names if n.startswith(prefix)}
        assert matched, f"0135's like-pattern '{pattern}' matches no catalogue row"
        targets.update(matched)
    return targets


def _simulate() -> dict[str, str]:
    """Apply the seed updates in order over the real catalogue names, honouring the
    ``where mechanism = ''`` guard (first classification wins, later ones skip)."""
    names = _catalogue_names()
    lanes: dict[str, str] = {}
    for stmt in _seed_updates():
        lane = _lane_of(stmt)
        if lane is None:  # not a classification statement
            continue
        where = _where_of(stmt)
        targets = _named_targets(where, names)
        if targets is None:
            # A structural sweep: the enum-mapped api lane, or the human catch-all.
            targets = _enum_mapped(names) if "platform_enum is not null" in where else set(names)
        for name in targets:
            lanes.setdefault(name, lane)  # the mechanism = '' guard
    return lanes


# --------------------------------------------------------------------------- #
# Structure: columns, closed vocabularies, RLS posture.
# --------------------------------------------------------------------------- #
def test_matrix_columns_and_checks_exist() -> None:
    sql = _MATRIX.read_text(encoding="utf-8").lower()
    for col in (
        "mechanism", "last_tested_at", "adapter_status", "link_verifiable",
        "media_support",
    ):
        assert f"add column if not exists {col}" in sql, col
    # text + CHECK closed vocabulary, never a new Postgres enum (0106 pattern).
    assert "create type" not in sql
    assert "web2_platforms_mechanism_check" in sql
    assert "check (mechanism in ('', 'api', 'extension', 'human', 'unsupported'))" in sql


def test_publish_method_lands_on_properties_with_its_own_vocabulary() -> None:
    sql = _MATRIX.read_text(encoding="utf-8").lower()
    assert "alter table public.web2_properties" in sql
    assert "add column if not exists publish_method text not null default 'api'" in sql
    assert "web2_properties_publish_method_check" in sql
    assert "check (publish_method in ('api', 'extension', 'manual'))" in sql


def test_no_row_level_security_work_needed_and_none_smuggled_in() -> None:
    """Both tables already run ENABLE+FORCE RLS (0062/0018); 0135 must be purely
    additive - a policy change hiding in a column migration would dodge review."""
    sql = _MATRIX.read_text(encoding="utf-8").lower()
    assert "create policy" not in sql
    assert "drop policy" not in sql
    assert "create table" not in sql


def test_seed_stamps_no_fake_test_timestamps() -> None:
    """last_tested_at records a real check passing; a migration tested nothing, so it
    must stamp nothing."""
    for stmt in _seed_updates():
        assert "last_tested_at" not in re.split(r"\bwhere\b", stmt, maxsplit=1)[0], (
            "the 0135 seed must never write last_tested_at"
        )


# --------------------------------------------------------------------------- #
# Re-apply idempotence semantics.
# --------------------------------------------------------------------------- #
def test_every_seed_update_is_guarded_on_the_unclassified_default() -> None:
    """`where mechanism = ''` on every update is what makes re-apply safe: a row an
    operator manually reclassified has mechanism != '' and is never clobbered."""
    updates = _seed_updates()
    assert updates, "expected seed updates in 0135"
    for stmt in updates:
        assert "mechanism = ''" in _where_of(stmt), f"unguarded update: {stmt[:80]}"


def test_reapply_is_a_no_op_by_construction() -> None:
    """After one apply, every row has mechanism != '' (see the coverage test), so a
    second apply's guarded updates match zero rows - simulated re-apply changes
    nothing."""
    first = _simulate()
    # Re-run the simulation seeded with the first pass's result: setdefault-style
    # guards must leave every lane exactly as it was.
    names = _catalogue_names()
    lanes = dict(first)
    for stmt in _seed_updates():
        lane = _lane_of(stmt)
        if lane is None:
            continue
        where = _where_of(stmt)
        targets = _named_targets(where, names)
        if targets is None:
            targets = _enum_mapped(names) if "platform_enum is not null" in where else set(names)
        for name in targets:
            lanes.setdefault(name, lane)
    assert lanes == first


# --------------------------------------------------------------------------- #
# The classification itself (deliverable invariants).
# --------------------------------------------------------------------------- #
def test_the_seed_migrations_still_insert_the_ninety_row_catalogue() -> None:
    assert len(_catalogue_names()) == 90


def test_every_catalogue_row_leaves_0135_classified() -> None:
    """The deliverable's first invariant: no row keeps mechanism '' after the seed -
    the closing human catch-all is what makes coverage total by construction."""
    lanes = _simulate()
    names = _catalogue_names()
    assert set(lanes) == names
    for name, lane in lanes.items():
        assert lane in _LANES, f"{name}: illegal lane {lane!r}"


def test_every_api_row_resolves_to_the_publishing_enum() -> None:
    """mechanism='api' claims the pipeline can publish there, which requires a
    platform_enum mapping (behind which a real Web2Publisher exists for every enum
    value). An api row the pipeline cannot NAME would fail at plan time."""
    enum_mapped = _enum_mapped(_catalogue_names())
    for name, lane in _simulate().items():
        if lane == "api":
            assert name in enum_mapped, f"{name} classified api without an enum mapping"


def test_every_unsupported_statement_records_its_reason() -> None:
    """A do-not-use verdict with no recorded reason is folklore. Every statement that
    classifies rows unsupported must write a non-empty adapter_status in the same
    guarded update."""
    saw_unsupported = False
    for stmt in _seed_updates():
        if _lane_of(stmt) != "unsupported":
            continue
        saw_unsupported = True
        set_part = re.split(r"\bwhere\b", stmt, maxsplit=1)[0]
        m = re.search(r"adapter_status = '(.+?)'", set_part, flags=re.DOTALL)
        assert m and m.group(1).strip(), f"unsupported without a reason: {stmt[:80]}"
    assert saw_unsupported, "the §6 do-not-use set must be classified"


def test_the_provider_plan_buckets_land_where_section_six_puts_them() -> None:
    """Spot-pins from plan §6 - the rows whose classification was the point."""
    lanes = _simulate()
    # Extension-assisted: no usable write API; the operator publishes in their own
    # logged-in session. Medium is the one enum-mapped member (its API is retired).
    for name in (
        "Substack", "Medium", "Wix", "Weebly", "Google Sites", "Carrd", "HubPages",
        "Vocal.media", "Behance", "Site123", "Strikingly", "Jimdo", "Webnode",
        "Zoho Sites", "Yola",
    ):
        assert lanes[name] == "extension", name
    # Do-not-use, each with a recorded reason (see the statement test above).
    for name in (
        "Write.as", "Pastebin.com", "paste.ee", "dpaste.org", "rentry.co", "Evernote",
        "Flipboard", "Scoop.it", "Diigo", "Bloglovin", "Instapaper", "Wakelet",
        "Newgrounds", "Nostr long-form (YakiHonne / Habla.news)",
    ):
        assert lanes[name] == "unsupported", name
    # Human lane: real, no API, no tooling yet.
    for name in (
        "Wattpad", "SlideShare", "Issuu", "About.me", "Bear Blog", "JustPaste.it",
        "Wikidot", "Listed.to (Standard Notes)", "diaspora* (diasp.org)", "Ucraft",
        "Bravenet",
    ):
        assert lanes[name] == "human", name
    # API: the enum-mapped remainder, including all three Mastodon rows.
    for name in ("WordPress.com", "dev.to", "Mastodon", "Mastodon (mas.to)", "Telegra.ph"):
        assert lanes[name] == "api", name


def test_extension_lane_contains_exactly_one_enum_mapped_row() -> None:
    """Medium is the documented exception: its enum value and adapter exist, but the
    publish API is retired - anything else enum-mapped drifting into the extension
    lane would silently remove a working API path."""
    lanes = _simulate()
    enum_mapped = _enum_mapped(_catalogue_names())
    crossed = {n for n, lane in lanes.items() if lane == "extension" and n in enum_mapped}
    assert crossed == {"Medium"}


def test_structurally_limited_api_rows_are_marked_never_link_verifiable() -> None:
    """GitLab Pages + the headless CMS rows publish things the pipeline can never
    fetch as a public page: link_verifiable=false, in the SAME guarded statement, so
    they are excluded from link counts rather than counted on faith."""
    structural = {"GitLab Pages", "Notion", "Sanity", "Storyblok", "Hygraph"}
    covered: set[str] = set()
    for stmt in _seed_updates():
        if _lane_of(stmt) != "api":
            continue
        set_part = re.split(r"\bwhere\b", stmt, maxsplit=1)[0]
        targets = _named_targets(_where_of(stmt), _catalogue_names()) or set()
        if targets & structural:
            assert "link_verifiable = false" in set_part, stmt[:80]
            covered.update(targets & structural)
    assert covered == structural


def test_thin_placements_are_annotated_not_hidden() -> None:
    """Disqus/Gravatar stay api (real adapters, fetchable pages) but the row must say
    what a placement there IS - a profile field, not a content page."""
    for stmt in _seed_updates():
        targets = _named_targets(_where_of(stmt), _catalogue_names()) or set()
        if targets & {"Disqus", "Gravatar"}:
            set_part = re.split(r"\bwhere\b", stmt, maxsplit=1)[0]
            assert _lane_of(stmt) == "api"
            assert "adapter_status" in set_part
            assert "link_verifiable = true" in set_part
            return
    raise AssertionError("no statement annotates the Disqus/Gravatar thin placements")
