"""Backlink-monitoring seam (7B): the ONLY door to a client's referring-domain
profile.

Off-page monitoring reads a domain's live backlink profile - referring domain,
anchor, an authority score + a spam score, and when the link was first seen - to
surface new/lost links and queue toxic ones for a disavow review. That intelligence
is reachable through the ``BacklinkProvider`` Protocol so a later monitoring chunk
can wrap it in a cost-gated ingest; nothing else calls the provider directly.

THREE ways in, mirroring the content seams' key-gated pattern:

* ``DataForSeoBacklinks`` - real, backed by the DataForSEO Backlinks API over the
  shared sync ``HttpProviderClient`` (retry/backoff; auth is HTTP Basic login+
  password, handed to httpx per request and NEVER logged). Credential-gated: an
  empty login/password -> ``ProviderNotConfiguredError`` naming the fix.
* ``CsvBacklinkImporter`` - the KEYLESS path. Parses a backlink CSV export (Ahrefs /
  Moz / DataForSEO / SEMrush shapes, headers matched case-insensitively) into the
  same ``BacklinkRecord`` set, so an agency with NO paid API can still ingest a
  profile by uploading an export. No network, no key.
* ``FakeBacklinkProvider`` - deterministic, network-free: sha256(target) -> a stable
  profile, so tests + degraded runs are reproducible with zero keys.

``classify_backlink`` is the shared MONITORING verdict (toxic wins on a high spam
score, else lost on a drop, else new) so the DB ``status`` is derived one way from
every source.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, runtime_checkable

from app.config import Settings
from app.logging_setup import get_logger
from integrations.errors import ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("integrations.backlinks")

_INSTALL_HINT = (
    "set DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD to enable live backlink monitoring "
    "(or import a CSV export - no key needed)"
)
_DFS_BASE = "https://api.dataforseo.com"
# Spam score at/above which a link is toxic (queued for a disavow review). Kept in
# sync with the flag-toxic endpoint default.
TOXIC_SPAM_THRESHOLD = 60


@dataclass(frozen=True)
class BacklinkRecord:
    """One monitored backlink from any source (API or CSV).

    ``authority`` / ``spam`` are 0-100 scores; ``first_seen`` is the discovery date
    (``None`` if the source omits it); ``lost`` marks a link the source reports as
    dropped since the last crawl. ``status`` is DERIVED via ``classify_backlink`` -
    never trusted from the raw source - so every ingest path agrees.
    """

    ref_domain: str
    anchor: str
    authority: int
    spam: int
    first_seen: date | None = None
    lost: bool = False

    @property
    def status(self) -> str:
        """The monitoring verdict for this record (new|lost|toxic)."""
        return classify_backlink(self.spam, lost=self.lost)


def classify_backlink(spam: int, *, lost: bool = False) -> str:
    """The monitoring status a backlink lands in.

    Toxicity wins: a high-spam link is worth disavowing whether or not it is still
    live, so ``spam >= TOXIC_SPAM_THRESHOLD`` -> ``toxic`` first; then a dropped link
    -> ``lost``; otherwise a live link -> ``new``.
    """
    if spam >= TOXIC_SPAM_THRESHOLD:
        return "toxic"
    if lost:
        return "lost"
    return "new"


@runtime_checkable
class BacklinkProvider(Protocol):
    """Fetch a domain's referring-domain profile as ``BacklinkRecord``s.

    ``target`` is the client domain (bare host or URL); ``limit`` caps how many links
    to pull.
    """

    def fetch_backlinks(self, target: str, *, limit: int = 100) -> list[BacklinkRecord]: ...


def _to_int(value: Any, *, lo: int = 0, hi: int = 100) -> int:
    """Coerce a source score into a bounded 0-100 int (defaults to ``lo``)."""
    try:
        n = round(float(value))
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, n))


def _to_date(value: Any) -> date | None:
    """Parse a source date (ISO ``YYYY-MM-DD`` or a full timestamp) to a ``date``."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    # Accept a bare date or the leading date of a timestamp ("2026-07-08 12:00:00").
    head = text.replace("T", " ").split(" ", 1)[0]
    try:
        return date.fromisoformat(head)
    except ValueError:
        return None


class DataForSeoBacklinks(HttpProviderClient):
    """Real ``BacklinkProvider`` over the DataForSEO Backlinks API.

    Auth is HTTP Basic (``login`` + ``password``), handed to httpx per request and
    NEVER logged. The caller (the factory / service layer) supplies the credential.
    """

    provider = "dataforseo_backlinks"

    def __init__(self, *, login: str, password: str, timeout: float = 30.0) -> None:
        if not login or not password:
            raise ProviderNotConfiguredError(f"DataForSEO backlinks unavailable: {_INSTALL_HINT}")
        super().__init__(
            base_url=_DFS_BASE,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        self._auth = (login, password)

    def fetch_backlinks(self, target: str, *, limit: int = 100) -> list[BacklinkRecord]:
        body = [{"target": target, "limit": limit, "mode": "as_is"}]
        data = self.request_json(
            "POST", "/v3/backlinks/backlinks/live", json_body=body, auth=self._auth
        )
        return [_record_from_dfs(item) for item in _dfs_items(data)]


def _dfs_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull ``tasks[].result[].items[]`` out of a DataForSEO envelope defensively."""
    items: list[dict[str, Any]] = []
    for task in data.get("tasks") or []:
        for result in (task or {}).get("result") or []:
            for item in (result or {}).get("items") or []:
                if isinstance(item, dict):
                    items.append(item)
    return items


def _record_from_dfs(item: dict[str, Any]) -> BacklinkRecord:
    """Map one DataForSEO backlink item to a ``BacklinkRecord``."""
    return BacklinkRecord(
        ref_domain=str(item.get("domain_from") or ""),
        anchor=str(item.get("anchor") or ""),
        authority=_to_int(item.get("rank") or item.get("domain_from_rank")),
        spam=_to_int(item.get("backlink_spam_score")),
        first_seen=_to_date(item.get("first_seen")),
        lost=bool(item.get("is_lost")),
    )


# --- Keyless CSV ingestion ----------------------------------------------------
# Header aliases per field (lowercased, punctuation-insensitive). Covers the common
# Ahrefs / Moz / SEMrush / DataForSEO export column names.
_DOMAIN_KEYS = ("ref_domain", "referring domain", "referring page url", "domain", "domain_from", "source url", "url")
_ANCHOR_KEYS = ("anchor", "anchor text", "anchor_text")
_AUTHORITY_KEYS = ("authority", "domain authority", "domain rating", "dr", "da", "rank")
_SPAM_KEYS = ("spam", "spam score", "spam_score", "toxicity score")
_FIRST_SEEN_KEYS = ("first_seen", "first seen", "firstseen", "first indexed", "date")
_LOST_KEYS = ("lost", "is_lost", "is lost", "status")


class CsvBacklinkImporter:
    """Keyless ``BacklinkRecord`` ingestion from a backlink CSV export.

    The degrade path when DataForSEO credentials are absent: an operator uploads an
    Ahrefs/Moz/SEMrush/DataForSEO export and it is parsed into the same record set.
    Header names are matched case-insensitively against known aliases so one importer
    handles every common export shape; unknown columns are ignored, and a row without
    a referring domain is skipped. No network, no key.
    """

    def parse(self, csv_text: str) -> list[BacklinkRecord]:
        reader = csv.DictReader(io.StringIO(csv_text))
        records: list[BacklinkRecord] = []
        for raw in reader:
            row = {(k or "").strip().lower(): v for k, v in raw.items() if k}
            ref_domain = _first(row, _DOMAIN_KEYS)
            if not ref_domain:
                continue  # a row with no referring domain is unusable
            records.append(
                BacklinkRecord(
                    ref_domain=ref_domain,
                    anchor=_first(row, _ANCHOR_KEYS),
                    authority=_to_int(_first(row, _AUTHORITY_KEYS) or 0),
                    spam=_to_int(_first(row, _SPAM_KEYS) or 0),
                    first_seen=_to_date(_first(row, _FIRST_SEEN_KEYS)),
                    lost=_is_lost(_first(row, _LOST_KEYS)),
                )
            )
        return records


def _first(row: dict[str, str], keys: tuple[str, ...]) -> str:
    """The first present, non-empty value among ``keys`` in a lowercased CSV row."""
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _is_lost(value: str) -> bool:
    """Whether a CSV ``lost``/``status`` cell marks the link as dropped."""
    return value.strip().lower() in ("1", "true", "yes", "lost", "dropped")


class FakeBacklinkProvider:
    """Deterministic, offline ``BacklinkProvider`` - sha256(target) -> a stable
    profile.

    Same target => identical records every run; different targets differ. The first
    three records are PINNED one-per-status (a high-spam toxic link, a dropped lost
    link, a clean live link) so monitoring tests exercise every branch with zero keys;
    any further records are digest-driven for stable variety.
    """

    # (spam, lost) seeds that pin the first records to toxic / lost / new.
    _PINNED: tuple[tuple[int, bool], ...] = ((92, False), (4, True), (3, False))

    def fetch_backlinks(self, target: str, *, limit: int = 100) -> list[BacklinkRecord]:
        digest = hashlib.sha256(target.encode()).hexdigest()
        n = 4 + int(digest[0:2], 16) % 3  # 4..6 links (>= the 3 pinned)
        records: list[BacklinkRecord] = []
        for i in range(min(n, limit)):
            seg = digest[i * 6 : i * 6 + 6] or digest[:6]
            if i < len(self._PINNED):
                spam, lost = self._PINNED[i]
            else:
                spam = int(seg[0:2], 16) % 101  # 0..100
                lost = (int(seg[4:5], 16) % 4) == 0  # ~25% dropped
            authority = int(seg[2:4], 16) % 101
            day = 1 + int(seg[5:6], 16) % 28
            records.append(
                BacklinkRecord(
                    ref_domain=f"ref-{seg}.example",
                    anchor=f"{target} anchor {i + 1}",
                    authority=authority,
                    spam=spam,
                    first_seen=date(2026, 7, day),
                    lost=lost,
                )
            )
        return records


def backlink_provider_from_settings(settings: Settings) -> BacklinkProvider | None:
    """The real DataForSEO provider when its credentials are present, else ``None``
    (degraded - live monitoring is off; the keyless ``CsvBacklinkImporter`` remains
    available for manual ingest). Mirrors ``content_providers_from_settings``: no
    secret is ever logged, only the degraded reason."""
    login = settings.dataforseo_login
    password = settings.dataforseo_password
    if not login or not password:
        logger.info("backlink_provider_degraded", reason="missing_dataforseo_credentials")
        return None
    return DataForSeoBacklinks(login=login, password=password.get_secret_value())
