"""Unit gate for SEO PARITY across the three WordPress transports.

HOW THE DEFECT WAS FOUND: reading ``workers.tasks.content._plugin_payload`` beside
``integrations.wordpress.PostDraft``. The plugin payload assembled a meta title, meta
description, focus keyword, post tags, a featured image and a JSON-LD graph; the
dataclass both other transports publish through carried five fields - title, content,
status, slug, wp_post_id. Nothing reconciled the two and nothing reported the gap, so a
client whose ``wp_connections`` row says ``app_password`` or ``xmlrpc`` received a bare
HTML post with none of its SEO metadata, and no operator could learn it had happened.

Everything here runs offline: the REST client's ``request_json`` and the XML-RPC
client's httpx transport are replaced with scripted recorders, so the WordPress
behaviours being asserted (term ids, ``_envelope``, silently-dropped meta, protected
meta) are reproduced rather than reached over the network.
"""

from __future__ import annotations

import xmlrpc.client
from typing import Any

import pytest

from app.config import Settings
from integrations.wordpress import (
    PostDraft,
    PublishResult,
    SeoFields,
    WordPressClient,
    XmlRpcWordPressPublisher,
    seo_meta,
)
from workers.tasks.content import WpTarget, publish_content_job

pytestmark = pytest.mark.unit

_YOAST_TITLE = "_yoast_wpseo_title"
_RANK_MATH_TITLE = "rank_math_title"


class FakeContentStore:
    """In-memory ``ContentStore`` keyed by ``code`` (mirrors the privileged repo)."""

    def __init__(self, row: dict[str, Any]) -> None:
        self.row = dict(row)

    def load(self, code: str) -> dict[str, Any] | None:
        return dict(self.row) if self.row.get("code") == code else None

    def update(self, code: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        self.row.update(fields)
        return dict(self.row)


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


def _publish_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": "CJ-7100",
        "client_id": None,  # skip the deliverable/email legs - hermetic
        "client_name": "Verde Cafe",
        "page_type": "blog",
        "topic": "best brunch in portland",
        "target": "WordPress",
        "status": "publishing",
        "draft_md": "# Best Brunch in Portland\n\n![Hero](https://img.test/hero.png)\n\nBody copy.\n",
        "qa_score": {"passed": True, "blocked_by": [], "weighted_total": 91},
        "wp_post_id": None,
        "outline": {
            "meta": {"title": "Best Brunch in Portland (2026)", "description": "The definitive guide."}
        },
        "keyword_map": {"primary": "best brunch in portland", "secondary": ["brunch spots"]},
        "json_ld": {"@graph": [{"@type": "Article"}]},
    }
    row.update(over)
    return row


class _DraftRecorder:
    """A ``WordPressPublisher`` that records the ``PostDraft`` it was handed.

    A publish that dropped every SEO field and one that carried them all return the
    identical ``PublishResult``, so the draft itself is the only evidence.
    """

    def __init__(self, dropped: tuple[str, ...] = ()) -> None:
        self.drafts: list[PostDraft] = []
        self._dropped = dropped

    def publish(self, site_url: str, post: PostDraft) -> PublishResult:
        self.drafts.append(post)
        return PublishResult(post_id=8801, url=f"{site_url}/{post.slug}", dropped=self._dropped)


def _wp(publisher: Any, site_url: str = "https://verde.example") -> Any:
    return lambda row, settings: WpTarget(site_url=site_url, publisher=publisher)


def _no_plugin(row: dict[str, Any], settings: Settings) -> None:
    return None


def _publish_through(publisher: Any, row: dict[str, Any] | None = None) -> FakeContentStore:
    store = FakeContentStore(row or _publish_row())
    publish_content_job(
        store, None, "CJ-7100",
        settings=_settings(), resolve_wp_plugin=_no_plugin, resolve_wp=_wp(publisher),
    )
    return store


# --------------------------------------------------------------------------- #
# 1. The worker fills the draft - the REST/XML-RPC path is no longer SEO-blind.
# --------------------------------------------------------------------------- #
def test_rest_path_no_longer_publishes_a_post_stripped_of_all_seo_metadata() -> None:
    """The core defect: ``_publish_via_rest`` built a five-field ``PostDraft``, so the
    meta title, meta description, focus keyword and tags that ``_plugin_payload``
    assembles never reached a client on ``app_password``/``xmlrpc``.

    Found by diffing the two payload builders (see the module docstring). Asserting on
    the DRAFT, not the result, is what makes this non-vacuous - the old code returned
    exactly the same PublishResult.
    """
    recorder = _DraftRecorder()
    _publish_through(recorder)

    draft = recorder.drafts[0]
    assert draft.seo is not None
    assert draft.seo.meta_title == "Best Brunch in Portland (2026)"
    assert draft.seo.meta_description == "The definitive guide."
    assert draft.seo.focus_keyword == "best brunch in portland"
    assert draft.seo.tags == ("best brunch in portland", "brunch spots")
    assert draft.seo.featured_image_url == "https://img.test/hero.png"
    assert "@graph" in draft.seo.schema_jsonld


def test_excerpt_is_filled_instead_of_being_a_field_no_caller_ever_set() -> None:
    """``PostDraft.excerpt`` existed and BOTH transports already sent it; no caller had
    ever passed one, so the branch was dead. Found while checking which existing fields
    were already wired before adding new ones."""
    recorder = _DraftRecorder()
    _publish_through(recorder)
    assert recorder.drafts[0].excerpt == "The definitive guide."


def test_both_transports_build_seo_from_one_source_so_they_cannot_drift() -> None:
    """The plugin payload and the REST draft must agree field for field. The original
    defect was not a missing feature but a SECOND, silent copy of the truth: the SEO
    derivation lived inside ``_plugin_payload`` where only one of three transports could
    reach it. Re-inlining it in either place and editing one copy fails this."""
    from workers.tasks.content import _plugin_payload

    row = _publish_row()
    recorder = _DraftRecorder()
    _publish_through(recorder, row)
    plugin = _plugin_payload(row, str(row["draft_md"]), "Best Brunch in Portland")
    seo = recorder.drafts[0].seo
    assert seo is not None

    assert plugin["meta_title"] == seo.meta_title
    assert plugin["meta_description"] == seo.meta_description
    assert plugin["focus_keyword"] == seo.focus_keyword
    assert plugin["tags"] == list(seo.tags)
    assert plugin["featured_image_url"] == seo.featured_image_url
    assert plugin["schema_jsonld"] == seo.schema_jsonld


def test_dropped_seo_fields_are_named_on_the_stage_the_operator_reads() -> None:
    """A transport that cannot carry a field must SAY so. The publish still succeeds -
    the post is live - so nothing in the status tells an operator their client got less;
    only a named note on the wire-visible ``stage`` can."""
    recorder = _DraftRecorder(dropped=("featured image (the REST API takes a media id)",))
    store = _publish_through(recorder)
    assert "featured image" in store.row["stage"]
    assert store.row["status"] == "done"  # a partial carry is NOT a failed publish


def test_a_full_parity_push_adds_no_note_to_the_stage() -> None:
    """The note must be evidence, not decoration: a transport that dropped nothing
    leaves the stage label byte-identical to what the dashboard already renders."""
    store = _publish_through(_DraftRecorder())
    assert store.row["stage"] == "Draft on WordPress: https://verde.example/best-brunch-in-portland"


# --------------------------------------------------------------------------- #
# 2. The REST client: what WordPress actually accepts, and what it silently drops.
# --------------------------------------------------------------------------- #
class _RestSpy(WordPressClient):
    """A ``WordPressClient`` whose ``request_json`` is scripted, reproducing the WP
    behaviours that matter: ``/wp/v2/tags`` answering an ARRAY under ``_envelope``, a
    403 on term creation (an author-level application password), and a post response
    that echoes back ONLY the meta keys a plugin registered with ``show_in_rest``."""

    def __init__(
        self,
        *,
        existing_tags: dict[str, int] | None = None,
        can_create_terms: bool = True,
        registered_meta: tuple[str, ...] = (),
    ) -> None:
        super().__init__(username="editor", app_password="pw")
        self.existing_tags = {k.lower(): v for k, v in (existing_tags or {}).items()}
        self.can_create_terms = can_create_terms
        self.registered_meta = registered_meta
        self.post_body: dict[str, Any] = {}
        self.next_term_id = 900

    def request_json(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        auth: tuple[str, str] | None = None,
    ) -> dict[str, Any]:
        if url.endswith("/wp/v2/tags"):
            assert (params or {}).get("_envelope") == 1  # the array route needs the envelope
            if method == "GET":
                name = str((params or {}).get("search") or "")
                term_id = self.existing_tags.get(name.lower())
                found = [{"id": term_id, "name": name}] if term_id is not None else []
                return {"body": found, "status": 200, "headers": {}}
            if not self.can_create_terms:
                return {"body": {"code": "rest_cannot_create"}, "status": 403, "headers": {}}
            self.next_term_id += 1
            return {
                "body": {"id": self.next_term_id, "name": str((json_body or {}).get("name") or "")},
                "status": 201,
                "headers": {},
            }
        self.post_body = dict(json_body or {})
        sent = self.post_body.get("meta") or {}
        landed = {k: v for k, v in sent.items() if k in self.registered_meta}
        return {"id": 4242, "link": "https://verde.example/brunch", "meta": landed}


def _seo() -> SeoFields:
    return SeoFields(
        meta_title="Best Brunch (2026)",
        meta_description="The definitive guide.",
        focus_keyword="best brunch",
        tags=("Best Brunch", "brunch spots"),
        featured_image_url="https://img.test/hero.png",
        schema_jsonld='{"@graph": []}',
    )


def _rest_draft() -> PostDraft:
    return PostDraft(
        title="Best Brunch", content="<p>Body</p>", slug="best-brunch",
        excerpt="The definitive guide.", seo=_seo(),
    )


def test_rest_publish_sends_excerpt_and_the_seo_plugin_post_meta() -> None:
    """The REST body carried title/content/status/slug only. ``meta`` is the ONLY route
    the WP REST API offers for an SEO title or description - they are plugin post meta,
    not native fields (the module docstring has said so since P7A-2)."""
    client = _RestSpy(registered_meta=(_YOAST_TITLE,))
    client.publish("https://verde.example", _rest_draft())

    body = client.post_body
    assert body["excerpt"] == "The definitive guide."
    # BOTH plugin families ride along: which one a client's site runs is unknowable here.
    assert body["meta"][_YOAST_TITLE] == "Best Brunch (2026)"
    assert body["meta"][_RANK_MATH_TITLE] == "Best Brunch (2026)"
    assert body["meta"]["_yoast_wpseo_focuskw"] == "best brunch"
    assert body["meta"]["rank_math_description"] == "The definitive guide."


def test_rest_tags_are_sent_as_term_ids_because_names_are_rejected_by_the_schema() -> None:
    """``tags`` on ``POST /wp/v2/posts`` is schema-typed as an array of INTEGER term ids;
    posting the names the job derived is a ``rest_invalid_param``, i.e. a publish that
    fails outright. Checked against the WP REST posts schema before writing the field -
    the brief's "do not invent field names" is exactly this trap."""
    client = _RestSpy(existing_tags={"best brunch": 31})
    client.publish("https://verde.example", _rest_draft())

    tags = client.post_body["tags"]
    assert all(isinstance(t, int) for t in tags)
    assert tags[0] == 31         # the existing term was FOUND, not duplicated
    assert tags[1] == 901        # the unknown term was created


def test_rest_tag_search_requires_an_exact_name_match() -> None:
    """``?search=`` is a fuzzy LIKE match, so taking the first hit would attach "brunch
    spots" to a post tagged "brunch" - a wrong tag is worse than a missing one."""
    client = _RestSpy(existing_tags={"brunch spots": 55})
    draft = PostDraft(title="T", content="<p>B</p>", seo=SeoFields(tags=("brunch",)))
    client.publish("https://verde.example", draft)
    assert client.post_body["tags"] == [901]  # created "brunch"; did not reuse 55


def test_rest_reports_a_tag_it_could_not_resolve_instead_of_dropping_it_quietly() -> None:
    """An author-level application password is 403'd on term creation (``manage_categories``).
    The post still publishes; the tag does not, and that has to be visible."""
    client = _RestSpy(can_create_terms=False)
    result = client.publish("https://verde.example", _rest_draft())
    assert "tags Best Brunch, brunch spots" in result.dropped_note()
    assert "tags" not in client.post_body  # nothing invented to fill the gap


def test_rest_reports_seo_meta_wordpress_accepted_with_a_200_and_silently_discarded() -> None:
    """WordPress answers 200 and echoes the OLD value for any meta key no plugin
    registered with ``show_in_rest`` - the failure the module docstring was written
    around. Trusting that 200 is how a publish path reports SEO metadata it never wrote,
    so the response's ``meta`` is compared against what was sent."""
    client = _RestSpy(registered_meta=())  # no SEO plugin exposes anything to REST
    result = client.publish("https://verde.example", _rest_draft())

    note = result.dropped_note()
    assert "meta_title" in note and "meta_description" in note and "focus_keyword" in note


def test_rest_does_not_cry_wolf_when_one_plugin_family_landed() -> None:
    """Both key families are always sent, so on a Rank Math site the Yoast keys never
    land - reporting that per KEY would flag a drop on every healthy publish and train
    an operator to ignore the note. A field is carried when ANY of its keys round-trips."""
    client = _RestSpy(registered_meta=(_RANK_MATH_TITLE, "rank_math_description", "rank_math_focus_keyword"))
    result = client.publish("https://verde.example", _rest_draft())
    assert "meta_title" not in result.dropped_note()


def test_rest_names_the_featured_image_and_schema_it_structurally_cannot_carry() -> None:
    """``featured_media`` takes a media id, not a URL, and no REST field carries JSON-LD -
    both are real protocol limits rather than omissions, and both are things the plugin
    path DOES deliver. Silence here is the exact failure the brief calls out."""
    client = _RestSpy(registered_meta=(_RANK_MATH_TITLE, "rank_math_description", "rank_math_focus_keyword"))
    note = client.publish("https://verde.example", _rest_draft()).dropped_note()
    assert "featured image" in note
    assert "schema JSON-LD" in note


def test_rest_publish_without_seo_is_unchanged() -> None:
    """A draft with no ``seo`` must produce the pre-change body and an empty drop list -
    the on-page editor and every other ``PostDraft`` caller still build one that way."""
    client = _RestSpy()
    result = client.publish("https://verde.example", PostDraft(title="T", content="<p>B</p>"))
    assert result.dropped == ()
    assert set(client.post_body) == {"title", "content", "status"}


# --------------------------------------------------------------------------- #
# 3. XML-RPC: what it CAN carry, and the two things it cannot.
# --------------------------------------------------------------------------- #
class _XmlRpcTransport:
    """A scripted httpx stand-in: answers ``wp.getPost`` with one existing custom field
    and every write with a plausible return value, recording each call."""

    def __init__(self, existing_meta: list[dict[str, Any]] | None = None) -> None:
        self.existing_meta = existing_meta if existing_meta is not None else []
        self.calls: list[tuple[str, list[Any]]] = []

    def post(self, url: str, content: bytes) -> Any:
        params, method = xmlrpc.client.loads(content.decode("utf-8"))
        self.calls.append((str(method), list(params)))
        if method == "wp.getPost":
            payload: Any = ({"custom_fields": self.existing_meta},)
        elif method == "wp.newPost":
            payload = ("9137",)
        else:
            payload = (True,)

        class _Resp:
            status_code = 200
            text = xmlrpc.client.dumps(payload, methodresponse=True)

        return _Resp()

    def struct_for(self, method: str) -> dict[str, Any]:
        for name, params in self.calls:
            if name == method:
                return dict(params[-1])
        raise AssertionError(f"{method} was never called")


def _xmlrpc(transport: _XmlRpcTransport) -> XmlRpcWordPressPublisher:
    pub = XmlRpcWordPressPublisher(username="editor", app_password="pw")
    pub._client = transport  # type: ignore[assignment]
    return pub


def test_xmlrpc_publish_sends_tags_by_name_and_the_writable_seo_meta() -> None:
    """XML-RPC published title/content/slug/excerpt and nothing else. ``terms_names``
    and ``custom_fields`` are documented ``wp.newPost`` fields, and ``terms_names`` even
    beats REST here - it takes NAMES and creates a missing term."""
    transport = _XmlRpcTransport()
    result = _xmlrpc(transport).publish("https://hostile.test", _rest_draft())

    struct = transport.struct_for("wp.newPost")
    assert struct["terms_names"] == {"post_tag": ["Best Brunch", "brunch spots"]}
    assert struct["post_excerpt"] == "The definitive guide."
    written = {f["key"]: f["value"] for f in struct["custom_fields"]}
    assert written[_RANK_MATH_TITLE] == "Best Brunch (2026)"
    assert result.post_id == 9137


def test_xmlrpc_does_not_write_protected_meta_core_refuses_and_says_which() -> None:
    """Core's ``set_custom_fields`` checks ``add_post_meta``, which ``map_meta_cap``
    denies for a protected ``_``-prefixed key - so every Yoast key is discarded with no
    error. Sending them anyway would be a write known to be inert; a Yoast-only site
    therefore shows no SEO title over this transport, and the operator is told."""
    transport = _XmlRpcTransport()
    result = _xmlrpc(transport).publish("https://hostile.test", _rest_draft())

    written = {f["key"] for f in transport.struct_for("wp.newPost")["custom_fields"]}
    assert not any(key.startswith("_") for key in written)
    assert seo_meta(_seo())[_YOAST_TITLE]  # the key IS in the shared payload...
    assert "Yoast" in result.dropped_note()  # ...and its absence here is reported


def test_xmlrpc_reuses_the_meta_id_so_a_republish_cannot_append_duplicate_rows() -> None:
    """``set_custom_fields`` calls ``add_post_meta`` for an entry with no ``id``, so a
    re-publish would append a SECOND ``rank_math_title`` row; ``get_post_meta(..., true)``
    keeps returning the first, the update looks applied and never is, and the duplicates
    pile up one per run. Found while checking the idempotent-UPDATE path, which is the
    only one that can hit it."""
    transport = _XmlRpcTransport(existing_meta=[{"id": "77", "key": _RANK_MATH_TITLE, "value": "old"}])
    draft = PostDraft(
        title="T", content="<p>B</p>", wp_post_id=4242, seo=SeoFields(meta_title="New Title")
    )
    _xmlrpc(transport).publish("https://hostile.test", draft)

    fields = {f["key"]: f for f in transport.struct_for("wp.editPost")["custom_fields"]}
    assert fields[_RANK_MATH_TITLE]["id"] == 77  # updated in place, not appended
    assert fields[_RANK_MATH_TITLE]["value"] == "New Title"


def test_xmlrpc_holds_the_meta_rather_than_duplicating_it_when_the_read_fails() -> None:
    """If the existing custom fields cannot be read, writing blind is the duplicate-row
    defect above. Skipping the write and NAMING it is the honest degrade."""

    class _NoGetPost(_XmlRpcTransport):
        def post(self, url: str, content: bytes) -> Any:
            _params, method = xmlrpc.client.loads(content.decode("utf-8"))
            if method == "wp.getPost":
                class _Err:
                    status_code = 500
                    text = ""

                return _Err()
            return super().post(url, content)

    transport = _NoGetPost()
    draft = PostDraft(
        title="T", content="<p>B</p>", wp_post_id=4242, seo=SeoFields(meta_title="New Title")
    )
    result = _xmlrpc(transport).publish("https://hostile.test", draft)

    assert "custom_fields" not in transport.struct_for("wp.editPost")
    assert "duplicate rows" in result.dropped_note()


def test_xmlrpc_names_the_featured_image_and_schema_it_cannot_carry() -> None:
    """``wp.newPost`` takes an attachment id for a thumbnail and has no JSON-LD field -
    the same two structural gaps as REST, reported rather than left silent."""
    note = _xmlrpc(_XmlRpcTransport()).publish("https://hostile.test", _rest_draft()).dropped_note()
    assert "featured image" in note and "schema JSON-LD" in note


def test_xmlrpc_publish_without_seo_is_unchanged() -> None:
    """No ``seo`` on the draft means no extra XML-RPC round trips and no drop list - the
    pre-change behaviour, byte for byte."""
    transport = _XmlRpcTransport()
    result = _xmlrpc(transport).publish("https://hostile.test", PostDraft(title="T", content="<p>B</p>"))
    assert result.dropped == ()
    assert [name for name, _ in transport.calls] == ["wp.newPost"]
    assert set(transport.struct_for("wp.newPost")) == {
        "post_type", "post_status", "post_title", "post_content",
    }


# --------------------------------------------------------------------------- #
# 4. The shared meta map itself.
# --------------------------------------------------------------------------- #
def test_seo_meta_never_writes_an_empty_value_over_a_human_edit() -> None:
    """Pushing ``""`` for a field the job produced nothing for would blank a meta
    description someone wrote on the site - a silent data loss dressed as an update."""
    assert seo_meta(SeoFields(meta_title="Only the title")) == {
        _YOAST_TITLE: "Only the title",
        _RANK_MATH_TITLE: "Only the title",
    }
    assert seo_meta(SeoFields()) == {}
