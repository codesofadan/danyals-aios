"""Turn a flat finding list into three altitudes: cause, instance, page.

THE MEASUREMENT THIS EXISTS FOR. Real run 837b75d6 (smileon.pk, 197 pages)
emitted 15,617 findings, 8,077 of them ``fail``/``warn``. Those 8,077 rows carry
only **81 distinct causes**. Handing a client 8,077 rows when there are 81 things
to fix is the defect; this module is the fix.

    8,077 rows  ->  81 findings + 8,077 instances     (99.0% less to read)

and the output reads the way an SEO lead would say it:

    [major] Image alt text optimization  -  197 pages

WHAT A CAUSE IS. A cause is ``(check_id, locus, discriminator)``. The LOCUS is
where the fix goes, and it is the whole idea: a missing H1 on 42 pages of one
template is ONE edit to ONE template, not 42 problems. So:

    site      the finding is about the site as a whole (robots.txt, TLS, sitemap)
    template  the same check fires across pages sharing a URL shape -> fix once
    url       the finding is genuinely specific to a single page
    entity    an off-site object (a directory listing, a GBP field)

WHAT NEVER ENTERS THE FINGERPRINT. No URL, no evidence value, no page id, no run
id, no count. Each of those changes when the SITE changes rather than when the
PROBLEM changes, and a fingerprint that moves with content cannot answer "is this
the same problem we saw last month" - which is the only question that makes a
delta, a trend or a fix-verification meaningful.

Pure: stdlib only, no database, no network, no clock. Same input -> same output,
byte for byte. That is what lets the ingest be re-run safely over one artifact.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

#: Bumping this changes every fingerprint and therefore orphans every open
#: finding, so it may only move with a migration that closes existing rows as
#: ``superseded``. It is stored on every row for exactly that reason.
FINGERPRINT_VERSION = 1

SEVERITY_ORDER = ("info", "minor", "major", "critical")
_SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITY_ORDER)}

#: A finding with one of these statuses is not a problem. `n_a` is separate from
#: `pass` upstream but neither is an issue.
NON_ISSUE_STATUSES = frozenset({"pass", "passed", "n_a", "na", "ok", "not_applicable"})

_RE_DIGITS = re.compile(r"^\d+$")
_RE_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_RE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RE_YEAR = re.compile(r"^(19|20)\d{2}$")


# --------------------------------------------------------------------------- #
# Template derivation (R4-25a)
# --------------------------------------------------------------------------- #

def url_path_segments(url: str) -> list[str]:
    path = urlsplit(url or "").path or "/"
    return [s for s in path.split("/") if s]


def _segment_shape(seg: str) -> str:
    """Collapse a segment that is obviously an identifier rather than a name."""
    if _RE_UUID.match(seg):
        return "{uuid}"
    if _RE_DATE.match(seg):
        return "{date}"
    if _RE_YEAR.match(seg):
        return "{year}"
    if _RE_DIGITS.match(seg):
        return "{n}"
    return seg


def assign_templates(urls: list[str]) -> dict[str, str]:
    """Map each URL to a template id, deterministically.

    Two passes, in this order:

    1. Shape obvious identifiers (dates, uuids, numbers) segment by segment.
    2. Collapse the LAST segment to ``{slug}`` when two or more URLs share the
       same parent prefix and differ only there - i.e. when the evidence says
       those pages are siblings generated from one template.

    Step 2 is what makes ``/services/implants`` and ``/services/braces`` one
    template while leaving a genuinely unique ``/contact`` alone. A site with one
    page per prefix produces per-URL templates, which is the honest answer: there
    is no template evidence to find.
    """
    shaped: dict[str, list[str]] = {}
    for u in urls:
        shaped[u] = [_segment_shape(s) for s in url_path_segments(u)]

    # Count distinct leaf values per parent prefix.
    leaves: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for segs in shaped.values():
        if segs:
            leaves[tuple(segs[:-1])].add(segs[-1])

    out: dict[str, str] = {}
    for u, segs in shaped.items():
        if not segs:
            out[u] = "/"
            continue
        parent = tuple(segs[:-1])
        last = segs[-1]
        if last.startswith("{") or len(leaves[parent]) >= 2:
            last = "{slug}" if not last.startswith("{") else last
        out[u] = "/" + "/".join([*parent, last])
    return out


# --------------------------------------------------------------------------- #
# Fingerprint (R4-24)
# --------------------------------------------------------------------------- #

def fingerprint(
    *,
    check_id: str,
    locus_kind: str,
    locus_value: str,
    discriminator: str = "",
    version: int = FINGERPRINT_VERSION,
) -> str:
    payload = {
        "v": version,
        "check": check_id,
        "scope": locus_kind,
        "locus": locus_value,
        "disc": discriminator,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Discriminators
# --------------------------------------------------------------------------- #
# A discriminator splits one check into genuinely different problems. It must be
# LOW CARDINALITY and derived from the KIND of failure, never from a measured
# value - "the title is 12 chars" and "the title is 14 chars" are one problem.
_STATUS_KEYS = ("target_status", "status_code", "http_status", "status")


def discriminator_for(check_id: str, evidence: dict[str, Any]) -> str:
    """Split a check into distinct causes where the failure KIND differs.

    Kept deliberately narrow. Every additional discriminator splits findings that
    would otherwise be one card, so a new one has to earn its place by describing
    a genuinely different fix.
    """
    if not isinstance(evidence, dict):
        return ""
    for key in _STATUS_KEYS:
        val = evidence.get(key)
        if isinstance(val, int) and 100 <= val <= 599:
            # A 404 and a 500 on the same check are different problems with
            # different owners; bucket by class so we do not split 404 from 410.
            return f"http_{val // 100}xx"
    return ""


# --------------------------------------------------------------------------- #
# Cause assembly
# --------------------------------------------------------------------------- #

@dataclass(slots=True)
class Instance:
    """One occurrence. NANO."""
    instance_key: str
    instance_kind: str
    url: str
    engine_page_id: int | None
    template_id: str
    observed: str
    expected: str
    detail: str
    evidence: dict[str, Any]
    severity: str


@dataclass(slots=True)
class Cause:
    """One problem with one fix. MICRO."""
    check_id: str
    check_name: str
    pillar: str
    subcategory: str
    dimension: str
    owner_agent: str
    automation: str
    severity: str
    status: str
    confidence: float | None
    locus_kind: str
    locus_value: str
    discriminator: str
    fingerprint: str
    remediation: str
    evidence: dict[str, Any]
    instances: list[Instance] = field(default_factory=list)

    @property
    def instance_count(self) -> int:
        return len(self.instances)

    @property
    def pages_affected(self) -> int:
        return len({i.url for i in self.instances if i.url})


def _decode(blob: Any) -> dict[str, Any]:
    """Evidence arrives as a JSON-ENCODED STRING, not a nested object."""
    if isinstance(blob, dict):
        return blob
    if isinstance(blob, str) and blob.strip():
        try:
            parsed = json.loads(blob)
            return parsed if isinstance(parsed, dict) else {"value": parsed}
        except (ValueError, TypeError):
            return {"raw": blob[:2000]}
    return {}


def _worst(a: str, b: str) -> str:
    return a if _SEVERITY_RANK.get(a, -1) >= _SEVERITY_RANK.get(b, -1) else b


def _detail_from(evidence: dict[str, Any]) -> str:
    """A single renderable line, so the nano row is readable without the blob."""
    if not evidence:
        return ""
    parts = []
    for k, v in list(evidence.items())[:4]:
        if isinstance(v, (str, int, float, bool)) or v is None:
            parts.append(f"{k}={v}")
        elif isinstance(v, list):
            parts.append(f"{k}=[{len(v)}]")
    return ", ".join(parts)[:500]


def _disambiguate_instance_keys(cause: Cause) -> None:
    """Make every instance key unique WITHIN its cause, without losing anything.

    Measured on real run 837b75d6: 394 of 8,077 instances share a (cause, url)
    pair, because two different analyzers both emit the same check for the same
    page with DIFFERENT evidence - e.g. ON-048 on /contact/ once reporting
    heading structure and once reporting snippet blocks. Those are two
    observations, not a duplicate, and collapsing them on a url-only key silently
    dropped 394 rows.

    A colliding key is therefore suffixed with a short hash of its own evidence,
    which is deterministic and content-derived rather than positional. If two
    instances are genuinely identical - same url, same evidence - the second is a
    true duplicate and an ordinal separates them so the count still reconciles.
    """
    seen: dict[str, int] = {}
    for inst in cause.instances:
        if sum(1 for i in cause.instances if i.instance_key == inst.instance_key) == 1:
            continue
        digest = hashlib.sha1(
            json.dumps(inst.evidence, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:8]
        key = f"{inst.instance_key}#{digest}"
        n = seen.get(key, 0)
        seen[key] = n + 1
        inst.instance_key = key if n == 0 else f"{key}.{n}"


def build_causes(
    findings: list[dict[str, Any]],
    pages_by_engine_id: dict[int, dict[str, Any]],
    *,
    include_non_issues: bool = False,
) -> list[Cause]:
    """Group findings into causes, keeping every original row as an instance.

    Grouping key is ``(check_id, locus_kind, locus_value, discriminator)``. Locus
    is decided per check, from evidence:

    * no page at all              -> ``site``
    * every affected page shares one template and there are 2+ -> ``template``
    * otherwise                   -> ``url`` (one cause per page)

    Nothing is discarded. ``pass``/``n_a`` rows are excluded by default because a
    cause is a problem, but they remain available for coverage accounting.
    """
    # Pass 1: bucket rows by (check_id, discriminator) so we can see, per check,
    # how many distinct templates it touches before deciding the locus.
    buckets: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for raw in findings:
        status = str(raw.get("status") or "").lower()
        if not include_non_issues and status in NON_ISSUE_STATUSES:
            continue
        check_id = str(raw.get("check_id") or "").strip()
        if not check_id:
            continue
        evidence = _decode(raw.get("evidence_json"))
        buckets[(check_id, discriminator_for(check_id, evidence))].append((raw, evidence))

    causes: dict[str, Cause] = {}
    for (check_id, disc), rows in sorted(buckets.items()):
        page_ids = [r.get("page_id") for r, _ in rows]
        has_pages = any(p is not None for p in page_ids)

        for raw, evidence in rows:
            pid = raw.get("page_id")
            page = pages_by_engine_id.get(int(pid)) if pid is not None else None
            url = (page or {}).get("url", "") or ""
            template_id = (page or {}).get("template_id", "") or ""

            if not has_pages or pid is None:
                # Nothing page-scoped: robots.txt, TLS, sitemap, an orphan report.
                locus_kind, locus_value = "site", ""
            elif len(rows) >= 2 and template_id:
                # The check fires on more than one page and those pages have a
                # template shape, so the fix belongs to the TEMPLATE. locus_value
                # is this page's template, which means a check touching three
                # templates yields three causes - deliberately. Merging them
                # would let one template get fixed while the finding stays open,
                # and the client is told nothing changed.
                locus_kind, locus_value = "template", template_id
            else:
                # A single affected page, or a page with no derivable shape.
                locus_kind, locus_value = "url", url

            fp = fingerprint(
                check_id=check_id, locus_kind=locus_kind,
                locus_value=locus_value, discriminator=disc,
            )
            severity = str(raw.get("severity") or "info").lower()
            cause = causes.get(fp)
            if cause is None:
                cause = Cause(
                    check_id=check_id,
                    check_name=str(raw.get("check_name") or ""),
                    pillar=str(raw.get("pillar") or raw.get("category") or ""),
                    subcategory=str(raw.get("subcategory") or ""),
                    dimension=str(raw.get("dimension") or ""),
                    owner_agent=str(raw.get("owner_agent") or ""),
                    automation=str(raw.get("automation") or ""),
                    severity=severity,
                    status="open",
                    confidence=raw.get("confidence"),
                    locus_kind=locus_kind,
                    locus_value=locus_value,
                    discriminator=disc,
                    fingerprint=fp,
                    remediation=str(raw.get("remediation") or ""),
                    evidence=evidence if locus_kind == "site" else {},
                )
                causes[fp] = cause
            else:
                cause.severity = _worst(cause.severity, severity)
                if not cause.remediation and raw.get("remediation"):
                    cause.remediation = str(raw["remediation"])

            key = url or f"page:{pid}" if pid is not None else f"site:{check_id}"
            cause.instances.append(Instance(
                instance_key=key,
                instance_kind="url" if url else "entity",
                url=url,
                engine_page_id=int(pid) if pid is not None else None,
                template_id=template_id,
                observed=_detail_from(evidence)[:200],
                expected="",
                detail=_detail_from(evidence),
                evidence=evidence,
                severity=severity,
            ))

    for cause in causes.values():
        _disambiguate_instance_keys(cause)

    # Deterministic order: worst first, then by size, then by id. Ties must break
    # the same way every run or the report reorders itself for no reason.
    return sorted(
        causes.values(),
        key=lambda c: (-_SEVERITY_RANK.get(c.severity, 0), -c.instance_count, c.check_id, c.fingerprint),
    )
