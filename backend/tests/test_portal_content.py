"""The client's own content surface: their pages, and the questions only they can answer.

No DB and no network - the client-experience service is monkeypatched and the portal repo
is a fake. What is pinned here is the trust boundary and the language, in that order:

  * THE OPERATOR'S STAGE WORDS NEVER REACH A CLIENT. The worker writes stage strings for
    an operator, and one of them - the batch hold - carries the AGENCY'S OWN SPEND CEILING
    and how much of it this build has used ("Held - batch ceiling reached ($2.00 of
    $5.00)"). Echoing the column would disclose the agency's cost structure to its
    customer. Translation is a whitelist, so a stage added to the pipeline tomorrow cannot
    reach a client's screen merely by existing.
  * THE TENANT IS PINNED SERVER-SIDE. Another client's job code answers 404, the same as a
    code that does not exist - so the portal cannot be used to probe for job codes.
  * A CLIENT AND AN OPERATOR SEE THE SAME OPTIONS for the same question. The portal route
    shares the option engine rather than deriving its own suggestions; two option sets for
    one question is how a client ends up confirming a fact the operator never saw.
  * AN INVENTED SLOT KEY IS REFUSED, not ignored: the pipeline decides which proof
    categories a page needs, and accepting an unknown key would let a caller mark a
    dossier complete without answering what was asked.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentClient, CurrentUser, get_current_client, get_current_user
from app.db.portal_repo import get_portal_repo
from app.routers import portal
from app.schemas.portal_content import PortalContentJobResponse, client_stage

pytestmark = pytest.mark.unit


# --- the stage whitelist -------------------------------------------------------
def test_the_batch_hold_never_shows_a_client_the_agency_spend_ceiling() -> None:
    raw = "Held - batch ceiling reached ($2.00 of $5.00)"
    out = client_stage(raw, "drafting")
    assert out == "Paused by your team"
    assert "$" not in out and "ceiling" not in out


def test_every_other_hold_reads_the_same_way_and_names_no_provider() -> None:
    for raw in (
        "Held - content research degraded: missing_serper_key",
        "Held - the image provider is not configured",
        "Held - outline degraded",
    ):
        assert client_stage(raw, "drafting") == "Paused by your team"


def test_the_experience_halt_is_kept_verbatim_because_it_addresses_the_client() -> None:
    raw = "Waiting on your experience answers (2 to go)"
    assert client_stage(raw, "drafting") == raw


def test_internal_stage_labels_are_translated_not_echoed() -> None:
    assert client_stage("QA", "drafting") == "Final checks"
    assert client_stage("AI images", "drafting") == "Adding images"
    assert client_stage("Schema & links", "drafting") == "Finishing touches"


def test_an_unrecognised_stage_falls_back_instead_of_leaking() -> None:
    """The whitelist's whole point: a label nobody has reviewed does not get through."""
    assert client_stage("Reticulating splines (internal)", "drafting") == "In progress"
    assert client_stage("Reticulating splines", "done") == "Published"
    assert client_stage("", "needs_review") == "With your team for review"
    assert client_stage("", "failed") == "Stopped"


def test_the_row_mapper_applies_the_translation() -> None:
    row = {
        "code": "CJ-1",
        "page_type": "service",
        "topic": "Emergency plumbing",
        "status": "drafting",
        "stage": "Held - batch ceiling reached ($2.00 of $5.00)",
        "words": 0,
        "wp_url": None,
    }
    out = PortalContentJobResponse.from_row(row)
    assert out.stage == "Paused by your team"
    # and the client-safe shape carries no cost / draft / score field at all
    emitted = set(PortalContentJobResponse.model_fields)
    assert not {"cost", "draft_md", "qa_score", "source_pack", "assignee"} & emitted


# --- the routes ----------------------------------------------------------------
def _client(client_id: str = "cl-1") -> CurrentClient:
    user = CurrentUser(
        id="pu-1", email="owner@acme.test", role="client", status="active",  # type: ignore[arg-type]
        name="Acme", title="", avatar_color="#000", phone="", two_fa=False,
        client_id=client_id,
    )
    return CurrentClient(user=user, client_id=client_id)


class _FakePortalRepo:
    """Only what the two routes under test call."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def list_content_jobs(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        return self.rows[offset : offset + limit]


_JOB = {
    "code": "CJ-9",
    "client_id": "cl-1",
    "topic": "Boiler repair in Leeds",
    "page_type": "service",
    "status": "drafting",
    "stage": "Waiting on your experience answers (1 to go)",
    "source_pack": {"proof_points": ["Gas Safe registered, number 552831"]},
}
_SLOTS = [
    {
        "slot_key": "license_permit",
        "question": "What licences or certifications can we name?",
        "answer": "",
        "artifact_url": "",
        "answered_at": None,
        "answer_evidence": "",
        "source": "",
    }
]


@pytest.fixture(autouse=True)
def _mount(app: FastAPI) -> None:
    app.include_router(portal.router, prefix="/api/v1")
    app.dependency_overrides[get_current_client] = lambda: _client()
    # The answer route is rate-limited per USER, and that limiter resolves the identity
    # itself - so a test that overrides only the tenant dep gets a 401 from the limiter.
    app.dependency_overrides[get_current_user] = lambda: _client().user
    app.dependency_overrides[get_portal_repo] = lambda: _FakePortalRepo(
        [
            {**_JOB, "code": "CJ-8", "stage": "Held - batch ceiling reached ($2.00 of $5.00)"},
            _JOB,
        ]
    )


async def test_the_page_list_is_translated_end_to_end(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/portal/content")
    assert resp.status_code == 200
    stages = [r["stage"] for r in resp.json()]
    assert stages == ["Paused by your team", "Waiting on your experience answers (1 to go)"]


async def test_the_questionnaire_offers_options_drawn_from_their_own_evidence(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        portal.client_experience, "job_for_client", lambda code, cid: dict(_JOB) if code == "CJ-9" else None
    )
    monkeypatch.setattr(
        portal.client_experience,
        "dossier_for_client_job",
        lambda job: ({"id": "d-1", "status": "empty", "cluster_key": "boiler"}, _SLOTS),
    )
    monkeypatch.setattr(
        portal.client_experience, "prior_answers_for_client", lambda cid, exclude_dossier_id="": []
    )
    monkeypatch.setattr(portal.client_experience, "client_facts", lambda cid: {"cn": "Acme"})

    resp = await client.get("/api/v1/portal/experience/CJ-9")
    assert resp.status_code == 200
    body = resp.json()
    assert body["topic"] == "Boiler repair in Leeds"
    slot = body["slots"][0]
    assert slot["slotKey"] == "license_permit"
    # The proof point the client supplied is offered back to them, WITH its provenance -
    # that is what makes picking an attestation rather than a guess.
    values = [o["value"] for o in slot["options"]]
    assert any("552831" in v for v in values)
    assert all(o["evidence"] for o in slot["options"])
    # Declining is always available, and is an explicit non-claim.
    assert any(o["kind"] == "decline" for o in slot["options"])


async def test_another_tenants_code_is_a_404_not_a_403(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(portal.client_experience, "job_for_client", lambda code, cid: None)
    resp = await client.get("/api/v1/portal/experience/CJ-OTHER")
    assert resp.status_code == 404


async def test_an_invented_slot_key_is_refused_and_nothing_is_written(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[Any] = []
    monkeypatch.setattr(portal.client_experience, "job_for_client", lambda code, cid: dict(_JOB))
    monkeypatch.setattr(
        portal.client_experience,
        "dossier_for_client_job",
        lambda job: ({"id": "d-1", "status": "empty", "cluster_key": "boiler"}, _SLOTS),
    )
    monkeypatch.setattr(
        portal.client_experience,
        "answer_slots_as_client",
        lambda *a, **k: written.append((a, k)) or "empty",
    )
    resp = await client.put(
        "/api/v1/portal/experience/CJ-9",
        json={"answers": [{"slotKey": "made_up", "answer": "x"}]},
    )
    assert resp.status_code == 400
    assert "made_up" in resp.json()["error"]["message"]
    assert written == []


async def test_a_client_answer_is_attributed_to_the_portal_user(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The value of a client-supplied fact is that the client stands behind it."""
    seen: dict[str, Any] = {}
    monkeypatch.setattr(portal.client_experience, "job_for_client", lambda code, cid: dict(_JOB))
    monkeypatch.setattr(
        portal.client_experience,
        "dossier_for_client_job",
        lambda job: ({"id": "d-1", "status": "empty", "cluster_key": "boiler"}, _SLOTS),
    )
    monkeypatch.setattr(
        portal.client_experience, "prior_answers_for_client", lambda cid, exclude_dossier_id="": []
    )
    monkeypatch.setattr(portal.client_experience, "client_facts", lambda cid: {})

    def _answer(dossier_id: str, rows: list[dict[str, str]], *, actor_id: str) -> str:
        seen.update({"dossier": dossier_id, "rows": rows, "actor": actor_id})
        return "partial"

    monkeypatch.setattr(portal.client_experience, "answer_slots_as_client", _answer)
    resp = await client.put(
        "/api/v1/portal/experience/CJ-9",
        json={
            "answers": [
                {
                    "slotKey": "license_permit",
                    "answer": "Gas Safe registered, number 552831",
                    "answerEvidence": "from what you supplied",
                }
            ]
        },
    )
    assert resp.status_code == 200
    assert seen["actor"] == "pu-1"
    assert seen["rows"][0]["answer_evidence"] == "from what you supplied"
    # Not complete, so nothing was re-queued and the payload says so.
    assert resp.json()["resumed"] is False
