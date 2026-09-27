"""The per-platform CONTENT MODEL - what each platform will actually accept.

``M05`` REQ-W2-006: every post is produced in a **platform-shaped variant**. This module
is the missing half of that requirement. Until it existed, the pipeline drafted one
~900-word HTML blog article and handed the identical bytes to every adapter, and the
adapters coped in whatever way they could.

THE DEFECT THAT MAKES THIS CONCRETE, read off the adapters rather than argued::

    MastodonClient._MAX_CHARS = 500     text[: self._MAX_CHARS]
    BlueskyClient._MAX_CHARS  = 300     text[: self._MAX_CHARS]
    WarpcastClient._MAX_CHARS = 320     text[: self._MAX_CHARS]
    PlurkClient                         content[:360]

A 900-word article is ~5,500 characters. Publishing it to Bluesky does not produce a
short post - it produces the first 300 characters of a blog article, cut mid-sentence,
with the editorial backlink the property exists to carry **sliced off the end**. The
placement then reports `verified` because the API returned a URL. Nobody was lying; the
content model simply was not written down anywhere the drafting stage could read it.

Twenty-one adapters also run ``_html_to_text`` over the body, so every heading, list and
link formatting the generator produced is discarded at publish time - work paid for by
the token and thrown away.

WHERE THESE FACTS COME FROM. Each :class:`PlatformSpec` carries an ``evidence`` string
naming the adapter behaviour it was derived from. That is deliberate: this repo has been
burned by reference tables that drifted from the code they described (0135's header says
so at length), and a spec whose provenance is "somebody wrote it down once" is a spec
nobody can re-check. An adapter that changes and a spec that does not now disagree
VISIBLY, because ``tests/test_web2_platform_spec.py`` re-derives the truncation facts
from the adapter source and fails when they diverge.

WHAT IS DELIBERATELY NOT HERE. Nothing is guessed. A platform whose adapter reveals no
limit gets ``max_body_chars=None`` ("no measured limit"), not an invented number, and
:data:`UNKNOWN_SPEC` is what an uncatalogued platform gets - a spec that promises nothing
and lets the writer produce a plain, self-contained article. A safe default is not a
judgement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

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
)
from integrations.web2_publishers import (
    UNSUPPORTED_PLATFORMS as _UNSUPPORTED,
)

#: How an adapter hands the body to the platform. Decides what the writer may USE:
#: markup that gets stripped at publish time is work paid for and discarded.
BodyFormat = Literal["html", "markdown", "text"]

#: The shape a placement takes on this platform. Not cosmetic - it decides the word
#: budget, whether headings exist, and how the editorial link is carried.
PostShape = Literal["article", "note", "snippet", "profile"]

#: Average characters per word in this generator's English output, used to convert a
#: platform's character ceiling into the word budget the writer is actually given.
#: 6.1 rather than the textbook 5.1: the generator writes business prose with long
#: service nouns ("emergency drain unblocking"), and a ceiling that assumes short words
#: produces a draft that still gets truncated - which is the whole failure being fixed.
CHARS_PER_WORD: Final = 6.1

#: A note-shaped placement must leave room for the link that justifies it. Reserved from
#: the character ceiling BEFORE the word budget is derived, because the adapters append
#: `anchor: url` AFTER the body and then truncate the whole string - so a body sized to
#: the full ceiling loses exactly the backlink the property exists to carry.
LINK_RESERVE_CHARS: Final = 120


@dataclass(frozen=True)
class PlatformSpec:
    """What one platform accepts, and the adapter behaviour that proves it."""

    platform: str
    shape: PostShape
    body_format: BodyFormat
    #: The platform's hard character ceiling on the body, or None when the adapter
    #: reveals none. NEVER a guess - see the module header.
    max_body_chars: int | None = None
    supports_title: bool = True
    supports_headings: bool = True
    supports_tags: bool = False
    max_tags: int = 0
    supports_slug: bool = False
    supports_images: bool = False
    images_required: bool = False
    supports_meta_description: bool = False
    supports_canonical: bool = False
    #: How the editorial backlink reaches the page. ``inline`` = a real anchor inside the
    #: prose; ``trailing`` = the adapter appends ``anchor: url`` after a plain-text body,
    #: so an inline markdown link would be shown as literal syntax.
    link_style: Literal["inline", "trailing"] = "inline"
    evidence: str = ""

    @property
    def word_target(self) -> int:
        """How many words the writer should actually produce for this platform.

        Derived from the measured ceiling, minus the link reserve, at this generator's
        real character-per-word rate. With no measured ceiling this is the module's
        article target - a branded authority post, not a pillar page.
        """
        if self.max_body_chars is None:
            return ARTICLE_WORD_TARGET
        usable = max(self.max_body_chars - LINK_RESERVE_CHARS, 40)
        # NO MINIMUM-WORD FLOOR. An earlier version floored this at 20 words, which
        # silently broke the one guarantee the budget exists to provide: Gravatar's
        # 200-character ceiling leaves 80 usable characters, and 20 words is ~122 - so
        # the "safe" target overran the platform by half again and the link was truncated
        # away exactly as before. A floor that can exceed its own budget is not a floor,
        # it is a second bug wearing the first one's clothes. A tiny ceiling honestly
        # yields a tiny target; 1 is the only floor that can never overrun.
        return max(int(usable / CHARS_PER_WORD), 1)

    @property
    def truncates(self) -> bool:
        """Whether this platform will CUT a body that overruns, rather than reject it.

        The dangerous case, and the reason the word target above is load-bearing: a
        rejection is a visible failure, a truncation is a published page that looks fine
        in the ledger and is cut mid-sentence on the web.
        """
        return self.max_body_chars is not None

    @property
    def strips_markup(self) -> bool:
        """Whether markup the generator produces is discarded before publication."""
        return self.body_format == "text"

    def describe(self) -> str:
        """The constraint note the drafting stage writes against.

        Deterministic and network-free: this is what the shaping node falls back to with
        no router configured, and what it hands the model as ground truth when there is
        one. It states only what this spec actually knows.
        """
        parts: list[str] = [_SHAPE_NOTES[self.shape]]
        if self.max_body_chars is not None:
            parts.append(
                f"HARD LIMIT {self.max_body_chars} characters - the platform TRUNCATES "
                f"anything longer, so write at most about {self.word_target} words"
            )
        else:
            parts.append(f"aim for about {self.word_target} words")
        if self.body_format == "markdown":
            parts.append("the body is Markdown")
        elif self.body_format == "text":
            parts.append(
                "the body is rendered to PLAIN TEXT before publishing: headings, lists "
                "and inline links are stripped, so do not use them"
            )
        else:
            parts.append("the body is HTML rendered from Markdown")
        parts.append(
            "headings are kept" if self.supports_headings else "there are no headings"
        )
        if self.supports_tags:
            parts.append(f"up to {self.max_tags} topical tags are supported")
        if self.images_required:
            parts.append("an image is REQUIRED for a post to publish at all")
        elif self.supports_images:
            parts.append("images are supported")
        if self.link_style == "trailing":
            parts.append(
                "the editorial link is appended after the body as 'anchor: url', so do "
                "NOT write it inline - leave the closing sentence to lead into it"
            )
        return "; ".join(parts) + "."


_SHAPE_NOTES: Final[dict[PostShape, str]] = {
    "article": "a full article on a blog-shaped platform",
    "note": "a SHORT social note, not an article - one idea, conversational, no headings",
    "snippet": "a plain-text document on a paste/snippet host - no formatting survives",
    "profile": "a short profile or comment placement, not an article",
}

#: A branded authority post on a platform with no measured ceiling. Unchanged from the
#: figure `web2_pipeline` has always used, imported by both so they cannot drift.
ARTICLE_WORD_TARGET: Final = 900


def _article(platform: str, *, evidence: str, **kw: object) -> PlatformSpec:
    return PlatformSpec(platform=platform, shape="article", body_format="html",
                        evidence=evidence, **kw)  # type: ignore[arg-type]


def _note(platform: str, *, max_chars: int, evidence: str, **kw: object) -> PlatformSpec:
    return PlatformSpec(
        platform=platform, shape="note", body_format="text", max_body_chars=max_chars,
        supports_headings=False, link_style="trailing", evidence=evidence, **kw,  # type: ignore[arg-type]
    )


def _snippet(platform: str, *, evidence: str, **kw: object) -> PlatformSpec:
    return PlatformSpec(
        platform=platform, shape="snippet", body_format="text", supports_headings=False,
        link_style="trailing", evidence=evidence, **kw,  # type: ignore[arg-type]
    )


#: Every spec, keyed by the platform constant. Derived from adapter behaviour; each
#: entry cites the line of reasoning that produced it.
PLATFORM_SPECS: Final[dict[str, PlatformSpec]] = {
    # --- full blog platforms: HTML body, title, no measured ceiling ----------------
    PLATFORM_WORDPRESS: _article(
        PLATFORM_WORDPRESS, supports_tags=True, max_tags=10, supports_slug=True,
        supports_images=True, supports_meta_description=True, supports_canonical=False,
        evidence=(
            "WordPressComClient sends title/content/slug/tags plus `excerpt` (REST v1.1 "
            "has no meta-description field; excerpt is what themes and feeds render). "
            "No canonical field exists on the endpoint, so none is claimed"
        ),
    ),
    PLATFORM_BLOGGER: _article(
        PLATFORM_BLOGGER, supports_tags=True, max_tags=20, supports_images=True,
        evidence="BloggerClient sends title/content/labels to Blogger v3; no truncation",
    ),
    PLATFORM_TUMBLR: _article(
        PLATFORM_TUMBLR, supports_tags=True, max_tags=20, supports_images=True,
        evidence="TumblrClient posts type=text with title/body/tags; no truncation",
    ),
    PLATFORM_GHOST: _article(
        PLATFORM_GHOST, supports_images=True, supports_meta_description=True,
        supports_canonical=True, supports_slug=True, supports_tags=True, max_tags=10,
        evidence=(
            "GhostClient posts title/html plus the Admin API's meta_description, "
            "canonical_url, feature_image(+alt), slug and tags; no truncation"
        ),
    ),
    PLATFORM_MATAROA: _article(
        PLATFORM_MATAROA, supports_slug=True,
        evidence="MataroaClient sends title/body/slug; no truncation",
    ),
    PLATFORM_WRITEAS: _article(
        PLATFORM_WRITEAS, supports_slug=True,
        evidence="WriteAsClient sends title/body/slug; no truncation",
    ),
    PLATFORM_WRITEFREELY: _article(
        PLATFORM_WRITEFREELY, supports_slug=True,
        evidence="WriteFreelyEuClient sends title/body/slug; no truncation",
    ),
    PLATFORM_WEBFLOW: _article(
        PLATFORM_WEBFLOW, supports_slug=True, supports_images=True,
        evidence="WebflowClient writes a CMS item with title/body/slug",
    ),
    PLATFORM_HUBSPOT: _article(
        PLATFORM_HUBSPOT, supports_slug=True, supports_meta_description=False,
        evidence=(
            "HubSpotClient writes a blog post with title/body/slug; its API exposes a meta description but the adapter does not send one "
            "yet, so the spec does not claim it - a claimed field nobody transmits is a "
            "metered model call producing a string nothing reads"
        ),
    ),
    PLATFORM_DRUPAL: _article(
        PLATFORM_DRUPAL, evidence="DrupalClient posts a node with title/body",
    ),
    PLATFORM_JOOMLA: _article(
        PLATFORM_JOOMLA, supports_slug=True,
        evidence="JoomlaClient posts an article with title/articletext/alias",
    ),
    PLATFORM_LIVEJOURNAL: _article(
        PLATFORM_LIVEJOURNAL,
        evidence="_LJProtocolClient posts plain-ish HTML over XML-RPC; no ceiling",
    ),
    PLATFORM_DREAMWIDTH: _article(
        PLATFORM_DREAMWIDTH,
        evidence="_LJProtocolClient (shared) over XML-RPC; no ceiling",
    ),
    PLATFORM_HATENA: _article(
        PLATFORM_HATENA, evidence="HatenaBlogClient posts an AtomPub entry",
    ),
    PLATFORM_LIVEDOOR: _article(
        PLATFORM_LIVEDOOR, evidence="_MetaWeblogClient posts title/description",
    ),
    PLATFORM_FC2: _article(
        PLATFORM_FC2, evidence="_MetaWeblogClient posts title/description",
    ),
    PLATFORM_SEESAA: _article(
        PLATFORM_SEESAA, evidence="_MetaWeblogClient posts title/description",
    ),
    PLATFORM_TELEGRAPH: PlatformSpec(
        platform=PLATFORM_TELEGRAPH, shape="article", body_format="html",
        supports_slug=False,
        evidence="TelegraPhClient caps only the TITLE (_MAX_TITLE=256); body is a node array",
    ),
    # --- markdown-native developer publishing --------------------------------------
    PLATFORM_DEVTO: PlatformSpec(
        platform=PLATFORM_DEVTO, shape="article", body_format="markdown",
        supports_tags=True, max_tags=4, supports_canonical=True,
        supports_meta_description=True, supports_images=True,
        evidence=(
            "DevToClient sends body_markdown, slices tags to _MAX_TAGS=4, and sends the "
            "Articles API's description / canonical_url / main_image fields"
        ),
    ),
    PLATFORM_HASHNODE: PlatformSpec(
        platform=PLATFORM_HASHNODE, shape="article", body_format="markdown",
        supports_slug=True, supports_canonical=False,
        evidence=(
            "HashnodeClient sends contentMarkdown + slug and DELIBERATELY omits "
            "originalArticleURL: its canonical field would declare the property a "
            "duplicate of the client's page and void the editorial link (see its comment)"
        ),
    ),
    PLATFORM_HACKMD: PlatformSpec(
        platform=PLATFORM_HACKMD, shape="article", body_format="markdown",
        supports_headings=True,
        evidence="HackMDClient posts a markdown note",
    ),
    # --- microblog / social notes: THE TRUNCATING SET ------------------------------
    PLATFORM_MASTODON: _note(
        PLATFORM_MASTODON, max_chars=500,
        evidence="MastodonClient._MAX_CHARS=500 and text[:_MAX_CHARS] after _html_to_text",
    ),
    PLATFORM_BLUESKY: _note(
        PLATFORM_BLUESKY, max_chars=300,
        evidence="BlueskyClient._MAX_CHARS=300 and text[:_MAX_CHARS] after _html_to_text",
    ),
    PLATFORM_WARPCAST: _note(
        PLATFORM_WARPCAST, max_chars=320,
        evidence="WarpcastClient._MAX_CHARS=320 and text[:_MAX_CHARS] after _html_to_text",
    ),
    PLATFORM_MISSKEY: _note(
        PLATFORM_MISSKEY, max_chars=3000,
        evidence="MisskeyClient._MAX_CHARS=3000 and text[:_MAX_CHARS] after _html_to_text",
    ),
    PLATFORM_PLURK: _note(
        PLATFORM_PLURK, max_chars=360,
        evidence="PlurkClient builds content[:360] from title + _html_to_text(body)[:200]",
    ),
    PLATFORM_PIXELFED: _note(
        PLATFORM_PIXELFED, max_chars=500, supports_images=True, images_required=True,
        evidence="PixelfedClient._MAX_CHARS=500; Pixelfed posts are image-mandatory (0135 media_support)",
    ),
    PLATFORM_MINDS: _note(
        PLATFORM_MINDS, max_chars=1500,
        evidence="MindsClient renders _html_to_text into an activity message",
    ),
    PLATFORM_LEMMY: _note(
        PLATFORM_LEMMY, max_chars=10000, supports_title=True,
        evidence="LemmyClient posts a title + plain-text body to a community",
    ),
    PLATFORM_WHITEWIND: PlatformSpec(
        platform=PLATFORM_WHITEWIND, shape="article", body_format="markdown",
        link_style="trailing",
        evidence="WhiteWindClient writes a markdown blog entry over AT Protocol",
    ),
    # --- paste / snippet hosts: plain text, nothing survives -----------------------
    PLATFORM_PASTEBIN: _snippet(
        PLATFORM_PASTEBIN, evidence="PastebinClient posts api_paste_code as plain text",
    ),
    PLATFORM_PASTE_EE: _snippet(
        PLATFORM_PASTE_EE, evidence="PasteEeClient posts a plain-text section",
    ),
    PLATFORM_DPASTE: _snippet(
        PLATFORM_DPASTE, evidence="DpasteClient posts plain-text content",
    ),
    PLATFORM_RENTRY: _snippet(
        PLATFORM_RENTRY, evidence="RentryClient posts plain-text markdown",
    ),
    PLATFORM_GITHUB_GIST: _snippet(
        PLATFORM_GITHUB_GIST, supports_slug=True,
        evidence="GitHubGistClient writes a plain-text file into a gist",
    ),
    PLATFORM_GITLAB_SNIPPETS: _snippet(
        PLATFORM_GITLAB_SNIPPETS, supports_slug=True,
        evidence="GitLabSnippetsClient writes a plain-text snippet file",
    ),
    # --- static site hosts: full HTML pages we render ourselves --------------------
    PLATFORM_GITHUB_PAGES: _article(
        PLATFORM_GITHUB_PAGES, supports_slug=True, supports_images=True,
        supports_meta_description=True, supports_canonical=True,
        evidence="GitHubPagesClient commits a full static HTML file we control end to end",
    ),
    PLATFORM_GITLAB_PAGES: _article(
        PLATFORM_GITLAB_PAGES, supports_slug=True, supports_images=True,
        supports_meta_description=True, supports_canonical=True,
        evidence="GitLabPagesClient commits a full static HTML file",
    ),
    PLATFORM_CODEBERG_PAGES: _article(
        PLATFORM_CODEBERG_PAGES, supports_slug=True, supports_images=True,
        supports_meta_description=True, supports_canonical=True,
        evidence="CodebergPagesClient commits a full static HTML file",
    ),
    PLATFORM_SOURCEHUT_PAGES: _article(
        PLATFORM_SOURCEHUT_PAGES, supports_slug=True, supports_images=True,
        supports_meta_description=True, supports_canonical=True,
        evidence="SourcehutPagesClient uploads a static site bundle",
    ),
    PLATFORM_NETLIFY: _article(
        PLATFORM_NETLIFY, supports_slug=True, supports_images=True,
        supports_meta_description=True, supports_canonical=True,
        evidence="NetlifyClient deploys a static file we render",
    ),
    PLATFORM_NEOCITIES: _article(
        PLATFORM_NEOCITIES, supports_slug=True, supports_images=True,
        supports_meta_description=True, supports_canonical=True,
        evidence="NeocitiesClient uploads a static HTML page",
    ),
    PLATFORM_MICROBLOG: _article(
        PLATFORM_MICROBLOG, supports_tags=True, max_tags=5,
        evidence="MicroBlogClient posts title/content/categories over Micropub",
    ),
    # --- headless CMS: structured entries, no public page we can fetch -------------
    PLATFORM_SANITY: _article(
        PLATFORM_SANITY, supports_slug=True,
        evidence="SanityClient writes a document with a slug; 0135 link_verifiable=false",
    ),
    PLATFORM_STORYBLOK: _article(
        PLATFORM_STORYBLOK, supports_slug=True,
        evidence="StoryblokClient writes a story with a slug; 0135 link_verifiable=false",
    ),
    PLATFORM_HYGRAPH: _article(
        PLATFORM_HYGRAPH, supports_slug=True,
        evidence="HygraphClient writes an entry with a slug; 0135 link_verifiable=false",
    ),
    PLATFORM_NOTION: PlatformSpec(
        platform=PLATFORM_NOTION, shape="article", body_format="text",
        supports_headings=False, link_style="trailing", max_body_chars=2000,
        evidence="NotionClient chunks rich_text at chunk[:2000] per paragraph block",
    ),
    # --- research / archive hosts --------------------------------------------------
    PLATFORM_ZENODO: _article(
        PLATFORM_ZENODO,
        evidence="ZenodoClient creates a deposition with a description body",
    ),
    PLATFORM_FIGSHARE: PlatformSpec(
        platform=PLATFORM_FIGSHARE, shape="article", body_format="text",
        supports_headings=False, max_body_chars=1000, link_style="trailing",
        evidence="FigshareClient sends description[:1000]",
    ),
    PLATFORM_OSF: PlatformSpec(
        platform=PLATFORM_OSF, shape="article", body_format="text",
        supports_headings=False, max_body_chars=1000, link_style="trailing",
        evidence="OSFClient sends description[:1000] after _html_to_text",
    ),
    PLATFORM_INTERNET_ARCHIVE: _article(
        PLATFORM_INTERNET_ARCHIVE, supports_slug=True,
        evidence="InternetArchiveClient uploads an item with a title/identifier",
    ),
    # --- thin profile / comment placements -----------------------------------------
    PLATFORM_DISQUS: PlatformSpec(
        platform=PLATFORM_DISQUS, shape="profile", body_format="text",
        supports_headings=False, max_body_chars=255, link_style="trailing",
        evidence="DisqusClient builds about=f'{title} - {anchor}'[:255]; the BODY is never sent",
    ),
    PLATFORM_GRAVATAR: PlatformSpec(
        platform=PLATFORM_GRAVATAR, shape="profile", body_format="text",
        supports_headings=False, max_body_chars=200, link_style="trailing",
        evidence="GravatarClient sends description=f'{title}: {anchor}'[:200]; the BODY is never sent",
    ),
}

#: What an uncatalogued platform gets. Promises nothing, guesses nothing - the writer
#: produces a plain, self-contained article and assumes no platform conventions.
UNKNOWN_SPEC: Final = PlatformSpec(
    platform="", shape="article", body_format="html",
    evidence="no adapter-derived spec: nothing is known about this platform",
)

#: Platforms with no publishing path at all (M05 REQ-W2-002 / A12).
#:
#: IMPORTED rather than redeclared. The publish path refuses these in
#: ``web2_pipeline.run_publish`` and this module refuses to shape content for them, and
#: two modules each holding their own idea of "unsupported" is how one of them ends up
#: drafting for a platform the other will not publish to.
UNSUPPORTED_PLATFORMS: Final[frozenset[str]] = _UNSUPPORTED


class PlatformUnsupported(ValueError):  # noqa: N818 - a routing verdict, not a fault
    """This platform must not be published to at all (``M05`` REQ-W2-002 / A12)."""


def spec_for(platform: str, *, strict: bool = False) -> PlatformSpec:
    """The content model for ``platform``.

    ``strict`` raises :class:`PlatformUnsupported` for a platform M05 rules out, and is
    what the publishing path passes; the drafting path leaves it False so an operator can
    still see what a placement WOULD look like without the pipeline refusing to render a
    preview.

    An unknown platform returns :data:`UNKNOWN_SPEC` rather than raising: the catalogue
    grows faster than this table, and refusing to draft for a platform whose adapter
    works would be a worse failure than drafting a plain article for it.
    """
    if strict and platform in UNSUPPORTED_PLATFORMS:
        raise PlatformUnsupported(
            f"{platform} has no supported publishing path (M05 REQ-W2-002: official "
            "APIs only, and this platform's was withdrawn)"
        )
    return PLATFORM_SPECS.get(platform, UNKNOWN_SPEC)


def word_target_for(platform: str) -> int:
    """How many words to draft for ``platform``. The one number the writer needs."""
    return spec_for(platform).word_target


def truncating_platforms() -> dict[str, int]:
    """Every platform that CUTS an overlong body, and where it cuts.

    Exposed for the report an operator can act on: these are the placements where a
    draft sized for a blog becomes a sentence fragment with the backlink sliced off.
    """
    return {
        name: spec.max_body_chars
        for name, spec in sorted(PLATFORM_SPECS.items())
        if spec.max_body_chars is not None
    }
