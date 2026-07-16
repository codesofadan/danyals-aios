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
# The data plane (both DB pools), the token-signing keypair, and the vault master
# key: without any one of these the app cannot authenticate, read/write, or seal.
_REQUIRED_IN_PROD = (
    "database_url",
    "database_admin_url",
    "jwt_private_key",
    "jwt_public_key",
    "vault_master_key",
)


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

    # --- Local Postgres (the data plane). Two DSNs, one per trust level. ---
    # Authenticated-role DSN -> the per-request RLS pool (RLS binds this connection).
    database_url: str | None = None
    # service_role DSN -> the privileged pool (BYPASSRLS); server-only, never logged.
    database_admin_url: str | None = None

    # --- Local auth (own EdDSA JWT). API-only private key SIGNS at login; the
    # public key VERIFIES every request. No networked JWKS, no shared secret. ---
    jwt_private_key: SecretStr | None = None  # Ed25519 PEM, API-only (signs access tokens)
    jwt_public_key: str | None = None  # Ed25519 PEM (verifies access tokens)
    local_jwt_issuer: str = "aios"  # expected `iss` on our own EdDSA tokens
    jwt_audience: str = "authenticated"  # expected `aud` on our own EdDSA tokens
    # Access-token lifetime (seconds). Short by default: a leaked token expires fast.
    jwt_access_ttl_seconds: int = 3600
    # --- Skills gateway (Part 9). A skill token is a SEPARATE, scoped credential
    # the MCP gateway authenticates (app/services/skill_tokens.py). Default TTL is
    # long-lived (30 days) since it drives standing local automation, but it is
    # per-token overridable at mint and always revocable. NOT a required secret. ---
    skill_token_ttl_seconds: int = 2_592_000  # 30 days

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

    # Fiverr upsell link shown on the PUBLIC free-audit report (P6C). Not a secret
    # (it is rendered to anonymous visitors); trivial to change per campaign.
    fiverr_upsell_url: str = "https://www.fiverr.com/danyalseo"

    # --- Context / AI-memory module (P6B). ALL optional and NOT in
    # _REQUIRED_IN_PROD: the module builds + unit-tests NOW with deterministic
    # fakes and ACTIVATES when these keys land (mirrors the audit-engine
    # key-gating). A keyless deploy runs the context pipeline in 'degraded' mode,
    # holding the freshness watermark until the keys arrive. ---
    # Summarizer (Anthropic - Haiku default / Sonnet for large folds). NOTE:
    # Anthropic has NO embeddings API, so the Embedder below is a SEPARATE
    # provider. Key is a SecretStr (never logged / never in a repr).
    anthropic_api_key: SecretStr | None = None
    anthropic_model_summary: str = "claude-haiku-4-5"  # cheap default fold
    anthropic_model_heavy: str = "claude-sonnet-5"  # heavier model for large folds
    # Embedder (Voyage AI - Anthropic has no embeddings API). embeddings_dim MUST
    # match the Pinecone index dimension AND the FakeEmbedder so real<->fake are
    # drop-in swappable (voyage-3 -> 1024).
    embeddings_provider: str = "voyage"
    embeddings_api_key: SecretStr | None = None
    embeddings_model: str = "voyage-3"
    embeddings_dim: int = 1024
    # Vector store (Pinecone; namespaced per entity 'entity_type:entity_id').
    pinecone_api_key: SecretStr | None = None
    pinecone_index: str | None = None
    pinecone_host: str | None = None  # optional index host override
    # Pipeline tuning: debounce window, bounded summary token budget, retrieval breadth.
    context_debounce_seconds: int = 30
    context_summary_token_budget: int = 1200
    context_topk: int = 6
    # Compaction-worker knobs (P6B-7). max_facts caps the folded fact set; the
    # backoff is how far the worker pushes a dirty row's next_eligible_at when it
    # DEGRADES (keys absent / spend blocked) or ERRORS, so it retries later without
    # hot-spinning; the dispatch batch caps how many due entities one beat tick claims.
    context_max_facts: int = 64
    context_backoff_seconds: int = 300
    context_dispatch_batch: int = 100
    # Reconcile sweep (P6B-9): a slow BEAT that walks every entity with vectors and
    # runs the ledger-vs-store drift detector (orphan/missing/mismatch), logging the
    # counts. It runs at a lazy cadence (default hourly) because Postgres is the
    # source of truth and sync_vectors already keeps the two in step per fold - the
    # sweep is a safety net for residual drift (a lost Pinecone write, a manual edit),
    # not a hot path. ``context_reconcile_repair`` (default OFF) turns the sweep from a
    # pure detector into a self-healer (delete orphans, re-embed missing/mismatched).
    context_reconcile_seconds: int = 3600
    context_reconcile_repair: bool = False
    # Per-call cost estimates for the money-dial (P6B-4 wires these into the cost path).
    context_summarize_cost_estimate: float = 0.02
    context_embed_cost_estimate: float = 0.001

    # --- Web in-product AI-assist surface (P9-5). The dashboard/portal calls OUR
    # backend, which calls Claude through the EXISTING summarizer seam
    # (integrations/llm.py) wrapped in the EXISTING cost gate (the `ai_assist`
    # money-dial feature) - the client NEVER holds an Anthropic key. Reuses the
    # SAME optional ``anthropic_api_key`` above: keyless OR a dial/budget block ->
    # a degraded stub (200), never a crash. Both knobs are additive + optional. ---
    ai_assist_cost_estimate: float = 0.02  # per-call estimate logged through the gate
    ai_assist_max_tokens: int = 700  # bound the assist prose to a small reply

    # --- Content module provider seams (P7A-2). ALL optional and NOT in
    # _REQUIRED_IN_PROD: the module builds + unit-tests NOW with deterministic
    # fakes and ACTIVATES per key as they land (mirrors the context key-gating).
    # The WRITER reuses the Anthropic summarizer above; these add the SERP-research
    # + image-generation keys. WordPress app-passwords are per-site and live in the
    # vault (NOT here) - the service layer decrypts them. Keys are SecretStr (never
    # logged / never in a repr). ---
    serper_api_key: SecretStr | None = None  # Serper.dev SERP research
    image_gen_api_key: SecretStr | None = None  # OpenAI-compatible image generation
    image_gen_model: str = "gpt-image-1"  # image model (provider-configurable)
    # Per-call cost estimates for the money-dial (a later chunk wires these in).
    content_research_cost_estimate: float = 0.01
    content_generate_cost_estimate: float = 0.15
    # --- Content RESEARCH service tuning (P7A-3). Operational knobs for the
    # keyword/intent research brief; additive + optional (never required in prod). ---
    # DA assumed when the client is un-audited / Moz DA is missing (winnability
    # falls back to this NEUTRAL authority and the brief is marked low_confidence).
    content_research_neutral_da: float = 30.0
    # How far above a client's DA a keyword's difficulty may sit and still be
    # judged winnable (a realistic stretch, on the 0-100 scale).
    content_research_winnable_stretch: float = 15.0
    # N1 SERP + top-10-teardown Redis cache TTL (seconds); 24h so a cluster/city
    # sprint reuses one pull. The gate serves a cache hit at ~$0.
    content_research_cache_ttl_seconds: int = 86_400
    # Per-URL bounded fetch timeout + how many ranking pages to tear down.
    content_teardown_timeout_seconds: float = 8.0
    content_teardown_max_pages: int = 10
    # --- Content WORKER + PUBLISH tuning (P7A-7/8). The pipeline worker composes
    # the merged content services; the publish path renders PDF/Markdown to a
    # controlled artifact root (traversal-guarded, like the audit store) when the
    # target is PDF/Markdown OR WordPress is credential-degraded. Unset -> falls
    # back to ``audit_artifact_dir``; if BOTH are unset no artifact is written. ---
    content_artifact_dir: str | None = None
    # Coarse R5 cost-precheck fan-out factors: the worker estimates the FULL job
    # spend upfront (research fan-out + generation) against the client budget +
    # daily spend-stop BEFORE it starts, and defers a job that would breach. These
    # multiply the per-call estimates; conservative (over-estimating) is the safe
    # side (defers a borderline job rather than half-spending then blocking).
    content_precheck_research_calls: int = 10  # ~ serp + up-to-8 metrics + teardown
    content_precheck_writer_calls: int = 14    # ~ one writer call per drafted section

    # --- Off-page module provider seams (7B). ALL optional and NOT in
    # _REQUIRED_IN_PROD: the module builds + unit-tests NOW with deterministic fakes
    # and ACTIVATES per key as they land (mirrors the content/context key-gating).
    # DataForSEO (backlink monitoring) uses HTTP Basic login+password; without them
    # live monitoring degrades to None and the keyless CSV-import path remains
    # available. BrightLocal (citation / NAP monitoring) uses an api-key. Keys are
    # SecretStr (never logged / never in a repr); the login is not a secret. ---
    dataforseo_login: str | None = None  # DataForSEO account login (Basic auth user)
    dataforseo_password: SecretStr | None = None  # DataForSEO API password (Basic auth)
    brightlocal_api_key: SecretStr | None = None  # BrightLocal citation-tracker key

    # --- Keyword-research module (Part 8). The DataForSEO login/password ABOVE are
    # reused for the keyword-metrics pull (volume / difficulty / CPC that Serper
    # can't supply - the deliberate provider exception); without them the module
    # degrades to a deterministic fake provider (never None). Additive + optional
    # (never required in prod). The per-call cost estimate is logged through the
    # cost gate against the `keyword_research` money-dial (R5 pre-check). ---
    keyword_research_cost_estimate: float = 0.02  # one DataForSEO keyword pull

    # --- Local-SEO module (Part 8 Phase 2E). ALL optional and NOT in
    # _REQUIRED_IN_PROD: the module builds + unit-tests NOW with a deterministic fake
    # and ACTIVATES per key as they land (mirrors the content/context key-gating).
    # The map-pack provider is TO-CONFIRM: the seam prefers the SERPER_API_KEY the
    # platform already holds (Serper Places - the house default), falls back to the
    # DataForSEO login/password above (DataForSEO Maps), and degrades to a
    # deterministic fake (never None). The per-check estimate is logged through the
    # cost gate against the `local_rank` money-dial (R5 pre-check), billed to the
    # ranking's CLIENT. ---
    local_rank_cost_estimate: float = 0.003  # one map-pack position check
    # The refresh BEAT's cadence + batch. Daily by default: a map-pack position does
    # not move hourly and every check is paid, so a tighter cadence buys noise at
    # linear cost. The batch caps how many rows ONE tick claims.
    local_rank_refresh_seconds: int = 86_400
    local_rank_refresh_batch: int = 100
    # Google Business Profile OAuth client (DORMANT). The GBP API is APPROVAL-gated -
    # a new project starts at 0 QPM and approval takes days-to-weeks - so these stay
    # unset and `sync_gbp_profile` HOLDS cleanly; map-pack rank + citations work
    # without them. The per-client refresh TOKEN is never here: it is AES-GCM sealed
    # in the vault and `gbp_profiles.oauth_vault_ref` points at it.
    gbp_oauth_client_id: str | None = None
    gbp_oauth_client_secret: SecretStr | None = None

    # --- Off-page Web 2.0 PUBLISH pipeline + monitoring worker tuning (7B-3).
    # Additive + optional (never required in prod). The write stage (Claude drafting
    # of the branded article) rides the EXISTING `content` money-dial; the publish +
    # backlink/citation monitoring pulls ride the EXISTING `backlinks` (off-page) dial
    # - no new dial feature. Per-account Web 2.0 OAuth tokens (WordPress.com / Blogger
    # / Tumblr) are per-property and live in the VAULT (like WordPress app passwords),
    # NOT here; the service layer builds a real publisher per publish, so the worker's
    # publisher factory degrades to 'hold at the review gate' until that wiring lands. ---
    web2_publish_cost_estimate: float = 0.0  # marginal cost of one blog-API publish
    offpage_monitor_cost_estimate: float = 0.05  # one backlink/citation provider pull

    # --- Reports module: the Google Sheets operational store (7D). OPTIONAL and NOT
    # in _REQUIRED_IN_PROD: the SheetStore buffers writes in Redis and unit-tests NOW
    # with a fake client, and ACTIVATES when this credential lands (mirrors the
    # content/off-page key-gating). A keyless deploy runs the store HELD (buffer
    # retained, sync optimistic) until the key arrives. The value is the full
    # service-account credential JSON (it carries a private key) - a SecretStr so it
    # is never logged / never in a repr. ---
    google_sheets_sa_json: SecretStr | None = None  # service-account credential JSON

    # --- Delivery layer: email + Slack (7F-1). OPTIONAL and NOT in _REQUIRED_IN_PROD:
    # the notifications/alerts service builds + unit-tests NOW with fakes and lights up
    # the email/Slack legs per key as they land (mirrors the content/sheets key-gating).
    # A keyless deploy still delivers IN-APP notifications + persists alert rows; only
    # the email + Slack legs are skipped until the keys arrive. Keys are SecretStr
    # (never logged / never in a repr); the ``from`` sender address is not a secret. ---
    resend_api_key: SecretStr | None = None  # Resend transactional-email API key
    resend_from_email: str = "AIOS <notifications@xegents.ai>"  # verified Resend sender
    slack_webhook_url: SecretStr | None = None  # Slack incoming-webhook URL (embeds a token)
    # --- Backups module (7G-1). Nightly/manual Postgres snapshots via pg_dump, a
    # guarded restore via pg_restore, and an OPTIONAL Backblaze B2 offsite copy. ALL
    # optional and NOT in _REQUIRED_IN_PROD: the module builds + unit-tests NOW
    # (subprocess mocked) and ACTIVATES as each piece lands. Without a dump root /
    # pg_dump binary a run DEGRADES to a recorded 'failed' snapshot, never a crash. ---
    backup_artifact_dir: str | None = None  # controlled root snapshots are written under
    pg_dump_bin: str = "pg_dump"  # pg_dump binary (on PATH or an absolute path)
    pg_restore_bin: str = "pg_restore"  # pg_restore binary (the guarded restore)
    # Worker-owned hard timeout for one dump/restore (pg_dump never times out itself).
    backup_timeout_seconds: int = 1800
    # Backblaze B2 offsite (S3-compatible). KEY-GATED on the full triple: without all
    # of key_id + application_key + bucket the offsite sync degrades to None (the local
    # snapshot still succeeds). The login-style key_id is not a secret (mirrors the
    # DataForSEO login); the application_key is a SecretStr (never logged / in a repr).
    b2_key_id: str | None = None  # B2 application keyID (Basic-style id)
    b2_application_key: SecretStr | None = None  # B2 application key (secret)
    b2_bucket: str | None = None  # destination bucket name
    b2_endpoint_url: str | None = None  # optional S3 endpoint override (region host)

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
