"""NAP (Name, Address, Phone) consistency against the canonical business record.

Ported from ``seo-content-os/scripts/nap_checker.py`` (P1B).

NAP must be byte-consistent everywhere it appears and match the Google Business
Profile. Silent variants - a different phone format, "St." for "Street", an
abbreviated direction - fracture the local ranking signal, because the matching that
consolidates a business's identity across the web is not as forgiving as a human
reader is.

THE DESIGN DECISION THAT MAKES THIS USABLE: it distinguishes a MISS from a VARIANT.

  * ``miss``    - the value is absent or wrong. A real problem.
  * ``variant`` - the right value in a different shape: a matching phone in another
    display format, "Ave" where the canonical says "Avenue", a case difference.

Both are reported, but they are different decisions. A miss must be fixed; a variant
is a judgement about whether to normalise. Collapsing the two would either bury real
misses in noise or let genuine inconsistencies pass as cosmetic - and the whole value
of the check is telling an operator which of those they are looking at.

Phone comparison tolerates a country-code prefix, so "+1 512 555 0100" and
"5125550100" are the same number rather than two.

PORT CHANGE: the original reads ``brand.yaml`` with PyYAML (one of only three corpus
scripts with a third-party import, and PyYAML is NOT a declared dependency of this
backend - it is present only transitively). This takes a :class:`CanonicalNap` built
from structured data instead, which is where the client profile lives in P2
(``brand_kits`` / ``sme_slots``). The YAML dependency disappears rather than becoming
a runtime dependency of the base install.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Street-abbreviation equivalences. Both directions map to the canonical word, so
# "Ave", "Ave." and "Avenue" normalise together.
ABBREV: dict[str, tuple[str, ...]] = {
    "street": ("st", "st."),
    "avenue": ("ave", "ave."),
    "boulevard": ("blvd", "blvd."),
    "road": ("rd", "rd."),
    "drive": ("dr", "dr."),
    "lane": ("ln", "ln."),
    "suite": ("ste", "ste."),
    "apartment": ("apt", "apt."),
    "north": ("n", "n."),
    "south": ("s", "s."),
    "east": ("e", "e."),
    "west": ("w", "w."),
    "highway": ("hwy", "hwy."),
    "parkway": ("pkwy", "pkwy."),
}

_ABBREV_REV: dict[str, str] = {}
for _full, _abbrs in ABBREV.items():
    for _a in _abbrs:
        _ABBREV_REV[_a] = _full
    _ABBREV_REV[_full] = _full

_NON_DIGIT_RE = re.compile(r"\D")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_PHONE_CANDIDATE_RE = re.compile(r"[\+\(]?[\d][\d\-\.\(\)\s]{6,}\d")

MISS = "miss"
VARIANT = "variant"


@dataclass(frozen=True)
class CanonicalNap:
    """The business's authoritative NAP. Any field may be blank and is then skipped."""

    name: str = ""
    phone: str = ""
    street: str = ""
    city: str = ""
    region: str = ""
    postal: str = ""


@dataclass(frozen=True)
class NapIssue:
    field: str
    kind: str  # MISS | VARIANT
    message: str


@dataclass(frozen=True)
class NapReport:
    issues: tuple[NapIssue, ...] = ()

    @property
    def misses(self) -> tuple[NapIssue, ...]:
        return tuple(i for i in self.issues if i.kind == MISS)

    @property
    def variants(self) -> tuple[NapIssue, ...]:
        return tuple(i for i in self.issues if i.kind == VARIANT)

    @property
    def passed(self) -> bool:
        """A miss fails. A variant is surfaced for a decision, not a failure -
        conflating the two is what makes NAP checks get ignored."""
        return not self.misses

    @property
    def exact(self) -> bool:
        """Byte-perfect everywhere, variants included."""
        return not self.issues


def digits_only(phone: str) -> str:
    return _NON_DIGIT_RE.sub("", phone or "")


def same_number(a: str, b: str) -> bool:
    """Same phone, tolerating a country-code prefix ("15125550100" vs "5125550100")."""
    da, db = digits_only(a), digits_only(b)
    if not da or not db:
        return False
    if da == db:
        return True
    lo, hi = sorted((da, db), key=len)
    return len(lo) >= 7 and hi.endswith(lo)


def contains_word(text: str, phrase: str) -> bool:
    """Word-boundary exact match, so "Ave" does not match inside "Avenue"."""
    if not phrase:
        return False
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text) is not None


def normalise_tokens(text: str) -> list[str]:
    """Lowercase, expand known street abbreviations, drop punctuation."""
    return [_ABBREV_REV.get(t, t) for t in _TOKEN_RE.findall((text or "").lower())]


def _check_name(text: str, name: str) -> list[NapIssue]:
    if not name or name in text:
        return []
    if name.lower() in text.lower():
        return [NapIssue("NAME", VARIANT, "present but not byte-exact (case differs)")]
    return [NapIssue("NAME", MISS, f"canonical name not found: {name!r}")]


def _check_phone(text: str, phone: str) -> list[NapIssue]:
    if not phone or phone in text:
        return []
    if any(same_number(found, phone) for found in _PHONE_CANDIDATE_RE.findall(text)):
        return [NapIssue("PHONE", VARIANT, f"correct number, different display format than {phone!r}")]
    return [NapIssue("PHONE", MISS, f"canonical phone not found: {phone!r}")]


def _check_address(text: str, nap: CanonicalNap) -> list[NapIssue]:
    out: list[NapIssue] = []
    text_norm = " ".join(normalise_tokens(text))

    if nap.street and not contains_word(text, nap.street):
        street_norm = " ".join(normalise_tokens(nap.street))
        if street_norm and street_norm in text_norm:
            out.append(NapIssue("ADDRESS.street", VARIANT,
                                f"street present but abbreviated differently than {nap.street!r}"))
        else:
            out.append(NapIssue("ADDRESS.street", MISS, f"street not found: {nap.street!r}"))

    for key, label in (("city", "ADDRESS.city"), ("region", "ADDRESS.region"),
                       ("postal", "ADDRESS.postal")):
        value = getattr(nap, key)
        if not value or contains_word(text, value):
            continue
        if contains_word(text.lower(), value.lower()):
            out.append(NapIssue(label, VARIANT, f"{key} present, case differs: {value!r}"))
        else:
            out.append(NapIssue(label, MISS, f"{key} not found: {value!r}"))
    return out


def check_nap(text: str, nap: CanonicalNap) -> NapReport:
    """Check one page's copy against the canonical NAP. Total: never raises, no I/O."""
    issues = _check_name(text, nap.name) + _check_phone(text, nap.phone) + _check_address(text, nap)
    return NapReport(issues=tuple(issues))
