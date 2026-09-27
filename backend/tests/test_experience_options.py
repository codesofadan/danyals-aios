"""The Experience questionnaire's option list: offered from evidence, never invented.

THE PROPERTY THESE TESTS HOLD is the one the whole feature rests on. A dropdown of
plausible-sounding answers would be exactly the fabrication the Experience gate exists to
prevent, wearing a click - so every option must be traceable to something the client
already supplied, and each must carry the words that say where it came from.

The two structural options (attach the proof / we do not have this) are the exception and
are deliberately not extractions: one routes to the artifact field, the other is an explicit
non-claim that satisfies the gate while forbidding the claim.
"""

from __future__ import annotations

import pytest

from app.services.experience_options import (
    DECLINE_TEXT,
    Evidence,
    PriorAnswer,
    evidence_from,
    options_for,
    options_for_all,
)

pytestmark = pytest.mark.unit


class TestNothingIsInvented:
    def test_an_empty_evidence_set_offers_only_the_two_structural_options(self) -> None:
        """With nothing supplied there is nothing to extract, and nothing is made up.

        This is the load-bearing case: a client we know nothing about must produce a
        questionnaire that asks, not one that guesses. The only options left are "I will
        attach it" and "we do not have this", neither of which asserts anything.
        """
        options = options_for("founding_date", Evidence())
        kinds = [o.kind for o in options]
        assert kinds == ["artifact", "decline"]

    def test_every_option_carries_its_provenance(self) -> None:
        ev = evidence_from(
            client={"since_year": 2016},
            source_pack={"proof_points": ["Completed 450 projects since 2016"]},
        )
        for slot in ("founding_date", "count_source", "license_permit", "review_source"):
            for option in options_for(slot, ev):
                assert option.evidence, f"{slot}/{option.kind} offered with no provenance"

    def test_the_decline_option_forbids_the_claim_rather_than_softening_it(self) -> None:
        """An explicit non-claim is a real answer: it satisfies the gate AND tells the
        writer not to state the thing. "Not sure" would satisfy the gate and permit it."""
        for slot, text in DECLINE_TEXT.items():
            assert "do not" in text.lower() or "keep it to" in text.lower(), slot


class TestExtractionFromTheClientsOwnWords:
    def test_a_founding_year_is_read_from_a_supplied_proof_point(self) -> None:
        ev = evidence_from(
            source_pack={"proof_points": ["Serving the region since 2011 without a callout fee"]}
        )
        values = [o.value for o in options_for("founding_date", ev)]
        assert any("2011" in v for v in values)

    def test_a_licence_number_survives_the_words_around_it(self) -> None:
        """`Licence no. ABC-12345 issued by the city` is the form people actually write.

        The first pattern allowed a space inside the identifier, and under IGNORECASE its
        letter class matched lowercase too - so it captured "ABC-12345 ISSUED BY THE".
        """
        ev = evidence_from(
            source_pack={"proof_points": ["Licence no. ABC-12345 issued by the city"]}
        )
        values = [o.value for o in options_for("license_permit", ev)]
        assert any(v.startswith("Licence ABC-12345") for v in values), values

    def test_the_participle_form_is_read_too(self) -> None:
        """"Gas Safe registered, number 552831" is how a trade actually writes it.

        The keyword list held `registration` and a word-bounded `reg`, and neither can
        match inside `registered` - so the commonest phrasing in the trades produced no
        option at all, and the licence question came back empty for exactly the clients
        most likely to have one.
        """
        ev = evidence_from(
            source_pack={"proof_points": ["Gas Safe registered, number 552831"]}
        )
        values = [o.value for o in options_for("license_permit", ev)]
        assert any("552831" in v for v in values), values

    def test_a_year_is_not_mistaken_for_a_licence(self) -> None:
        ev = evidence_from(source_pack={"proof_points": ["Registered in 2019"]})
        assert not [o for o in options_for("license_permit", ev) if "2019" in o.value]

    def test_a_job_count_is_read_through_an_adjective(self) -> None:
        ev = evidence_from(source_pack={"unique_data": ["Our review of 200 past projects"]})
        values = [o.value for o in options_for("count_source", ev)]
        assert any(v.startswith("200 projects") for v in values), values

    def test_a_review_count_is_not_offered_as_a_job_count(self) -> None:
        """"87 reviews" is not 87 jobs. Sharing one pattern between the two questions
        would offer a review tally as a project tally on the neighbouring slot."""
        ev = evidence_from(source_pack={"testimonials": ["see our 87 Google reviews"]})
        reviews = [o.value for o in options_for("review_source", ev)]
        counts = [o.value for o in options_for("count_source", ev) if o.kind == "supplied"]
        assert any("87" in v and "Google" in v for v in reviews), reviews
        assert not counts, f"a review count leaked into the job-count question: {counts}"

    def test_a_bare_year_in_free_text_is_not_treated_as_a_founding_date(self) -> None:
        """A four-digit number is a price, a postcode or a model number as often as a year.

        Only a year NEXT TO a founding word counts, or one read from the field that MEANS
        a year on the client's own record.
        """
        ev = evidence_from(source_pack={"proof_points": ["Model 2019 boilers fitted"]})
        assert [o.kind for o in options_for("founding_date", ev)] == ["artifact", "decline"]

    def test_the_client_record_is_offered_and_labelled_as_such(self) -> None:
        ev = evidence_from(client={"since_year": 2016, "contact_name": "Sarah Whitfield",
                                   "contact_role": "Operations Manager"})
        founding = options_for("founding_date", ev)
        team = options_for("named_team", ev)
        assert founding[0].kind == "record" and "2016" in founding[0].value
        assert team[0].kind == "record" and "Sarah Whitfield" in team[0].value


class TestAPriorAttestationIsTheStrongestOption:
    def test_a_prior_answer_is_offered_first_and_names_its_cluster(self) -> None:
        """The client wrote it, about themselves, for the same purpose. Nothing we can
        extract beats that, so it is offered first and says where it came from."""
        ev = Evidence(prior=(PriorAnswer(
            slot_key="license_permit", answer="Licence M-41982",
            cluster_key="emergency repair", answered_on="12 Sep 2026",
        ),))
        options = options_for("license_permit", ev)
        assert options[0].kind == "prior"
        assert options[0].value == "Licence M-41982"
        assert "emergency repair" in options[0].evidence
        assert "12 Sep 2026" in options[0].evidence

    def test_a_prior_answer_for_another_slot_is_not_offered_here(self) -> None:
        ev = Evidence(prior=(PriorAnswer(slot_key="photo", answer="Our own crew photos"),))
        assert not [o for o in options_for("license_permit", ev) if o.kind == "prior"]


class TestNoDuplicateOffers:
    def test_the_same_fact_from_two_sources_is_offered_once(self) -> None:
        ev = Evidence(prior=(PriorAnswer(slot_key="founding_date", answer="Trading since 2016."),),
                      since_year="2016")
        values = [o.value for o in options_for("founding_date", ev)]
        assert values.count("Trading since 2016.") == 1, values


class TestTheWholeDossier:
    def test_options_for_all_answers_every_slot_it_is_given(self) -> None:
        ev = evidence_from(source_pack={"proof_points": ["Since 2016"]})
        out = options_for_all(("founding_date", "photo", "named_team"), ev)
        assert set(out) == {"founding_date", "photo", "named_team"}
        # A slot with nothing to extract still gets its structural options - an empty list
        # would render as a dead dropdown.
        assert all(out[slot] for slot in out)

    def test_evidence_from_tolerates_junk_in_the_source_pack(self) -> None:
        """`source_pack` is operator-seeded jsonb: its shape is whatever was written."""
        ev = evidence_from(
            client=None,
            source_pack={"facts": "not a dict", "proof_points": "not a list", "services": 7},
        )
        assert ev.proof_points == () and ev.services == ()
