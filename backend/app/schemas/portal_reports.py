"""Client-portal report visualization models in the frontend shapes (``lib/client.ts``
``ReportViz`` / ``GaugeDatum`` / ``StatDatum``).

``ReportVizResponse`` mirrors ``ReportViz`` BYTE-FOR-BYTE - the same 11 single-word
lowercase keys, no ``serialization_alias`` (so the JSON keys equal the TS field
names one-for-one). The ``kind`` union is pinned verbatim to ``VizKind`` (§3 enum
fidelity). The optional fields are only populated for the kinds that use them
(``labels``/``points`` for area/bars, ``gauges`` for gauge, ``progress`` for
progress, ``stats`` for stat).

``PortalReportResponse`` is the endpoint wrapper: ``{key, viz, placeholder}``. The
``placeholder`` flag (true = representative/sample data, not yet a live provider
feed) lives HERE, never inside ``ReportVizResponse`` - so the viz stays byte-for-byte
identical to the frontend type.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

# VizKind verbatim from lib/client.ts.
VizKind = Literal["area", "bars", "gauge", "progress", "stat"]


class GaugeDatumResponse(BaseModel):
    """One gauge in the frontend ``GaugeDatum`` shape (for ``kind = "gauge"``)."""

    label: str
    value: float
    unit: str
    max: float
    good: float


class StatDatumResponse(BaseModel):
    """One stat row in the frontend ``StatDatum`` shape (for ``kind = "stat"``)."""

    label: str
    value: str
    delta: str | None = None
    up: bool | None = None


class ReportVizResponse(BaseModel):
    """One report visualization in the frontend ``ReportViz`` shape - the exact 11
    keys, no aliasing. ``headline`` is the big number shown once unlocked; ``caption``
    the one-line read-out. The remaining fields are per-kind and default to unset."""

    kind: VizKind
    headline: str
    unit: str | None = None
    caption: str
    delta: str | None = None
    up: bool | None = None
    labels: list[str] | None = None
    points: list[float] | None = None
    gauges: list[GaugeDatumResponse] | None = None
    progress: int | None = None
    stats: list[StatDatumResponse] | None = None


class PortalReportResponse(BaseModel):
    """One granted report surface: its key + its viz + whether the viz is sample
    (placeholder) data. The client dashboard renders exactly the granted keys."""

    key: str
    viz: ReportVizResponse
    placeholder: bool
