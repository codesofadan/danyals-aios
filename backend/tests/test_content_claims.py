"""The claims-grounding triggers: which sentences must cite a supplied fact.

Every quote marked REAL below is a verbatim sentence from the six pages generated
for a live client on 2026-08-30, after the operator had truthfully answered that
the company has no clients in those verticals, no certification, no reviews and no
photographs. The pipeline invented them anyway. They are the regression corpus.
"""

from __future__ import annotations

import pytest

from app.services.content_pipeline.claims import (
    AUTO_DELETE_TRIGGERS,
    REVIEW_TRIGGERS,
    Atom,
    build_atoms,
    needs_citation,
    render_atoms,
    strip_citations,
    unknown_contact,
    vendor_pattern,
)

CONTACTS = frozenset({"business.zainsaeed@gmail.com", "+923088040606", "northwind.com"})


# --------------------------------------------------------------------------- #
# Atoms
# --------------------------------------------------------------------------- #

class TestAtoms:
    def test_facts_are_numbered_so_a_sentence_can_point_at_one(self) -> None:
        atoms = build_atoms(["founded 2013", "7 client accounts"])
        assert [a.id for a in atoms] == ["a1", "a2"]
        assert atoms[0].source == "experience"

    def test_experience_answers_outrank_the_brief(self) -> None:
        # A dossier answer is something a human was made to sit down and write; a
        # brief bullet is cheaper to produce and easier to overstate.
        atoms = build_atoms(["dossier fact"], brief_facts=["brief fact"])
        assert atoms[0].text == "dossier fact"
        assert [a.source for a in atoms] == ["experience", "brief"]

    def test_blanks_and_duplicates_are_dropped_so_ids_stay_meaningful(self) -> None:
        atoms = build_atoms(["  ", "same fact", "SAME FACT", ""], brief_facts=["same fact"])
        assert len(atoms) == 1

    def test_the_rendered_block_carries_the_id_the_writer_must_cite(self) -> None:
        assert render_atoms([Atom("a1", "founded 2013", "experience")]) == "  [[a1]] founded 2013"

    @pytest.mark.parametrize(("raw", "want"), [
        ("We were founded in 2013 [[a1]].", "We were founded in 2013."),
        ("Founded 2013 [[a1]], with 7 accounts [[a2]].", "Founded 2013, with 7 accounts."),
        ("No citations here.", "No citations here."),
    ])
    def test_markers_never_reach_the_published_page(self, raw: str, want: str) -> None:
        assert strip_citations(raw) == want


# --------------------------------------------------------------------------- #
# The triggers, against the real corpus
# --------------------------------------------------------------------------- #

class TestTheRealFabricationsAreCaught:
    @pytest.mark.parametrize("sentence", [
        # REAL - healthcare page, company has zero healthcare clients
        "Each verification agent scores compliance against the relevant state regulations"
        " and federal rules (HIPAA, CMS, state patient-data laws).",
        "Another verifies the DEA number and controlled-substance prescribing eligibility.",
        "The architecture supports HIPAA-grade compliance logging, data isolation, and audit trails.",
        # REAL - real-estate page, zero real-estate clients
        "It flags liens and encumbrances against title databases.",
        "Cross-verified against three external sources - public records, comps databases,"
        " and title records - in real time.",
        # REAL - absolute data-handling assurances, nothing supplied backs them
        "No data leaves your systems.",
        'Zero data movement to Northwind servers, zero export-import cycles, zero "data residency" risk.',
        # REAL - a published warranty
        "We commit to an accuracy threshold in the audit.",
        # REAL - invented third-party integrations
        "Integration into Salesforce, HubSpot, or Pipedrive happens via standard APIs;"
        " data flows both directions so your CRM stays current without manual entry.",
    ])
    def test_it_fires(self, sentence: str) -> None:
        assert needs_citation(sentence, allowed_contacts=CONTACTS), sentence

    def test_an_invented_contact_address_is_caught(self) -> None:
        # The one defect that costs the client money on a page that reads perfectly:
        # every lead the page generates is routed to an address nobody owns.
        fired = needs_citation("email us at hello@northwind.com", allowed_contacts=CONTACTS)
        assert "T7-CONTACT" in fired

    def test_the_operators_own_contact_details_pass(self) -> None:
        assert unknown_contact("Call +92 308 804 0606 today.", CONTACTS) is None


class TestLegitimateProseSurvives:
    @pytest.mark.parametrize("sentence", [
        # A general industry statement is TRUE and is not a claim about the vendor.
        "Healthcare providers must comply with HIPAA.",
        "Dental practices must comply with HIPAA.",
        # A question is not an assertion.
        "Is there a HIPAA-compliant option?",
    ])
    def test_it_does_not_fire(self, sentence: str) -> None:
        assert not needs_citation(sentence, allowed_contacts=CONTACTS), sentence

    @pytest.mark.parametrize("sentence", [
        "We hold no regulatory approval.",
        "Northwind has no published HIPAA audit or certification.",
        "Acme Dental holds no certification of any kind.",
        "Your clinic's HIPAA compliance is your IT and legal team's responsibility.",
    ])
    def test_an_honest_disclaimer_is_never_deleted(self, sentence: str) -> None:
        # Deleting a retraction makes the page LESS true than the writer left it -
        # strictly worse than the fabrication this module removes.
        vendor = vendor_pattern(["Northwind", "Acme Dental"])
        assert not needs_citation(sentence, allowed_contacts=CONTACTS, vendor=vendor), sentence


class TestTheVendorSubjectGate:
    def test_a_compliance_claim_needs_a_vendor_subject(self) -> None:
        # Measured: without this gate T3's false-positive rate is 29.5%; with it, 4%.
        assert "T3-COMPLIANCE" not in needs_citation("Clinics must comply with HIPAA.")
        assert "T3-COMPLIANCE" in needs_citation("Our audit trail satisfies state board inspections.")

    def test_the_clients_own_name_counts_as_the_vendor(self) -> None:
        # A page written in the third person says "Acme Dental is HIPAA compliant",
        # which the generic we/our gate cannot see.
        sentence = "Acme Dental is HIPAA compliant and certified."
        assert "T3-COMPLIANCE" not in needs_citation(sentence)
        assert "T3-COMPLIANCE" in needs_citation(sentence, vendor=vendor_pattern(["Acme Dental"]))

    def test_a_multi_word_client_name_is_matched_whole(self) -> None:
        # re.escape already escapes the space for VERBOSE mode; escaping it twice
        # yields a pattern that matches a literal backslash and therefore nothing.
        assert vendor_pattern(["Acme Dental"]).search("Acme Dental ships it.")
        assert not vendor_pattern(["Acme Dental"]).search("AcmeDental ships it.")

    def test_a_client_name_with_regex_characters_does_not_explode(self) -> None:
        assert vendor_pattern(["C++ Systems (UK)"]).search("C++ Systems (UK) is certified.")


class TestTheTwoLanes:
    def test_the_lanes_are_disjoint_and_cover_every_trigger(self) -> None:
        assert not (AUTO_DELETE_TRIGGERS & REVIEW_TRIGGERS)
        assert len(AUTO_DELETE_TRIGGERS | REVIEW_TRIGGERS) == 7

    def test_the_legal_classes_are_the_ones_deleted_automatically(self) -> None:
        # Measured 7.4% false positives on this lane versus 19.8% on the review
        # lane, and it is where the legal-severity claims concentrate.
        assert {
            "T3-COMPLIANCE", "T4-THIRDPARTY", "T6-ABSOLUTE", "T7-CONTACT",
        } == AUTO_DELETE_TRIGGERS

    def test_numbers_and_customer_claims_go_to_a_human(self) -> None:
        # Too noisy to delete silently; a reviewer settles them in seconds.
        assert {"T1-NUMERIC", "T2-CUSTOMER", "T5-GUARANTEE"} == REVIEW_TRIGGERS


# --------------------------------------------------------------------------- #
# The audit and the deletion pass
# --------------------------------------------------------------------------- #

from app.services.content_pipeline.claims import (  # noqa: E402
    apply_deletions,
    audit_draft,
    split_units,
)

_ATOMS = build_atoms(["founded 2013", "used across 7 client accounts"])


class TestTheAudit:
    def test_a_cited_claim_is_kept(self) -> None:
        audit = audit_draft("We have served 7 client accounts [[a2]].", _ATOMS)
        assert [f.lane for f in audit.findings] == ["cited"]

    def test_an_uncited_compliance_claim_goes_to_the_delete_lane(self) -> None:
        audit = audit_draft("Our platform is HIPAA compliant.", _ATOMS)
        assert [f.lane for f in audit.findings] == ["delete"]

    def test_an_uncited_number_goes_to_a_human_not_the_bin(self) -> None:
        # 19.8% false positives on this lane: too noisy to delete silently.
        audit = audit_draft("We handle 40 intakes a week.", _ATOMS)
        assert [f.lane for f in audit.findings] == ["review"]

    def test_an_invented_atom_id_does_not_count_as_a_citation(self) -> None:
        # Otherwise the writer buys immunity by inventing a reference too.
        audit = audit_draft("Our platform is HIPAA compliant [[a99]].", _ATOMS)
        assert [f.lane for f in audit.findings] == ["delete"]


class TestDeletion:
    _DRAFT = (
        "## What we do\n\n"
        "We were founded in 2013 [[a1]]. Our platform is HIPAA compliant. "
        "We have served 7 client accounts [[a2]].\n"
    )

    def test_it_removes_the_uncited_claim_and_keeps_the_cited_ones(self) -> None:
        audit = audit_draft(self._DRAFT, _ATOMS)
        out, removed = apply_deletions(self._DRAFT, audit)
        assert removed == 1
        assert "HIPAA" not in out
        assert "founded in 2013" in out
        assert "7 client accounts" in out

    def test_a_heading_is_reported_but_never_removed(self) -> None:
        # Deleting a heading orphans its section: a sentence-level defect becomes a
        # structural one.
        draft = "## Real workflows we have automated for clients\n\nSome prose.\n"
        audit = audit_draft(draft, _ATOMS)
        out, removed = apply_deletions(draft, audit)
        assert removed == 0
        assert "## Real workflows" in out

    def test_nothing_is_deleted_when_the_markers_were_lost(self) -> None:
        """THE IMPORTANT ONE. convert/voice/grounding rewrite the draft wholesale
        through an LLM. A model that drops the markers would leave every claim
        looking unsourced - and deleting on that signal removes the page rather
        than its fabrications. A collapse means the markers were lost, not that
        the writer invented everything."""
        stripped = self._DRAFT.replace("[[a1]]", "").replace("[[a2]]", "")
        audit = audit_draft(stripped, _ATOMS)
        assert audit.deletable is False
        out, removed = apply_deletions(stripped, audit)
        assert removed == 0
        assert out == stripped

    def test_a_real_draft_with_no_markers_survives_untouched(self) -> None:
        # Measured against the six pages generated before citations existed: 78
        # claim-sentences flagged, 31 in the delete lane, zero removed.
        draft = "\n".join(f"Our system is HIPAA compliant in case {i}." for i in range(20))
        audit = audit_draft(draft, _ATOMS)
        assert len(audit.to_delete) == 20
        assert apply_deletions(draft, audit)[1] == 0


def test_units_split_headings_whole_and_prose_by_sentence() -> None:
    units = split_units("## A heading. With a stop\n\nOne. Two. Three.\n")
    assert units[0] == "## A heading. With a stop"
    assert units[1:] == ["One.", "Two.", "Three."]


class TestCitationFormsTheWriterActuallyEmits:
    """MEASURED on a live run: told it "may cite more than one" without being shown
    how, the writer invented "[[a9], [a10]]". The strict single-id pattern neither
    recognised it (so the sentence counted as unsourced and was queued for deletion)
    nor stripped it (so the marker reached the published page). Both halves of that
    are worse than accepting a loose format, so every plural form is parsed."""

    @pytest.mark.parametrize(("text", "ids"), [
        ("Founded 2013 [[a1]].", ["a1"]),
        ("Founded 2013 [[a1]][[a2]].", ["a1", "a2"]),
        ("Founded 2013 [[a1, a2]].", ["a1", "a2"]),
        ("Founded 2013 [[a9], [a10]].", ["a9", "a10"]),   # the real one
        ("Nothing cited here.", []),
    ])
    def test_every_plural_form_is_read(self, text: str, ids: list[str]) -> None:
        from app.services.content_pipeline.claims import cited_ids

        assert cited_ids(text) == ids

    @pytest.mark.parametrize("text", [
        "Founded 2013 [[a1]].",
        "Founded 2013 [[a9], [a10]].",
        "Founded 2013 [[a1, a2]].",
    ])
    def test_no_marker_form_survives_to_the_reader(self, text: str) -> None:
        assert "[[" not in strip_citations(text)

    def test_a_markdown_link_is_not_mistaken_for_a_citation(self) -> None:
        text = "See the [pricing page](https://example.com/pricing) [[a1]]."
        assert strip_citations(text) == "See the [pricing page](https://example.com/pricing)."


class TestHeadingsThatEndedUpMidParagraph:
    """MEASURED on a live run: a 4,176-character line holding an H2 and ~900 words,
    with two more H2s buried inside it. Markdown only honours "##" at the START of a
    line, so those publish as literal hash characters in a wall of text and the
    headings carrying the page's keyword intent never become headings at all."""

    def test_a_buried_heading_is_moved_onto_its_own_line(self) -> None:
        from app.services.content_pipeline.claims import normalise_headings

        out, moved = normalise_headings("Intro prose. ## A Heading And more prose.")
        assert moved == 1
        assert out.startswith("Intro prose.\n\n## A Heading")

    @pytest.mark.parametrize("text", [
        "See https://example.com/page#section for more.",   # a URL fragment
        "A hex colour #fff and a C# note.",                 # not a heading
        "## Already correct",                               # already fine
    ])
    def test_it_leaves_everything_that_is_not_a_buried_heading_alone(self, text: str) -> None:
        from app.services.content_pipeline.claims import normalise_headings

        assert normalise_headings(text) == (text, 0)

    def test_a_fenced_code_block_is_not_touched(self) -> None:
        from app.services.content_pipeline.claims import normalise_headings

        fenced = "```\nrun ## this is shell, not a heading\n```"
        assert normalise_headings(fenced) == (fenced, 0)

    def test_a_heading_that_swallowed_its_paragraph_is_reported_not_guessed_at(self) -> None:
        # Moving a heading onto its own line is unambiguous. Deciding WHERE the
        # heading ends and the prose begins is not, and a wrong split trades this
        # defect for a different silent one - so it is surfaced to a human.
        from app.services.content_pipeline.claims import overlong_headings

        assert overlong_headings("## " + "word " * 60)
        assert not overlong_headings("## A normal length heading")
