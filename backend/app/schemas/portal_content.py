"""Client-portal CONTENT models: what a client may see about their pages, and the
questionnaire only they can answer.

Two shapes, two very different trust levels, deliberately kept apart:

* :class:`PortalContentJobResponse` is a READ of the client-safe view
  ``portal_content_jobs`` (0156). It carries the stage, whether the page published and
  where - and nothing else. No draft, no cost, no QA score, no publish target. The
  client approves nothing; a lead stays the only publisher.
* :class:`PortalExperienceResponse` is the one place a client WRITES. It is not a content
  mutation: it is the client supplying their own first-party facts, which is the only
  input the pipeline cannot obtain any other way.

Each option offered on a slot carries its own provenance (``evidence``), because the
value of a picked answer is entirely in being able to say, later, where it came from.
These are operational models with no ``frontend/lib/*.ts`` mirror, so they sit outside
``test_contract_lock`` (the same treatment ``PolicyAskResponse`` gets) and emit camelCase
through ``serialization_alias``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else (str(value) if value else None)


#: The ONLY stage words a client is shown, keyed by the internal label the worker streams
#: (`workers/tasks/content_pipeline.STAGE_LABEL`). A WHITELIST, not a rewrite list: an
#: unrecognised stage collapses to "In progress" rather than being echoed, so a label added
#: to the pipeline tomorrow cannot reach a client's screen just by existing.
_CLIENT_STAGE: dict[str, str] = {
    "Experience": "Collecting your input",
    "Research": "Researching",
    "Outline": "Planning the page",
    "Draft": "Writing",
    "Claims check": "Checking claims",
    "Conversion": "Writing",
    "Voice": "Matching your voice",
    "Fact-check": "Fact-checking",
    "AI images": "Adding images",
    "Titles & meta": "Finishing touches",
    "Schema & links": "Finishing touches",
    "QA": "Final checks",
    "Applying your edits": "Applying edits",
    "Failed": "Stopped",
}

#: What the client is told when a page is HELD for any reason other than their own answers.
#: The raw hold stage must never be echoed: it is written for an operator and can name a
#: provider outage, a dial position, or - in the batch case - the agency's own spend ceiling
#: and how much of it this client's build has used. "Held - batch ceiling reached
#: ($2.00 of $5.00)" on a client's screen would disclose the agency's cost structure.
_CLIENT_HELD = "Paused by your team"


def client_stage(stage: str, status: str) -> str:
    """The stage in words a client may read - never the operator's own.

    The one held-state that IS client-facing is kept verbatim: the Experience halt's label
    is already addressed to them ("Waiting on your experience answers (2 to go)") and is
    the whole reason this screen exists.
    """
    raw = (stage or "").strip()
    if raw.lower().startswith("waiting on your"):
        return raw
    if raw.lower().startswith("held"):
        return _CLIENT_HELD
    if raw in _CLIENT_STAGE:
        return _CLIENT_STAGE[raw]
    if status == "done":
        return "Published"
    if status == "needs_review":
        return "With your team for review"
    if status == "publishing":
        return "Publishing"
    if status in {"rejected", "failed"}:
        return "Stopped"
    return "In progress"


class PortalContentJobResponse(BaseModel):
    """One of the client's pages, as the client may see it."""

    code: str
    page_type: str = Field(serialization_alias="pageType")
    topic: str
    status: str
    stage: str
    words: int = 0
    images: int = 0
    #: The permalink, once a publish actually reached their site. Empty before that -
    #: which reads as "not published yet" rather than as a broken link.
    url: str = ""
    publish_at: str | None = Field(default=None, serialization_alias="publishAt")
    created_at: str = Field(default="", serialization_alias="createdAt")
    updated_at: str | None = Field(default=None, serialization_alias="updatedAt")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> PortalContentJobResponse:
        return cls(
            code=str(row.get("code") or ""),
            page_type=str(row.get("page_type") or ""),
            topic=str(row.get("topic") or ""),
            status=str(row.get("status") or ""),
            stage=client_stage(str(row.get("stage") or ""), str(row.get("status") or "")),
            words=int(row.get("words") or 0),
            images=int(row.get("images") or 0),
            url=str(row.get("wp_url") or ""),
            publish_at=_iso(row.get("publish_at")),
            created_at=_iso(row.get("created_at")) or "",
            updated_at=_iso(row.get("updated_at")),
        )


class ExperienceOptionResponse(BaseModel):
    """One pickable answer, with the words that say where it came from."""

    value: str
    evidence: str
    kind: str


class PortalExperienceSlot(BaseModel):
    """One proof question, its current answer, and the options for it."""

    slot_key: str = Field(serialization_alias="slotKey")
    question: str = ""
    answer: str = ""
    artifact_url: str = Field(default="", serialization_alias="artifactUrl")
    answered: bool = False
    answer_evidence: str = Field(default="", serialization_alias="answerEvidence")
    answered_on: str = Field(default="", serialization_alias="answeredOn")
    #: Who attested it, in kind rather than identity (client / operator / ...).
    source: str = ""
    options: list[ExperienceOptionResponse] = Field(default_factory=list)

    @classmethod
    def from_row(cls, row: dict[str, Any], options: list[Any]) -> PortalExperienceSlot:
        answer = str(row.get("answer") or "")
        artifact = str(row.get("artifact_url") or "")
        answered_at = row.get("answered_at")
        return cls(
            slot_key=str(row.get("slot_key") or ""),
            question=str(row.get("question") or ""),
            answer=answer,
            artifact_url=artifact,
            answered=bool(answer.strip() or artifact.strip()),
            answer_evidence=str(row.get("answer_evidence") or ""),
            answered_on=(
                answered_at.strftime("%d %b %Y") if isinstance(answered_at, datetime) else ""
            ),
            source=str(row.get("source") or ""),
            options=[ExperienceOptionResponse(**o.as_dict()) for o in options],
        )


class PortalExperienceResponse(BaseModel):
    """The questionnaire for one page: where it stands and what is still needed."""

    code: str
    #: empty | partial | complete | not_started (the page has not run yet)
    status: str
    cluster_key: str = Field(default="", serialization_alias="clusterKey")
    topic: str = ""
    slots: list[PortalExperienceSlot] = Field(default_factory=list)
    #: Set by the answer call: whether a completed dossier actually re-queued the page.
    resumed: bool = False


class PortalExperienceSummary(BaseModel):
    """One page waiting on the client, for the portal's to-do list."""

    code: str
    topic: str = ""
    page_type: str = Field(default="", serialization_alias="pageType")
    status: str = ""
    stage: str = ""
    cluster_key: str = Field(default="", serialization_alias="clusterKey")
    slots: int = 0
    answered: int = 0

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> PortalExperienceSummary:
        return cls(
            code=str(row.get("code") or ""),
            topic=str(row.get("topic") or ""),
            page_type=str(row.get("page_type") or ""),
            status=str(row.get("status") or ""),
            # Through the same whitelist as the page list: these rows are experience-held
            # today, so the label is already the client-facing one - but a row arriving here
            # in any other state must not be the exception that leaks an operator's words.
            stage=client_stage(str(row.get("stage") or ""), str(row.get("status") or "")),
            cluster_key=str(row.get("cluster_key") or ""),
            slots=int(row.get("slots") or 0),
            answered=int(row.get("answered") or 0),
        )


class ExperienceAnswerIn(BaseModel):
    """One submitted answer.

    ``answer_evidence`` is the provenance string from the option that was picked. It is
    stored as supplied rather than re-derived, because it describes what the answerer was
    looking at when they attested - which the server cannot reconstruct afterwards. It is
    never treated as a claim in itself: the draft grounds on ``answer``.
    """

    slot_key: str = Field(alias="slotKey")
    answer: str = ""
    artifact_url: str = Field(default="", alias="artifactUrl")
    answer_evidence: str = Field(default="", alias="answerEvidence")

    model_config = {"populate_by_name": True}

    def as_row(self) -> dict[str, str]:
        return {
            "slot_key": self.slot_key,
            "answer": self.answer,
            "artifact_url": self.artifact_url,
            "answer_evidence": self.answer_evidence,
        }


class PortalExperienceAnswers(BaseModel):
    """The answer payload: a list, so a client can fill several slots in one save."""

    answers: list[ExperienceAnswerIn] = Field(default_factory=list)
