"""Client + site request/response models in the frontend shapes.

``ClientResponse`` mirrors ``ClientRecord`` (with nested ``Contact`` and
``PortalAccess``). The portal password is never persisted or revealed - it is
returned as a fixed mask so the shape is complete while honoring secret hygiene.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.clients_business import ClientBusinessProfileInput
from app.util.text import initials
from app.util.timefmt import format_date, relative_ago

SubTier = Literal["Starter", "Growth", "Scale"]
SubStatus = Literal["active", "trial", "past_due", "paused"]

# The portal password is intentionally never stored or exposed.
_PORTAL_PASS_MASK = "••••••••"


class Contact(BaseModel):
    """Primary client contact (frontend ``Contact``)."""

    name: str
    role: str
    email: str
    init: str
    c: str


class PortalAccess(BaseModel):
    """Client portal access metadata (frontend ``PortalAccess``); pass is masked."""

    admin: str
    pass_: str = Field(default=_PORTAL_PASS_MASK, serialization_alias="pass")
    seats: int
    two_fa: bool = Field(serialization_alias="twoFA")
    last_login: str = Field(serialization_alias="lastLogin")


class ClientResponse(BaseModel):
    """A client account in the frontend ``ClientRecord`` shape."""

    id: str
    cn: str
    industry: str
    sites: int
    since: str
    contact: Contact
    tier: SubTier
    status: SubStatus
    renews: str
    mrr: int
    portal: PortalAccess

    @classmethod
    def from_row(cls, row: dict[str, Any], *, site_count: int) -> ClientResponse:
        contact_name = row.get("contact_name", "")
        return cls(
            id=str(row["id"]),
            cn=row.get("name", ""),
            industry=row.get("industry", ""),
            sites=site_count,
            since=str(row["since_year"]) if row.get("since_year") else "",
            contact=Contact(
                name=contact_name,
                role=row.get("contact_role", ""),
                email=row.get("contact_email", ""),
                init=initials(contact_name),
                c=row.get("contact_color", "#7B69EE"),
            ),
            tier=row.get("tier", "Starter"),
            status=row.get("status", "trial"),
            renews=format_date(row.get("renews_at")),
            mrr=int(row.get("mrr", 0)),
            portal=PortalAccess(
                admin=row.get("portal_admin", ""),
                seats=int(row.get("portal_seats", 0)),
                two_fa=bool(row.get("portal_two_fa", False)),
                last_login=relative_ago(row.get("portal_last_login_at")),
            ),
        )


class ContactInput(BaseModel):
    name: str = ""
    role: str = ""
    email: str = ""
    color: str = "#7B69EE"


class PortalInput(BaseModel):
    admin: str = ""
    seats: int = 0
    two_fa: bool = Field(default=False, alias="twoFA")


class ClientCreate(BaseModel):
    """Create payload for a client (contact/portal nested to match the frontend)."""

    cn: str = Field(min_length=1)
    industry: str = ""
    since: int | None = None
    tier: SubTier = "Starter"
    status: SubStatus = "trial"
    renews: str | None = None  # ISO date (YYYY-MM-DD)
    mrr: int = 0
    contact: ContactInput = Field(default_factory=ContactInput)
    portal: PortalInput = Field(default_factory=PortalInput)
    # The client's own NAP, captured up front so the first citation campaign has a real
    # name/address to submit. Optional: an omitted (or empty) profile is simply not
    # persisted - the operator fills it in later from the Edit modal.
    business: ClientBusinessProfileInput | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "name": self.cn,
            "industry": self.industry,
            "since_year": self.since,
            "tier": self.tier,
            "status": self.status,
            "renews_at": self.renews,
            "mrr": self.mrr,
            "contact_name": self.contact.name,
            "contact_role": self.contact.role,
            "contact_email": self.contact.email,
            "contact_color": self.contact.color,
            "portal_admin": self.portal.admin,
            "portal_seats": self.portal.seats,
            "portal_two_fa": self.portal.two_fa,
        }


class ClientUpdate(BaseModel):
    """Partial update; only provided fields are written."""

    cn: str | None = None
    industry: str | None = None
    since: int | None = None
    tier: SubTier | None = None
    status: SubStatus | None = None
    renews: str | None = None
    mrr: int | None = None
    contact: ContactInput | None = None

    def to_row(self) -> dict[str, Any]:
        mapping = {
            "cn": "name",
            "industry": "industry",
            "since": "since_year",
            "tier": "tier",
            "status": "status",
            "renews": "renews_at",
            "mrr": "mrr",
        }
        row: dict[str, Any] = {}
        for field, column in mapping.items():
            value = getattr(self, field)
            if value is not None:
                row[column] = value
        if self.contact is not None:
            row["contact_name"] = self.contact.name
            row["contact_role"] = self.contact.role
            row["contact_email"] = self.contact.email
            row["contact_color"] = self.contact.color
        return row


class ReportGrantsUpdate(BaseModel):
    """PUT /clients/{id}/report-grants body: the full replace-set of report keys a
    client is granted (mirrors the Add-Client wizard's ``reports``)."""

    reports: list[str] = Field(default_factory=list)


class StaffDeliverableResponse(BaseModel):
    """One deliverable as STAFF see it - including the ones a client cannot.

    Deliberately not the portal shape: this carries `status`, which is the whole
    point of the screen (what is waiting for a decision), and `sourceKind`/`sourceId`
    so a reviewer can tell which run produced the document. It still does not carry
    `artifactKey`: the path is resolved server-side on download, here as in the portal.
    """

    id: str
    title: str
    kind: str
    icon: str
    period: str
    status: str
    requires: str
    issued_at: str | None = Field(default=None, serialization_alias="issuedAt")
    size_label: str = Field(default="", serialization_alias="sizeLabel")
    source_kind: str = Field(default="", serialization_alias="sourceKind")
    source_id: str | None = Field(default=None, serialization_alias="sourceId")
    #: False when the row carries no stored artifact - a document that cannot be
    #: downloaded must not be released to a client as if it could.
    has_file: bool = Field(default=False, serialization_alias="hasFile")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> StaffDeliverableResponse:
        issued = row.get("issued_at")
        return cls(
            id=str(row["id"]),
            title=str(row.get("title") or ""),
            kind=str(row.get("kind") or ""),
            icon=str(row.get("icon") or ""),
            period=str(row.get("period") or ""),
            status=str(row.get("status") or ""),
            requires=str(row.get("requires") or ""),
            issued_at=issued.isoformat() if issued is not None else None,
            size_label=str(row.get("size_label") or ""),
            source_kind=str(row.get("source_kind") or ""),
            source_id=str(row["source_id"]) if row.get("source_id") else None,
            has_file=bool(row.get("artifact_key")),
        )


class SiteCreate(BaseModel):
    domain: str = Field(min_length=1)
    cms_type: str = "wordpress"


class SiteResponse(BaseModel):
    id: str
    client_id: str = Field(serialization_alias="clientId")
    domain: str
    cms: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SiteResponse:
        return cls(
            id=str(row["id"]),
            client_id=str(row["client_id"]),
            domain=row.get("domain", ""),
            cms=row.get("cms_type", "wordpress"),
        )
