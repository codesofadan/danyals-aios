"""Policy Radar request/response models in the frontend shapes (``lib/policy.ts``).

Four response models mirror their TS types EXACTLY (contract-lock enforced):

* ``SourceResponse`` <-> ``Source`` (9 keys: ``id, name, kind, url, icon,
  lastChecked, lastHash, status, note``)
* ``ChangeEventResponse`` <-> ``ChangeEvent`` (6 keys)
* ``KBEntryResponse`` <-> ``KBEntry`` (11 keys)
* ``RecommendationResponse`` <-> ``Recommendation`` (11 keys)

Every camelCase wire key is produced from a snake_case attribute via
``serialization_alias`` (ruff N815 forbids a raw mixedCase attribute); the internal
``*_id`` columns never surface (``sourceName``/``sourceUrl``/``kbId`` are display
SNAPSHOTS). The seven enum unions are pinned verbatim from ``policy.ts`` and locked
field-for-field by ``test_contract_lock``. Relative-time fields (``lastChecked`` /
``detected``) are humanized from their ``*_at`` timestamps by the ``from_row`` maps.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.util.timefmt import relative_ago

# --- the seven enums, verbatim from policy.ts -------------------------------- #
Severity = Literal["critical", "major", "minor", "info"]
Category = Literal["algorithm", "policy", "technical", "content", "local", "geo"]
Region = Literal["global", "national"]
TargetModule = Literal["audit", "content", "portal"]
Scope = Literal["global", "client", "site"]
RecStatus = Literal["new", "acknowledged", "applied", "dismissed"]
SourceStatus = Literal["ok", "change"]

_SEVERITIES: frozenset[str] = frozenset({"critical", "major", "minor", "info"})
_CATEGORIES: frozenset[str] = frozenset(
    {"algorithm", "policy", "technical", "content", "local", "geo"}
)
_REGIONS: frozenset[str] = frozenset({"global", "national"})
_TARGETS: frozenset[str] = frozenset({"audit", "content", "portal"})
_SCOPES: frozenset[str] = frozenset({"global", "client", "site"})
_REC_STATUSES: frozenset[str] = frozenset(
    {"new", "acknowledged", "applied", "dismissed"}
)
_SOURCE_STATUSES: frozenset[str] = frozenset({"ok", "change"})

# The action a lead may drive a recommendation through, and the status each lands
# on. Used as the {action} path enum on the transition route (FastAPI validates it
# -> 422 on an unknown action) and to keep the verb/status mapping single-sourced.
RecommendationAction = Literal["acknowledge", "apply", "dismiss"]

_ACTION_TO_STATUS: dict[str, RecStatus] = {
    "acknowledge": "acknowledged",
    "apply": "applied",
    "dismiss": "dismissed",
}


def action_to_status(action: str) -> RecStatus:
    """The ``rec_status`` an action lands a recommendation on (acknowledge ->
    acknowledged, apply -> applied, dismiss -> dismissed)."""
    return _ACTION_TO_STATUS[action]


# --- responses --------------------------------------------------------------- #


class SourceResponse(BaseModel):
    """One watched source in the frontend ``Source`` shape - and ONLY those 9 keys.
    ``lastChecked`` is the relative time of the last WATCHER poll ("38s ago", or
    "never" pre-live); ``lastHash`` is the content-diff anchor."""

    id: str
    name: str
    kind: str
    url: str
    icon: str
    last_checked: str = Field(serialization_alias="lastChecked")
    last_hash: str = Field(serialization_alias="lastHash")
    status: SourceStatus
    note: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SourceResponse:
        status = row.get("status")
        return cls(
            id=str(row["id"]),
            name=row.get("name", ""),
            kind=row.get("kind", ""),
            url=row.get("url", ""),
            icon=row.get("icon", ""),
            last_checked=relative_ago(row.get("last_checked"), empty="never"),
            last_hash=row.get("last_hash", ""),
            status=status if status in _SOURCE_STATUSES else "ok",
            note=row.get("note", ""),
        )


class ChangeEventResponse(BaseModel):
    """One detected change in the frontend ``ChangeEvent`` shape - and ONLY those 6
    keys. ``sourceName`` is a display snapshot so the internal ``source_id`` never
    leaks; ``detected`` is the relative detection time."""

    id: str
    source_id: str = Field(serialization_alias="sourceId")
    source_name: str = Field(serialization_alias="sourceName")
    summary: str
    severity: Severity
    detected: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ChangeEventResponse:
        severity = row.get("severity")
        source_id = row.get("source_id")
        return cls(
            id=str(row["id"]),
            source_id=str(source_id) if source_id is not None else "",
            source_name=row.get("source_name", ""),
            summary=row.get("summary", ""),
            severity=severity if severity in _SEVERITIES else "info",
            detected=relative_ago(row.get("detected_at"), empty="just now"),
        )


class KBEntryResponse(BaseModel):
    """One knowledge-base entry in the frontend ``KBEntry`` shape - and ONLY those
    11 keys. The 3 axes ``severity``/``category``/``region`` are pinned enums;
    ``sourceName``/``sourceUrl`` are the citation snapshots; ``detected`` is the
    relative detection time."""

    id: str
    title: str
    summary: str
    severity: Severity
    category: Category
    region: Region
    region_label: str = Field(serialization_alias="regionLabel")
    source_name: str = Field(serialization_alias="sourceName")
    source_url: str = Field(serialization_alias="sourceUrl")
    version: str
    detected: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> KBEntryResponse:
        severity = row.get("severity")
        category = row.get("category")
        region = row.get("region")
        return cls(
            id=str(row["id"]),
            title=row.get("title", ""),
            summary=row.get("summary", ""),
            severity=severity if severity in _SEVERITIES else "info",
            category=category if category in _CATEGORIES else "algorithm",
            region=region if region in _REGIONS else "global",
            region_label=row.get("region_label", ""),
            source_name=row.get("source_name", ""),
            source_url=row.get("source_url", ""),
            version=row.get("version", "v1"),
            detected=relative_ago(row.get("detected_at"), empty="just now"),
        )


class RecommendationResponse(BaseModel):
    """One recommendation in the frontend ``Recommendation`` shape - and ONLY those
    11 keys. ``kbId`` is the public KB reference snapshot (a synthetic ``kb-base-*``
    for a baseline rec); ``target`` is the module the action lands on; ``clients`` is
    the affected-client display list (empty when unscoped). The internal
    ``kb_entry_id`` never surfaces."""

    id: str
    kb_id: str = Field(serialization_alias="kbId")
    title: str
    why: str
    action: str
    scope: Scope
    target: TargetModule
    region: Region
    region_label: str = Field(serialization_alias="regionLabel")
    status: RecStatus
    clients: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RecommendationResponse:
        scope = row.get("scope")
        target = row.get("target_module")
        region = row.get("region")
        status = row.get("status")
        return cls(
            id=str(row["id"]),
            kb_id=row.get("kb_ref", ""),
            title=row.get("title", ""),
            why=row.get("why", ""),
            action=row.get("action", ""),
            scope=scope if scope in _SCOPES else "global",
            target=target if target in _TARGETS else "audit",
            region=region if region in _REGIONS else "global",
            region_label=row.get("region_label", ""),
            status=status if status in _REC_STATUSES else "new",
            clients=row.get("affected_clients", ""),
        )


def source_to_response(row: dict[str, Any]) -> SourceResponse:
    """Map a ``policy_sources`` row to the frontend ``Source`` shape."""
    return SourceResponse.from_row(row)


def change_to_response(row: dict[str, Any]) -> ChangeEventResponse:
    """Map a ``change_events`` row to the frontend ``ChangeEvent`` shape."""
    return ChangeEventResponse.from_row(row)


def kb_to_response(row: dict[str, Any]) -> KBEntryResponse:
    """Map a ``kb_entries`` row to the frontend ``KBEntry`` shape."""
    return KBEntryResponse.from_row(row)


def rec_to_response(row: dict[str, Any]) -> RecommendationResponse:
    """Map a ``recommendations`` row to the frontend ``Recommendation`` shape."""
    return RecommendationResponse.from_row(row)
