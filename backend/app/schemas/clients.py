"""Client + site request/response models in the frontend shapes.

``ClientResponse`` mirrors ``ClientRecord`` (with nested ``Contact`` and
``PortalAccess``). The portal password is never persisted or revealed - it is
returned as a fixed mask so the shape is complete while honoring secret hygiene.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

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
        return row


class ReportGrantsUpdate(BaseModel):
    """PUT /clients/{id}/report-grants body: the full replace-set of report keys a
    client is granted (mirrors the Add-Client wizard's ``reports``)."""

    reports: list[str] = Field(default_factory=list)


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
