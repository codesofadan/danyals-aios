"""Client business-profile (NAP) request/response models - Wave 4.

The client's OWN business identity captured at creation (``client_business_profiles``,
0051): the source-of-truth name / address / phone / categories / hours the Add-Client
wizard collects and the citation-builder derives its first submission profile from.

Distinct from ``app.modules.citations.schemas.BusinessProfileResponse``, which is the
multi-location SUBMISSION NAP a citation form is filled with. This is the single,
per-client identity that seeds it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

BusinessMarket = Literal["US", "UK", "CA", "AU", "GLOBAL"]
_MARKETS: frozenset[str] = frozenset({"US", "UK", "CA", "AU", "GLOBAL"})


class ClientBusinessProfileInput(BaseModel):
    """The NAP payload the Add-Client wizard / Edit modal submits.

    Every field is optional with a safe default so the wizard can create a client with
    a partial (or empty) profile and the operator can fill it in later from the Edit
    modal - the citation-builder degrades honestly when the name/address is still blank
    rather than submitting an empty listing.
    """

    model_config = ConfigDict(populate_by_name=True)

    business_name: str = Field(default="", alias="businessName")
    address_line1: str = Field(default="", alias="addressLine1")
    address_line2: str = Field(default="", alias="addressLine2")
    city: str = ""
    region: str = ""
    postal_code: str = Field(default="", alias="postalCode")
    market: BusinessMarket = "US"
    phone: str = ""
    website_url: str = Field(default="", alias="websiteUrl")
    primary_category: str = Field(default="", alias="primaryCategory")
    extra_categories: list[str] = Field(default_factory=list, alias="extraCategories")
    hours: dict[str, str] = Field(default_factory=dict)
    description: str = ""

    def has_content(self) -> bool:
        """Whether the operator actually entered anything worth persisting - a wholly
        empty profile from a wizard that skipped the NAP step is not written."""
        return bool(
            self.business_name.strip()
            or self.address_line1.strip()
            or self.city.strip()
            or self.phone.strip()
            or self.website_url.strip()
            or self.primary_category.strip()
            or self.description.strip()
        )

    def to_row(self) -> dict[str, Any]:
        """The ``client_business_profiles`` column dict (client_id/client_name are added
        by the repo from the verified client, never trusted from the wire)."""
        return {
            "business_name": self.business_name.strip(),
            "address_line1": self.address_line1.strip(),
            "address_line2": self.address_line2.strip(),
            "city": self.city.strip(),
            "region": self.region.strip(),
            "postal_code": self.postal_code.strip(),
            "market": self.market,
            "phone": self.phone.strip(),
            "website_url": self.website_url.strip(),
            "primary_category": self.primary_category.strip(),
            "extra_categories": [c.strip() for c in self.extra_categories if c.strip()],
            "hours": self.hours,
            "description": self.description.strip(),
        }


class ClientBusinessProfileResponse(BaseModel):
    """A client's stored NAP in the frontend ``ClientBusinessProfile`` shape."""

    id: str
    client: str
    business_name: str = Field(serialization_alias="businessName")
    address_line1: str = Field(serialization_alias="addressLine1")
    address_line2: str = Field(serialization_alias="addressLine2")
    city: str
    region: str
    postal_code: str = Field(serialization_alias="postalCode")
    market: BusinessMarket
    phone: str
    website_url: str = Field(serialization_alias="websiteUrl")
    primary_category: str = Field(serialization_alias="primaryCategory")
    extra_categories: list[str] = Field(serialization_alias="extraCategories")
    hours: dict[str, str]
    description: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ClientBusinessProfileResponse:
        market = row.get("market")
        hours = row.get("hours")
        return cls(
            id=str(row["id"]),
            client=row.get("client_name", ""),
            business_name=row.get("business_name", ""),
            address_line1=row.get("address_line1", ""),
            address_line2=row.get("address_line2", ""),
            city=row.get("city", ""),
            region=row.get("region", ""),
            postal_code=row.get("postal_code", ""),
            market=market if market in _MARKETS else "US",
            phone=row.get("phone", ""),
            website_url=row.get("website_url", ""),
            primary_category=row.get("primary_category", ""),
            extra_categories=list(row.get("extra_categories") or []),
            hours=dict(hours) if isinstance(hours, dict) else {},
            description=row.get("description", ""),
        )
