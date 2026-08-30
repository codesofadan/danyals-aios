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
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# Atoms - the supplied facts, given identities so a sentence can point at one.
# --------------------------------------------------------------------------- #

#: How a citation appears in the draft. Deliberately unlikely to occur in prose,
#: and stripped before anything is published.
CITATION_RE = re.compile(r"\[\[(a\d+)\]\]")


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
    cleaned = CITATION_RE.sub("", markdown)
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
#: "Xegents has no published HIPAA audit or certification." - which does not just
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
