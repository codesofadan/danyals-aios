"""Re-host a client's own logo and photographs (P6.2).

`site_analyzer` captures every asset URL on the page and v1 threw them away. That is
why a client whose own photograph is already on their site still got a generated stock
image on every new page: the real one had been measured and discarded.

A CLIENT-HOSTED URL IS NOT AN ASSET WE CAN RELY ON. It can 404 after a redesign, sit
behind hotlink protection, or move when the client changes host - and by then it is
embedded in fifty published pages. So the bytes are fetched once, stored under our own
root, and referenced from there.

CONTENT-ADDRESSED, so a logo appearing on every captured page is fetched once and
stored once. The dedup is enforced by `brand_assets_kit_sha_idx`, not by a check in
this module: two workers fetching the same asset concurrently would both pass a check.

THE SSRF CONTRACT IS THE SAME ONE `SsrfSafePageFetcher` KEEPS, and it matters more here
because the URLs come from a page WE DID NOT WRITE. A client's site can carry an <img>
pointing at 169.254.169.254 or at an internal host, and fetching it would make this
worker a proxy into the private network.

  - the host is validated BEFORE any connection is opened
  - redirects are DISABLED, because a 30x can bounce to an internal address that the
    pre-flight validation never saw
  - a non-200 is dropped rather than stored

BINARY FETCHING NEEDS THREE LIMITS THAT HTML FETCHING DOES NOT:

  - a SIZE CAP enforced while streaming, not after. `len(response.content)` has already
    bought the whole body; a 500MB "logo" would be in memory before anyone checked.
  - a CONTENT-TYPE allowlist, so an HTML error page served with status 200 is not
    stored as a JPEG and later published as a broken image.
  - a MAGIC-BYTES check, because Content-Type is whatever the remote server felt like
    saying. The header and the bytes must agree.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.security import PrivateAddressError, validate_public_host
from app.logging_setup import get_logger

logger = get_logger("services.brand_assets")

# 8 MB. A logo is tens of kilobytes and a hero photograph is low single-digit
# megabytes; past this it is not a brand asset, whatever the extension claims.
MAX_ASSET_BYTES = 8 * 1024 * 1024

# Read in chunks so the cap can be enforced DURING the download.
_CHUNK = 64 * 1024

FETCH_TIMEOUT = 15.0

# What we are willing to store, mapped to the extension we store it under. The client's
# URL extension is not trusted - plenty of real logos are served from paths with no
# extension at all.
ALLOWED_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/svg+xml": ".svg",
    "image/x-icon": ".ico",
    "image/vnd.microsoft.icon": ".ico",
}

# Leading bytes each format actually starts with. Content-Type is a claim; this is
# evidence. SVG is text so it is matched loosely, on the first non-whitespace markup.
_MAGIC: dict[str, tuple[bytes, ...]] = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".gif": (b"GIF87a", b"GIF89a"),
    ".webp": (b"RIFF",),
    ".ico": (b"\x00\x00\x01\x00",),
}


@dataclass(frozen=True)
class FetchedAsset:
    """One asset we actually hold the bytes for."""

    source_url: str
    data: bytes
    content_type: str
    extension: str
    sha256: str

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def stored_name(self) -> str:
        """Content-addressed filename: identical bytes are always the same file."""
        return f"{self.sha256}{self.extension}"


@dataclass(frozen=True)
class SkippedAsset:
    """One asset we refused, and why. Never an exception: a client's page having one
    unreachable image must not fail the capture that found forty good ones."""

    source_url: str
    reason: str


class AssetFetcher(Protocol):
    """The single door to the network, so the guard cannot be bypassed by a caller."""

    def fetch(self, url: str, *, timeout: float) -> tuple[int, str, bytes] | None:
        """``(status, content_type, body)`` or None. Body is already size-capped."""


class HttpAssetFetcher:
    """Real fetcher: redirects disabled, body streamed under a hard cap."""

    def __init__(self, *, user_agent: str = "AIOSContentBot/1.0") -> None:
        self._ua = user_agent

    def fetch(self, url: str, *, timeout: float) -> tuple[int, str, bytes] | None:
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx is a base dep
            logger.warning("asset_fetch_no_httpx")
            return None
        try:
            with (
                httpx.Client(
                    follow_redirects=False,  # a 30x can bounce past the pre-flight check
                    timeout=httpx.Timeout(timeout),
                    headers={"User-Agent": self._ua},
                ) as client,
                client.stream("GET", url) as resp,
            ):
                if resp.status_code != 200:
                    return (resp.status_code, "", b"")
                content_type = (
                    str(resp.headers.get("content-type", "")).split(";")[0].strip().lower()
                )
                body = bytearray()
                for chunk in resp.iter_bytes(_CHUNK):
                    body.extend(chunk)
                    # Enforced DURING the download. Checking afterwards means the whole
                    # body is already in memory.
                    if len(body) > MAX_ASSET_BYTES:
                        logger.info("asset_too_large", url=_safe(url))
                        return None
                return (200, content_type, bytes(body))
        except Exception:
            logger.info("asset_fetch_failed", url=_safe(url))
            return None


def _safe(url: str) -> str:
    """A URL safe to log: query strings can carry tokens."""
    return str(url).split("?", 1)[0][:200]


def _looks_like(extension: str, data: bytes) -> bool:
    """Whether the bytes match the format the Content-Type claimed."""
    if extension == ".svg":
        head = data[:512].lstrip()
        return head.startswith(b"<?xml") or head.startswith(b"<svg") or b"<svg" in data[:1024]
    magics = _MAGIC.get(extension)
    if not magics:
        return True
    return any(data.startswith(m) for m in magics)


def fetch_asset(
    url: str, *, fetcher: AssetFetcher, timeout: float = FETCH_TIMEOUT
) -> FetchedAsset | SkippedAsset:
    """Fetch one asset under the full SSRF + size + type contract.

    Total: never raises. Every refusal comes back as a `SkippedAsset` carrying the
    reason, because one bad image on a client's page must not lose the other forty.
    """
    clean = (url or "").strip()
    if not clean:
        return SkippedAsset(source_url=url, reason="empty URL")
    if not clean.lower().startswith(("http://", "https://")):
        # data: and file: URIs are not assets to re-host; file: would read our disk.
        return SkippedAsset(source_url=clean, reason="not an http(s) URL")

    try:
        validate_public_host(clean)
    except PrivateAddressError as exc:
        # The URL came off a page we did not write. This is the case that matters.
        logger.info("asset_blocked_private_host", url=_safe(clean))
        return SkippedAsset(source_url=clean, reason=f"blocked: {exc}")
    except ValueError as exc:
        return SkippedAsset(source_url=clean, reason=f"unusable URL: {exc}")

    result = fetcher.fetch(clean, timeout=timeout)
    if result is None:
        return SkippedAsset(source_url=clean, reason="fetch failed or exceeded the size cap")
    status, content_type, data = result
    if status != 200:
        return SkippedAsset(source_url=clean, reason=f"HTTP {status}")
    if not data:
        return SkippedAsset(source_url=clean, reason="empty body")
    if len(data) > MAX_ASSET_BYTES:
        return SkippedAsset(source_url=clean, reason="over the size cap")

    extension = ALLOWED_TYPES.get(content_type)
    if extension is None:
        # An HTML error page served with status 200 lands here rather than being
        # stored as a JPEG and published as a broken image.
        return SkippedAsset(source_url=clean, reason=f"unsupported content-type {content_type!r}")
    if not _looks_like(extension, data):
        return SkippedAsset(
            source_url=clean,
            reason=f"content-type said {content_type} but the bytes do not match",
        )

    return FetchedAsset(
        source_url=clean, data=data, content_type=content_type, extension=extension,
        sha256=hashlib.sha256(data).hexdigest(),
    )


def store_asset(asset: FetchedAsset, root: str | Path) -> str:
    """Write the bytes under ``root`` and return the stored key.

    Idempotent by construction: the name is the content hash, so re-storing identical
    bytes overwrites them with themselves. Two workers racing on the same asset
    therefore cannot corrupt it.
    """
    base = Path(root)
    base.mkdir(parents=True, exist_ok=True)
    path = base / asset.stored_name
    # `resolve()` and a containment check, because stored_name is derived from a hash
    # and an extension we chose - but a future caller might pass something else.
    resolved = path.resolve()
    if not str(resolved).startswith(str(base.resolve())):
        raise ValueError(f"refusing to write outside the asset root: {asset.stored_name}")
    if not resolved.exists():
        resolved.write_bytes(asset.data)
    return asset.stored_name


# --------------------------------------------------------------------------- #
# Tying it together: a kit's captured URLs -> stored, deduped, recorded assets
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RehostReport:
    """What happened to one kit's assets. Every URL is accounted for."""

    stored: tuple[str, ...] = ()
    deduped: tuple[str, ...] = ()
    skipped: tuple[SkippedAsset, ...] = ()

    @property
    def attempted(self) -> int:
        return len(self.stored) + len(self.deduped) + len(self.skipped)

    def notes(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.stored:
            out.append(f"{len(self.stored)} asset(s) re-hosted")
        if self.deduped:
            out.append(f"{len(self.deduped)} already held (same bytes)")
        for skip in self.skipped:
            # Every refusal is named. A silent skip here is a client's own photograph
            # quietly replaced by a generated stock image on fifty pages.
            out.append(f"skipped {_safe(skip.source_url)}: {skip.reason}")
        return tuple(out)


class AssetRecorder(Protocol):
    """The `brand_assets` write path (`ContentPlanningStore.record_brand_asset`)."""

    def record_brand_asset(
        self, *, kit_id: str, kind: str, source_url: str, stored_key: str = "",
        sha256: str = "", width: int | None = None, height: int | None = None,
    ) -> str | None: ...


def rehost_assets(
    urls: Sequence[tuple[str, str]],
    *,
    kit_id: str,
    root: str | Path,
    fetcher: AssetFetcher,
    recorder: AssetRecorder,
    timeout: float = FETCH_TIMEOUT,
) -> RehostReport:
    """Fetch, store and record every asset for one kit.

    ``urls`` is ``(url, analyzer_kind)`` pairs - the kind comes from `site_analyzer`
    and is translated to the database enum by `brand_kit.asset_kind_for`.

    Total: never raises. A client's page having one unreachable image must not lose the
    other forty, and a partial re-host is worth far more than an exception.

    Dedup is the DATABASE's: `record_brand_asset` returns None when those bytes are
    already held, because two workers fetching the same logo concurrently would both
    pass an existence check here.
    """
    from app.services.brand_kit import asset_kind_for

    stored: list[str] = []
    deduped: list[str] = []
    skipped: list[SkippedAsset] = []

    for url, analyzer_kind in urls:
        try:
            kind = asset_kind_for(analyzer_kind)
        except ValueError as exc:
            skipped.append(SkippedAsset(source_url=url, reason=str(exc)))
            continue

        result = fetch_asset(url, fetcher=fetcher, timeout=timeout)
        if isinstance(result, SkippedAsset):
            skipped.append(result)
            continue

        try:
            key = store_asset(result, root)
        except OSError as exc:
            skipped.append(SkippedAsset(source_url=url, reason=f"could not store: {exc}"))
            continue

        try:
            recorded = recorder.record_brand_asset(
                kit_id=kit_id, kind=kind, source_url=result.source_url,
                stored_key=key, sha256=result.sha256,
            )
        except Exception as exc:
            skipped.append(
                SkippedAsset(source_url=url, reason=f"could not record: {type(exc).__name__}")
            )
            continue

        (stored if recorded is not None else deduped).append(key)

    return RehostReport(
        stored=tuple(stored), deduped=tuple(deduped), skipped=tuple(skipped)
    )
