"""The SME stage - collect first-party Experience, or HALT.

This is Law 16 made operational, and the owner's standing decision made enforceable.

WHY A HALT AND NOT A WARNING. Experience is the one E-E-A-T signal no competitor and
no model can scrape, because it lives only in the operator's head and invoice history.
Ask a model to write it anyway and it will - fluently, plausibly, and invented:
"our team has seen", "over 1,200 jobs", "years of experience". That output is
indistinguishable from the real thing AS PROSE, so no downstream reader, reviewer or
scorer can catch it. The only place it can be stopped is before drafting, by refusing
to start.

WHAT THIS STAGE ACTUALLY DOES:

  1. Ensures a dossier exists for the page's cluster - per CLUSTER, not per page,
     because the questions that unlock "emergency AC repair" unlock every page in that
     cluster. Asking once is the difference between three questions and thirty.
  2. Generates the questions if there are none, using the corpus's own
     `sme-interviewer` agent as the stage role. ONE call per cluster, on the cheap
     tier - this is question drafting, not prose.
  3. Refuses to proceed while any slot is unanswered, and names exactly which
     artifacts are missing so the operator answers three specific questions rather
     than filling in a generic intake form.

WHAT IT DOES NOT DO: invent, infer, or soften an answer. A slot with no answer stays
unanswered. There is no "assume the usual" path, because that is precisely the
fabrication the whole gate exists to prevent.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from app.services.content_pipeline.context import PipelineContext, StageResult
from app.services.content_pipeline.writer import DoctrineWriter, WriteAccounting

STAGE = "sme"

# Proof categories, named to match what `content_lint.experience` reports as MISSING.
# That correspondence is the point: the gate says "this claim needs a license_permit",
# and the questionnaire has a slot called exactly that.
BASE_SLOTS: tuple[str, ...] = ("founding_date", "license_permit", "count_source")

# Extra categories a page type genuinely needs. A service page lives or dies on proof
# of work; an about page is ABOUT the people, so a named team member is not optional
# there; a local page needs something tying the business to the place.
PAGE_TYPE_SLOTS: dict[str, tuple[str, ...]] = {
    "service": ("photo", "review_source"),
    "local": ("photo", "review_source"),
    "about": ("named_team", "photo"),
    "faq": (),
    "blog": (),
    "gbp_post": (),
    "homepage": ("named_team", "review_source"),
    "location": ("photo",),
    "service_area": ("photo",),
}

# Human-readable prompts, used when the model is unavailable or returns junk. These
# are DEFAULTS, not filler: a real operator can answer them as they stand, so a
# degraded run still produces a usable questionnaire rather than an empty one.
FALLBACK_QUESTIONS: dict[str, str] = {
    "founding_date": "What year did the business start trading, and is there a public "
                     "record of it (a registration, an incorporation date, a first review)?",
    "license_permit": "What is the licence, permit or registration NUMBER, and which "
                      "body issued it?",
    "count_source": "How many of these jobs have you completed, over what period, and "
                    "what backs that number (invoices, a CRM export, a job log)?",
    "photo": "Can you supply an original dated photo of your own crew or work on this "
             "service? Not a stock image.",
    "review_source": "Where can your reviews be read, and how many are there right now?",
    "named_team": "Which named person leads this work, and what is their role and "
                  "credential?",
    "credential_source": "What certification or accreditation do you hold for this, and "
                         "who can verify it?",
}


class DossierStore(Protocol):
    def get_or_create_dossier(self, *, engagement_id: str, cluster_key: str = "") -> Any: ...
    def upsert_slot(self, **kwargs: Any) -> None: ...
    def refresh_dossier_status(self, dossier_id: str) -> str: ...


def required_slots(page_type: str) -> tuple[str, ...]:
    """The proof categories this page type must be able to back."""
    extra = PAGE_TYPE_SLOTS.get(page_type, PAGE_TYPE_SLOTS["service"])
    seen: list[str] = []
    for key in (*BASE_SLOTS, *extra):
        if key not in seen:
            seen.append(key)
    return tuple(seen)


def _parse_questions(raw: str, wanted: tuple[str, ...]) -> dict[str, str]:
    """Pull ``{slot_key: question}`` out of the model's reply.

    Tolerant by design: a malformed reply degrades to the fallbacks rather than
    failing the stage, because the questionnaire's job is to be answerable, and a
    slightly blunter question the operator can answer beats no question at all.
    """
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {
        key: str(value).strip()
        for key, value in parsed.items()
        if key in wanted and isinstance(value, str) and value.strip()
    }


def _question_prompt(ctx: PipelineContext, wanted: tuple[str, ...]) -> str:
    return "\n".join([
        f"A local {ctx.page_type} page is being written for {ctx.client_name or 'this client'} "
        f"targeting '{ctx.primary_keyword}'"
        + (f" in {ctx.geo}" if ctx.geo else "")
        + ".",
        "",
        "Write ONE interview question per proof category below. Each question must ask "
        "for a SPECIFIC, checkable artifact the operator can actually produce - a "
        "number, a date, a document, a named person, a photo they own. Never ask "
        "something answerable with an adjective.",
        "",
        "Proof categories: " + ", ".join(wanted),
        "",
        'Reply with ONLY a JSON object mapping each category to its question, e.g. '
        '{"founding_date": "...", "license_permit": "..."}',
    ])


def run_sme(
    ctx: PipelineContext,
    *,
    store: DossierStore,
    writer: DoctrineWriter | None = None,
    cluster_key: str = "",
) -> StageResult:
    """Ensure the dossier exists and is answered, or halt.

    Returns ``halted`` when anything is missing. A halt is the system working, not an
    error: it must not be retried or alerted on.
    """
    accounting = WriteAccounting()
    notes: list[str] = []

    if not ctx.engagement_id:
        # No engagement means no dossier can exist. Halting rather than skipping is
        # deliberate: a page drafted with no Experience store is exactly the
        # ungoverned path this stage exists to close.
        return ctx.record(StageResult(
            STAGE, outcome="halted",
            notes=("no engagement: the Experience dossier has nowhere to live",),
        ))

    key = cluster_key or ctx.primary_keyword.strip().lower()
    dossier = store.get_or_create_dossier(engagement_id=ctx.engagement_id, cluster_key=key)
    wanted = required_slots(ctx.page_type)
    existing = {s.slot_key for s in dossier.slots}
    missing_slots = tuple(k for k in wanted if k not in existing)

    if missing_slots:
        questions: dict[str, str] = {}
        if writer is not None:
            try:
                raw = writer.write(
                    STAGE,
                    _question_prompt(ctx, missing_slots),
                    page_type=ctx.page_type,
                    vertical=ctx.vertical or None,
                    max_tokens=900,
                    expected_calls=1,
                    accounting=accounting,
                )
                questions = _parse_questions(raw, missing_slots)
            except Exception as exc:  # spend block / provider error
                # Degrade to the fallbacks. The questionnaire still exists and is
                # still answerable, which is what the halt needs.
                notes.append(f"question generation unavailable ({type(exc).__name__}); "
                             "using the default interview questions")
        for slot_key in missing_slots:
            store.upsert_slot(
                dossier_id=dossier.id,
                slot_key=slot_key,
                question=questions.get(slot_key) or FALLBACK_QUESTIONS.get(slot_key, ""),
            )
        store.refresh_dossier_status(dossier.id)
        dossier = store.get_or_create_dossier(engagement_id=ctx.engagement_id, cluster_key=key)

    if not dossier.complete:
        outstanding = [s.slot_key for s in dossier.unanswered]
        notes.append(
            "Experience not collected. The operator must supply: " + ", ".join(outstanding)
        )
        # Even halted, publish what IS known: a later re-run reuses answered slots.
        ctx.proof_signals = dossier.proof_signals()
        return ctx.record(StageResult(
            STAGE, outcome="halted", notes=tuple(notes),
            data={"dossier_id": dossier.id, "missing": outstanding,
                  "questions": {s.slot_key: s.question for s in dossier.unanswered}},
            cost=accounting.cost, llm_calls=accounting.calls,
            input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
            cache_write_tokens=accounting.cache_write_tokens,
            cache_read_tokens=accounting.cache_read_tokens,
            chunk_ids=tuple(accounting.chunk_ids),
        ))

    ctx.proof_signals = dossier.proof_signals()
    ctx.facts = tuple(
        f"{s.slot_key}: {s.answer}".strip() for s in dossier.answered if s.answer.strip()
    )
    return ctx.record(StageResult(
        STAGE, outcome="ok", notes=tuple(notes),
        data={"dossier_id": dossier.id, "signals": sorted(ctx.proof_signals)},
        cost=accounting.cost, llm_calls=accounting.calls,
        input_tokens=accounting.input_tokens, output_tokens=accounting.output_tokens,
        cache_write_tokens=accounting.cache_write_tokens,
        cache_read_tokens=accounting.cache_read_tokens,
        chunk_ids=tuple(accounting.chunk_ids),
    ))
