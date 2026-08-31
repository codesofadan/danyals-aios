"""Claims grounding: which sentences must cite a supplied fact, and what to do when they do not.

WHY THIS EXISTS, measured rather than assumed. On 2026-08-30 six real pages were
generated for a client after the operator had answered the Experience gate
TRUTHFULLY - "zero clients in this vertical", "no licence or certification of any
kind", "no reviews", "no photos". The pipeline suppressed every trap it had been
named (no invented rating, no invented review count, no named client, no
sister-company-as-customer) and then invented 44 OTHER claims, 29 of them
legal-class: HIPAA and CMS compliance scoring, DEA number verification, title and
lien database lookups, FHIR/HL7 writes, a data-processing agreement, an accuracy
warranty with free rework, and a contact address that does not exist.

The lesson is the shape of the failure, not its size. The old mechanism blocked
STRINGS IT HAD BEEN GIVEN; it had no notion of a claim. So this module does not
enumerate forbidden things. It asks the opposite question - which sentences are
making a checkable claim at all - and then requires those to point at a fact the
operator actually supplied.

HOW THE RULES WERE DERIVED. Not by intuition: the seven triggers below were fitted
to the 44 confirmed fabrications and then measured over all 1008 sentence-units of
the six drafts, with every flagged non-fabrication hand-labelled.

    coverage        44/44 of the confirmed fabrications
    flag rate       40.5 per 100 units
    false positives 14.5% of flags = 5.9 legitimate sentences per 100
    precision       56.1%

FIVE of the seven are load-bearing: no subset of four reaches full coverage.

WHY TWO LANES, AND WHY NOTHING ELSE IS AUTO-DELETED. 56% precision is a usable
DETECTOR and an unusable executioner - deleting six legitimate sentences per
hundred silently is not a trade worth making. Measured separately, the classes
split cleanly:

    auto-delete lane (T3/T4/T6/T7)  17.5 flags per 100, 7.4% FP, catches 22 of 44
    review lane      (T1/T2/T5)     23.0 flags per 100, 19.8% FP, catches 22 of 44

So the machine deletes only where it is right 92.6% of the time - and that lane is
exactly where the legal-severity claims live (compliance, third-party systems,
absolute data-handling guarantees, contact details). The noisy, judgement-heavy
classes - numbers, customer claims, promises - are handed to the reviewer with the
sentence quoted, because a human can settle them in seconds and a regex cannot.

WHAT THIS CANNOT DO, stated plainly because a green result must not be read as
"the page is true":

  * It cannot check that a cited atom SAYS what the sentence says. Roughly a
    quarter of the measured corpus fires a trigger, would carry a valid citation,
    and would survive - invented agent names, a renamed source, invented team
    domains. Comparing sentence to atom is an LLM or human job.
  * `E_DISCLAIM` protects honest retractions ("we hold no certification") from
    deletion. It is a negation heuristic and therefore an exploitable bypass.
  * It sees one sentence at a time, so two sentences that contradict each other
    both pass.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # circular at runtime: context imports nothing from here
    from app.services.content_pipeline.context import PipelineContext, StageResult
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Atoms - the supplied facts, given identities so a sentence can point at one.
# --------------------------------------------------------------------------- #

#: A citation MARKER GROUP: the whole "[[...]]" bracket, whatever is inside it.
#: Deliberately unlikely to occur in prose, and stripped before publication.
#:
#: Tolerant on purpose. The prompt asks for "[[a2]]" and a writer told it may cite
#: more than one will invent its own plural form - MEASURED, a real run emitted
#: "[[a9], [a10]]", which the strict single-id pattern neither recognised as a
#: citation (so the sentence counted as unsourced) nor stripped (so the marker
#: reached the published page). Both halves of that failure are worse than
#: accepting a loose format, so the group is matched first and the ids are read
#: out of it afterwards.
#: Non-greedy from "[[" to the first "]]" on the same line - the only form that
#: survives every plural the writer has invented. Markdown has no "[[ ]]"
#: construct, so the collision risk against real prose is nil.
CITATION_GROUP_RE = re.compile(r"\[\[[^\n]*?\]\]")

#: The atom ids inside a marker group.
_ATOM_ID_RE = re.compile(r"\ba(\d+)\b")


def cited_ids(text: str) -> list[str]:
    """Every atom id cited anywhere in ``text``, in order, however it was written."""
    ids: list[str] = []
    for group in CITATION_GROUP_RE.findall(text):
        ids.extend(f"a{n}" for n in _ATOM_ID_RE.findall(group))
    return ids


@dataclass(frozen=True)
class Atom:
    """One supplied fact the writer is allowed to assert, with an id to cite."""

    id: str
    text: str
    #: Where it came from: "experience" (the SME dossier), "brief" (the operator's
    #: proof points / unique data / services), "profile" (the client's own NAP).
    source: str


def build_atoms(
    facts: Iterable[str],
    *,
    brief_facts: Iterable[str] = (),
    profile_facts: Iterable[str] = (),
) -> tuple[Atom, ...]:
    """Number every supplied fact, in a stable order, dropping blanks and duplicates.

    Order is experience-first because those answers are the ones a human was made to
    sit down and write; a brief bullet is cheaper to produce and easier to overstate.
    """
    atoms: list[Atom] = []
    seen: set[str] = set()
    for source, group in (
        ("experience", facts),
        ("brief", brief_facts),
        ("profile", profile_facts),
    ):
        for raw in group:
            text = " ".join(str(raw).split())
            key = text.lower()
            if not text or key in seen:
                continue
            seen.add(key)
            atoms.append(Atom(id=f"a{len(atoms) + 1}", text=text, source=source))
    return tuple(atoms)


def render_atoms(atoms: Iterable[Atom]) -> str:
    """The fact block for the draft prompt: one numbered atom per line."""
    return "\n".join(f"  [[{a.id}]] {a.text}" for a in atoms)


def strip_citations(markdown: str) -> str:
    """Remove every citation marker. Runs before the draft is shown or published."""
    cleaned = CITATION_GROUP_RE.sub("", markdown)
    # A marker usually sits before the full stop, leaving " ." behind.
    cleaned = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned)


# --------------------------------------------------------------------------- #
# The triggers. Each was fitted to the real corpus; the comment on each names the
# fabrication class it is the SOLE catch for, because that is what stops a later
# reader deleting it as redundant.
# --------------------------------------------------------------------------- #

#: A claim is only a vendor claim when the vendor is its subject. Without this gate
#: T3 fires on every general industry sentence ("clinics must comply with HIPAA")
#: and its false-positive rate measured 29.5%; with it, 4%.
VENDOR_SUBJECT = re.compile(
    r"""(?ix)
    (?: \bwe\b | \bour\b | \bus\b
      | \bthe\s+(?:system|platform|architecture|model|pipeline|agent|agents|tool|audit|
                   chain|engine|fact-?checker|log|trail|first|second|third|fourth|fifth)\b
      | \bthis\s+(?:audit|log|trail|system|architecture|report)\b
      | \b(?:each|another|one|multiple|four|five|ten|parallel|every)\s+
        (?:agent|agents|team|teams|module|modules|verification|specialist)\b
      | ^\s*(?:another|it|each)\s+(?:verifies|validates|checks|flags|runs|scores|extracts|
             cross-references|reviews|owns|handles|queries|pulls|reads|routes)\b
      | \bit\s+(?:flags|checks|pulls|reads|runs|scores|verifies|extracts|routes|handles|
                 cross-references|reviews|owns)\b
    )"""
)

# Sole catch for two quantified before/after case-study fabrications, both
# legal-severity ("a mortgage application that took three minutes now completes in
# under 60 seconds"). It is 51% of flag volume and still cannot be dropped.
T1_NUMERIC = re.compile(
    r"""(?ix)
    (?: \b\d[\d,\.]*\s*% | [\$£€]\s?\d | \b\d[\d,\.]*\b
      | \b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|
             forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion|
             dozen|twice|double|triple)\b
      | \bone\s+(?:command|run|pass|execution|call|week|day|hour|minute|clinic|page|
                   direction|deal|article|prospect)\b )"""
)

# The single most load-bearing trigger: sole catch on 12 of the 44.
T2_CUSTOMER = re.compile(
    r"""(?ix)
    (?: \b(?:client|clients|customer|customers|account|accounts|user|users|
             subscriber|subscribers)\b
      | \bdeploy(?:ed|s|ment|ments|ing)?\b
      | \bin\s+production\b | \bproduction\s+(?:use|deployment)\b
      | \bpilot(?:s|\s+(?:team|teams|program|customer))?\b
      | \b(?:currently|already|now)\s+(?:working|running|using|serving|live)\b
      | \bworking\s+with\b
      | \b(?:case\s+stud|real\s+(?:result|results|example|examples|workflow|workflows|
             production|world))\b
      | \b(?:teams|clinics|brokers|brokerages|agents|firms|enterprises|companies|
             practices|providers|lenders|shops|agencies)\s+
        (?:who|that|using|use|choose|chose|find|report|see|get|start|deploy|run|adopt|switch)\b
      | \b(?:choose|chose|select|selected|switch|switched|adopt|adopted|onboard)\b
      | \b(?:has|have|had)\s+(?:automated|delivered|built|shipped|served)\b
      | \b(?:across|over)\s+\w+\s+(?:client|customer|account)\w*\b
      | \bat\s+scale\b | \broll(?:ed|ing)?\s*out\b )"""
)

# Sole catch on 8, every one legal-severity. GATED on VENDOR_SUBJECT.
T3_COMPLIANCE = re.compile(
    r"""(?ix)
    (?: \bHIPAA\b | \bSOC\s?2\b | \bISO\s?\d | \bGDPR\b | \bCCPA\b | \bPCI(?:\s?DSS)?\b
      | \bDEA\b | \bCMS\b | \bFDA\b | \bFINRA\b | \bSEC\b | \bOSHA\b | \bFERPA\b | \bHL7\b
      | \bFHIR\b | \bE&O\b | \bNIST\b | \bFedRAMP\b | \bSOX\b | \bPHI\b | \bPII\b
      | \bcomplian\w+ | \bcompl(?:y|ies|ied)\b | \bregulat\w+ | \bstatut\w+
      | \baudit(?:ed|able)?\s+trail\w*\b | \baudit\s+log\w*\b
      | \b(?:state\s+board|insurance\s+audit|inspection|inspections)\b
      | \bcertif\w+ | \baccredit\w+ | \blicen[cs]\w+ | \bpermit(?:s|ted)?\b
      | \bregistr(?:ation|ed|y)\b
      | \b(?:legal|liabilit\w+|attorney|counsel|lawsuit|litigation|indemnif\w+)\b
      | \blien\w*\b | \bencumbrance\w*\b
      | \btitle\s+(?:search|record|records|verification|database|databases|issue|issues|report)\b
      | \bzoning\b | \bdisclosur\w+ | \bcontract\w*\b | \bdeed\w*\b
      | \bdata[\s-]processing\s+agreement\b | \bDPA\b
      | \bpatient\s+data\b | \bcontrolled[\s-]substance\b | \bprescrib\w+
      | \bbilling\s+code\w*\b | \bmedical\s+cod\w+
      | \bpublic\s+records?\b | \bcounty\s+records?\b )"""
)

# Named third-party systems: an integration claim is a promise about someone
# else's product, and is checkable by the reader in a way puffery is not.
T4_THIRDPARTY = re.compile(
    r"""(?ix)
    (?: \b(?:
        salesforce|hubspot|pipedrive|zoho|dynamics|netsuite|sap|oracle|workday|
        follow\s?up\s?boss|zurple|kvcore|boomtown|intralinks|
        epic|cerner|athenahealth|allscripts|meditech|ehr|ehrs|mls|
        stripe|quickbooks|xero|docusign|dropbox|box|slack|notion|airtable|shopify|
        hootsuite|mailchimp|marketo|pardot|outreach|salesloft|
        aws|azure|gcp|google\s+cloud|snowflake|databricks|twilio|sendgrid|
        openai|gpt|gemini|llama|mistral|cohere )\b
      | \b(?:county|public|title|land|deed|court|credit|comps?|lien|policy|insurance|
             licensing)\b[\s-]*
        \b(?:record|records|registry|database|databases|feed|feeds|api|apis)\b
      | \b(?:external|independent|third[\s-]party)\s+sources?\b
      | \bbi[\s-]?directional\b | \bboth\s+directions\b | \btwo[\s-]way\b )"""
)

# Sole catch on the published accuracy warranty ("we commit to an accuracy
# threshold"), which is a contractual representation, not marketing.
T5_GUARANTEE = re.compile(
    r"""(?ix)
    (?: \bwe\s+(?:commit|guarantee|promise|warrant|assure|ensure|pledge)\b
      | \bguarantee\w*\b | \bwarrant(?:y|ies|ed)\b | \bSLA\b | \bensur\w+ | \bassur\w+
      | \byou\s+(?:will|won't|will\s+not|do\s+not|don't)\s+\w+
      | \bat\s+no\s+(?:additional\s+)?cost\b | \bfree\s+of\s+charge\b
      | \bmoney[\s-]back\b | \brefund\w*\b
      | \bsatisf(?:y|ies|ied)\b | \bproof\s+of\b | \bsufficient\s+for\b
      | \bthreshold\b | \bcommit(?:s|ment|ted)?\b
      | \bno\s+lock[\s-]?in\b | \bno\s+minimum\b )"""
)

# Sole catch on the absolute data-handling assurances ("No data leaves your
# systems"), which read as contractual and were unbacked by any supplied fact.
T6_ABSOLUTE = re.compile(
    r"""(?ix)
    (?: \bzero\b
      | \bno\s+(?:data|server|servers|subscription|infrastructure|setup|training|
                 lock[\s-]?in|human|manual|additional|risk|cost|fee|fees|login|minimum|
                 delay|downtime|black\s+box|per-seat)\b
      | \bnever\b | \balways\b | \b100\s?%\b | \bfully\s+automat\w+
      | \bevery\s+(?:claim|fact|article|check|lead|touch|record|output|deal|document|
                    extraction|decision|verification|sequence|piece|outreach)\b
      | \ball\s+\d | \bwithout\s+(?:manual|human|any)\b | \beliminat\w+ | \bnothing\b )"""
)

_CONTACT_TOKEN = re.compile(
    r"""(?ix)
    (?: [\w\.\-\+]+@[\w\-]+\.[\w\.\-]+
      | \+?\d[\d\s\-\(\)]{7,}\d
      | \b(?:https?://)?(?:www\.)?[\w\-]+\.(?:com|net|org|io|ai|co)\b )"""
)


def _normalise_contact(token: str) -> str:
    value = re.sub(r"[\s\-()]", "", token).lower().rstrip(".")
    return re.sub(r"^https?://", "", value)


def unknown_contact(sentence: str, allowed: frozenset[str]) -> str | None:
    """Return the first contact detail that is not one the operator supplied.

    A wrong email or phone number is the one defect on this list that costs the
    client money on a page that otherwise reads perfectly: every lead the page
    generates is routed to an address nobody owns. Measured 2 fires in 1008 units
    at 100% precision, so it is never exempted.
    """
    known = {_normalise_contact(c) for c in allowed}
    known |= {c.lstrip("+") for c in known}
    for token in [str(x) for x in _CONTACT_TOKEN.findall(sentence)]:
        value = _normalise_contact(token)
        if value not in known and value.lstrip("+") not in known:
            return token
    return None


# --------------------------------------------------------------------------- #
# Exemptions. Together they halve the false-positive rate (12.3 -> 5.9 per 100)
# at ZERO cost to coverage.
# --------------------------------------------------------------------------- #

#: An honest retraction must never be deleted. Before this existed the pass removed
#: "Northwind has no published HIPAA audit or certification." - which does not just
#: lose a sentence, it makes the page less true than the writer left it.
_NEGATION = re.compile(
    r"""(?ix)
    (?: \b(?:has\s+not|have\s+not|hold[s]?\s+no|has\s+no|have\s+no|holds\s+none|
             do(?:es)?\s+not\s+claim|no\s+published|not\s+yet|cannot|is\s+not|are\s+not|
             does\s+not|do\s+not|never\s+claimed|makes\s+no)\b )"""
)

E_DISCLAIMER = re.compile(
    r"""(?ix)
    (?: \bno\s+system\s+gives\b | \bnone\s+is\s+(?:required|claimed)\b
      | \bis\s+your\s+(?:IT|legal|compliance)\b )"""
)


def _is_disclaimer(sentence: str, subject: re.Pattern[str]) -> bool:
    """A retraction about the vendor, which must never be deleted.

    Deleting "we hold no certification" does not merely lose a sentence: it makes
    the page LESS TRUE than the writer left it, and it does so silently. That is
    strictly worse than the fabrication this module exists to remove, so the
    exemption is checked before any trigger is allowed to delete.

    It keys on the VENDOR SUBJECT rather than a fixed "we|our", because a page
    written in the third person says "Acme Dental holds no certification" and an
    exemption that only understands the first person would delete exactly the
    sentence a careful operator added on purpose.

    This is a negation heuristic and therefore an exploitable bypass - a writer
    that phrases a claim as a double negative walks through it. It is here to
    protect honest text, not to be a security boundary.
    """
    if E_DISCLAIMER.search(sentence):
        return True
    return bool(subject.search(sentence) and _NEGATION.search(sentence))

#: Headings, bold run-ins and calls to action. The void clause matters: a step
#: heading that names the vendor or a regulated capability is NOT navigation.
E_NAVIGATION = re.compile(
    r"""(?ix)
    (?: ^\s*\#+\s*(?:step|stage|q:|faq|is\ there|does\ this|how\ do\ we|can\ i)
      | ^\s*\*\*
      | \b(?:call|visit|email)\s+(?:us|\+|https?) )"""
)

#: Never exempted, whatever else the sentence looks like.
HARD_TRIGGERS = frozenset({"T7-CONTACT"})

#: Deleted automatically: measured 7.4% false positives, and where the
#: legal-severity claims concentrate.
AUTO_DELETE_TRIGGERS = frozenset({"T3-COMPLIANCE", "T4-THIRDPARTY", "T6-ABSOLUTE", "T7-CONTACT"})

#: Surfaced to the reviewer instead: 19.8% false positives is too noisy to delete
#: silently, and a human settles these in seconds.
REVIEW_TRIGGERS = frozenset({"T1-NUMERIC", "T2-CUSTOMER", "T5-GUARANTEE"})


def vendor_pattern(vendor_terms: Iterable[str] = ()) -> re.Pattern[str]:
    """``VENDOR_SUBJECT`` widened with this client's own names.

    The generic gate keys on "we", "our" and "the system", which is what carried
    the measured corpus. But a page that says "Acme Dental is HIPAA compliant"
    names the vendor in the third person and would slip past it, so the client's
    own name and product names are folded in per run. Terms are escaped: a client
    called "C++ Systems" must not compile as a pattern.
    """
    terms = []
    cleaned_terms = []
    for term in vendor_terms:
        cleaned = " ".join(str(term).split())
        if not cleaned:
            continue
        cleaned_terms.append(cleaned)
        # `re.escape` already escapes the space - it is in CPython's special-char
        # map precisely because this pattern is compiled VERBOSE, where a bare
        # space is discarded. Escaping it a second time yields "Acme\\ Dental",
        # which matches a literal backslash and therefore nothing. Measured.
        terms.append(re.escape(cleaned))
    if not terms:
        return VENDOR_SUBJECT
    # The base pattern carries inline (?ix) flags, which Python only accepts at the
    # very start of an expression, so they are stripped before composing.
    base = VENDOR_SUBJECT.pattern.lstrip()
    if base.startswith("(?ix)"):
        base = base[len("(?ix)"):]
    # A word boundary only exists next to a word character. A client called
    # "C++ Systems (UK)" ends in ")", so a trailing \b would require a word char
    # after it and the name would never match - so each side is anchored only
    # where it can be.
    parts = []
    for raw, escaped in zip(cleaned_terms, terms, strict=True):
        left = r"\b" if raw[:1].isalnum() or raw[:1] == "_" else ""
        right = r"\b" if raw[-1:].isalnum() or raw[-1:] == "_" else ""
        parts.append(f"{left}(?:{escaped}){right}")
    extra = "|".join(parts)
    return re.compile(f"(?:{base})|(?:{extra})", re.IGNORECASE | re.VERBOSE)


def needs_citation(
    sentence: str,
    *,
    allowed_contacts: frozenset[str] = frozenset(),
    vendor: re.Pattern[str] | None = None,
) -> dict[str, str]:
    """Which triggers fire on ``sentence``. Empty dict means no citation is required."""
    subject = vendor if vendor is not None else VENDOR_SUBJECT
    fired: dict[str, str] = {}
    for name, pattern in (
        ("T1-NUMERIC", T1_NUMERIC),
        ("T2-CUSTOMER", T2_CUSTOMER),
        ("T4-THIRDPARTY", T4_THIRDPARTY),
        ("T5-GUARANTEE", T5_GUARANTEE),
        ("T6-ABSOLUTE", T6_ABSOLUTE),
    ):
        match = pattern.search(sentence)
        if match:
            fired[name] = match.group(0)
    compliance = T3_COMPLIANCE.search(sentence)
    if compliance and subject.search(sentence):
        fired["T3-COMPLIANCE"] = compliance.group(0)
    contact = unknown_contact(sentence, allowed_contacts)
    if contact:
        fired["T7-CONTACT"] = contact

    if not fired:
        return {}
    if fired.keys() & HARD_TRIGGERS:
        return fired
    navigational = bool(E_NAVIGATION.search(sentence)) and not (
        subject.search(sentence)
        or fired.keys() & {"T3-COMPLIANCE", "T4-THIRDPARTY"}
    )
    if sentence.rstrip().endswith("?") or _is_disclaimer(sentence, subject) or navigational:
        return {}
    return fired


# --------------------------------------------------------------------------- #
# The audit: what the draft claims, and what it is allowed to keep.
# --------------------------------------------------------------------------- #

#: Below this share of claim-sentences carrying a marker, deletion is ABANDONED.
#: The repair stages rewrite the draft wholesale through an LLM, and a model that
#: drops the markers would leave every claim looking unsourced - deleting the page
#: rather than its fabrications. A collapse means the markers were lost, not that
#: the writer invented everything, and the two must never be confused.
MIN_CITED_SHARE = 0.15

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_ABBREVIATION = re.compile(r"\b(?:e\.g|i\.e|etc|vs|Mr|Mrs|Dr|Inc|Ltd|Co|U\.S|approx|No)\.$")


def split_units(markdown: str) -> list[str]:
    """Split into the units the triggers were measured on: headings whole, prose by sentence."""
    units: list[str] = []
    for raw in markdown.split("\n"):
        line = " ".join(raw.split())
        if not line:
            continue
        if line.startswith("#") or line.startswith("!["):
            units.append(line)
            continue
        buffer = ""
        for part in _SENTENCE_SPLIT.split(line):
            buffer = f"{buffer} {part}".strip() if buffer else part
            if not _ABBREVIATION.search(buffer):
                units.append(buffer)
                buffer = ""
        if buffer:
            units.append(buffer)
    return units


@dataclass(frozen=True)
class ClaimFinding:
    """One sentence that makes a checkable claim, and what backs it."""

    sentence: str
    triggers: tuple[str, ...]
    cited: tuple[str, ...]
    lane: str  # "delete" | "review" | "cited"


@dataclass(frozen=True)
class ClaimAudit:
    findings: tuple[ClaimFinding, ...]
    units: int
    #: True when the markers survived well enough to trust a deletion.
    deletable: bool

    @property
    def to_delete(self) -> tuple[ClaimFinding, ...]:
        return tuple(f for f in self.findings if f.lane == "delete")

    @property
    def for_review(self) -> tuple[ClaimFinding, ...]:
        return tuple(f for f in self.findings if f.lane == "review")


def audit_draft(
    markdown: str,
    atoms: Iterable[Atom],
    *,
    allowed_contacts: frozenset[str] = frozenset(),
    vendor: re.Pattern[str] | None = None,
) -> ClaimAudit:
    """Classify every claim-bearing sentence as cited, deletable, or for review."""
    valid = {a.id for a in atoms}
    findings: list[ClaimFinding] = []
    units = split_units(markdown)
    claim_units = 0
    cited_units = 0

    for unit in units:
        fired = needs_citation(unit, allowed_contacts=allowed_contacts, vendor=vendor)
        if not fired:
            continue
        claim_units += 1
        cited = tuple(c for c in cited_ids(unit) if c in valid)
        if cited:
            cited_units += 1
            lane = "cited"
        elif fired.keys() & AUTO_DELETE_TRIGGERS:
            lane = "delete"
        else:
            lane = "review"
        findings.append(
            ClaimFinding(sentence=unit, triggers=tuple(sorted(fired)), cited=cited, lane=lane)
        )

    deletable = claim_units == 0 or (cited_units / claim_units) >= MIN_CITED_SHARE
    return ClaimAudit(findings=tuple(findings), units=len(units), deletable=deletable)


def apply_deletions(markdown: str, audit: ClaimAudit) -> tuple[str, int]:
    """Remove the auto-delete lane's sentences. Returns the draft and the count removed.

    A heading is never removed even when it fires, because deleting a heading
    orphans the section under it - the sentence-level defect becomes a structural
    one. A flagged heading is reported instead.
    """
    if not audit.deletable:
        return markdown, 0
    targets = {f.sentence for f in audit.to_delete if not f.sentence.startswith("#")}
    if not targets:
        return markdown, 0
    removed = 0
    out: list[str] = []
    for raw in markdown.split("\n"):
        line = " ".join(raw.split())
        if not line or line.startswith("#") or line.startswith("!["):
            out.append(raw)
            continue
        kept = []
        for unit in split_units(raw):
            if unit in targets:
                removed += 1
                continue
            kept.append(unit)
        out.append(" ".join(kept) if kept else "")
    # A paragraph emptied by deletion leaves a blank line; collapse the runs.
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text), removed


# --------------------------------------------------------------------------- #
# The stage
# --------------------------------------------------------------------------- #

STAGE = "claims"


def run_claims(
    ctx: PipelineContext,
    *,
    allowed_contacts: frozenset[str] = frozenset(),
    vendor_terms: Iterable[str] = (),
) -> StageResult:
    """Delete the uncited claims the machine is reliably right about; report the rest.

    Runs IMMEDIATELY AFTER the draft, and the position is the whole design.

    The obvious place is at the end, auditing the text that actually ships. That was
    tried and it does not work: `convert`, `voice` and `grounding` each rewrite the
    document wholesale through an LLM, and MEASURED over six real pages, the citation
    markers did not survive them - 5 of 6 finished pages carried none. With no
    markers every claim looks unsourced, the fail-safe correctly refuses to delete,
    and the stage becomes a no-op that reports. Fabrications on that run: 43, against
    a baseline of 44.

    So it runs where the evidence still exists. The cost is real and worth naming:
    a later stage could introduce a claim this never saw. Those stages are instructed
    not to add facts, and the QA gate still scores the finished page - but the honest
    statement is that this check covers the DRAFT, not the final text.

    It never fails the page. A page whose fabrications were removed is a shorter,
    truer page; a page whose markers were lost is reported and left alone. Neither
    is an error, so the outcome is "ok" or "degraded", never "failed".
    """
    from app.services.content_pipeline.context import StageOutcome, StageResult

    atoms = build_atoms(ctx.facts)
    vendor = vendor_pattern([*vendor_terms, ctx.client_name] if ctx.client_name else vendor_terms)
    audit = audit_draft(
        ctx.draft_md, atoms, allowed_contacts=allowed_contacts, vendor=vendor
    )

    cleaned, removed = apply_deletions(ctx.draft_md, audit)
    # Markdown only honours "##" at the start of a line, so a heading left mid-
    # paragraph publishes as literal hash characters and its keyword intent never
    # becomes a heading at all. Repaired here because it is a formatting invariant
    # with one correct answer.
    cleaned, moved = normalise_headings(cleaned)
    # The markers are the pipeline's private bookkeeping and must never reach a
    # reader, whether or not anything was deleted.
    ctx.draft_md = strip_citations(cleaned)

    notes: list[str] = []
    if moved:
        notes.append(f"moved {moved} heading(s) back onto their own line")
    for heading in overlong_headings(ctx.draft_md):
        notes.append(f"heading appears to have swallowed its paragraph: {heading}")
    if removed:
        notes.append(
            f"removed {removed} sentence(s) making a compliance, third-party, "
            "absolute or contact claim that cited no supplied fact"
        )
    if not audit.deletable and audit.findings:
        notes.append(
            "citation markers did not survive the rewrite stages, so NOTHING was "
            "deleted - the claims below are reported, not removed"
        )
    for finding in audit.for_review:
        notes.append(f"unverified claim, needs a human: {finding.sentence[:160]}")
    for finding in audit.to_delete if not audit.deletable else ():
        notes.append(f"unsourced claim, NOT removed: {finding.sentence[:160]}")

    structural = bool(overlong_headings(ctx.draft_md))
    outcome: StageOutcome = (
        "ok" if (audit.deletable and not audit.for_review and not structural) else "degraded"
    )
    return ctx.record(StageResult(
        STAGE,
        outcome=outcome,
        notes=tuple(notes),
        data={
            "removed": removed,
            "deletable": audit.deletable,
            "claims": len(audit.findings),
            "for_review": [f.sentence for f in audit.for_review],
            "unsourced_kept": [f.sentence for f in audit.to_delete] if not audit.deletable else [],
        },
    ))


#: A markdown ATX heading that has ended up mid-line. Requires whitespace before
#: the hashes and a space after them, so a URL fragment ("...#section"), a hex
#: colour and a "C# developer" are all left alone.
_INLINE_HEADING_RE = re.compile(r"(?<=\S)[ \t]+(\#{2,6})[ \t]+(?=\S)")

_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")


def normalise_headings(markdown: str) -> tuple[str, int]:
    """Put every heading back on its own line. Returns the text and the count moved.

    MEASURED: a real run produced a 4,176-character line holding an H2 and roughly
    900 words of prose, with two more H2s buried inside it. Markdown only treats
    "##" as a heading at the START of a line, so those render as literal hash
    characters in the middle of a wall of text on the client's published page -
    and the section headings that carry the page's keyword intent never become
    headings at all.

    This is done mechanically rather than by asking the writer again, because it is
    a formatting invariant with one correct answer, and a stage that spends money to
    re-request compliance can still come back wrong. Fenced code blocks are skipped:
    inside one, "## " is content.
    """
    out: list[str] = []
    moved = 0
    in_fence = False
    for line in markdown.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or "#" not in line:
            out.append(line)
            continue
        pieces = _INLINE_HEADING_RE.split(line)
        if len(pieces) == 1:
            out.append(line)
            continue
        # split() yields [text, hashes, text, hashes, text...]
        rebuilt = [pieces[0]]
        for i in range(1, len(pieces), 2):
            moved += 1
            rebuilt.append("")
            rebuilt.append(f"{pieces[i]} {pieces[i + 1].lstrip()}")
        out.extend(x for x in rebuilt)
    return "\n".join(out), moved


#: A heading longer than this has almost certainly swallowed the paragraph that
#: should follow it. Measured: a real run produced an H2 carrying ~900 words.
MAX_HEADING_CHARS = 120


def overlong_headings(markdown: str) -> list[str]:
    """Headings that appear to have absorbed their own body text.

    Moving a buried heading onto its own line is unambiguous and done. Deciding
    WHERE the heading ends and the prose begins is not - "(Beyond Chat) AI
    automation for real estate goes..." has no reliable boundary - and a wrong
    split produces a different silent defect in place of this one. So these are
    reported for a human instead of guessed at.
    """
    found: list[str] = []
    in_fence = False
    for line in markdown.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        stripped = line.strip()
        if in_fence or not stripped.startswith("#"):
            continue
        if len(stripped) > MAX_HEADING_CHARS:
            found.append(stripped[:160])
    return found
