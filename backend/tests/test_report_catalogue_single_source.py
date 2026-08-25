"""The client-report catalogue must be identical on both sides of the wire.

``_REPORT_ORDER`` in ``app/services/report_viz.py`` decides which reports the portal
SERVES. ``clientReports`` in ``frontend/lib/data.ts`` decides which cards the client
dashboard RENDERS and which bubbles the admin's report-access editor offers.

They are two hand-maintained copies of one list, and this repository has already paid
for that shape once: the feature catalogue was cut from 17 keys to 11 in
``app/rbac/matrix.py`` and ``lib/data.ts`` and never propagated to the six module
routers guarding on the removed keys, which left roughly 54 endpoints owner-only and
silently 403ing every admin and manager. ``test_feature_key_registration.py`` is the
guard for that instance; this is the guard for the same shape in the report catalogue.

The two failure directions are asymmetric and both bad:

* a key in the FRONTEND but not the backend renders a permanently empty card, and the
  admin can grant access to a report that will never contain anything;
* a key in the BACKEND but not the frontend is served to a client that has no card to
  put it in - work done and thrown away.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.services.report_viz import _REPORT_ORDER

pytestmark = pytest.mark.unit

_DATA_TS = (
    Path(__file__).resolve().parents[2] / "frontend" / "lib" / "data.ts"
)


def _frontend_report_keys() -> list[str]:
    """`clientReports` keys, in declaration order, read out of the TS source."""
    src = _DATA_TS.read_text(encoding="utf-8")
    m = re.search(r"export const clientReports: ClientReport\[\] = \[(.*?)\n\];", src, re.S)
    assert m, "could not locate `clientReports` in frontend/lib/data.ts"
    return re.findall(r'\{\s*key:\s*"([a-z_]+)"', m.group(1))


def test_the_reader_finds_a_catalogue() -> None:
    """Guard-for-the-guard: a parse failure must FAIL, never vacuously pass."""
    keys = _frontend_report_keys()
    assert len(keys) >= 1, "parsed no report keys - the reader is broken, not the code"
    assert len(_REPORT_ORDER) >= 1


def test_the_two_catalogues_are_identical_and_in_the_same_order() -> None:
    frontend = _frontend_report_keys()
    backend = list(_REPORT_ORDER)
    assert frontend == backend, (
        "the client-report catalogue has drifted.\n"
        f"  frontend/lib/data.ts clientReports : {frontend}\n"
        f"  app/services/report_viz.py         : {backend}\n"
        "A frontend-only key renders a permanently empty card the admin can still grant; "
        "a backend-only key is served to a client with nowhere to show it. Order matters "
        "too - build_report_viz emits in _REPORT_ORDER and the dashboard renders in "
        "clientReports order."
    )


def test_report_bundles_only_grant_keys_that_exist() -> None:
    """A bundle is a one-click grant; it must not hand out a key nobody serves."""
    src = _DATA_TS.read_text(encoding="utf-8")
    m = re.search(r"export const reportBundles: ReportBundle\[\] = \[(.*?)\n\];", src, re.S)
    assert m, "could not locate `reportBundles` in frontend/lib/data.ts"

    known = set(_REPORT_ORDER)
    bad: dict[str, list[str]] = {}
    for bundle in re.finditer(r'key:\s*"([a-z_]+)",\s*label:.*?grants:\s*(\[[^\]]*\]|ALL_REPORT_KEYS)', m.group(1), re.S):
        name, grants_src = bundle.group(1), bundle.group(2)
        if grants_src == "ALL_REPORT_KEYS":
            continue  # derived from clientReports, so correct by construction
        offenders = [k for k in ast.literal_eval(grants_src.replace('"', "'")) if k not in known]
        if offenders:
            bad[name] = offenders
    assert not bad, (
        f"reportBundles grant report key(s) that no longer exist: {bad}. "
        f"Known keys: {sorted(known)}"
    )
