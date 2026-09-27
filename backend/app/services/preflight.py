"""What this deploy can actually deliver, BEFORE an operator spends money on it.

WHAT WAS WRONG. Every provider dependency in this platform degrades honestly - a
missing Serper key makes the content bundle hold at ``drafting`` with $0 logged, a
missing PageSpeed key leaves Core Web Vitals blank, a dial set to ``off`` blocks a
feature at the gate. Each of those is correct in isolation and invisible in advance.
The operator learned what this deploy could not do by running a job and reading the
degrade note afterwards, one feature at a time - and on a paid depth, after the bill.

``GET /integrations`` already answers "is this key present". That is a different
question from the one an agency owner actually asks, which is always about the WORK:

    "If I run a deep audit right now, will off-page actually be measured?"
    "If I queue thirty pages tonight, will they draft - or hold at $0?"

This module answers that one. It maps each CAPABILITY the operator can launch to what
it needs, and reports what will run, what will quietly come back unmeasured, and the
one concrete fix for each gap.

THREE THINGS IT GETS RIGHT THAT A KEY LIST CANNOT:

  * THE AUDIT ENGINE READS ITS OWN ``.env``, NOT OURS. It is a separate product invoked
    as a subprocess (``integrations/audit_engine.py``), and ``audit_engine.config``
    loads ``<engine>/.env`` plus the inherited process environment. A SERPER_API_KEY in
    the PLATFORM's ``.env`` reaches ``Settings`` but is NOT exported to ``os.environ``
    by pydantic-settings, so it can be green on the integrations screen and absent from
    every audit. Engine-side keys are therefore reported from where the ENGINE looks.
  * A DIAL AT ``off`` IS A BLOCKER, and so is the global spend halt. Both stop a run at
    the cost gate before any provider is called, which an operator reading a green key
    list has no way to see.
  * DEGRADES ARE SEPARATED FROM BLOCKS. "Images will be skipped" and "nothing will
    draft" are not the same sentence, and a board that renders them identically is the
    reason nobody reads it.

Pure: a function of (settings, vault providers, dial modes, halt, engine env keys). The
router supplies the three live inputs. No secret VALUE reaches a field here - only the
fact that one is present.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import Settings
from app.services.content_images import content_image_dir

Severity = Literal["blocks", "degrades"]
Verdict = Literal["ready", "partial", "blocked"]

# The engine env var names this board reports on, WITH the fallbacks the engine itself
# honours (``audit_engine.config.APIKeys.from_env``): one unrestricted GOOGLE_API_KEY
# stands in for the per-service Google keys, and a Maps key stands in for Places.
# Telling an operator to "set GOOGLE_PAGESPEED_API_KEY" when they have already
# provisioned one unrestricted key would be wrong, so the fallback chain is part of the
# check rather than a footnote.
_PSI_KEYS: tuple[str, ...] = ("GOOGLE_PAGESPEED_API_KEY", "GOOGLE_API_KEY")
_PLACES_KEYS: tuple[str, ...] = ("GOOGLE_PLACES_API_KEY", "GOOGLE_MAPS_API_KEY", "GOOGLE_API_KEY")
_SERPER_KEYS: tuple[str, ...] = ("SERPER_API_KEY",)
_ANTHROPIC_KEYS: tuple[str, ...] = ("ANTHROPIC_API_KEY",)


class PreflightGap(BaseModel):
    """One thing that will not happen, why, and the single action that fixes it."""

    what: str
    why: str
    fix: str
    severity: Severity


class PreflightCapability(BaseModel):
    """One piece of work an operator can launch, and what it will really deliver."""

    id: str
    name: str
    group: str
    verdict: Verdict
    summary: str
    #: What this capability WILL do on this deploy, in the operator's words.
    measures: list[str]
    gaps: list[PreflightGap]


class PreflightBoard(BaseModel):
    """The whole board, plus the counts a header renders."""

    spend_halted: bool = Field(serialization_alias="spendHalted")
    ready: int
    partial: int
    blocked: int
    capabilities: list[PreflightCapability]


def _present(value: object) -> bool:
    """Truthiness that treats ``None`` / ``""`` / an empty ``SecretStr`` as absent."""
    getter = getattr(value, "get_secret_value", None)
    raw = getter() if callable(getter) else value
    return bool(raw)


def _any_key(engine_keys: set[str], names: Iterable[str]) -> bool:
    return any(n in engine_keys for n in names)


def _dial_gap(feature: str, label: str, modes: Mapping[str, str]) -> PreflightGap | None:
    """The gap a dial position creates, or None when the dial permits the call.

    ``byhand`` is NOT a gap: it is a deliberate operator choice to do that work
    manually, and reporting a chosen setting as a defect teaches people to ignore the
    board. ``off`` is a gap, because the run will be refused at the gate.
    """
    if modes.get(feature, "") != "off":
        return None
    return PreflightGap(
        what=f"{label} will be refused before it starts",
        why=f"the money dial for '{feature}' is set to off, so the cost gate blocks it",
        fix=f"set the '{feature}' dial to api on the Cost screen",
        severity="blocks",
    )


def _halt_gap(what: str) -> PreflightGap:
    return PreflightGap(
        what=what,
        why="the agency-wide spend halt is engaged, and it blocks every metered feature",
        fix="release the halt on the Cost screen when you are ready to spend again",
        severity="blocks",
    )


def _verdict(gaps: list[PreflightGap]) -> Verdict:
    if any(g.severity == "blocks" for g in gaps):
        return "blocked"
    return "partial" if gaps else "ready"


def _cap(
    id_: str,
    name: str,
    group: str,
    measures: list[str],
    gaps: list[PreflightGap],
    *,
    ready: str,
) -> PreflightCapability:
    verdict = _verdict(gaps)
    if verdict == "ready":
        summary = ready
    elif verdict == "blocked":
        blockers = [g for g in gaps if g.severity == "blocks"]
        first = blockers[0].what if len(blockers) == 1 else f"{len(blockers)} things will stop it"
        summary = first[:1].upper() + first[1:]
    else:
        summary = f"It will run, with {len(gaps)} gap{'' if len(gaps) == 1 else 's'}"
    return PreflightCapability(
        id=id_,
        name=name,
        group=group,
        verdict=verdict,
        summary=summary,
        measures=measures,
        gaps=gaps,
    )


def preflight(
    settings: Settings,
    *,
    vault_providers: Iterable[str] = (),
    dial_modes: Mapping[str, str] | None = None,
    spend_halted: bool = False,
    engine_keys: Iterable[str] = (),
    llm_health: tuple[str, str] | None = None,
) -> PreflightBoard:
    """Every launchable capability with what it will really deliver on this deploy.

    ``engine_keys`` is the set of env var NAMES the AUDIT ENGINE will resolve (its own
    ``.env`` plus the inherited process environment) - not the platform's ``Settings``,
    because the engine does not read those. ``dial_modes`` is the persisted cost-dial
    map; an absent key means that feature's default, which this board treats as
    permitting the call - only an explicit ``off`` blocks.

    ``llm_health`` is ``(verdict, detail)`` from a LIVE probe of the Anthropic key
    (``services.provider_health``), passed in rather than performed here so this function
    stays pure and testable. It answers the question a key-presence check cannot: a key
    can be configured, valid, and attached to an account with no credit - which is exactly
    what happened on 2026-09-26, while this board reported the content pipeline READY and
    every page died at the compose stage. ``None`` means nobody probed, and the board then
    claims nothing either way.
    """
    modes = dict(dial_modes or {})
    vault = {str(p) for p in vault_providers}
    keys = {str(k) for k in engine_keys}

    engine_ready = _present(settings.audit_engine_dir) and _present(settings.audit_engine_python)
    psi = _any_key(keys, _PSI_KEYS)
    serper_engine = _any_key(keys, _SERPER_KEYS)
    places = _any_key(keys, _PLACES_KEYS)
    anthropic_engine = _any_key(keys, _ANTHROPIC_KEYS)

    engine_missing = PreflightGap(
        what="no audit will run at all",
        why="the audit engine is not configured, so there is nothing to invoke",
        fix="set AUDIT_ENGINE_DIR and AUDIT_ENGINE_PYTHON",
        severity="blocks",
    )
    psi_gap = PreflightGap(
        what="Core Web Vitals will be blank",
        why="the engine has no PageSpeed key, so speed scores are skipped",
        fix="add GOOGLE_PAGESPEED_API_KEY (or one unrestricted GOOGLE_API_KEY) to the "
        "audit engine's .env",
        severity="degrades",
    )
    serper_gap = PreflightGap(
        what="search-visibility findings will come back not measured",
        why="the engine has no Serper key, so nothing can look at the SERP",
        fix="add SERPER_API_KEY to the audit engine's .env",
        severity="degrades",
    )

    caps: list[PreflightCapability] = []

    # --- the free lead magnet -------------------------------------------------
    free_gaps: list[PreflightGap] = []
    if not engine_ready:
        free_gaps.append(engine_missing)
    if spend_halted:
        # The free run makes no paid call, but it is still a metered FEATURE and the halt
        # is the gate's FIRST check for every one of them - so the halt does stop it.
        # That surprises people, which is exactly why it belongs on the board.
        free_gaps.append(_halt_gap("the free audit funnel will refuse every request"))
    dial = _dial_gap("public_audit", "The free audit", modes)
    if dial:
        free_gaps.append(dial)
    if not psi:
        free_gaps.append(psi_gap)
    caps.append(
        _cap(
            "audit_free",
            "Free audit (lead magnet)",
            "Audit",
            [
                "A condensed crawl of the site's most important pages",
                "On-page and technical findings, each with evidence",
                "Core Web Vitals" if psi else "No speed scores - PageSpeed is not keyed",
                "A shareable report page and a PDF",
            ],
            free_gaps,
            ready="Ready - and it spends nothing",
        )
    )

    # --- the two metered depths ----------------------------------------------
    for depth_id, depth_name, wants_places, wants_ai in (
        ("audit_standard", "Standard audit", False, False),
        ("audit_deep", "Deep audit", True, True),
    ):
        gaps: list[PreflightGap] = []
        if not engine_ready:
            gaps.append(engine_missing)
        if spend_halted:
            gaps.append(_halt_gap(f"the {depth_name.lower()} will refuse to start"))
        dial = _dial_gap("tech_audit", depth_name, modes)
        if dial:
            gaps.append(dial)
        if not psi:
            gaps.append(psi_gap)
        if not serper_engine:
            gaps.append(serper_gap)
        if wants_places and not places:
            gaps.append(
                PreflightGap(
                    what="the local checks will be skipped for local-business clients",
                    why="the engine has no Places key, so the map pack and GBP presence "
                    "cannot be read",
                    fix="add GOOGLE_PLACES_API_KEY (or a Maps key) to the audit engine's .env",
                    severity="degrades",
                )
            )
        if wants_ai and not anthropic_engine:
            gaps.append(
                PreflightGap(
                    what="the strategy narrative and the AI agent findings will be missing",
                    why="the engine has no Anthropic key, so the agent fan-out does not fire",
                    fix="add ANTHROPIC_API_KEY to the audit engine's .env",
                    severity="degrades",
                )
            )
        measures = [
            "Everything the free audit covers, across more pages",
            "Search visibility against the live SERP"
            if serper_engine
            else "The deterministic crawl only - no SERP data",
        ]
        if wants_places:
            measures.append(
                "Map-pack and citation presence for local clients"
                if places
                else "No local checks - Places is not keyed"
            )
        if wants_ai:
            measures.append(
                "AI agent findings and a written strategy narrative"
                if anthropic_engine
                else "No AI narrative - Anthropic is not keyed engine-side"
            )
            measures.append("A cost estimate you confirm before it runs")
        caps.append(
            _cap(
                depth_id,
                depth_name,
                "Audit",
                measures,
                gaps,
                ready="Ready - every dimension will be measured",
            )
        )

    # --- comparison + sharing: no provider at all ----------------------------
    caps.append(
        _cap(
            "audit_compare",
            "Since-last-audit comparison",
            "Audit",
            [
                "Fixed, new and still-open findings against any earlier run of the same site",
                "Findings this run did not re-check, listed apart and never counted as fixed",
                "A score delta only when both runs measured the same checks",
                "A shareable public link, with views counted and an optional expiry",
            ],
            [],
            ready="Ready - it reads your own stored audits, nothing external",
        )
    )

    # --- content -------------------------------------------------------------
    draft_gaps: list[PreflightGap] = []
    if spend_halted:
        draft_gaps.append(_halt_gap("every page will hold at drafting with $0 spent"))
    dial = _dial_gap("content", "Content drafting", modes)
    if dial:
        draft_gaps.append(dial)
    if not _present(settings.anthropic_api_key):
        draft_gaps.append(
            PreflightGap(
                what="nothing will draft - every page holds at drafting, honestly, at $0",
                why="there is no Anthropic key, so there is no writer",
                fix="set ANTHROPIC_API_KEY",
                severity="blocks",
            )
        )
    elif llm_health is not None and llm_health[0] not in ("ok", "unknown"):
        # THE KEY IS THERE AND IT DOES NOT WORK. A presence check cannot see this, and
        # the board reporting READY over a dead key is worse than reporting nothing: it
        # is the screen an operator trusts before demoing to a client.
        verdict, detail = llm_health
        draft_gaps.append(
            PreflightGap(
                what="nothing will draft - every page fails at the writing stage",
                why=detail or f"the Anthropic key is not usable ({verdict})",
                fix=(
                    "top up the Anthropic account at console.anthropic.com/settings/billing"
                    if verdict == "no_credit"
                    else "replace ANTHROPIC_API_KEY with a working key"
                ),
                severity="blocks",
            )
        )
    if not _present(settings.serper_api_key):
        draft_gaps.append(
            PreflightGap(
                what="nothing will draft - every page holds at drafting, honestly, at $0",
                why="there is no Serper key, and the pipeline refuses to draft from "
                "synthetic research rather than publish invented competitors to a "
                "client's site",
                fix="set SERPER_API_KEY",
                severity="blocks",
            )
        )
    if not (_present(settings.dataforseo_login) and _present(settings.dataforseo_password)):
        draft_gaps.append(
            PreflightGap(
                what="keyword volume and difficulty will be estimated, not measured",
                why="DataForSEO is not configured, so the brief labels those numbers as "
                "estimates",
                fix="set DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD",
                severity="degrades",
            )
        )
    caps.append(
        _cap(
            "content_draft",
            "Content pipeline (research → draft)",
            "Content",
            [
                "A researched brief from the live top-10, per page",
                "A drafted page in the client's own design and voice",
                "The experience gate: a page needing first-hand knowledge halts and asks "
                "rather than inventing it",
                "Named review flags on every draft, before anyone approves it",
            ],
            draft_gaps,
            ready="Ready - pages will research, draft and reach review",
        )
    )

    image_gaps: list[PreflightGap] = []
    if not _present(settings.image_gen_api_key):
        image_gaps.append(
            PreflightGap(
                what="drafts will have no images",
                why="there is no image-generation key, so the image stage is skipped",
                fix="set IMAGE_GEN_API_KEY",
                severity="degrades",
            )
        )
    elif not content_image_dir(settings):
        image_gaps.append(
            PreflightGap(
                what="generated images will be discarded",
                why="the generator returns bytes and no artifact root is configured to "
                "host them",
                fix="set CONTENT_IMAGE_DIR (or CONTENT_ARTIFACT_DIR / AUDIT_ARTIFACT_DIR)",
                severity="degrades",
            )
        )
    caps.append(
        _cap(
            "content_images",
            "Page images",
            "Content",
            [
                "A hero image and section images generated per page",
                "Uploaded into the client's own media library at publish, so their page "
                "does not hotlink to us",
            ],
            image_gaps,
            ready="Ready - pages will be illustrated",
        )
    )

    publish_gaps: list[PreflightGap] = []
    if "wordpress" not in vault:
        publish_gaps.append(
            PreflightGap(
                what="nothing can be published to a client's site",
                why="no WordPress credential is sealed in the vault for any client",
                fix="add a WordPress application password for the client in the Vault",
                severity="blocks",
            )
        )
    caps.append(
        _cap(
            "content_publish",
            "Publish to WordPress",
            "Content",
            [
                "Approved pages pushed to the client's site as a draft or a live post",
                "Images uploaded to their media library and the body rewritten to use them",
                "A record of what we published, so an edit on their side is detected "
                "before we overwrite it",
            ],
            publish_gaps,
            ready="Ready - approved pages can go live",
        )
    )

    counts = {"ready": 0, "partial": 0, "blocked": 0}
    for cap in caps:
        counts[cap.verdict] += 1
    return PreflightBoard(
        spend_halted=spend_halted,
        ready=counts["ready"],
        partial=counts["partial"],
        blocked=counts["blocked"],
        capabilities=caps,
    )


def engine_env_keys(engine_dir: str | None, process_env: Mapping[str, str]) -> set[str]:
    """The env var NAMES the audit engine will actually resolve, from BOTH its sources.

    The engine reads ``<engine_dir>/.env`` via ``load_dotenv`` AND inherits the parent
    process environment (``integrations/audit_engine.py`` passes ``{**os.environ, ...}``).
    ``load_dotenv`` does not override an already-set variable, so presence in EITHER
    source means the engine sees a value - which is why both are unioned rather than
    the file alone being read.

    Only NAMES are returned. A value is read solely to reject a blank assignment
    (``SERPER_API_KEY=`` in a .env is worse than absent: it looks configured), and it is
    never stored, returned or logged.
    """
    names = {k for k, v in process_env.items() if v}
    if not engine_dir:
        return names
    try:
        text = (Path(engine_dir) / ".env").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return names
    for line in text.splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        name, _, value = raw.partition("=")
        # Strip the quoting dotenv accepts, so KEY="v" reads as present while KEY="" does
        # not.
        if value.strip().strip("'\"").strip():
            names.add(name.strip().removeprefix("export ").strip())
    return names
