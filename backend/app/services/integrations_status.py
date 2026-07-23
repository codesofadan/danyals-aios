"""Integration connectivity catalogue - the API-Management view's REAL status.

Reports, for every integration the platform supports, whether it is CONNECTED (from
the real env-backed ``Settings`` and the vault) or MISSING. This replaces the
dashboard's old hard-coded checkmark list: an env-configured provider (Serper,
Anthropic, Resend, ...) now shows connected because its key is ACTUALLY present, and
a per-client credential KIND (WordPress, GBP, ...) shows connected when at least one
such secret is sealed in the vault.

The CATALOGUE is static (the SET of providers the code can talk to is a fact about
the code); the STATUS is computed live, so nothing here is a hard-coded "connected".
``integration_statuses`` is a PURE function of ``(settings, vault_providers)`` so it
is trivially unit-testable; the router supplies the vault provider set from one
distinct-query. Presence uses plain truthiness: ``None``, ``""`` and an empty
``SecretStr`` all read as absent (an empty env var arrives as one of these), matching
``config.validate_settings`` and ``email_sender_from_settings``.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from app.config import Settings


class IntegrationStatus(BaseModel):
    """One integration's live connection verdict (frontend-rendered as-is)."""

    id: str
    name: str
    category: str
    connected: bool
    source: str  # "config" (env-backed) | "vault" (per-client sealed secret)
    detail: str  # short, non-secret reason / how to connect (never a secret value)


def _present(value: object) -> bool:
    """Truthiness that treats ``None`` / ``""`` / an empty ``SecretStr`` as absent."""
    return bool(value)


def integration_statuses(
    settings: Settings, vault_providers: Iterable[str] = ()
) -> list[IntegrationStatus]:
    """Every supported integration with a live connected/missing status.

    ``vault_providers`` is the set of provider slugs that have at least one sealed
    vault key (the per-client credential kinds); everything else is judged from the
    env-backed ``settings``. Pure - no I/O.
    """
    vault = {str(p) for p in vault_providers}

    def cfg(
        id_: str, name: str, category: str, present: bool, key_hint: str
    ) -> IntegrationStatus:
        return IntegrationStatus(
            id=id_,
            name=name,
            category=category,
            connected=present,
            source="config",
            detail=(f"{key_hint} configured" if present else f"Set {key_hint}"),
        )

    def vlt(id_: str, name: str, category: str) -> IntegrationStatus:
        present = id_ in vault
        return IntegrationStatus(
            id=id_,
            name=name,
            category=category,
            connected=present,
            source="vault",
            detail=("Sealed in the key vault" if present else "Add a key in the vault"),
        )

    return [
        # --- Rankings / SERP data ---
        cfg("serper", "Serper.dev", "Rankings",
            _present(settings.serper_api_key), "SERPER_API_KEY"),
        cfg("dataforseo", "DataForSEO", "Rankings",
            _present(settings.dataforseo_login) and _present(settings.dataforseo_password),
            "DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD"),
        # --- Google APIs (Search Console / GA4 OAuth client) ---
        cfg("google", "Google APIs", "Google APIs",
            _present(settings.google_oauth_client_id)
            and _present(settings.google_oauth_client_secret),
            "GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET"),
        # --- AI / Content ---
        cfg("anthropic", "Anthropic (Claude)", "AI / Content",
            _present(settings.anthropic_api_key), "ANTHROPIC_API_KEY"),
        cfg("imagegen", "Image Generation", "AI / Content",
            _present(settings.image_gen_api_key), "IMAGE_GEN_API_KEY"),
        cfg("voyage", "Voyage Embeddings", "AI / Content",
            _present(settings.embeddings_api_key), "EMBEDDINGS_API_KEY"),
        cfg("pinecone", "Pinecone", "AI / Content",
            _present(settings.pinecone_api_key) and _present(settings.pinecone_index),
            "PINECONE_API_KEY + PINECONE_INDEX"),
        # --- Sheets ---
        cfg("gsheets", "Google Sheets", "Sheets",
            _present(settings.google_sheets_sa_json), "GOOGLE_SHEETS_SA_JSON"),
        # --- Delivery (email / Slack) ---
        cfg("resend", "Resend (Email)", "Delivery",
            _present(settings.resend_api_key), "RESEND_API_KEY"),
        cfg("slack", "Slack", "Delivery",
            _present(settings.slack_webhook_url), "SLACK_WEBHOOK_URL"),
        # --- Off-page (citations / monitoring) ---
        cfg("foursquare", "Foursquare", "Off-page",
            _present(settings.foursquare_api_key), "FOURSQUARE_API_KEY"),
        cfg("bing_places", "Bing Places", "Off-page",
            _present(settings.bing_places_api_key), "BING_PLACES_API_KEY"),
        cfg("apify", "Apify", "Off-page",
            _present(settings.apify_api_token), "APIFY_API_TOKEN"),
        cfg("captcha", "CAPTCHA Solver", "Off-page",
            _present(settings.captcha_solver_api_key), "CAPTCHA_SOLVER_API_KEY"),
        cfg("brightlocal", "BrightLocal", "Off-page",
            _present(settings.brightlocal_api_key), "BRIGHTLOCAL_API_KEY"),
        # --- Backups (offsite) ---
        cfg("b2", "Backblaze B2", "Backups",
            _present(settings.b2_key_id)
            and _present(settings.b2_application_key)
            and _present(settings.b2_bucket),
            "B2_KEY_ID + B2_APPLICATION_KEY + B2_BUCKET"),
        # --- Publishing (per-site secrets live in the vault) ---
        vlt("wordpress", "WordPress", "Publishing"),
        # --- Per-client access collected at onboarding (vault-sealed) ---
        vlt("gbp", "Google Business Profile", "Client Access"),
        vlt("website_cms", "Website / CMS", "Client Access"),
        vlt("analytics", "Analytics", "Client Access"),
        vlt("search_console", "Search Console", "Client Access"),
    ]
