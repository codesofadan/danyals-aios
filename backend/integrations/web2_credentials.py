"""Web2 credential factory (7B-4): builds a per-client, per-platform
``Web2Publisher`` from a vault-sealed JSON blob, replacing the
``web2_publisher_from_settings`` stub that always returned ``None`` -- the gap
``web2_publishers.py`` itself used to flag as "a later chunk".

Convention: a Web 2.0 OAuth token / API key is ONE vault row per ACCOUNT:

* ``provider`` = ``f"web2:{platform}"`` (e.g. ``"web2:WordPress.com"``)
* ``label``    = the ``public.web2_accounts.id`` that owns the credential (R2-06).
  It was the CLIENT id until 0100/0101 landed, which is precisely the defect being
  retired: keying by client meant one shared house login was COPIED into every
  client's vault row, so a single suspension took every client's property down at
  once and the copies made the clients mutually identifiable. One account is now one
  credential, stored once. Properties written before the reconciliation
  (``app/cli/web2_migrate_house.py``) still carry a client-id label, so the CALLER
  passes the label rather than this factory guessing it.
* ``secret``   = a JSON object whose keys match
  ``web2_publishers.PLATFORM_CREDENTIAL_FIELDS[platform]`` (e.g. WordPress.com wants
  ``{"oauth_token": "...", "site": "clientblog.wordpress.com"}``)
* ``kind``     = ``"client_access"`` (a client's own login/token, exactly like the
  WordPress application passwords ``client_onboarding`` already stores this way --
  NOT an agency ``api_key`` row)

A missing row, malformed JSON, or an incomplete credential all degrade to ``None`` --
the publish stage HOLDS the placement at ``needs_review``, never crashes and never
half-publishes. This mirrors every other off-page seam's key-gating; a typo in a
vault entry must not take a worker down.
"""

from __future__ import annotations

import json
from typing import Any, Final, Protocol, cast

from app.logging_setup import get_logger
from integrations.errors import ProviderNotConfiguredError
from integrations.web2_publishers import (
    PLATFORM_BLOGGER,
    PLATFORM_BLUESKY,
    PLATFORM_CODEBERG_PAGES,
    PLATFORM_DEVTO,
    PLATFORM_DISQUS,
    PLATFORM_DPASTE,
    PLATFORM_DREAMWIDTH,
    PLATFORM_DRUPAL,
    PLATFORM_FC2,
    PLATFORM_FIGSHARE,
    PLATFORM_GHOST,
    PLATFORM_GITHUB_GIST,
    PLATFORM_GITHUB_PAGES,
    PLATFORM_GITLAB_PAGES,
    PLATFORM_GITLAB_SNIPPETS,
    PLATFORM_GRAVATAR,
    PLATFORM_HACKMD,
    PLATFORM_HASHNODE,
    PLATFORM_HATENA,
    PLATFORM_HUBSPOT,
    PLATFORM_HYGRAPH,
    PLATFORM_INTERNET_ARCHIVE,
    PLATFORM_JOOMLA,
    PLATFORM_LEMMY,
    PLATFORM_LIVEDOOR,
    PLATFORM_LIVEJOURNAL,
    PLATFORM_MASTODON,
    PLATFORM_MATAROA,
    PLATFORM_MICROBLOG,
    PLATFORM_MINDS,
    PLATFORM_MISSKEY,
    PLATFORM_NEOCITIES,
    PLATFORM_NETLIFY,
    PLATFORM_NOTION,
    PLATFORM_OSF,
    PLATFORM_PASTE_EE,
    PLATFORM_PASTEBIN,
    PLATFORM_PIXELFED,
    PLATFORM_PLURK,
    PLATFORM_RENTRY,
    PLATFORM_SANITY,
    PLATFORM_SEESAA,
    PLATFORM_SOURCEHUT_PAGES,
    PLATFORM_STORYBLOK,
    PLATFORM_TELEGRAPH,
    PLATFORM_TUMBLR,
    PLATFORM_WARPCAST,
    PLATFORM_WEBFLOW,
    PLATFORM_WHITEWIND,
    PLATFORM_WORDPRESS,
    PLATFORM_WRITEAS,
    PLATFORM_WRITEFREELY,
    PLATFORM_ZENODO,
    BloggerClient,
    BlueskyClient,
    CodebergPagesClient,
    DevToClient,
    DisqusClient,
    DpasteClient,
    DreamwidthClient,
    DrupalClient,
    FC2BlogClient,
    FigshareClient,
    GhostClient,
    GitHubGistClient,
    GitHubPagesClient,
    GitLabPagesClient,
    GitLabSnippetsClient,
    GravatarClient,
    HackMDClient,
    HashnodeClient,
    HatenaBlogClient,
    HubSpotClient,
    HygraphClient,
    InternetArchiveClient,
    JoomlaClient,
    LemmyClient,
    LivedoorBlogClient,
    LiveJournalClient,
    MastodonClient,
    MataroaClient,
    MicroBlogClient,
    MindsClient,
    MisskeyClient,
    NeocitiesClient,
    NetlifyClient,
    NotionClient,
    OSFClient,
    PastebinClient,
    PasteEeClient,
    PixelfedClient,
    PlurkClient,
    RentryClient,
    SanityClient,
    SeesaaBlogClient,
    SourcehutPagesClient,
    StoryblokClient,
    TelegraPhClient,
    TumblrClient,
    WarpcastClient,
    Web2Publisher,
    WebflowClient,
    WhiteWindClient,
    WordPressComClient,
    WriteAsClient,
    WriteFreelyEuClient,
    ZenodoClient,
)

logger = get_logger("integrations.web2_credentials")

# Final so the type narrows to Literal["client_access"] - app.services.vault.add_key
# takes a VaultKind literal, and a plain `str` here would force every caller to cast.
VAULT_KIND_CLIENT_ACCESS: Final = "client_access"


def vault_provider_for(platform: str) -> str:
    """The vault ``provider`` column value for a platform's per-client credential."""
    return f"web2:{platform}"


class SecretLookup(Protocol):
    """The one seam this factory needs: reveal a vault secret by ``(provider,
    label)``. Satisfied by ``app.services.vault.find_secret`` in production and a
    plain dict-backed fake in tests -- no DB, no encryption, on the test path."""

    def __call__(self, *, provider: str, label: str) -> str | None: ...


# Each builder takes the parsed credential dict and returns the real client. A
# missing/blank required field surfaces as THAT client's own
# ``ProviderNotConfiguredError`` (naming the exact fix), not a bare ``KeyError`` --
# every constructor already validates its own required fields (see
# web2_publishers.py), so these lambdas just map field names, they never guard.
_BUILDERS: dict[str, Any] = {
    PLATFORM_WORDPRESS: lambda c: WordPressComClient(
        oauth_token=c.get("oauth_token", ""), target=c.get("site", "")
    ),
    PLATFORM_BLOGGER: lambda c: BloggerClient(
        oauth_token=c.get("oauth_token", ""), target=c.get("blog_id", "")
    ),
    PLATFORM_TUMBLR: lambda c: TumblrClient(
        oauth_token=c.get("oauth_token", ""), target=c.get("blog", "")
    ),
    PLATFORM_DEVTO: lambda c: DevToClient(api_key=c.get("api_key", "")),
    PLATFORM_WRITEAS: lambda c: WriteAsClient(token=c.get("token", ""), target=c.get("alias", "")),
    PLATFORM_TELEGRAPH: lambda c: TelegraPhClient(access_token=c.get("access_token", "")),
    PLATFORM_MATAROA: lambda c: MataroaClient(api_key=c.get("api_key", "")),
    PLATFORM_GHOST: lambda c: GhostClient(
        admin_api_key=c.get("admin_api_key", ""), api_url=c.get("api_url", "")
    ),
    PLATFORM_MASTODON: lambda c: MastodonClient(
        oauth_token=c.get("access_token", ""), target=c.get("instance_url", "")
    ),
    PLATFORM_GITHUB_PAGES: lambda c: GitHubPagesClient(
        token=c.get("token", ""), owner=c.get("owner", ""), repo=c.get("repo", "")
    ),
    PLATFORM_GITLAB_PAGES: lambda c: GitLabPagesClient(
        token=c.get("token", ""), project_id=c.get("project_id", "")
    ),
    # Micro.blog's Micropub token is already scoped to one blog; `target` only needs
    # to satisfy the shared OAuth base-class guard (both fields non-empty).
    PLATFORM_MICROBLOG: lambda c: MicroBlogClient(oauth_token=c.get("token", ""), target="micro.blog"),
    PLATFORM_HASHNODE: lambda c: HashnodeClient(
        pat=c.get("pat", ""), publication_id=c.get("publication_id", "")
    ),
    PLATFORM_HATENA: lambda c: HatenaBlogClient(
        hatena_id=c.get("hatena_id", ""), blog_id=c.get("blog_id", ""), api_key=c.get("api_key", "")
    ),
    PLATFORM_LIVEJOURNAL: lambda c: LiveJournalClient(
        username=c.get("username", ""), password=c.get("password", "")
    ),
    PLATFORM_DREAMWIDTH: lambda c: DreamwidthClient(
        username=c.get("username", ""), password=c.get("password", "")
    ),
    PLATFORM_WEBFLOW: lambda c: WebflowClient(
        api_token=c.get("api_token", ""), collection_id=c.get("collection_id", ""),
        site=c.get("site", ""), url_path=c.get("url_path", "blog"),
    ),
    PLATFORM_HUBSPOT: lambda c: HubSpotClient(
        access_token=c.get("access_token", ""), content_group_id=c.get("content_group_id", ""),
    ),
    PLATFORM_DRUPAL: lambda c: DrupalClient(
        base_url=c.get("base_url", ""), username=c.get("username", ""),
        password=c.get("password", ""), content_type=c.get("content_type", "article"),
    ),
    PLATFORM_JOOMLA: lambda c: JoomlaClient(
        base_url=c.get("base_url", ""), api_token=c.get("api_token", ""), catid=c.get("catid", ""),
    ),
    PLATFORM_HACKMD: lambda c: HackMDClient(token=c.get("token", "")),
    PLATFORM_GITHUB_GIST: lambda c: GitHubGistClient(token=c.get("token", "")),
    PLATFORM_GITLAB_SNIPPETS: lambda c: GitLabSnippetsClient(token=c.get("token", "")),
    PLATFORM_PASTE_EE: lambda c: PasteEeClient(api_key=c.get("api_key", "")),
    PLATFORM_PASTEBIN: lambda c: PastebinClient(api_dev_key=c.get("api_dev_key", "")),
    PLATFORM_NETLIFY: lambda c: NetlifyClient(
        api_token=c.get("api_token", ""), site_id=c.get("site_id", "")
    ),
    PLATFORM_NEOCITIES: lambda c: NeocitiesClient(
        api_key=c.get("api_key", ""), sitename=c.get("sitename", "")
    ),
    # Anonymous - no credential fields are read from the vault row at all.
    PLATFORM_RENTRY: lambda _c: RentryClient(),
    PLATFORM_DPASTE: lambda _c: DpasteClient(),
    PLATFORM_MISSKEY: lambda c: MisskeyClient(
        token=c.get("token", ""), instance_url=c.get("instance_url") or "https://misskey.io"
    ),
    PLATFORM_LEMMY: lambda c: LemmyClient(
        username=c.get("username", ""), password=c.get("password", ""),
        community=c.get("community", ""), base_url=c.get("base_url") or "https://lemmy.world",
    ),
    PLATFORM_BLUESKY: lambda c: BlueskyClient(
        identifier=c.get("identifier", ""), app_password=c.get("app_password", "")
    ),
    PLATFORM_WHITEWIND: lambda c: WhiteWindClient(
        identifier=c.get("identifier", ""), app_password=c.get("app_password", "")
    ),
    PLATFORM_DISQUS: lambda c: DisqusClient(
        access_token=c.get("access_token", ""), api_key=c.get("api_key", ""), username=c.get("username", ""),
    ),
    PLATFORM_PLURK: lambda c: PlurkClient(
        consumer_key=c.get("consumer_key", ""), consumer_secret=c.get("consumer_secret", ""),
        access_token=c.get("access_token", ""), access_token_secret=c.get("access_token_secret", ""),
    ),
    PLATFORM_PIXELFED: lambda c: PixelfedClient(
        access_token=c.get("access_token", ""), placeholder_image_url=c.get("placeholder_image_url", ""),
        instance_url=c.get("instance_url") or "https://pixelfed.social",
    ),
    PLATFORM_NOTION: lambda c: NotionClient(
        integration_token=c.get("integration_token", ""), parent_page_id=c.get("parent_page_id", ""),
    ),
    PLATFORM_GRAVATAR: lambda c: GravatarClient(
        api_token=c.get("api_token", ""), username=c.get("username", "")
    ),
    PLATFORM_MINDS: lambda c: MindsClient(access_token=c.get("access_token", "")),
    PLATFORM_ZENODO: lambda c: ZenodoClient(
        access_token=c.get("access_token", ""), creator_name=c.get("creator_name", "")
    ),
    PLATFORM_INTERNET_ARCHIVE: lambda c: InternetArchiveClient(
        access_key=c.get("access_key", ""), secret_key=c.get("secret_key", ""),
        item_prefix=c.get("item_prefix", ""),
    ),
    PLATFORM_OSF: lambda c: OSFClient(access_token=c.get("access_token", "")),
    PLATFORM_FIGSHARE: lambda c: FigshareClient(access_token=c.get("access_token", "")),
    PLATFORM_CODEBERG_PAGES: lambda c: CodebergPagesClient(
        token=c.get("token", ""), owner=c.get("owner", ""), repo=c.get("repo", "")
    ),
    PLATFORM_LIVEDOOR: lambda c: LivedoorBlogClient(
        livedoor_id=c.get("livedoor_id", ""), blog_name=c.get("blog_name", ""), api_key=c.get("api_key", "")
    ),
    PLATFORM_FC2: lambda c: FC2BlogClient(
        blog_id=c.get("blog_id", ""), username=c.get("username", ""), password=c.get("password", "")
    ),
    PLATFORM_SEESAA: lambda c: SeesaaBlogClient(
        blog_id=c.get("blog_id", ""), username=c.get("username", ""), password=c.get("password", "")
    ),
    PLATFORM_WARPCAST: lambda c: WarpcastClient(
        api_key=c.get("api_key", ""), signer_uuid=c.get("signer_uuid", "")
    ),
    PLATFORM_SOURCEHUT_PAGES: lambda c: SourcehutPagesClient(
        token=c.get("token", ""), domain=c.get("domain", "")
    ),
    PLATFORM_SANITY: lambda c: SanityClient(
        api_token=c.get("api_token", ""), project_id=c.get("project_id", ""),
        dataset=c.get("dataset", ""), doc_type=c.get("doc_type") or "post",
    ),
    PLATFORM_STORYBLOK: lambda c: StoryblokClient(
        token=c.get("token", ""), space_id=c.get("space_id", ""),
        component=c.get("component") or "page",
    ),
    PLATFORM_HYGRAPH: lambda c: HygraphClient(
        endpoint=c.get("endpoint", ""), token=c.get("token", ""), model=c.get("model") or "post",
    ),
    PLATFORM_WRITEFREELY: lambda c: WriteFreelyEuClient(
        instance_url=c.get("instance_url", ""), token=c.get("token", ""), target=c.get("target", ""),
    ),
}


def build_publisher(*, vault_label: str, platform: str, lookup: SecretLookup) -> Web2Publisher | None:
    """Build the real ``Web2Publisher`` for the credential stored at ``(web2:<platform>,
    vault_label)``, or ``None`` when there is no usable credential (the caller HOLDS the
    placement at review, exactly as if the platform were entirely unconfigured). Medium
    (and any platform with no registered builder) always returns ``None`` -- draft-only
    platforms have no live publisher to build.

    ``vault_label`` is passed in rather than derived, because WHICH account a placement
    publishes through is a fact about the placement, not something this factory can
    infer. It is a ``web2_accounts.id`` for a property attributed to an account, and a
    legacy ``client_id`` for a property that predates the accounts table (R2-06). Both
    are opaque ids, safe to log; neither is a secret."""
    builder = _BUILDERS.get(platform)
    if builder is None:
        return None
    raw = lookup(provider=vault_provider_for(platform), label=vault_label)
    if raw is None:
        logger.info("web2_credential_missing", vault_label=vault_label, platform=platform)
        return None
    try:
        creds = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("web2_credential_malformed", vault_label=vault_label, platform=platform)
        return None
    if not isinstance(creds, dict):
        logger.warning("web2_credential_malformed", vault_label=vault_label, platform=platform)
        return None
    try:
        # _BUILDERS is dict[str, Any] (the lambdas construct many unrelated client
        # classes), so the call itself is untyped -- cast to the declared return type
        # rather than let `Any` silently widen the function's real contract.
        return cast("Web2Publisher | None", builder(creds))
    except ProviderNotConfiguredError:
        logger.warning("web2_credential_incomplete", vault_label=vault_label, platform=platform)
        return None
