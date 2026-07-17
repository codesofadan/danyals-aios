"""The data-import ALLOW-LIST - this module's injection boundary.

Everything a user controls in an import is a STRING that ends up next to SQL: the
uploaded header row, the ``column_map`` they post, the file's cell values. Exactly one
of those - the ``column_map``'s TARGET side - would otherwise decide a *column name*.
So it never does: a target field is only ever the ``name`` of a :class:`TargetField`
frozen in this file, and the privileged writer iterates THIS tuple to build its
identifiers, checking membership in the row rather than reading the row's keys. A
``column_map`` naming ``password_hash`` (or anything else not listed here) is rejected
at validation and, belt-and-braces, again in the store.

Every column below was verified against the REAL migration that owns it - not against
memory, and not against the frontend:

* ``keywords``           - ``0035_keyword_research.sql``
* ``tracked_keywords``   - ``0036_rank_tracker.sql``
* ``backlinks``          - ``0018_offpage.sql``
* ``citations``          - ``0018_offpage.sql``
* ``search_console_rows``- ``0042_data_import.sql`` (this module's own table)

Two kinds of column exist per target and the split is load-bearing:

* ``fields``  - the MAPPABLE allow-list. A ``column_map`` may name these and only these.
* ``derived`` - columns the SERVER stamps (``client_id``/``client_name`` from the run,
  ``action`` from the NAP rule, ``normalized_keyword`` from the keyword, the
  ``source='import'`` marker). A ``column_map`` may NEVER name one: they are how the
  module keeps tenant attribution and enum invariants out of user hands.

``aliases`` are NORMALIZED header synonyms (see ``service.normalize_header``) tuned to
the real exports the agency actually uploads - Google Search Console, Semrush and
Ahrefs - so the auto-suggested mapping lands without a human re-teaching it monthly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# The 0042 enums, pinned verbatim (the module's schema tests assert each tuple against
# the migration's ``create type``). These ARE the wire values.
ImportSourceType = Literal[
    "search_console", "keywords", "backlinks", "rankings", "citations", "custom"
]
ImportStatus = Literal[
    "uploaded", "mapping", "validating", "importing", "imported", "partial", "failed"
]

SOURCE_TYPES: tuple[str, ...] = (
    "search_console", "keywords", "backlinks", "rankings", "citations", "custom",
)
STATUSES: tuple[str, ...] = (
    "uploaded", "mapping", "validating", "importing", "imported", "partial", "failed",
)

# The statuses a run can never leave. The worker CLAIMS a run out of a non-terminal
# status with a conditional UPDATE, so a redelivered terminal run is a no-op.
TERMINAL_STATUSES: frozenset[str] = frozenset({"imported", "partial", "failed"})
# The statuses the commit worker may claim FROM (uploaded/mapping/validating). Notably
# NOT ``importing``: a run already being imported must not be picked up twice, which is
# what makes an ``acks_late`` redelivery mid-import a no-op instead of a double insert.
CLAIMABLE_STATUSES: tuple[str, ...] = ("uploaded", "mapping", "validating")

# How a source_type renders in the workspace table's Type column.
SOURCE_TYPE_LABELS: dict[str, str] = {
    "search_console": "Search Console",
    "keywords": "Keywords",
    "backlinks": "Backlinks",
    "rankings": "Rankings",
    "citations": "Citations",
    "custom": "Custom",
}

# Upload gates. The extension allow-list is checked AND the bytes are sniffed - the
# extension alone is a claim by the uploader, not evidence.
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({"csv", "tsv", "xlsx"})
# The content types browsers/curl actually send for those three. ``application/
# octet-stream`` is DELIBERATELY absent: accepting it would make the MIME gate
# decorative, since it is what a client sends when it knows nothing about the file.
ALLOWED_CONTENT_TYPES: frozenset[str] = frozenset(
    {
        "text/csv",
        "application/csv",
        "text/plain",
        "text/tab-separated-values",
        "application/vnd.ms-excel",  # what Excel + several browsers label .csv
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # .xlsx
    }
)


@dataclass(frozen=True)
class TargetField:
    """One MAPPABLE target column: its canonical name (= the real DB column), how a
    value is coerced into it, and the normalized header synonyms that auto-map onto it.

    ``name`` is the ONLY place a column identifier ever comes from. ``kind`` selects
    the pure coercion in ``service.py``; ``enum_values`` pins an enum column's legal
    set to its migration's ``create type``.
    """

    name: str
    kind: Literal["text", "domain", "int", "score", "ctr", "position", "numeric", "date", "enum", "intent"]
    required: bool = False
    aliases: tuple[str, ...] = ()
    enum_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportTarget:
    """One source_type's commit target: the table, its mappable allow-list, the columns
    the server derives, and the natural key (if the table has one).

    ``table`` is ``None`` for ``custom`` - a staging-only import with an EMPTY allow-
    list, so validation rejects any mapping and the commit route refuses outright.
    """

    source_type: str
    table: str | None
    fields: tuple[TargetField, ...] = ()
    # Server-stamped columns. A column_map may never name one (validation rejects it,
    # because these are not in ``fields``).
    derived: tuple[str, ...] = ()
    # The target's EXISTING uniqueness key, reused verbatim for ``on conflict``. Empty
    # when the table has none (backlinks / citations / search_console_rows are
    # append-shaped ledgers) - there the run-claim, not a constraint, is the
    # idempotency guard.
    conflict: tuple[str, ...] = ()
    # True when the target's client_id is NOT NULL (0036 tracked_keywords), so an
    # agency-global import of this type is impossible and the router says so.
    requires_client: bool = False
    fixed: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def field_names(self) -> tuple[str, ...]:
        """The mappable allow-list - the ONLY targets a column_map may name."""
        return tuple(f.name for f in self.fields)

    @property
    def all_columns(self) -> tuple[str, ...]:
        """Every column the writer may touch: mappable + server-derived. The store
        iterates this to build identifiers; nothing else is ever writable."""
        return self.field_names + self.derived

    def field(self, name: str) -> TargetField | None:
        return next((f for f in self.fields if f.name == name), None)


# The 0035 search_intent enum (capitalised - they ARE the display cells).
_INTENTS: tuple[str, ...] = (
    "Informational", "Commercial", "Transactional", "Navigational", "Local",
)
# The 0018 backlink_status / nap_status enums.
_BACKLINK_STATUSES: tuple[str, ...] = ("new", "lost", "toxic")
_NAP_STATUSES: tuple[str, ...] = ("consistent", "inconsistent", "missing")
# The 0036 rank_engine / rank_device enums.
_ENGINES: tuple[str, ...] = ("google", "bing")
_DEVICES: tuple[str, ...] = ("desktop", "mobile", "tablet")


# --------------------------------------------------------------------------- #
# The targets. Columns verified against the owning migration, one by one.
# --------------------------------------------------------------------------- #
_SEARCH_CONSOLE = ImportTarget(
    source_type="search_console",
    table="public.search_console_rows",
    # A real GSC export is "Query, Clicks, Impressions, CTR, Position" (Queries tab) or
    # "Page, Clicks, Impressions, CTR, Position" (Pages tab) - so NEITHER query nor page
    # is required on its own; a row needs one or the other, which the service enforces.
    fields=(
        TargetField("query", "text", aliases=("query", "queries", "search query", "top queries", "keyword")),
        TargetField("page", "text", aliases=("page", "pages", "landing page", "url", "top pages", "address")),
        TargetField("clicks", "int", aliases=("clicks", "click", "total clicks", "url clicks")),
        TargetField("impressions", "int", aliases=("impressions", "impression", "total impressions", "impr")),
        TargetField("ctr", "ctr", aliases=("ctr", "click through rate", "clickthrough rate", "site ctr", "url ctr")),
        TargetField("position", "position", aliases=("position", "avg position", "average position", "avg pos")),
        TargetField("date", "date", aliases=("date", "day", "dates")),
    ),
    derived=("client_id", "client_name", "import_run_id"),
)

_KEYWORDS = ImportTarget(
    source_type="keywords",
    table="public.keywords",
    fields=(
        TargetField(
            "keyword", "text", required=True,
            aliases=("keyword", "keywords", "query", "term", "search term"),
        ),
        TargetField(
            "volume", "int",
            aliases=("volume", "search volume", "avg monthly searches", "monthly searches", "sv", "vol"),
        ),
        TargetField(
            # 0035: numeric(5,2) check between 0 and 100. Semrush ships "KD"/"KD %",
            # Ahrefs ships "KD"/"Difficulty".
            "difficulty", "score",
            aliases=("difficulty", "kd", "keyword difficulty", "kd %", "competition index", "seo difficulty"),
        ),
        TargetField("cpc", "numeric", aliases=("cpc", "cpc usd", "cost per click", "avg cpc")),
        TargetField(
            "intent", "intent", enum_values=_INTENTS,
            aliases=("intent", "search intent", "keyword intent"),
        ),
        TargetField("geo", "text", aliases=("geo", "location", "country", "region", "market")),
    ),
    # 0035: `unique nulls not distinct (client_id, keyword, geo)`. Reused verbatim, so a
    # re-import of last month's export refreshes nothing and duplicates nothing.
    conflict=("client_id", "keyword", "geo"),
    derived=("client_id", "client_name", "source"),
    # 0035 keyword_source enum includes 'import' - which is exactly this path.
    fixed=(("source", "import"),),
)

_RANKINGS = ImportTarget(
    source_type="rankings",
    table="public.tracked_keywords",
    fields=(
        TargetField("keyword", "text", required=True, aliases=("keyword", "keywords", "query", "term")),
        TargetField("location", "text", aliases=("location", "locale", "geo", "city", "area")),
        TargetField("target_url", "text", aliases=("target url", "url", "landing page", "target", "page")),
        TargetField("device", "enum", enum_values=_DEVICES, aliases=("device", "platform")),
        TargetField("engine", "enum", enum_values=_ENGINES, aliases=("engine", "search engine", "se")),
        TargetField("language", "text", aliases=("language", "lang", "language code")),
        TargetField("country", "text", aliases=("country", "country code", "cc")),
    ),
    # 0036: `unique nulls not distinct (client_id, normalized_keyword, engine, device,
    # location, language)`. Reused verbatim so an import can never create a DUPLICATE
    # SUBSCRIPTION - which on this table would be a duplicate nightly CHARGE.
    conflict=("client_id", "normalized_keyword", "engine", "device", "location", "language"),
    derived=("client_id", "client_name", "normalized_keyword"),
    # 0036: `client_id uuid NOT NULL`. A tracked keyword is a standing per-client bill,
    # so there is no such thing as an agency-global rankings import.
    requires_client=True,
)

_BACKLINKS = ImportTarget(
    source_type="backlinks",
    table="public.backlinks",
    fields=(
        TargetField(
            # 0018: `ref_domain text not null`. Semrush exports "Source url" and Ahrefs
            # "Referring page URL" - full URLs - so the coercion reduces a URL to its
            # host rather than storing a whole URL in a domain column.
            "ref_domain", "domain", required=True,
            aliases=(
                "ref domain", "referring domain", "domain", "source url", "source page url",
                "referring page url", "referring page", "source", "from url", "link from",
            ),
        ),
        TargetField("anchor", "text", aliases=("anchor", "anchor text", "link anchor")),
        TargetField(
            # 0018: `authority integer check (authority between 0 and 100)`. Semrush
            # ships "Page ascore"/"Authority Score"; Ahrefs ships "Domain rating"/"DR".
            "authority", "score",
            aliases=(
                "authority", "page ascore", "ascore", "authority score", "domain rating",
                "dr", "ur", "url rating", "domain authority", "da",
            ),
        ),
        TargetField(
            # 0018: `spam integer check (spam between 0 and 100)`.
            "spam", "score",
            aliases=("spam", "spam score", "toxicity score", "toxic score", "spam level"),
        ),
        TargetField("first_seen", "date", aliases=("first seen", "first indexed", "found", "first found", "seen")),
        TargetField(
            "status", "enum", enum_values=_BACKLINK_STATUSES,
            aliases=("status", "link status", "state"),
        ),
    ),
    # 0018 declares NO unique key on backlinks - it is an append-shaped monitoring
    # ledger. Adding one here would silently change the off-page module's semantics, so
    # the run-claim is this target's idempotency guard instead.
    derived=("client_id", "client_name"),
)

_CITATIONS = ImportTarget(
    source_type="citations",
    table="public.citations",
    fields=(
        TargetField(
            "directory", "text", required=True,
            aliases=("directory", "site", "citation", "source", "listing", "platform", "aggregator"),
        ),
        TargetField(
            "nap_status", "enum", enum_values=_NAP_STATUSES,
            aliases=("nap status", "nap", "status", "listing status", "accuracy"),
        ),
        TargetField("note", "text", aliases=("note", "notes", "detail", "details", "comment", "issue")),
    ),
    # `action` is DERIVED from nap_status via the off-page module's OWN existing rule
    # (``app.schemas.offpage.action_for``: missing -> Submit, else Update), never
    # mapped. Letting a spreadsheet column drive it would let an import contradict the
    # NAP state the same row carries.
    derived=("client_id", "client_name", "action"),
)

_CUSTOM = ImportTarget(
    source_type="custom",
    # Staging ONLY: no target table, and therefore an EMPTY allow-list - so
    # ``validate_mapping`` rejects every non-empty map and the commit route refuses.
    # A custom upload still sniffs its headers + sample values for a human to read.
    table=None,
)

TARGETS: dict[str, ImportTarget] = {
    "search_console": _SEARCH_CONSOLE,
    "keywords": _KEYWORDS,
    "rankings": _RANKINGS,
    "backlinks": _BACKLINKS,
    "citations": _CITATIONS,
    "custom": _CUSTOM,
}


def target_for(source_type: str) -> ImportTarget | None:
    """The commit target for ``source_type``, or ``None`` when it is not a known type."""
    return TARGETS.get(source_type)


def allowed_fields(source_type: str) -> tuple[str, ...]:
    """The mappable target fields for ``source_type`` - the allow-list a ``column_map``
    is validated against. An unknown type (or ``custom``) yields an empty tuple, which
    makes every mapping invalid by construction rather than by a special case."""
    target = TARGETS.get(source_type)
    return target.field_names if target else ()
