"""Semantic form mapping: what does THIS field on THIS page actually want?

WHY THIS EXISTS. The extension can already fill a form correctly - it writes through
the prototype's native value setter so React's internal tracker observes the change,
then reads the value back and reports per-field truth. What it has never had is
somewhere to put things. The field plan comes from ``public.directory_specs`` - human
verified, immutable, "earned" specs - and there are none active, so for essentially
every directory the panel falls back to copy buttons and a person pastes eight fields
by hand, on 200+ directories, forever.

This module is the fallback lane: a structured digest of the open form goes out, a
``{selector -> canonical key}`` plan comes back, and the existing filler consumes it
unchanged. The earned spec always wins where one exists; this is what happens when
one does not.

FOUR RULES THAT SHAPE EVERY DECISION HERE.

1. **The digest is PII-free and it is not the DOM.** What leaves the browser is field
   STRUCTURE - tag, type, name, id, label, placeholder, aria, nearby text, option
   labels, required, step. Never values, never the page HTML, never anything the
   operator has typed. A form intelligence feature that shipped whole pages to a model
   would be exfiltrating client data through a convenience.

2. **The mapping is CACHED BY FORM FINGERPRINT, so the second visit is free.** A
   directory's add-listing form changes rarely; the same form seen again is the same
   mapping. Without this, every operator on every listing pays for the same inference,
   which is how a per-seat feature becomes a per-click bill.

3. **Confidence is carried, and low confidence does not get typed silently.** The
   filler reports what it actually filled; this layer reports how sure it was. A field
   below the review threshold is offered rather than applied, because a phone number
   typed into a "fax" box is worse than an empty box.

4. **IGNORE is a real answer.** Consent checkboxes, captchas, honeypots, search boxes,
   promo codes and "confirm email" duplicates must map to nothing. A mapper that tries
   to fill a honeypot gets the submission silently discarded, and the operator is told
   it worked.

THE OUTPUT IS NOT A PROMISE THAT THE FORM WILL SUBMIT. It is a proposal the operator
reviews and submits themselves - unchanged from the existing workflow, which never
auto-submits and never touches a CAPTCHA.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.logging_setup import get_logger
from integrations.llm import LLMResult

logger = get_logger("app.services.form_intelligence")

#: The canonical business-listing vocabulary a directory field can map to. Kept here
#: (not in a prompt string) so the allowed set, the validator and the client data
#: resolver cannot drift from one another.
CANONICAL_KEYS: tuple[str, ...] = (
    "business_name",
    "phone",
    "email",
    "website",
    "description",
    "address_line1",
    "address_line2",
    "city",
    "region",
    "postal_code",
    "country",
    "category",
    "hours",
    "logo_url",
    "facebook_url",
    "instagram_url",
    "twitter_url",
    "linkedin_url",
    "year_founded",
    "contact_name",
)

#: The explicit "this is not listing data" answer. See rule 4.
IGNORE = "IGNORE"

#: Below this, a mapping is OFFERED but not applied. Tuned conservative on purpose:
#: an unfilled field costs one paste, a wrongly filled one can cost a listing.
APPLY_THRESHOLD = 0.75

#: Field kinds the mapper is allowed to see at all. Anything else (password, file,
#: hidden) is dropped before the digest is built - a password box is never listing
#: data, and a hidden field is usually a honeypot or a CSRF token.
ALLOWED_KINDS = frozenset({
    "text", "tel", "email", "url", "number", "search", "textarea",
    "select", "radio", "checkbox", "contenteditable",
})

#: Never send these, whatever the page calls them. Matched against name/id/label.
# Deliberately PREFIX-matching (no trailing boundary): `cc[-_]?num` with a trailing
# boundary missed `cc_number`, and over-dropping costs the operator one paste while
# under-dropping sends a credential-shaped field to a third party.
_NEVER_SEND = re.compile(
    r"(?:^|[\W_])(?:passw(?:or)?d|pwd|cc[-_]?num|card[-_]?num|cvv|cvc|ssn|"
    r"csrf|xsrf|authenticity[-_]?token|api[-_]?key|secret)",
    re.I,
)

_MAX_FIELDS = 60
_MAX_TEXT = 160
_MAX_OPTIONS = 25


@dataclass(frozen=True)
class FieldDigest:
    """One form field, described STRUCTURALLY. Carries no value the operator typed."""

    index: int
    #: A CSS selector the extension resolved for this field, opaque to the mapper.
    selector: str
    kind: str
    name: str = ""
    element_id: str = ""
    label: str = ""
    placeholder: str = ""
    aria_label: str = ""
    #: Visible text immediately around the field - often the only clue on a form
    #: whose inputs are named f_1..f_9.
    near_text: str = ""
    options: tuple[str, ...] = ()
    required: bool = False
    #: Multi-step forms: which step this field is on, when the page exposes one.
    step: int = 0

    def prompt_view(self) -> dict[str, Any]:
        """What the model sees. The SELECTOR IS DELIBERATELY ABSENT - it is an
        implementation detail the mapper cannot reason about, it can be long, and it
        sometimes embeds page content. The index is the join key."""
        out: dict[str, Any] = {"i": self.index, "kind": self.kind}
        for key, value in (
            ("name", self.name), ("id", self.element_id), ("label", self.label),
            ("placeholder", self.placeholder), ("aria", self.aria_label),
            ("near", self.near_text),
        ):
            if value:
                out[key] = value[:_MAX_TEXT]
        if self.options:
            out["options"] = list(self.options[:_MAX_OPTIONS])
        if self.required:
            out["required"] = True
        if self.step:
            out["step"] = self.step
        return out


@dataclass(frozen=True)
class FieldMapping:
    """One field's resolved meaning."""

    index: int
    selector: str
    key: str
    confidence: float

    @property
    def fillable(self) -> bool:
        """Whether this may be typed WITHOUT the operator confirming it first."""
        return self.key != IGNORE and self.confidence >= APPLY_THRESHOLD


@dataclass(frozen=True)
class FormPlan:
    """The mapper's answer for one form."""

    fingerprint: str
    mappings: tuple[FieldMapping, ...] = ()
    #: True when this came from the cache, so the caller can report a $0 run honestly.
    cached: bool = False
    #: Set when the mapper could not produce a plan. The caller degrades to copy
    #: buttons; it NEVER invents a mapping.
    error: str = ""
    usage: LLMResult | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def to_fill(self) -> tuple[FieldMapping, ...]:
        return tuple(m for m in self.mappings if m.fillable)

    @property
    def to_review(self) -> tuple[FieldMapping, ...]:
        """Mapped, but below the apply threshold - offered, not typed."""
        return tuple(
            m for m in self.mappings
            if m.key != IGNORE and m.confidence < APPLY_THRESHOLD
        )


def sanitize(raw_fields: list[dict[str, Any]]) -> tuple[list[FieldDigest], list[str]]:
    """Turn what the extension collected into a digest that is safe to send.

    This is the privacy boundary, and it is deliberately a WHITELIST: an unknown field
    kind is dropped rather than passed through, so a future browser control cannot
    quietly start travelling. Returns the digest plus the notes explaining anything
    dropped, which the panel shows - a silently shortened form looks like a mapper
    that missed fields.
    """
    digest: list[FieldDigest] = []
    notes: list[str] = []
    dropped_sensitive = dropped_kind = 0

    for raw in raw_fields[:_MAX_FIELDS]:
        kind = str(raw.get("kind") or "").strip().lower()
        if kind not in ALLOWED_KINDS:
            dropped_kind += 1
            continue
        name = str(raw.get("name") or "")
        element_id = str(raw.get("id") or "")
        label = str(raw.get("label") or "")
        if _NEVER_SEND.search(f"{name} {element_id} {label}"):
            # A credential-shaped field never leaves the browser, even as a name.
            dropped_sensitive += 1
            continue
        selector = str(raw.get("selector") or "")
        if not selector:
            continue
        options = tuple(
            str(o)[:_MAX_TEXT] for o in (raw.get("options") or [])[:_MAX_OPTIONS] if o is not None
        )
        digest.append(
            FieldDigest(
                index=len(digest),
                selector=selector,
                kind=kind,
                name=name[:_MAX_TEXT],
                element_id=element_id[:_MAX_TEXT],
                label=label[:_MAX_TEXT],
                placeholder=str(raw.get("placeholder") or "")[:_MAX_TEXT],
                aria_label=str(raw.get("aria") or "")[:_MAX_TEXT],
                near_text=str(raw.get("near") or "")[:_MAX_TEXT],
                options=options,
                required=bool(raw.get("required")),
                step=int(raw.get("step") or 0),
            )
        )

    if len(raw_fields) > _MAX_FIELDS:
        notes.append(
            f"only the first {_MAX_FIELDS} fields were analysed; this form has "
            f"{len(raw_fields)}"
        )
    if dropped_sensitive:
        notes.append(f"{dropped_sensitive} credential-shaped field(s) were not sent")
    if dropped_kind:
        notes.append(f"{dropped_kind} field(s) of an unsupported kind were skipped")
    return digest, notes


def fingerprint(digest: list[FieldDigest], *, host: str) -> str:
    """A stable id for THIS form on THIS host, for the cache.

    Built from the host plus each field's structural identity - NOT from the selectors
    (which can carry generated class names that change per page load) and NOT from the
    order alone. Two visits to the same add-listing form produce the same fingerprint;
    a form that gained a field produces a different one, which is exactly when the
    mapping must be recomputed rather than reused.
    """
    parts = [host.strip().lower()]
    for f in sorted(digest, key=lambda d: (d.kind, d.name, d.element_id, d.label)):
        parts.append("|".join((f.kind, f.name, f.element_id, f.label, f.placeholder)))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


SYSTEM_PROMPT = (
    "You map web form fields to canonical business-listing data keys for a directory "
    "submission. You are given field STRUCTURE only - never values.\n"
    "Answer with a JSON array and nothing else: objects with keys \"i\" (the field "
    "index you were given), \"key\" (one canonical key, or IGNORE), and \"confidence\" "
    "(0.0-1.0, your honest certainty).\n"
    "Rules:\n"
    "- Every field you were given gets exactly one entry. Do not invent indices.\n"
    "- Use IGNORE for anything that is not business listing data: consent checkboxes, "
    "captchas, honeypots, search boxes, promo/coupon codes, quantity pickers, and "
    "DUPLICATE confirmation fields such as 'confirm email'.\n"
    "- A field whose meaning is genuinely unclear gets its best key with a LOW "
    "confidence, not a guess with a high one. Low confidence is reviewed by a human; "
    "an overconfident wrong answer is typed into a live form.\n"
    "- Prefer the label over the name attribute when they disagree: the label is what "
    "the person filling the form actually reads."
)


def build_prompt(digest: list[FieldDigest]) -> str:
    """The user half of the request. Kept separate from the system half so the system
    prompt is a stable cache prefix across every form."""
    return (
        "Canonical keys: " + ", ".join((*CANONICAL_KEYS, IGNORE)) + "\n\n"
        "FIELDS:\n" + json.dumps([f.prompt_view() for f in digest], indent=1)
    )


def parse_response(text: str, digest: list[FieldDigest]) -> tuple[list[FieldMapping], list[str]]:
    """Turn the model's reply into mappings, discarding anything it made up.

    EVERY entry is validated against the digest and the canonical vocabulary: an
    unknown index, an unknown key or a non-numeric confidence is dropped with a note
    rather than trusted. The model is a suggestion engine here, not an authority - it
    is proposing what to type into somebody's live business listing.
    """
    notes: list[str] = []
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return [], ["the mapper did not return a JSON array"]
    try:
        raw = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return [], ["the mapper's response was not valid JSON"]
    if not isinstance(raw, list):
        return [], ["the mapper's response was not a list"]

    by_index = {f.index: f for f in digest}
    seen: set[int] = set()
    out: list[FieldMapping] = []
    invented = unknown_key = 0

    for item in raw:
        if not isinstance(item, dict):
            continue
        rank_index = item.get("i")
        if rank_index is None:
            continue
        try:
            index = int(rank_index)
        except (TypeError, ValueError):
            continue
        field_digest = by_index.get(index)
        if field_digest is None or index in seen:
            invented += 1
            continue
        key = str(item.get("key") or "").strip()
        if key not in CANONICAL_KEYS and key != IGNORE:
            unknown_key += 1
            continue
        try:
            confidence = float(item.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        seen.add(index)
        out.append(
            FieldMapping(
                index=index,
                selector=field_digest.selector,
                key=key,
                confidence=max(0.0, min(1.0, confidence)),
            )
        )

    if invented:
        notes.append(f"{invented} mapping(s) referenced a field that was not sent")
    if unknown_key:
        notes.append(f"{unknown_key} mapping(s) used a key outside the vocabulary")
    missing = [f.index for f in digest if f.index not in seen]
    if missing:
        # Not an error: an unmapped field simply stays a copy button. Said out loud so
        # the panel does not look like it quietly skipped part of the form.
        notes.append(f"{len(missing)} field(s) were left unmapped")
    return out, notes


def plan_form(
    summarizer: Any,
    raw_fields: list[dict[str, Any]],
    *,
    host: str,
    model: str,
    max_tokens: int = 1500,
) -> FormPlan:
    """Analyse one form and return its plan. NEVER raises.

    A failure here must leave the operator exactly where they were - copy buttons and
    a paste - rather than breaking the panel. So every failure path returns a
    ``FormPlan`` carrying its reason, and none of them fabricate a mapping.
    """
    digest, notes = sanitize(raw_fields)
    if not digest:
        return FormPlan(fingerprint="", error="no fillable fields were found on this page",
                        notes=tuple(notes))

    fp = fingerprint(digest, host=host)
    try:
        result = summarizer.summarize(
            build_prompt(digest),
            model=model,
            max_tokens=max_tokens,
            system=SYSTEM_PROMPT,
        )
    except TypeError:
        # A plain Summarizer (no `system` support). Fold the contract into the prompt
        # rather than losing it.
        try:
            result = summarizer.summarize(
                SYSTEM_PROMPT + "\n\n" + build_prompt(digest),
                model=model,
                max_tokens=max_tokens,
            )
        except Exception:
            logger.exception("form_intelligence_failed", host=host)
            return FormPlan(fingerprint=fp, error="the form mapper is unavailable",
                            notes=tuple(notes))
    except Exception:
        logger.exception("form_intelligence_failed", host=host)
        return FormPlan(fingerprint=fp, error="the form mapper is unavailable",
                        notes=tuple(notes))

    mappings, parse_notes = parse_response(result.text, digest)
    notes.extend(parse_notes)
    if not mappings:
        return FormPlan(
            fingerprint=fp,
            error="the form could not be mapped",
            usage=result,
            notes=tuple(notes),
        )
    return FormPlan(
        fingerprint=fp,
        mappings=tuple(mappings),
        usage=result,
        notes=tuple(notes),
    )


def apply_values(plan: FormPlan, values: dict[str, str]) -> list[dict[str, str]]:
    """Turn a plan plus the client's canonical facts into the filler's field plan.

    The shape returned is EXACTLY what ``extension/src/content/filler.ts`` already
    consumes (``{selector, valueKey, value}``), which is the point: the semantic lane
    and the earned-spec lane produce the same instruction, so the read-back honesty
    layer that reports per-field success is unchanged and untouched by this feature.

    A mapped field with no value for its key is omitted - typing an empty string into
    a directory form is not neutral, it can clear a pre-filled default.
    """
    out: list[dict[str, str]] = []
    for mapping in plan.to_fill:
        value = (values.get(mapping.key) or "").strip()
        if not value:
            continue
        out.append({"selector": mapping.selector, "valueKey": mapping.key, "value": value})
    return out
