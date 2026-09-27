"""Two local-audit defects, each a case of a guarantee that lived only in prose.

1. ``Place.identity_verified`` REACHED NOTHING. ``find_place`` graded whether the
   matched Google Business Profile actually belongs to the audited domain, and its
   docstring instructed "the caller must treat every profile-derived verdict as
   low-confidence". No caller did. The flag's only consumer was a ``console.print``,
   so an unverified profile - possibly a different company's - produced findings at
   ``confidence=1.0`` and could report ``critical`` remediation about a listing the
   client cannot edit. Now :func:`identity_of` grades the evidence and
   :func:`qualify_for_identity` applies the consequence to every GBP-derived verdict
   at ONE seam, so a GBP check added later cannot forget it.

2. The NAP check LOOKED IN THE WRONG PLACE. ``check_nap_consistency_on_site`` joined
   each page's title, meta description and headings, on the written assumption that
   "on a footer-laden site the relevant tokens are usually here". A NAP block is
   footer BODY text and a contact page's address is a paragraph, so a site with a
   correct NAP on every page scored ``fail`` / ``critical``. ``body_text`` was
   already parsed and free.

Re-inject either and the matching test fails.
"""

from __future__ import annotations

import pytest

from audit_engine.analyzers.local import (
    GBP_DERIVED_CHECKS,
    IDENTITY_CORROBORATED,
    IDENTITY_DOMAIN,
    IDENTITY_UNCHECKED,
    IDENTITY_UNVERIFIED,
    UNVERIFIED_SEVERITY_CAP,
    check_nap_consistency_on_site,
    identity_of,
    iter_local_findings,
    qualify_for_identity,
    site_text_of,
)
from audit_engine.integrations.places import Place
from audit_engine.parsers.html import Heading, ParsedHTML

pytestmark = pytest.mark.unit

_GBP_ADDRESS = "1200 Wilshire Blvd, Suite 400, Los Angeles, CA 90017, USA"
_GBP_PHONE = "+1 213-555-0142"


def _place(**over: object) -> Place:
    base: dict[str, object] = {
        "place_id": "place-1",
        "name": "Ace Plumbing",
        "formatted_address": _GBP_ADDRESS,
        "phone": _GBP_PHONE,
        "website": None,
        "primary_type": "plumber",
        "identity_verified": False,
    }
    base.update(over)
    return Place(**base)  # type: ignore[arg-type]


def _page(
    *,
    url: str = "https://ace.example/contact",
    title: str = "Contact",
    body_text: str = "",
    headings: tuple[str, ...] = (),
    meta: str | None = None,
) -> ParsedHTML:
    return ParsedHTML(
        url=url,
        title=title,
        meta_description=meta,
        body_text=body_text,
        headings=[Heading(level=2, text=h) for h in headings],
    )


# --------------------------------------------------------------------------- #
# 1. The identity ladder.
# --------------------------------------------------------------------------- #
def test_a_domain_match_is_the_strongest_grade() -> None:
    assert identity_of(_place(identity_verified=True), []) == IDENTITY_DOMAIN


def test_the_gbp_phone_on_the_site_corroborates_identity() -> None:
    """A business publishing this phone number on its own site is strong evidence the
    listing is theirs - and it costs nothing, because the page is already crawled.
    This is the case the domain check CANNOT cover: a great many legitimate GBPs
    carry no website at all, so without corroboration they were all 'unverified'."""
    page = _page(body_text="Call us on (213) 555-0142 for a free quote.")
    assert identity_of(_place(), [page]) == IDENTITY_CORROBORATED


def test_the_phone_matches_on_digits_not_formatting() -> None:
    """The site writes 213.555.0142, Google writes +1 213-555-0142. Comparing the
    formatted strings would miss every real site."""
    page = _page(body_text="Reach the shop at 213.555.0142.")
    assert identity_of(_place(), [page]) == IDENTITY_CORROBORATED


def test_street_number_and_postal_code_together_corroborate() -> None:
    page = _page(body_text="Visit us at 1200 Wilshire Blvd, Los Angeles CA 90017.")
    assert identity_of(_place(phone=None), [page]) == IDENTITY_CORROBORATED


def test_a_street_number_alone_does_not_corroborate() -> None:
    """'1200' appears on plenty of pages that are not this address. A signal that
    fires on a number alone would mark almost every profile corroborated, which is
    the same failure as never checking."""
    page = _page(body_text="Over 1200 jobs completed this year.")
    assert identity_of(_place(phone=None), [page]) == IDENTITY_UNVERIFIED


def test_nothing_matching_stays_unverified() -> None:
    page = _page(body_text="We are a plumbing company serving the whole county.")
    assert identity_of(_place(), [page]) == IDENTITY_UNVERIFIED


def test_no_crawled_pages_is_unchecked_rather_than_unverified() -> None:
    """"We looked and found nothing" and "there was nothing to look at" are different
    statements. Both carry the same consequences - the severity cap and the confidence
    discount - but the finding says which, because a report that claims it checked the
    site's text when no page was crawled is the same class of overclaim this module was
    fixed for."""
    assert identity_of(_place(), []) == IDENTITY_UNCHECKED
    assert identity_of(_place(), None) == IDENTITY_UNCHECKED


def test_both_unproven_grades_take_the_cap_and_the_discount() -> None:
    """The grades differ in what they SAY, never in how much they are trusted."""
    for grade in (IDENTITY_UNVERIFIED, IDENTITY_UNCHECKED):
        out = qualify_for_identity(_critical(), _place(), grade)  # type: ignore[arg-type]
        assert out.severity == UNVERIFIED_SEVERITY_CAP, grade
        assert out.confidence < 1.0, grade
        assert out.evidence["gbp_identity"] == grade
        assert out.remediation is not None and "confirm" in out.remediation.lower()


def test_the_unchecked_basis_does_not_claim_the_site_was_read() -> None:
    unchecked = qualify_for_identity(_critical(), _place(), IDENTITY_UNCHECKED)  # type: ignore[arg-type]
    assert "no crawled pages" in unchecked.evidence["gbp_identity_basis"]
    unverified = qualify_for_identity(_critical(), _place(), IDENTITY_UNVERIFIED)  # type: ignore[arg-type]
    assert "site's own text" in unverified.evidence["gbp_identity_basis"]


# --------------------------------------------------------------------------- #
# 2. The consequence: what an unverified profile is allowed to claim.
# --------------------------------------------------------------------------- #
def _critical() -> object:
    from audit_engine.analyzers.common import Verdict

    return Verdict(
        "fail", 0.0, "critical", 1.0,
        {"missing_fields": ["hours", "phone"]},
        "Add to GBP: hours, phone.",
    )


def test_an_unverified_profile_cannot_raise_a_critical() -> None:
    """THE defect. A profile matched by name alone produced critical findings with
    remediation telling the client to edit a listing that may not be theirs."""
    out = qualify_for_identity(_critical(), _place(), IDENTITY_UNVERIFIED)  # type: ignore[arg-type]
    assert out.severity == UNVERIFIED_SEVERITY_CAP
    assert out.confidence < 1.0


def test_an_unverified_finding_says_to_confirm_the_listing_first() -> None:
    """The client's actual first action is to check WHICH listing this is, so that
    instruction comes before the fix - and names the candidate so it takes seconds."""
    out = qualify_for_identity(_critical(), _place(), IDENTITY_UNVERIFIED)  # type: ignore[arg-type]
    assert out.remediation is not None
    assert "confirm" in out.remediation.lower()
    assert "Ace Plumbing" in out.remediation
    assert "Add to GBP" in out.remediation  # the original fix is kept, not replaced
    assert out.evidence["gbp_candidate_address"] == _GBP_ADDRESS


def test_a_domain_verified_profile_keeps_its_severity_and_confidence() -> None:
    """The discount must not punish a profile we actually proved. A verified GBP
    missing four fields IS critical."""
    out = qualify_for_identity(_critical(), _place(identity_verified=True), IDENTITY_DOMAIN)  # type: ignore[arg-type]
    assert out.severity == "critical"
    assert out.confidence == 1.0
    assert out.evidence["gbp_identity"] == IDENTITY_DOMAIN


def test_a_corroborated_profile_keeps_its_severity_but_is_discounted() -> None:
    """Corroboration is inference, not proof - so the finding is actionable (it can
    still be critical) and slightly less confident."""
    out = qualify_for_identity(_critical(), _place(), IDENTITY_CORROBORATED)  # type: ignore[arg-type]
    assert out.severity == "critical"
    assert 0.0 < out.confidence < 1.0


def test_an_n_a_verdict_is_returned_untouched() -> None:
    from audit_engine.analyzers.common import Verdict

    original = Verdict("n_a", 0.0, "info", 0.4, {"reason": "GOOGLE_API_KEY not set"})
    assert qualify_for_identity(original, _place(), IDENTITY_UNVERIFIED) is original


def test_every_gbp_derived_check_carries_the_identity_grade() -> None:
    """The seam, not the individual checks. This is what stops the next GBP check
    shipping without the discount - which is exactly how the original defect
    survived: the rule lived in find_place's docstring and in nothing that ran."""
    findings = {
        cid: verdict
        for cid, _cat, _agent, verdict in iter_local_findings(
            place=_place(), citations=None, parsed_pages=[_page(body_text="plumbing")]
        )
    }
    assert set(findings) >= GBP_DERIVED_CHECKS
    for check_id in GBP_DERIVED_CHECKS:
        verdict = findings[check_id]
        if verdict.status == "n_a":
            continue
        assert verdict.evidence.get("gbp_identity") == IDENTITY_UNVERIFIED, check_id
        assert verdict.severity in ("info", UNVERIFIED_SEVERITY_CAP), check_id


def test_the_nap_check_is_graded_for_context_but_not_severity_capped() -> None:
    """LOC-013's subject is the SITE - does it publish a NAP at all - and that is
    worth answering whoever the profile belongs to. So it carries the grade for
    context and keeps its severity."""
    findings = {
        cid: verdict
        for cid, _cat, _agent, verdict in iter_local_findings(
            place=_place(), citations=None,
            parsed_pages=[_page(body_text="no address or phone here")],
        )
    }
    nap = findings["LOC-013"]
    assert nap.evidence.get("gbp_identity") == IDENTITY_UNVERIFIED
    assert nap.severity == "critical"  # NOT capped


# --------------------------------------------------------------------------- #
# 3. Where the NAP check looks.
# --------------------------------------------------------------------------- #
def test_site_text_includes_the_body() -> None:
    text = site_text_of(_page(title="Contact", body_text="1200 Wilshire Blvd", headings=("Visit",)))
    assert "1200 wilshire blvd" in text
    assert "contact" in text and "visit" in text


def test_a_footer_nap_is_found_and_passes() -> None:
    """THE defect. This exact site - address and phone in the footer of every page,
    nowhere in a title or heading - used to score fail/critical with
    "Neither GBP address nor phone appears on the site"."""
    footer = f"Ace Plumbing - {_GBP_ADDRESS} - {_GBP_PHONE} - (c) 2026"
    pages = [
        _page(url=f"https://ace.example/p{i}", title=f"Page {i}", body_text=f"Some copy. {footer}")
        for i in range(5)
    ]
    verdict = check_nap_consistency_on_site(_place(), pages)
    assert verdict.status == "pass"
    assert verdict.evidence["address_matches"] == 5
    assert verdict.evidence["phone_matches"] == 5


def test_a_site_with_no_nap_anywhere_still_fails() -> None:
    """The fix widened where we look; it must not make the check toothless. A site
    that genuinely publishes no NAP is still a critical finding."""
    pages = [_page(url=f"https://ace.example/p{i}", body_text="We fix pipes.") for i in range(4)]
    verdict = check_nap_consistency_on_site(_place(), pages)
    assert verdict.status == "fail"
    assert verdict.severity == "critical"
    assert verdict.evidence["address_matches"] == 0


def test_the_verdict_records_what_it_read() -> None:
    """A disputed NAP verdict has to be traceable to the evidence rather than to the
    reader's guess about where we looked - which is what made the original bug hard
    to see from the report."""
    verdict = check_nap_consistency_on_site(_place(), [_page(body_text="x")])
    assert "body text" in verdict.evidence["read"]


def test_a_nap_only_in_headings_is_still_found() -> None:
    """Headings stayed in the scan: a contact page routinely puts the address in an
    <h2>, and dropping them to 'fix' the body omission would trade one miss for
    another."""
    pages = [_page(body_text="", headings=(_GBP_ADDRESS, "Call " + _GBP_PHONE))]
    verdict = check_nap_consistency_on_site(_place(), pages)
    assert verdict.evidence["address_matches"] == 1
