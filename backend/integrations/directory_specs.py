"""The EARNED directory-spec whitelist (0108), read for extension autofill.

This module is what survived the retirement of the Playwright citation bot
(off-page redesign Phase 3, plan C1). The bot - stealth launch args, fingerprint
masking, human-cadence typing, residential proxy, live CAPTCHA solving - is gone,
and with it the 50-entry unverified ``FORM_SPECS`` seed catalogue. What was worth
keeping is the DATA: ``public.directory_specs`` rows a human verified against the
live DOM and proved with a real listing URL. Those specs now power exactly one
thing - the Chrome extension's autofill in the operator queue (``QueueFieldValue.
selector``): a person opens the form in their own browser, the extension types the
canonical NAP into the selectors an earned spec recorded, and the PERSON reviews
and submits. Nothing here drives a browser, fills a CAPTCHA, or submits a form.

The earned contract is unchanged and still lives in the DATABASE (0108): a spec is
immutable, activation requires a dated human DOM check plus one submission that
produced a public listing URL, and drift deactivates it fail-closed
(``DirectorySpecsRepo.record_drift``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.logging_setup import get_logger

if TYPE_CHECKING:
    from integrations.citation_submitters import CitationJob

logger = get_logger("integrations.directory_specs")


@dataclass(frozen=True)
class FormField:
    """One form field an earned spec describes: a CSS selector + which NAP attribute
    feeds it (or a fixed ``literal:<text>`` value)."""

    selector: str
    value_key: str


@dataclass(frozen=True)
class FormSpec:
    """One directory's add-listing form, as a human verified it: where it lives, which
    selectors take which values, and (historically) how a submission announced success.

    ``submit_selector`` and ``success_indicator`` are retained because the stored 0108
    jsonb carries them and the shape has exactly one reader - but no code clicks the
    submit selector any more. The extension's filler never touches it (the operator
    submits), and the checked outcome is the probe-verified live URL, not a success
    string on a page."""

    directory_name: str
    url: str
    fields: tuple[FormField, ...]
    submit_selector: str
    success_indicator: str


# A spec source consulted PER JOB rather than held as a dict, so activating or
# deactivating a spec takes effect on the next queue read instead of a process restart
# - which matters because deactivation is how drift is contained. Returning None means
# "not earned yet": the queue then offers copy-buttons instead of autofill.
SpecLoader = Callable[["CitationJob"], "FormSpec | None"]


def spec_from_json(raw: dict[str, Any], directory_name: str = "") -> FormSpec:
    """Rehydrate a stored ``directory_specs.spec`` jsonb payload.

    The DB already enforced the shape (0108's ``directory_specs_shape`` CHECK: https
    url, >=1 field, a submit selector, a success indicator), so this does not
    re-validate it. A legacy row that carries a ``captcha`` key is read fine - the key
    is simply ignored, because nothing solves CAPTCHAs any more."""
    return FormSpec(
        directory_name=directory_name,
        url=str(raw["url"]),
        fields=tuple(
            FormField(selector=str(f["selector"]), value_key=str(f["value_key"]))
            for f in raw.get("fields", [])
        ),
        submit_selector=str(raw["submit_selector"]),
        success_indicator=str(raw.get("success_indicator", "")),
    )


def db_spec_loader(job: CitationJob) -> FormSpec | None:
    """A :data:`SpecLoader` over the 0108 whitelist: the ACTIVE spec for one directory,
    or ``None`` when nothing is earned - the honest common case, rendered as
    copy-buttons rather than autofill."""
    specs = active_form_specs(directory_name=job.directory_name)
    return specs.get(job.directory_name)


def active_form_specs(*, directory_name: str | None = None) -> dict[str, FormSpec]:
    """The EARNED whitelist: every directory with an active, verified spec, keyed by
    directory name (what a queue row carries).

    Runs on the privileged connection: the queue read has no need of tenant identity
    and the whitelist is reference data.

    NEVER RAISES. A database that is unreachable, or a schema that predates 0108,
    yields an EMPTY whitelist - the queue then shows copy-buttons everywhere, which is
    the correct direction to fail: a smaller feature, never a fabricated selector."""
    try:
        from app.db.database import privileged_connection
    except Exception:  # pragma: no cover - import-time environment problem
        return {}
    try:
        with privileged_connection() as cur:
            if directory_name is None:
                cur.execute(
                    "select d.name as directory_name, s.spec "
                    "from public.directory_specs s "
                    "join public.directories d on d.id = s.directory_id "
                    "where s.active"
                )
            else:
                cur.execute(
                    "select d.name as directory_name, s.spec "
                    "from public.directory_specs s "
                    "join public.directories d on d.id = s.directory_id "
                    "where s.active and d.name = %s",
                    (directory_name,),
                )
            rows = list(cur.fetchall())
    except Exception:
        logger.info("citation_specs_unavailable", reason="whitelist read failed; no autofill offered")
        return {}

    out: dict[str, FormSpec] = {}
    for row in rows:
        try:
            name = str(row["directory_name"])
            out[name] = spec_from_json(dict(row["spec"]), name)
        except Exception:
            # One malformed row must not deny every other directory its verified spec.
            logger.warning("citation_spec_malformed", directory=str(row.get("directory_name")))
    return out
