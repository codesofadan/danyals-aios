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

CONTACTS = frozenset({"business.zainsaeed@gmail.com", "+923088040606", "xegents.com"})


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
        'Zero data movement to Xegents servers, zero export-import cycles, zero "data residency" risk.',
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
        fired = needs_citation("email us at hello@xegents.com", allowed_contacts=CONTACTS)
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
        "Xegents has no published HIPAA audit or certification.",
        "Acme Dental holds no certification of any kind.",
        "Your clinic's HIPAA compliance is your IT and legal team's responsibility.",
    ])
    def test_an_honest_disclaimer_is_never_deleted(self, sentence: str) -> None:
        # Deleting a retraction makes the page LESS true than the writer left it -
        # strictly worse than the fabrication this module removes.
        vendor = vendor_pattern(["Xegents", "Acme Dental"])
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
