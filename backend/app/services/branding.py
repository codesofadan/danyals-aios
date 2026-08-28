"""Client-facing branding, read from the engine's `branding.json`.

WHY A SEPARATE MODULE. `branding.json` at the audit engine's repo root is
documented there as the ONLY file to edit when the operator sends their details.
The engine's own reporters already read it; the platform's deliverables were
hardcoded to the platform's palette, so a report generated here and a report
generated there carried different brands for the same agency.

WHAT IT WILL NOT DO. It will not fail a report. Every field has a usable default
and a missing, unreadable, or malformed file degrades to those defaults rather
than raising - a deliverable that does not render because a colour was absent is
worse than one that renders in the platform's own violet.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

#: The platform's own accent, used whenever the brand has not set one. Not a
#: placeholder to be shown as text - a real colour that renders correctly.
_DEFAULT_ACCENT = "#432B52"

#: A CSS colour we are willing to interpolate into a stylesheet. `branding.json`
#: is operator-edited, and the value lands inside a `<style>` block, so anything
#: that is not plainly a hex colour is refused rather than escaped.
_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


@dataclass(frozen=True, slots=True)
class Brand:
    name: str = "AIOS"
    contact_email: str = ""
    website: str = ""
    accent: str = _DEFAULT_ACCENT

    @property
    def has_contact(self) -> bool:
        """A placeholder address is not a contact. Printing `danyal@example.com`
        under "who to reply to" is worse than printing nothing."""
        e = self.contact_email
        return bool(e) and "@" in e and not e.endswith(("example.com", "example.org"))


def _pick(data: dict[str, object], *keys: str) -> str:
    for k in keys:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _candidates() -> list[Path]:
    out: list[Path] = []
    engine_dir = getattr(get_settings(), "audit_engine_dir", None)
    if engine_dir:
        out.append(Path(engine_dir) / "branding.json")
    # The platform and the engine are checked out side by side in every
    # environment that has both; `parents[3]` is the shared root from
    # backend/app/services/branding.py.
    root = Path(__file__).resolve().parents[3]
    out.append(root / "danyals-audit-system" / "branding.json")
    out.append(root / "branding.json")
    return out


@lru_cache(maxsize=1)
def brand() -> Brand:
    """The brand, or the defaults. Cached: it is read once per process and the
    file does not change under a running worker."""
    for path in _candidates():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        accent = _pick(data, "accent_color", "accent")
        return Brand(
            name=_pick(data, "brand_name", "client_name") or "AIOS",
            contact_email=_pick(data, "contact_email"),
            website=_pick(data, "website"),
            accent=accent if _HEX.match(accent) else _DEFAULT_ACCENT,
        )
    return Brand()
