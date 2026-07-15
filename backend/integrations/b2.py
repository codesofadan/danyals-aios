"""Backblaze B2 offsite seam (7G-1): the ONLY door to the offsite backup bucket.

Nightly/manual Postgres snapshots land first on the VPS volume; when offsite is
enabled AND keyed, the backups service copies the artifact to a Backblaze B2 bucket
for a second, off-box copy. That upload is reachable exclusively through the
``OffsiteStore`` Protocol so the service can hold a real client or a fake with the
SAME shape - and unit-tests run fully live with zero creds.

Two impls satisfy the Protocol, mirroring the sheets/content seams exactly:

* ``BackblazeB2Client`` - real, backed by B2's S3-compatible API through ``boto3``.
  KEY-GATED on the (key_id, application_key, bucket) triple; ``boto3`` is LAZILY
  imported (an OPTIONAL extra, absent from the base install so the gate stays light).
  Absent creds/lib -> ``ProviderNotConfiguredError`` naming the fix. The application
  key is NEVER logged; only the (non-secret) bucket + endpoint are exposed.
* ``FakeOffsiteStore`` - deterministic, in-memory: records every upload into a
  per-key store and counts the calls, so the service's offsite path runs with no
  network and no creds.

``offsite_store_from_settings`` assembles the real client when the full credential
triple is present and degrades to ``None`` otherwise (or when ``boto3`` is missing) -
the service then keeps the local snapshot and simply leaves ``offsite_synced`` false,
exactly as the sheet store holds its buffer until its key lands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.logging_setup import get_logger
from integrations.errors import ProviderCallError, ProviderNotConfiguredError

if TYPE_CHECKING:
    from app.config import Settings

logger = get_logger("integrations.b2")

_INSTALL_HINT = (
    "install the b2 extra (boto3) and set B2_KEY_ID + B2_APPLICATION_KEY + B2_BUCKET "
    "(and optionally B2_ENDPOINT_URL) to a Backblaze B2 application key"
)


@runtime_checkable
class OffsiteStore(Protocol):
    """Copy a local backup artifact to offsite storage.

    ``upload`` streams the file at ``path`` to object ``key`` in the configured
    bucket and returns a stable remote reference (``bucket/key``). It raises
    ``ProviderCallError`` on a transport/API failure - the caller keeps the local
    snapshot and records the offsite copy as not-synced.
    """

    def upload(self, key: str, path: str) -> str: ...


class BackblazeB2Client:
    """Real ``OffsiteStore`` backed by Backblaze B2's S3-compatible API (``boto3``).

    The S3 client is built once at construction (lazily importing ``boto3``); a
    genuinely absent lib/credential raises ``ProviderNotConfiguredError`` naming the
    fix. The application key never leaves this object and is never logged - only the
    (non-secret) ``bucket`` / ``endpoint_url`` are exposed for a connection panel.
    """

    def __init__(
        self,
        *,
        key_id: str,
        application_key: str,
        bucket: str,
        endpoint_url: str | None = None,
    ) -> None:
        if not key_id or not application_key or not bucket:
            raise ProviderNotConfiguredError(f"Backblaze B2 client unavailable: {_INSTALL_HINT}")
        try:
            import boto3  # optional extra, absent from the base install
        except ImportError as exc:
            raise ProviderNotConfiguredError(
                f"Backblaze B2 client unavailable: {_INSTALL_HINT}"
            ) from exc
        # Non-secret identity for a connection panel (never the application key).
        self.bucket = bucket
        self.endpoint_url = endpoint_url or ""
        try:
            self._s3 = boto3.client(
                "s3",
                endpoint_url=endpoint_url or None,
                aws_access_key_id=key_id,
                aws_secret_access_key=application_key,
            )
        except Exception as exc:
            # A malformed client config. Never echo the key - just name the fix.
            raise ProviderNotConfiguredError(
                "Backblaze B2 client unavailable: could not build the S3 client "
                "(check B2_ENDPOINT_URL)"
            ) from exc

    def upload(self, key: str, path: str) -> str:
        try:
            self._s3.upload_file(path, self.bucket, key)
        except Exception as exc:
            # Never log the key/path body - only the (non-secret) bucket + object key.
            logger.error("b2_upload_failed", bucket=self.bucket, object_key=key)
            raise ProviderCallError("Backblaze B2 upload failed") from exc
        return f"{self.bucket}/{key}"


class FakeOffsiteStore:
    """Deterministic, in-memory ``OffsiteStore`` for the backups offsite tests.

    Every ``upload`` is recorded into ``store[key] = path`` and ``calls`` counts the
    round trips, so a test can prove the service synced offsite exactly when config
    enables it. No network.
    """

    def __init__(self, *, bucket: str = "fake-bucket") -> None:
        self.bucket = bucket
        self.store: dict[str, str] = {}
        self.calls: int = 0

    def upload(self, key: str, path: str) -> str:
        self.calls += 1
        self.store[key] = path
        return f"{self.bucket}/{key}"


@dataclass(frozen=True)
class B2ConnectionInfo:
    """The (non-secret) identity of a configured B2 bucket, or the degraded form."""

    connected: bool
    bucket: str = ""
    endpoint_url: str = ""


def offsite_store_from_settings(settings: Settings) -> OffsiteStore | None:
    """A real ``BackblazeB2Client`` when the full credential triple is present, else
    ``None``.

    Degrades to ``None`` (never raises) when any of key_id/application_key/bucket is
    absent OR ``boto3`` is not installed - the service then keeps the local snapshot
    and leaves the offsite copy unsynced. No secret is ever logged; the degraded path
    logs only the reason.
    """
    key_id = settings.b2_key_id
    app_key = settings.b2_application_key
    bucket = settings.b2_bucket
    if not key_id or not app_key or not bucket:
        logger.info("b2_offsite_degraded", reason="missing_credentials")
        return None
    try:
        return BackblazeB2Client(
            key_id=key_id,
            application_key=app_key.get_secret_value(),
            bucket=bucket,
            endpoint_url=settings.b2_endpoint_url,
        )
    except ProviderNotConfiguredError as exc:
        logger.info("b2_offsite_degraded", reason=str(exc))
        return None


def connection_info_from_settings(settings: Settings) -> B2ConnectionInfo:
    """The (non-secret) B2 bucket identity from settings - the degraded
    (``connected=False``) form when no credential resolves."""
    store = offsite_store_from_settings(settings)
    if not isinstance(store, BackblazeB2Client):
        return B2ConnectionInfo(connected=False)
    return B2ConnectionInfo(
        connected=True, bucket=store.bucket, endpoint_url=store.endpoint_url
    )
