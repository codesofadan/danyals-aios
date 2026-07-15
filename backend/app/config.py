"""Application settings and config validation.

All settings come from the environment (12-factor). One cached ``Settings`` instance
is used app-wide. Secrets are ``SecretStr`` so they can never appear in a log or repr.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

# Config that must be present for the app to actually function in production.
_REQUIRED_IN_PROD = ("supabase_url", "supabase_service_role_key", "supabase_anon_key")


class ConfigError(RuntimeError):
    """Raised when required configuration is missing in production."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_env: Literal["dev", "prod"] = "dev"
    log_level: LogLevel = "INFO"
    api_cors_origins: str = "http://localhost:3000"
    trusted_hosts: str = "*"

    # --- Supabase (server-side). service_role bypasses RLS -> server-only, never logged. ---
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_anon_key: SecretStr | None = None

    # --- Auth (JWT verification). Supabase signs access tokens with asymmetric
    # keys (ES256/RS256); the API verifies them against the project's JWKS. No
    # shared secret is needed. ---
    supabase_jwt_aud: str = "authenticated"
    supabase_jwks_url: str | None = None  # defaults to <supabase_url>/auth/v1/.well-known/jwks.json

    # --- Local Postgres (P6A migration; ADDITIVE dual-config window). These sit
    # alongside SUPABASE_* and are OPTIONAL until the cutover (P6A-8) promotes them
    # into _REQUIRED_IN_PROD. Nothing here is wired into the running app yet. ---
    # Authenticated-role DSN -> the per-request RLS pool (RLS binds this connection).
    database_url: str | None = None
    # service_role DSN -> the privileged pool (BYPASSRLS); server-only, never logged.
    database_admin_url: str | None = None

    # --- Local auth (own EdDSA JWT; replaces networked JWKS at cutover). API-only
    # private key SIGNS at login; the public key VERIFIES. ---
    jwt_private_key: SecretStr | None = None  # Ed25519 PEM, API-only (signs access tokens)
    jwt_public_key: str | None = None  # Ed25519 PEM (verifies access tokens)
    # NOTE: `jwt_issuer` is already a DERIVED PROPERTY (from supabase_url) that
    # core/auth.py still imports for the live Supabase path. To avoid shadowing it
    # (a field would break that property + mypy), the local issuer is a distinct
    # field. At cutover it becomes the sole issuer and the property is retired.
    local_jwt_issuer: str = "aios"  # expected `iss` on our own EdDSA tokens
    jwt_audience: str = "authenticated"  # expected `aud` on our own EdDSA tokens
    # Access-token lifetime (seconds). Short by default: a leaked token expires fast.
    jwt_access_ttl_seconds: int = 3600

    # --- Seed owner (dev/test bootstrap ONLY; never a prod login path). The
    # provision_owner CLI reads these to mint the first local OWNER so the app +
    # integration tests are usable. The password is a SecretStr (never logged). ---
    seed_owner_username: str | None = None
    seed_owner_password: SecretStr | None = None
    seed_owner_email: str = "owner@local.aios"
    seed_owner_name: str = "AIOS Owner"

    # --- Vault (app-layer AES-256-GCM; replaces Supabase Vault at cutover). The
    # master key lives ONLY in process env, NEVER in Postgres. base64 32-byte key. ---
    vault_master_key: SecretStr | None = None

    # --- Redis (app cache + readiness) and Celery (separate logical DBs) ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # --- Audit engine (Module 01). The SEO audit engine (danyals-audit-system)
    # is a SEPARATE Python product with its OWN dependency set; it is invoked as
    # an EXTERNAL subprocess using ITS OWN interpreter, never imported here. ---
    audit_engine_dir: str | None = None  # repo root of danyals-audit-system
    audit_engine_python: str | None = None  # interpreter inside that repo's venv
    # Worker-owned hard timeout for one engine run. MUST be < the Celery
    # task_time_limit (1800) so the worker kills a hung engine (which never
    # times out itself) and marks the job failed - it never leaves it "running".
    audit_timeout_seconds: int = 1500
    audit_max_pages: int = 100  # default crawl breadth passed to the engine
    audit_profile: str = "general"  # engine --profile
    # Controlled root the worker copies each run's report PDF + findings.json
    # into (under <audit_id>/), and the API serves guarded downloads from. On the
    # single-VPS deploy the API + worker share this filesystem. Unset -> no
    # artifacts are stored/served (the pdf/json flags stay false).
    audit_artifact_dir: str | None = None
    # The engine emits no machine-readable spend; a Paid run logs this estimate
    # through the Part-2 cost path (a Free run always logs 0).
    audit_paid_cost_estimate: float = 1.5

    # --- Tuning ---
    readiness_timeout_seconds: float = 3.0

    # --- Sentry (optional) ---
    sentry_dsn: SecretStr | None = None

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, v: object) -> object:
        return v.upper() if isinstance(v, str) else v

    @property
    def is_prod(self) -> bool:
        return self.app_env == "prod"

    @property
    def jwks_url(self) -> str | None:
        """Resolved JWKS endpoint for verifying Supabase access tokens."""
        if self.supabase_jwks_url:
            return self.supabase_jwks_url
        if self.supabase_url:
            return f"{self.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        return None

    @property
    def jwt_issuer(self) -> str | None:
        """Expected ``iss`` claim on Supabase access tokens."""
        return f"{self.supabase_url.rstrip('/')}/auth/v1" if self.supabase_url else None

    @staticmethod
    def _pem(raw: str | None) -> str | None:
        """Normalize a PEM stored single-line in .env into real multi-line PEM.

        The keypair ships in ``.env`` as one quoted, ``\\n``-escaped line so
        pydantic-settings/dotenv can read it. dotenv keeps the literal ``\\n``, so
        we restore real newlines here (a no-op if the value already has them).
        Blank/absent -> ``None`` (falsiness, mirroring ``validate_settings``).
        """
        return raw.replace("\\n", "\n") if raw else None

    @property
    def jwt_private_key_pem(self) -> str | None:
        """The Ed25519 PRIVATE-key PEM used to SIGN access tokens (API-only)."""
        secret = self.jwt_private_key
        return self._pem(secret.get_secret_value()) if secret else None

    @property
    def jwt_public_key_pem(self) -> str | None:
        """The Ed25519 PUBLIC-key PEM used to VERIFY access tokens."""
        return self._pem(self.jwt_public_key)

    @property
    def docs_enabled(self) -> bool:
        return not self.is_prod

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def trusted_hosts_list(self) -> list[str]:
        """Allowed Host headers for ``TrustedHostMiddleware``; empty -> allow any."""
        hosts = [h.strip() for h in self.trusted_hosts.split(",") if h.strip()]
        return hosts or ["*"]


@lru_cache
def get_settings() -> Settings:
    """Return the cached, app-wide settings instance."""
    return Settings()


def validate_settings(settings: Settings) -> None:
    """Fail fast in prod when a required secret is missing; warn (non-fatal) in dev.

    Uses falsiness, not ``is None``: a blank env value arrives as ``""`` /
    ``SecretStr("")`` (present but empty) and must still count as missing.
    """
    missing = [name for name in _REQUIRED_IN_PROD if not getattr(settings, name)]
    if not missing:
        return
    if settings.is_prod:
        raise ConfigError(f"Missing required configuration in production: {', '.join(missing)}")
    logging.getLogger("app.config").warning(
        "Missing config (dev, non-fatal): %s. Dependent features will report 'not configured'.",
        ", ".join(missing),
    )
