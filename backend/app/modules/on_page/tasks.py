"""On-page workers: the analysis run + THE APPLY PATH THAT REWRITES A LIVE SITE.

This is the highest-risk module in Part 8, and it is built with the same discipline as
``workers.tasks.content``'s publish path (never-stuck / never-re-raise / idempotent /
cost-gated / credential-degrading), plus two guards that path does not need:

**1. THE DRIFT-GUARD.** Between the analysis and the apply, a human may have hand-edited
the page. Writing our proposal then would silently CLOBBER their work. So every write
re-reads the live value first and refuses if it no longer matches the snapshot we took
at analysis time (``current_value``). ``force=True`` - a deliberate lead decision - re-
snapshots and proceeds. Revert drift-guards too, against what we APPLIED, so a rollback
cannot clobber a later manual edit either.

**2. THE VERIFY.** The SEO ``<title>`` and meta description are NOT native WP REST
fields: they are SEO-plugin post meta (``_yoast_wpseo_title`` / ``rank_math_title``
...), and WordPress **silently drops writes to meta keys no plugin registered with
``show_in_rest``** - answering 200 with the OLD value. A caller that trusts the 200
reports a false success forever. So we (a) only write a meta key the live post PROVES
is registered (its presence in the ``context=edit`` ``meta`` object IS that proof), and
(b) re-read the post afterwards and compare. A write that did not land becomes
``held("SEO-plugin bridge missing")`` - NEVER a reported success.

WHY THE APPLY IS LEAD-ATTRIBUTED, NOT A SERVICE-ROLE WORKER. The 0038
``onpage_guard_update`` trigger forbids ``service_role`` from driving a recommendation's
lifecycle at all. Rewriting a client's live pages must be attributable to a human, so
``apply``/``revert`` take a ``RecStore`` bound to the ACTING LEAD's RLS identity (the
router passes its ``OnPageRepo``), and Postgres itself enforces that. Only
``analyze_page`` - which changes nothing on the client's site - runs privileged.

Statuses are honest about *why* something did not happen: ``held`` means "the
recommendation is still good, we just could not deliver it" (no credential, no
plugin bridge); ``failed`` is reserved for a real error. A missing credential is
NEVER a failure - it is the key-gated dormant->live path every provider here takes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urljoin

from app.config import Settings, get_settings
from app.core.security import PrivateAddressError, validate_public_host
from app.logging_setup import get_logger
from app.modules.on_page.repo import ServiceOnPageStore, service_on_page_store
from app.modules.on_page.service import (
    MANUAL_FIX_KIND,
    ContentScore,
    Recommendation,
    analyze_parsed_page,
    map_audit_findings,
    parse_page,
    priority_score,
    quick_win,
)
from app.services import pricing
from app.services.content_research import FetchedPage, salient_entities
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from integrations.wordpress import WordPressEditor

logger = get_logger("workers.on_page")

# The on-page analysis's OWN money-dial feature: the SERP pull that supplies the
# content score's entity-coverage dimension. Its own dial so ops can throttle on-page
# spend independently of content research. `job_type` is the cost-log label.
_FEATURE = "on_page"
_JOB_TYPE = "on_page"
_ERROR_MAX = 500  # cap the stored error string; server-side only

# The worker owns an analysis ONLY while it is queued: every other status is
# terminal-for-the-worker, so a redelivery there is an idempotent no-op.
_WORKER_OWNED: frozenset[str] = frozenset({"queued"})

# Redirect handling: we follow them MANUALLY so every hop is re-validated (a 30x can
# point at 169.254.169.254 - see app/core/security's caller contract). Bounded so a
# redirect loop cannot spin the worker.
_MAX_REDIRECT_HOPS = 5
_MAX_HTML_CHARS = 400_000

# --------------------------------------------------------------------------- #
# The SEO-plugin bridge
# --------------------------------------------------------------------------- #
# The post-meta keys the two dominant WordPress SEO plugins use for the SERP title +
# description. NEITHER is a native WP REST field - this mapping is the whole reason
# the apply path needs a detect + verify step.
_SEO_META_KEYS: dict[str, dict[str, str]] = {
    "yoast": {"title": "_yoast_wpseo_title", "meta": "_yoast_wpseo_metadesc"},
    "rank_math": {"title": "rank_math_title", "meta": "rank_math_description"},
}
# The fix kinds the SEO-plugin bridge can deliver. Anything else must carry an
# explicit `fix_payload.wp_fields` (native REST fields) or it holds: we do NOT guess
# at how to rewrite a live page's prose or markup.
_SEO_META_KINDS: frozenset[str] = frozenset({"title", "meta"})

_HELD_NO_CREDENTIAL = "no WordPress credential for this site (add the app password to the vault)"
_HELD_NO_POST = "no WordPress post is linked to this page"
_HELD_NO_BRIDGE = (
    "SEO-plugin bridge missing: WordPress accepted the request but did not store the "
    "value (the SEO plugin has not registered this meta key with show_in_rest)"
)
_HELD_NO_PATH = "no automated apply path for a {kind} fix - a human must make this change"
_HELD_NO_PROPOSAL = "the recommendation carries no proposed value"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# --------------------------------------------------------------------------- #
# Seams
# --------------------------------------------------------------------------- #
class RecStore(Protocol):
    """The recommendation seam the apply/revert cores need.

    Satisfied by :class:`app.modules.on_page.repo.OnPageRepo` bound to the acting
    LEAD - which is exactly what the 0038 guard requires for a live-site write.
    """

    def get_recommendation(self, rec_id: str) -> dict[str, Any] | None: ...
    def update_recommendation(
        self, rec_id: str, changes: dict[str, Any], expect_status: str | None = ...
    ) -> dict[str, Any] | None: ...


class EntitySource(Protocol):
    """The (paid, gated) source of a keyword's table-stakes entities - a SERP pull.

    ``None`` when no Serper key is configured, which DEGRADES the content score to
    its deterministic dimensions rather than failing it.
    """

    def entities_for(self, keyword: str) -> list[str]: ...


@dataclass(frozen=True)
class WpTarget:
    """A resolved live-site write target: the site + a ready editor."""

    site_url: str
    editor: WordPressEditor


class SerpEntitySource:
    """Real :class:`EntitySource`: one Serper SERP pull -> the content engine's own
    ``salient_entities``. Reuses the Part-7 extractor rather than inventing a second
    notion of what a page's table-stakes entities are."""

    def __init__(self, researcher: Any, *, limit: int = 8) -> None:
        self._researcher = researcher
        self._limit = limit

    def entities_for(self, keyword: str) -> list[str]:
        return salient_entities(self._researcher.serp(keyword), limit=self._limit)


def entity_source_from_settings(settings: Settings) -> EntitySource | None:
    """Build the SERP entity source, or ``None`` when no Serper key is configured.

    Deliberately independent of ``content_providers_from_settings`` (which needs the
    ANTHROPIC key): entity coverage is a SERP question, so a Serper-only install
    still scores it. No key -> ``None`` -> the score degrades honestly.
    """
    key = settings.serper_api_key
    if not key:
        return None
    try:
        from integrations.content_research import SerperResearcher

        return SerpEntitySource(SerperResearcher(api_key=key.get_secret_value()))
    except Exception:  # an unavailable provider degrades the score, never crashes
        logger.info("on_page_entity_source_unavailable")
        return None


class _NullCostCache:
    """A no-op ``CostCache``: a live SERP pull for an on-page analysis is not
    cache-keyed here; the dial + budgets still gate it."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate() -> CostGate:
    return CostGate(PostgresCostStore(), _NullCostCache())


# --------------------------------------------------------------------------- #
# The SSRF-guarded fetch (every hop re-validated)
# --------------------------------------------------------------------------- #
class SsrfGuardedFetcher:
    """Fetch a page, re-validating the host at EVERY redirect hop.

    ``app/core/security``'s caller contract is explicit that one-shot validation is
    insufficient: ``httpx`` re-resolves DNS and a 30x can bounce to
    ``169.254.169.254``. So automatic redirects are DISABLED and each ``Location`` is
    re-validated through ``validate_public_host`` before we follow it. Non-raising:
    any failure returns ``None`` (the analysis then holds honestly).

    ``validate_public_host`` BLOCKS on DNS - which is fine here (a Celery worker has
    no event loop). The ROUTER, which is async, offloads its own pre-check with
    ``asyncio.to_thread``.
    """

    def __init__(self, *, user_agent: str = "AIOSOnPageBot/1.0") -> None:
        self._ua = user_agent

    def fetch(self, url: str, *, timeout: float) -> FetchedPage | None:
        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx is a base dep
            logger.warning("on_page_fetch_no_httpx")
            return None
        current = url
        try:
            with httpx.Client(
                follow_redirects=False,  # we follow MANUALLY so every hop is re-checked
                timeout=httpx.Timeout(timeout),
                headers={"User-Agent": self._ua},
            ) as client:
                for _hop in range(_MAX_REDIRECT_HOPS):
                    validate_public_host(current)  # re-validated EVERY hop, not just once
                    resp = client.get(current)
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location", "")
                        if not location:
                            return None
                        current = urljoin(current, location)
                        continue
                    if resp.status_code != 200:
                        return None
                    return FetchedPage(
                        url=current, html=resp.text[:_MAX_HTML_CHARS], status=resp.status_code
                    )
        except PrivateAddressError:
            # A hop pointed somewhere internal. This is the guard doing its job.
            logger.warning("on_page_fetch_ssrf_blocked", url=str(url).split("?", 1)[0])
            raise
        except Exception:  # any transport error degrades to a hold, never a crash
            logger.info("on_page_fetch_failed", url=str(url).split("?", 1)[0])
            return None
        logger.info("on_page_fetch_redirect_loop", url=str(url).split("?", 1)[0])
        return None


class PageFetcherPort(Protocol):
    """Fetch one page (SSRF-guarded internally), or ``None`` on any failure."""

    def fetch(self, url: str, *, timeout: float) -> FetchedPage | None: ...


# --------------------------------------------------------------------------- #
# Outcomes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class AnalysisOutcome:
    """The verdict of one :func:`execute_analysis` run (JSON-serializable)."""

    code: str
    status: str
    state: str  # analyzed | degraded | noop | held | failed
    recommendations: int = 0
    score: float = 0.0
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "state": self.state,
            "recommendations": self.recommendations,
            "score": self.score,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ApplyOutcome:
    """The verdict of one apply/revert (JSON-serializable).

    ``state`` is the honest vocabulary: ``applied`` / ``reverted`` / ``noop`` (already
    done - idempotent) / ``skipped`` (a manual fix; a human must do it) / ``held`` (we
    could not deliver it) / ``blocked`` (the drift-guard refused) / ``failed``.
    """

    rec_id: str
    state: str
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.rec_id, "state": self.state, "reason": self.reason}


# --------------------------------------------------------------------------- #
# The analysis core
# --------------------------------------------------------------------------- #
def _rec_rows(
    recs: list[Recommendation], *, client_id: str, site_id: str | None, page_url: str
) -> list[dict[str, Any]]:
    """Flatten the pure recommendations into insertable rows, denormalising the
    tenant + page and computing the Impact x Effort ranking."""
    return [
        {
            "client_id": client_id,
            "site_id": site_id,
            "page_url": page_url,
            "issue": rec.issue,
            "issue_code": rec.issue_code,
            "impact": rec.impact,
            "fix_kind": rec.fix_kind,
            "fix_payload": rec.fix_payload,
            # The snapshot the drift-guard and the revert both depend on.
            "current_value": rec.current_value,
            "priority_score": priority_score(rec.impact, rec.fix_kind),
            "quick_win": quick_win(rec.impact, rec.fix_kind),
            "detail": rec.detail,
        }
        for rec in recs
    ]


def _entities_for(
    source: EntitySource | None,
    gate: CostGate,
    settings: Settings,
    *,
    keyword: str,
    client_id: str | None,
    code: str,
) -> list[str] | None:
    """The R5 pre-check + the (paid) entity pull. Returns ``None`` to DEGRADE.

    The gate is consulted BEFORE the call, never after - a decision taken afterwards
    would already have spent the money it exists to prevent. A block, an absent key,
    or a provider error all degrade to ``None`` (deterministic-only scoring); none of
    them is an error.
    """
    if source is None or not keyword.strip():
        return None
    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=client_id,
        provider="Serper",
        estimated_cost=float(settings.onpage_analyze_cost_estimate),
        job_id=code,
        job_type=_JOB_TYPE,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        logger.info("on_page_entities_blocked", code=code, outcome=decision.outcome)
        return None
    try:
        entities = source.entities_for(keyword)
    except Exception:
        logger.warning("on_page_entity_fetch_failed", code=code)
        return None
    # ACTUAL cost = one Serper SERP pull x the per-query unit price (pricing.py).
    gate.commit(ctx, pricing.serper_cost(settings, queries=1))
    return entities


def _load_findings(store: ServiceOnPageStore, settings: Settings, audit_id: str) -> list[dict[str, Any]]:
    """Read an audit run's stored ``findings.json`` through the traversal-safe artifact
    store. Any failure yields ``[]``, which falls the analysis back to a live fetch -
    a missing artifact must never fail an analysis."""
    try:
        import json

        from app.services.audit_artifacts import local_store_from_settings

        key = store.audit_json_path(audit_id)
        artifacts = local_store_from_settings(settings)
        if not key or artifacts is None:
            return []
        path = artifacts.resolve(key)  # refuses anything escaping the root
        if path is None:
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [f for f in data if isinstance(f, dict)] if isinstance(data, list) else []
    except Exception:
        logger.warning("on_page_findings_load_failed", audit_id=audit_id)
        return []


def execute_analysis(
    store: ServiceOnPageStore,
    code: str,
    *,
    settings: Settings,
    gate: CostGate,
    fetcher: PageFetcherPort | None = None,
    entity_source: EntitySource | None = None,
) -> AnalysisOutcome:
    """Analyse ONE page and (re)build its recommendation queue. Never raises.

    Idempotent: only a ``queued`` analysis is the worker's to run, so a redelivered
    job is a no-op (``task_acks_late`` would otherwise re-fetch and re-spend). The
    page is fetched SSRF-guarded with every redirect hop re-validated - unless a
    ``source_audit_id`` is set, in which case the 363-check run's findings are MAPPED
    instead (it already knows more about the page than a single fetch ever can).

    Reads NOTHING on the client's site but the page itself, so it runs privileged
    (``service_role``); the 0038 trigger still holds it to queued -> analyzing ->
    done|held|failed.
    """
    row = store.load_analysis(code)
    if row is None:
        logger.warning("on_page_analysis_missing", code=code)
        return AnalysisOutcome(code, "failed", "failed", reason="not found")

    status = str(row.get("status") or "")
    if status not in _WORKER_OWNED:
        return AnalysisOutcome(code, status, "noop", reason="not worker-owned (idempotent)")

    store.update_analysis(code, {"status": "analyzing"})
    try:
        return _run_analysis(
            store, code, row, settings=settings, gate=gate,
            fetcher=fetcher or SsrfGuardedFetcher(), entity_source=entity_source,
        )
    except PrivateAddressError as exc:
        # The SSRF guard refused the target. Terminal by nature: the URL will not
        # become public on a retry, so this is `failed`, not `held`.
        return _fail(store, code, error=f"blocked: {exc}")
    except Exception as exc:  # never re-raise: acks_late would redeliver
        logger.exception("on_page_analysis_crashed", code=code)
        return _fail(store, code, error=f"worker error: {exc!r}")


def _run_analysis(
    store: ServiceOnPageStore,
    code: str,
    row: dict[str, Any],
    *,
    settings: Settings,
    gate: CostGate,
    fetcher: PageFetcherPort,
    entity_source: EntitySource | None,
) -> AnalysisOutcome:
    """The happy-path composition (fetch|map -> detect -> score -> persist)."""
    page_url = str(row.get("page_url") or "")
    keyword = str(row.get("target_keyword") or "")
    client_id = str(row["client_id"])
    site_id = str(row["site_id"]) if row.get("site_id") else None
    audit_id = str(row["source_audit_id"]) if row.get("source_audit_id") else None

    fetched = fetcher.fetch(page_url, timeout=float(settings.onpage_fetch_timeout_seconds))
    if fetched is None:
        # We could not read the page (transient error / non-200). HELD, not failed:
        # the analysis is still valid work, it just could not be done right now, and
        # a re-analyze picks it straight back up.
        store.update_analysis(code, {"status": "held", "error": "page could not be fetched"})
        logger.info("on_page_analysis_held", code=code, reason="fetch")
        return AnalysisOutcome(code, "held", "held", reason="page could not be fetched")

    page = parse_page(fetched.html, page_url)

    recs: list[Recommendation]
    score: ContentScore
    if audit_id:
        findings = _load_findings(store, settings, audit_id)
        if findings:
            # An audit run exists: map its verdicts rather than re-detecting them.
            recs = map_audit_findings(findings, page_url)
            score = _score_only(page, keyword, entity_source, gate, settings, code, client_id)
        else:
            recs, score = _detect(page, keyword, row, entity_source, gate, settings, code, client_id)
    else:
        recs, score = _detect(page, keyword, row, entity_source, gate, settings, code, client_id)

    # Resolve the WP post ONCE (never per-apply: a re-resolve could drift onto a
    # different post and duplicate content). Only if not already recorded.
    fields: dict[str, Any] = {"status": "done", "score": score.as_dict(), "error": None}
    if row.get("wp_post_id") is None:
        resolved = _resolve_wp_post_id(page, fetched)
        if resolved is not None:
            fields["wp_post_id"] = resolved

    analysis_id = str(row["id"])
    store.clear_open_recommendations(analysis_id)
    inserted = store.insert_recommendations(
        analysis_id,
        _rec_rows(recs, client_id=client_id, site_id=site_id, page_url=page_url),
    )
    store.update_analysis(code, fields)
    logger.info(
        "on_page_analysis_done", code=code, recommendations=inserted,
        score=score.total, degraded=score.degraded,
    )
    return AnalysisOutcome(
        code, "done", "degraded" if score.degraded else "analyzed",
        recommendations=inserted, score=score.total,
        reason="; ".join(score.notes) if score.degraded else "",
    )


def _detect(
    page: Any, keyword: str, row: dict[str, Any], entity_source: EntitySource | None,
    gate: CostGate, settings: Settings, code: str, client_id: str,
) -> tuple[list[Recommendation], ContentScore]:
    entities = _entities_for(
        entity_source, gate, settings, keyword=keyword, client_id=client_id, code=code
    )
    return analyze_parsed_page(
        page, keyword, brand=str(row.get("client_name") or ""), entities=entities
    )


def _score_only(
    page: Any, keyword: str, entity_source: EntitySource | None, gate: CostGate,
    settings: Settings, code: str, client_id: str,
) -> ContentScore:
    from app.modules.on_page.service import score_page_content

    entities = _entities_for(
        entity_source, gate, settings, keyword=keyword, client_id=client_id, code=code
    )
    return score_page_content(page, keyword, entities=entities)


def _resolve_wp_post_id(page: Any, fetched: FetchedPage) -> int | None:
    """The page's WordPress post id, from the ``shortlink`` / body markers WordPress
    emits (``<link rel='shortlink' href='.../?p=123'>``, ``<body class="postid-123">``).

    ``None`` when we cannot prove it - and an unproven post id is exactly the thing
    we must never guess: every apply UPDATEs this id, so a wrong one edits the wrong
    page. A lead can still set it out of band.
    """
    import re

    for pattern in (
        r"[?&]p=(\d+)",                      # the shortlink WordPress always emits
        r"\bpostid-(\d+)\b",                 # body class
        r"\bpage-id-(\d+)\b",                # body class (pages)
        r'name="post_id"\s+value="(\d+)"',   # comment form
    ):
        match = re.search(pattern, fetched.html)
        if match:
            try:
                return int(match.group(1))
            except ValueError:  # pragma: no cover - the group is \d+
                continue
    return None


def _fail(store: ServiceOnPageStore, code: str, *, error: str) -> AnalysisOutcome:
    """Mark the analysis ``failed`` (any->failed is always legal) - never stuck."""
    try:
        store.update_analysis(code, {"status": "failed", "error": error[:_ERROR_MAX]})
    except Exception:  # even the fail-write must not raise out of the task
        logger.warning("on_page_fail_write_failed", code=code)
    return AnalysisOutcome(code, "failed", "failed", reason=error[:_ERROR_MAX])


# --------------------------------------------------------------------------- #
# The vault -> WordPress resolution (mirrors content's _resolve_wp_from_vault)
# --------------------------------------------------------------------------- #
def _resolve_wp_from_vault(row: dict[str, Any], settings: Settings) -> WpTarget | None:
    """Resolve a per-site WordPress EDITOR from the recommendation's site + the vault.

    Mirrors ``workers.tasks.content._resolve_wp_from_vault``: the app password is
    per-site, lives sealed in the vault, is revealed SERVER-SIDE only, and is never
    logged (it rides the HTTP Basic header the shared client keeps out of every log
    line). Any missing piece - no site, no vault key, a reveal failure - returns
    ``None``, and the caller HOLDS (never fails, never writes).

    THE VAULT CONVENTION: one ``vault_keys`` row per WordPress site, ``provider =
    'wordpress'``, ``label`` = the site's domain, secret = ``"<username>:<application
    password>"``. Until such a row exists the apply path is dormant - exactly the
    key-gated dormant->live posture every other provider here takes.
    """
    site_id = row.get("site_id")
    if not site_id:
        return None
    try:
        from app.db.database import privileged_connection

        with privileged_connection() as cur:
            cur.execute("select domain from public.sites where id = %s limit 1", (str(site_id),))
            site = cur.fetchone()
            if site is None:
                return None
            domain = str(site.get("domain") or "").strip()
            if not domain:
                return None
            cur.execute(
                "select id from public.vault_keys "
                "where provider = 'wordpress' and label = %s limit 1",
                (domain,),
            )
            key_row = cur.fetchone()
        if key_row is None:
            return None

        from app.services.vault import reveal_secret

        secret = reveal_secret(str(key_row["id"]))
    except Exception:
        logger.warning("on_page_wp_credential_reveal_failed", rec=str(row.get("id", "")))
        return None
    if not secret or ":" not in secret:
        return None
    username, app_password = secret.split(":", 1)
    if not username.strip() or not app_password.strip():
        return None
    site_url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
    try:
        from integrations.wordpress import WordPressClient

        editor: WordPressEditor = WordPressClient(
            username=username.strip(), app_password=app_password.strip()
        )
    except Exception:
        logger.warning("on_page_wp_client_unavailable", rec=str(row.get("id", "")))
        return None
    return WpTarget(site_url=site_url, editor=editor)


# --------------------------------------------------------------------------- #
# The write plan (what we will send, and what we will read back to verify it)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class WritePlan:
    """One field's worth of live-site write + how to read that field back."""

    fields: dict[str, Any]
    meta: dict[str, Any]
    read_key: str        # the key to read the value back from
    in_meta: bool        # whether read_key lives under the post's `meta` object


def detect_seo_plugin(post_meta: dict[str, Any]) -> str | None:
    """Which SEO plugin's meta keys this post EXPOSES over REST, if any.

    Key PRESENCE is the proof we need: WordPress only returns a post-meta key in the
    REST representation once a plugin has registered it with ``show_in_rest`` - which
    is the exact same condition under which a WRITE to it will be stored rather than
    silently dropped. An empty value is fine; an absent key is the red flag.
    """
    for plugin, keys in _SEO_META_KEYS.items():
        if any(key in post_meta for key in keys.values()):
            return plugin
    return None


def _plan_write(fix_kind: str, payload: dict[str, Any], live_post: dict[str, Any]) -> WritePlan | None:
    """Build the write plan for a fix, or ``None`` when we have no safe path.

    ``None`` is not a failure - it is the honest answer for a fix whose delivery we
    cannot prove: a heading/content/schema change needs a human unless the detector
    supplied explicit native ``wp_fields``, and a title/meta change needs a live SEO
    plugin whose meta key is REST-registered.
    """
    proposed = payload.get("proposed_value")
    if proposed is None or str(proposed) == "":
        return None
    # An explicit native-field escape hatch (none of today's detectors set it; it is
    # how a future detector delivers a content/heading fix without guesswork).
    wp_fields = payload.get("wp_fields")
    if isinstance(wp_fields, dict) and wp_fields:
        key = next(iter(wp_fields))
        return WritePlan(fields=dict(wp_fields), meta={}, read_key=str(key), in_meta=False)
    if fix_kind not in _SEO_META_KINDS:
        return None
    plugin = detect_seo_plugin(_as_dict(live_post.get("meta")))
    if plugin is None:
        return None  # no REST-registered SEO meta -> the write would be dropped
    key = _SEO_META_KEYS[plugin][fix_kind]
    return WritePlan(fields={}, meta={key: str(proposed)}, read_key=key, in_meta=True)


def _read_value(post: dict[str, Any], plan: WritePlan) -> str:
    """Read the planned field back out of a post representation.

    Native WP fields come back as ``{"raw": ...}`` under ``context=edit`` (the raw
    form is what we wrote); meta values are flat.
    """
    if plan.in_meta:
        return str(_as_dict(post.get("meta")).get(plan.read_key, "") or "")
    value = post.get(plan.read_key)
    if isinstance(value, dict):
        return str(value.get("raw", "") or "")
    return str(value or "")


# --------------------------------------------------------------------------- #
# THE APPLY CORE (the highest-risk path in the module)
# --------------------------------------------------------------------------- #
def execute_apply(
    store: RecStore,
    rec_id: str,
    *,
    actor_id: str,
    settings: Settings,
    force: bool = False,
    resolve_wp: Any = _resolve_wp_from_vault,
) -> ApplyOutcome:
    """Apply ONE recommendation to the client's LIVE site. Never raises.

    The full contract, in order:

    1. **Idempotent.** ``applied_at`` already set -> ``noop``. A ``task_acks_late``
       redelivery must not write the site twice.
    2. **Never auto-applies a ``manual`` fix** -> ``skipped``. (The router 422s these
       before they get here; this is the defence in depth that makes that guarantee
       true regardless of caller.)
    3. **No credential -> ``held``, never ``failed``.** The recommendation is still
       good; only the delivery path is missing.
    4. **The DRIFT-GUARD.** Re-read the live value; if it differs from the
       ``current_value`` snapshot taken at analysis time, someone hand-edited the page
       after we analysed it and applying would clobber them -> ``blocked`` (the router
       409s). ``force=True`` re-snapshots the live value and proceeds - a deliberate
       lead decision to overwrite.
    5. **The VERIFY.** Re-read the post after writing and compare. WordPress silently
       drops writes to meta keys no SEO plugin registered - a write that did not land
       becomes ``held``, NEVER a reported success.
    6. On success: ``applied`` + ``applied_at``/``applied_by``, and ``current_value``
       is re-snapshotted to the value that was live IMMEDIATELY BEFORE our write - so
       a later revert restores exactly what we replaced.
    """
    row = store.get_recommendation(rec_id)
    if row is None:
        return ApplyOutcome(rec_id, "failed", "not found")

    # (1) Idempotency - keyed on the stamp, not just the status, so a half-written
    # row (status changed, stamp set) is still recognised as done.
    if row.get("applied_at") is not None or str(row.get("status")) == "applied":
        return ApplyOutcome(rec_id, "noop", "already applied (idempotent)")

    # (2) A manual fix is human work, by definition. Never automated.
    fix_kind = str(row.get("fix_kind") or MANUAL_FIX_KIND)
    if fix_kind == MANUAL_FIX_KIND:
        return ApplyOutcome(rec_id, "skipped", "manual fixes must be made by a human")

    try:
        return _apply_to_site(
            store, rec_id, row, actor_id=actor_id, settings=settings,
            force=force, resolve_wp=resolve_wp,
        )
    except Exception as exc:  # never re-raise: acks_late would redeliver = double write
        logger.exception("on_page_apply_crashed", rec=rec_id)
        return ApplyOutcome(rec_id, "failed", f"apply error: {exc!r}"[:_ERROR_MAX])


def _apply_to_site(
    store: RecStore,
    rec_id: str,
    row: dict[str, Any],
    *,
    actor_id: str,
    settings: Settings,
    force: bool,
    resolve_wp: Any,
) -> ApplyOutcome:
    wp: WpTarget | None = resolve_wp(row, settings)
    if wp is None:
        return _hold(store, rec_id, _HELD_NO_CREDENTIAL)

    post_id = row.get("wp_post_id")
    if post_id is None:
        return _hold(store, rec_id, _HELD_NO_POST)

    # Read the post as the EDITOR sees it: only context=edit carries `meta` and the
    # raw field values the drift-guard must compare against.
    live_post = wp.editor.get_post(wp.site_url, int(post_id), context="edit")

    payload = _as_dict(row.get("fix_payload"))
    plan = _plan_write(str(row.get("fix_kind")), payload, live_post)
    if plan is None:
        proposed = payload.get("proposed_value")
        if proposed is None or str(proposed) == "":
            return _hold(store, rec_id, _HELD_NO_PROPOSAL)
        if str(row.get("fix_kind")) in _SEO_META_KINDS:
            return _hold(store, rec_id, _HELD_NO_BRIDGE)
        return _hold(store, rec_id, _HELD_NO_PATH.format(kind=row.get("fix_kind")))

    live_value = _read_value(live_post, plan)
    snapshot = str(row.get("current_value") or "")

    # (4) THE DRIFT-GUARD.
    if live_value != snapshot and not force:
        logger.info("on_page_apply_drift_blocked", rec=rec_id)
        return ApplyOutcome(
            rec_id, "blocked",
            "the live page changed after this analysis - applying would overwrite a "
            "manual edit; re-analyze, or apply with force to overwrite it anyway",
        )

    proposed = str(payload.get("proposed_value"))
    updated = wp.editor.update_post(
        wp.site_url, int(post_id), fields=plan.fields or None, meta=plan.meta or None
    )

    # (5) THE VERIFY - a FRESH read, not the update's echo. A plugin that reflects the
    # request back would otherwise fake a success the site never actually stored.
    verified = wp.editor.get_post(wp.site_url, int(post_id), context="edit")
    if _read_value(verified, plan) != proposed:
        logger.warning(
            "on_page_apply_write_dropped", rec=rec_id, key=plan.read_key,
            echoed=_read_value(updated, plan) == proposed,
        )
        return _hold(store, rec_id, _HELD_NO_BRIDGE)

    # (6) Success. current_value is re-snapshotted to what was live IMMEDIATELY
    # BEFORE our write - that is precisely what a revert has to put back.
    updated_row = store.update_recommendation(
        rec_id,
        {
            "status": "applied",
            "applied_at": _utcnow(),
            "applied_by": actor_id,
            "current_value": live_value,
        },
        "open",
    )
    if updated_row is None:
        # A racing apply already moved the row (optimistic concurrency). The site
        # write is idempotent (same post, same absolute value), so this is safe.
        return ApplyOutcome(rec_id, "noop", "already applied concurrently (idempotent)")
    logger.info("on_page_fix_applied", rec=rec_id, issue=row.get("issue_code"))
    return ApplyOutcome(rec_id, "applied", f"applied to {wp.site_url}")


def _hold(store: RecStore, rec_id: str, reason: str) -> ApplyOutcome:
    """Hold a recommendation: still valid work, just not deliverable right now.

    Best-effort - a hold-write failure must not turn into an exception out of the
    apply (the site was NOT written in any hold path, so there is nothing to undo).
    """
    try:
        store.update_recommendation(rec_id, {"status": "held"}, "open")
    except Exception:
        logger.warning("on_page_hold_write_failed", rec=rec_id)
    logger.info("on_page_fix_held", rec=rec_id, reason=reason)
    return ApplyOutcome(rec_id, "held", reason)


# --------------------------------------------------------------------------- #
# THE REVERT CORE
# --------------------------------------------------------------------------- #
def execute_revert(
    store: RecStore,
    rec_id: str,
    *,
    actor_id: str,
    settings: Settings,
    force: bool = False,
    resolve_wp: Any = _resolve_wp_from_vault,
) -> ApplyOutcome:
    """Roll ONE applied recommendation back on the live site. Never raises.

    Writes ``current_value`` - the value that was live immediately before we applied -
    back, and marks the recommendation ``reverted``.

    IT DRIFT-GUARDS TOO, and this is not symmetry for its own sake: between our apply
    and this revert, a human may have edited the field again. Restoring our snapshot
    then would clobber THEIR edit just as surely as a blind apply would. So we re-read
    and refuse unless the live value is still exactly what WE applied
    (``fix_payload.proposed_value``). ``force=True`` overrides, deliberately.
    """
    row = store.get_recommendation(rec_id)
    if row is None:
        return ApplyOutcome(rec_id, "failed", "not found")
    if str(row.get("status")) != "applied":
        return ApplyOutcome(rec_id, "noop", "not applied - nothing to revert")

    try:
        return _revert_on_site(
            store, rec_id, row, actor_id=actor_id, settings=settings,
            force=force, resolve_wp=resolve_wp,
        )
    except Exception as exc:  # never re-raise
        logger.exception("on_page_revert_crashed", rec=rec_id)
        return ApplyOutcome(rec_id, "failed", f"revert error: {exc!r}"[:_ERROR_MAX])


def _revert_on_site(
    store: RecStore,
    rec_id: str,
    row: dict[str, Any],
    *,
    actor_id: str,
    settings: Settings,
    force: bool,
    resolve_wp: Any,
) -> ApplyOutcome:
    wp: WpTarget | None = resolve_wp(row, settings)
    if wp is None:
        return ApplyOutcome(rec_id, "held", _HELD_NO_CREDENTIAL)
    post_id = row.get("wp_post_id")
    if post_id is None:
        return ApplyOutcome(rec_id, "held", _HELD_NO_POST)

    live_post = wp.editor.get_post(wp.site_url, int(post_id), context="edit")
    payload = _as_dict(row.get("fix_payload"))
    plan = _plan_write(str(row.get("fix_kind")), payload, live_post)
    if plan is None:
        return ApplyOutcome(rec_id, "held", _HELD_NO_BRIDGE)

    applied_value = str(payload.get("proposed_value") or "")
    live_value = _read_value(live_post, plan)
    if live_value != applied_value and not force:
        logger.info("on_page_revert_drift_blocked", rec=rec_id)
        return ApplyOutcome(
            rec_id, "blocked",
            "the live page changed since this fix was applied - reverting would "
            "overwrite a later manual edit",
        )

    restore = str(row.get("current_value") or "")
    write_fields = {plan.read_key: restore} if not plan.in_meta else None
    write_meta = {plan.read_key: restore} if plan.in_meta else None
    wp.editor.update_post(wp.site_url, int(post_id), fields=write_fields, meta=write_meta)

    verified = wp.editor.get_post(wp.site_url, int(post_id), context="edit")
    if _read_value(verified, plan) != restore:
        return ApplyOutcome(rec_id, "held", _HELD_NO_BRIDGE)

    updated_row = store.update_recommendation(
        rec_id, {"status": "reverted", "applied_at": None, "applied_by": actor_id}, "applied"
    )
    if updated_row is None:
        return ApplyOutcome(rec_id, "noop", "already moved concurrently (idempotent)")
    logger.info("on_page_fix_reverted", rec=rec_id)
    return ApplyOutcome(rec_id, "reverted", f"reverted on {wp.site_url}")


# --------------------------------------------------------------------------- #
# Celery entry points (thin; import the app after the pure cores, per the template)
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="analyze_page")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def analyze_page(code: str) -> dict[str, Any]:
    """Entry point: analyse one page + rebuild its recommendation queue.

    Wraps the pure core so the task NEVER re-raises (a redelivery would re-fetch and
    re-spend); a failure comes back as a result dict. The WIRING (settings, store,
    gate, provider) is inside the guard too - a task that only guarded its core would
    still re-raise if a seam failed to construct."""
    try:
        settings = get_settings()
        return execute_analysis(
            service_on_page_store(),
            code,
            settings=settings,
            gate=_gate(),
            entity_source=entity_source_from_settings(settings),
        ).as_dict()
    except Exception:
        logger.exception("analyze_page_task_failed", code=code)
        return {"code": code, "status": "failed", "state": "failed", "reason": "task failed"}


@celery_app.task(name="apply_onpage_fix")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def apply_onpage_fix(rec_id: str, actor_id: str, force: bool = False) -> dict[str, Any]:
    """Entry point for an ASYNC apply.

    ``actor_id`` is REQUIRED and is not ceremony: the 0038 guard rejects a
    recommendation lifecycle write that is not lead-attributed, so this task runs on
    the LEAD's RLS identity exactly as the synchronous router path does. There is no
    anonymous route to a client's live site anywhere in this module.
    """
    from app.modules.on_page.repo import OnPageRepo

    try:
        return execute_apply(
            OnPageRepo(actor_id), rec_id, actor_id=actor_id,
            settings=get_settings(), force=force,
        ).as_dict()
    except Exception:
        logger.exception("apply_onpage_fix_task_failed", rec=rec_id)
        return {"id": rec_id, "state": "failed", "reason": "task failed"}


@celery_app.task(name="revert_onpage_fix")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def revert_onpage_fix(rec_id: str, actor_id: str, force: bool = False) -> dict[str, Any]:
    """Entry point for an ASYNC revert (lead-attributed, exactly like the apply)."""
    from app.modules.on_page.repo import OnPageRepo

    try:
        return execute_revert(
            OnPageRepo(actor_id), rec_id, actor_id=actor_id,
            settings=get_settings(), force=force,
        ).as_dict()
    except Exception:
        logger.exception("revert_onpage_fix_task_failed", rec=rec_id)
        return {"id": rec_id, "state": "failed", "reason": "task failed"}
