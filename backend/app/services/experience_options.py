"""Offer the Experience questions as PICKABLE options, without inventing an answer.

THE PROBLEM THIS SOLVES. The SME gate refuses to draft a page until its first-party
facts are supplied (``content_pipeline/sme.py``), and the only way to supply them was to
write prose into a textarea. A business owner asked to type seven paragraphs abandons the
form, so pages sat held and the module's best safety property read as its worst friction.

THE RULE THAT MAKES A DROPDOWN SAFE. Every option here is DERIVED FROM EVIDENCE THE
CLIENT ALREADY GAVE US - their own supplied proof points, their own site copy, their own
prior answers for another cluster, their own business record - and every option carries
the words that say where it came from. Nothing is generated, nothing is inferred from
"businesses like this usually", and there is no model call in this module. So a pick is
the client CONFIRMING their own fact, which is the thing the gate actually wants; what it
forbids is a fluent sentence nobody can trace, and that is precisely what cannot be
produced here.

    option.value     what gets stored as the answer
    option.evidence  where it came from, in words a human can check later

THREE OPTIONS ARE NOT EXTRACTIONS, and each is a deliberate non-claim:

  * ``decline``  - "we do not have this, do not reference it". An explicit refusal is a
    real, useful answer: it satisfies the gate (the operator HAS answered) while telling
    the writer not to claim the thing. Without it the only way past a question you cannot
    answer is to make something up, which is the failure mode we are avoiding.
  * ``artifact`` - "I will attach the document/photo". The artifact IS the answer under
    the doctrine, so this option exists to route the answer to the upload field rather
    than to prose.
  * ``own_words`` - the free-text escape. Kept first-class and never removed: a dropdown
    cannot carry "the job that taught us to check the loft first", and the moment the
    options pretend otherwise the client picks the nearest lie.

Pure: stdlib only, no database, no network, no clock, no model. Same evidence in, same
options out - which is what lets the whole surface be tested without a provider.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: The kinds of option, ordered by how much weight a reader should give them. `prior`
#: first because a fact the client already attested for another cluster is the strongest
#: thing we can offer: they wrote it, about themselves, for the same purpose.
OPTION_KINDS: tuple[str, ...] = (
    "prior",      # attested by this client for another cluster
    "supplied",   # from the grounding this job's operator supplied (proof points etc.)
    "record",     # from the client's own stored business record
    "site",       # quoted from the client's own site copy
    "artifact",   # "I will attach the proof" - routes to the upload field
    "decline",    # "we do not have this" - an explicit, honest non-claim
    "own_words",  # free text
)


@dataclass(frozen=True, slots=True)
class Option:
    """One pickable answer. ``value`` is stored verbatim; ``evidence`` says why it was offered."""

    value: str
    evidence: str
    kind: str

    def as_dict(self) -> dict[str, str]:
        return {"value": self.value, "evidence": self.evidence, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class PriorAnswer:
    """An answer this client already attested, for a different cluster."""

    slot_key: str
    answer: str
    cluster_key: str = ""
    answered_on: str = ""  # already formatted for display; this module has no clock


@dataclass(slots=True)
class Evidence:
    """Everything we legitimately know about the client, gathered by the caller.

    Every field is something the client or their operator supplied. There is no field for
    a guess, and nothing in this module writes one.
    """

    client_name: str = ""
    city: str = ""
    site_url: str = ""
    industry: str = ""
    since_year: str = ""
    contact_name: str = ""
    contact_role: str = ""
    services: tuple[str, ...] = ()
    proof_points: tuple[str, ...] = ()
    testimonials: tuple[str, ...] = ()
    unique_data: tuple[str, ...] = ()
    #: Copy read off the client's own site (about/home text, already trimmed).
    site_copy: tuple[str, ...] = ()
    #: Answers this client attested for other clusters.
    prior: tuple[PriorAnswer, ...] = ()
    #: Google Business Profile facts, when the platform holds them.
    review_count: int | None = None
    review_rating: float | None = None
    review_platform: str = ""
    _seen: set[str] = field(default_factory=set, repr=False)


# --------------------------------------------------------------------------- #
# Extraction patterns. Deliberately narrow: a pattern that matches loosely
# produces a confident-looking option built on nothing, which is worse than no
# option at all - the client would be picking OUR mistake and attesting it.
# --------------------------------------------------------------------------- #

# "since 2016", "established 1998", "est. 2009", "trading since 2014", "founded in 2020"
_YEAR_RE = re.compile(
    r"\b(?:since|established|estd?\.?|founded(?:\s+in)?|serving\s+\w+\s+since|operating\s+since)"
    r"\D{0,12}(19[5-9]\d|20[0-4]\d)\b",
    re.IGNORECASE,
)
# A bare 4-digit year is NOT enough on its own (a price, a postcode, a model number all
# match), so the bare form is only read from a field that MEANS a year.
_BARE_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")

# "licence no. ABC-1234", "license #99321", "registration number 0987654", "Reg No: 12345"
#
# The optional `no. / number / #` group in the middle is load-bearing and was missed
# first time round: "Licence no. ABC-12345" is the form people actually write, and a
# pattern that only allowed punctuation between the keyword and the number skipped every
# one of them - so the commonest licence phrasing on earth produced no option at all.
_LICENCE_RE = re.compile(
    # `registered` before `reg`: the commonest English phrasing is the PARTICIPLE
    # ("Gas Safe registered, number 552831", "VAT registered 12345678"), and `\breg\b`
    # cannot match inside it, so the form people actually write produced no option at
    # all. Longest-first, because alternation is ordered.
    r"\b(licen[cs]e|permit|registration|registered|reg|abn|acn|ein|utr|vat)\b"
    r"(?:[^A-Za-z0-9]{0,4}(?:no\.?|number|num\.?|#|id)\b)?"
    # NO SPACE inside the identifier class. Under IGNORECASE, `[A-Z]` also matches
    # lowercase, so a class containing a space ran straight on into the prose after the
    # number: "Licence no. ABC-12345 issued by the city" captured
    # "ABC-12345 ISSUED BY THE". A licence number written with internal spaces is
    # indistinguishable from a sentence, which is the ambiguity that bit here.
    r"[^A-Za-z0-9]{0,6}((?:[A-Z]{1,4}-?)?\d[\dA-Za-z\-]{2,18})",
    re.IGNORECASE,
)
# "450+ projects", "1,200 jobs completed", "over 300 installations", "80 homes"
_COUNT_RE = re.compile(
    r"\b(?:over\s+|more\s+than\s+|completed\s+)?(\d{1,3}(?:,\d{3})+|\d{2,6})\s*\+?\s*"
    # Up to two words may sit between the number and its noun ("200 past projects",
    # "450 successfully completed installs"); without this the commonest phrasings a
    # business actually writes were skipped and the question offered nothing.
    r"(?:[\w-]+\s+){0,2}?"
    r"(jobs?|projects?|clients?|customers?|installs?|installations?|repairs?|homes?|"
    r"businesses|sites?|properties|cases?|patients?|students?|audits?|campaigns?)\b",
    re.IGNORECASE,
)
# "87 reviews", "over 1,200 five-star reviews", "rated by 340 customers"
_REVIEW_COUNT_RE = re.compile(
    r"\b(?:over\s+|more\s+than\s+)?(\d{1,3}(?:,\d{3})+|\d{1,6})\s*\+?\s*"
    r"(?:[\w-]+\s+){0,2}?reviews?\b",
    re.IGNORECASE,
)
# Review platforms we are willing to name, because a wrong platform is a wrong citation.
_REVIEW_PLATFORMS: tuple[tuple[str, str], ...] = (
    ("google", "Google"),
    ("trustpilot", "Trustpilot"),
    ("yelp", "Yelp"),
    ("checkatrade", "Checkatrade"),
    ("houzz", "Houzz"),
    ("facebook", "Facebook"),
    ("tripadvisor", "Tripadvisor"),
    ("clutch", "Clutch"),
)
# "— Sarah Whitfield, Operations Manager" / "Dr. Amir Khan, Principal Dentist"
_NAMED_ROLE_RE = re.compile(
    r"\b((?:Dr\.?\s+|Mr\.?\s+|Ms\.?\s+|Mrs\.?\s+)?[A-Z][a-z]+(?:\s+[A-Z][a-z'\-]+){1,2})"
    r"\s*[,—-]\s*([A-Z][A-Za-z /]{3,40}?(?:Manager|Director|Owner|Founder|Lead|Engineer|"
    r"Technician|Dentist|Surgeon|Principal|Partner|Consultant|Specialist|Officer|Plumber|"
    r"Electrician|Chef|Trainer|Therapist))\b"
)

#: The canonical refusals. Written as instructions to the writer, not as prose it could
#: paraphrase into a claim - "do not reference" is unambiguous in a grounding trace.
DECLINE_TEXT: dict[str, str] = {
    "founding_date": "No public founding record to cite - do not state a founding year.",
    "license_permit": "No licence, permit or registration for this work - do not "
                      "reference one.",
    "count_source": "No job or project count we can evidence - do not state a number.",
    "photo": "No original photography available - do not imply first-hand imagery.",
    "review_source": "No public reviews to cite - do not state a review count or rating.",
    "named_team": "No named individual to attribute this to - keep it to the business.",
    "credential_source": "No certification or accreditation for this - do not claim one.",
}

#: What an "I will attach it" pick means per slot, and it routes to the upload field.
ARTIFACT_TEXT: dict[str, str] = {
    "photo": "Our own dated photograph - attached.",
    "license_permit": "Licence document - attached.",
    "credential_source": "Certificate - attached.",
    "count_source": "Job log or CRM export - attached.",
    "founding_date": "Registration document - attached.",
    "review_source": "Review export - attached.",
    "named_team": "Team biography or profile - attached.",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _add(out: list[Option], seen: set[str], option: Option) -> None:
    """Append unless an identical VALUE is already offered (same fact, two sources)."""
    key = option.value.strip().lower()
    if not key or key in seen:
        return
    seen.add(key)
    out.append(option)


def _evidence_lines(ev: Evidence) -> tuple[tuple[str, str], ...]:
    """Every line of client-supplied text, paired with what to call it.

    The label is the whole point: it becomes ``answer_evidence``, so a reader six months
    later can go back to the same place and check.
    """
    lines: list[tuple[str, str]] = []
    for text in ev.proof_points:
        lines.append((text, "a proof point you supplied for this build"))
    for text in ev.unique_data:
        lines.append((text, "your own data, supplied for this build"))
    for text in ev.testimonials:
        lines.append((text, "a testimonial you supplied"))
    for text in ev.site_copy:
        lines.append((text, f"copy on your own site{f' ({ev.site_url})' if ev.site_url else ''}"))
    return tuple((_clean(t), label) for t, label in lines if _clean(t))


def _prior_options(ev: Evidence, slot_key: str, out: list[Option], seen: set[str]) -> None:
    for prior in ev.prior:
        if prior.slot_key != slot_key:
            continue
        answer = _clean(prior.answer)
        if not answer:
            continue
        where = f"the '{prior.cluster_key}' cluster" if prior.cluster_key else "another cluster"
        when = f" on {prior.answered_on}" if prior.answered_on else ""
        _add(out, seen, Option(answer, f"you answered this for {where}{when}", "prior"))


def _founding_options(ev: Evidence, out: list[Option], seen: set[str]) -> None:
    if ev.since_year:
        year = _clean(ev.since_year)
        match = _BARE_YEAR_RE.search(year)
        if match:
            _add(out, seen, Option(
                f"Trading since {match.group(1)}.",
                "the founding year on your client record",
                "record",
            ))
    for text, label in _evidence_lines(ev):
        found = _YEAR_RE.search(text)
        if found:
            _add(out, seen, Option(
                f"Trading since {found.group(1)}, as stated in: “{text[:140]}”",
                label,
                "site" if "site" in label else "supplied",
            ))


def _licence_options(ev: Evidence, out: list[Option], seen: set[str]) -> None:
    for text, label in _evidence_lines(ev):
        for kind, number in _LICENCE_RE.findall(text):
            number = _clean(number)
            if len(number) < 4:
                continue
            _add(out, seen, Option(
                f"{_clean(kind).title()} {number}, as stated in: “{text[:140]}”",
                label,
                "site" if "site" in label else "supplied",
            ))


def _count_options(ev: Evidence, out: list[Option], seen: set[str]) -> None:
    for text, label in _evidence_lines(ev):
        for number, noun in _COUNT_RE.findall(text):
            _add(out, seen, Option(
                f"{number} {_clean(noun).lower()} - the figure you gave in: “{text[:140]}”",
                label,
                "site" if "site" in label else "supplied",
            ))


def _review_options(ev: Evidence, out: list[Option], seen: set[str]) -> None:
    if ev.review_count:
        platform = _clean(ev.review_platform) or "Google Business Profile"
        rating = f" at {ev.review_rating:.1f}★" if ev.review_rating else ""
        _add(out, seen, Option(
            f"{ev.review_count} reviews on {platform}{rating}.",
            f"measured from your {platform} listing",
            "record",
        ))
    for text, label in _evidence_lines(ev):
        low = text.lower()
        for needle, name in _REVIEW_PLATFORMS:
            if needle not in low:
                continue
            # A REVIEW count, read with its own pattern rather than the job-count one:
            # "87 reviews" is not 87 jobs, and sharing a regex between the two would let
            # a review tally be offered as a project tally on the neighbouring question.
            count = _REVIEW_COUNT_RE.search(text)
            detail = f" - {count.group(1)} of them" if count else ""
            _add(out, seen, Option(
                f"Reviews are public on {name}{detail}.",
                label,
                "site" if "site" in label else "supplied",
            ))


def _named_team_options(ev: Evidence, out: list[Option], seen: set[str]) -> None:
    if ev.contact_name:
        role = f", {_clean(ev.contact_role)}" if ev.contact_role else ""
        _add(out, seen, Option(
            f"{_clean(ev.contact_name)}{role}.",
            "the primary contact on your client record",
            "record",
        ))
    for text, label in _evidence_lines(ev):
        for name, role in _NAMED_ROLE_RE.findall(text):
            _add(out, seen, Option(
                f"{_clean(name)}, {_clean(role)}.",
                label,
                "site" if "site" in label else "supplied",
            ))


def _photo_options(ev: Evidence, out: list[Option], seen: set[str]) -> None:
    if ev.site_url:
        _add(out, seen, Option(
            f"Use the original photographs already published on {ev.site_url}.",
            "your own site's imagery",
            "site",
        ))


#: slot_key -> the extractor that can honestly offer options for it.
_EXTRACTORS = {
    "founding_date": _founding_options,
    "license_permit": _licence_options,
    "credential_source": _licence_options,
    "count_source": _count_options,
    "review_source": _review_options,
    "named_team": _named_team_options,
    "photo": _photo_options,
}


def options_for(slot_key: str, ev: Evidence) -> list[Option]:
    """Every option we can honestly offer for one proof slot, strongest first.

    The order is the reading order the client gets: their own prior attestation, then
    what this build supplied, then their record and their site, then the two structural
    non-claims (attach it / we do not have it), and free text last. An empty extraction
    is a perfectly good result - the client simply types the answer, which is exactly
    the behaviour before this module existed.
    """
    out: list[Option] = []
    seen: set[str] = set()
    _prior_options(ev, slot_key, out, seen)
    extractor = _EXTRACTORS.get(slot_key)
    if extractor is not None:
        extractor(ev, out, seen)
    artifact = ARTIFACT_TEXT.get(slot_key)
    if artifact:
        _add(out, seen, Option(artifact, "you will attach the proof", "artifact"))
    decline = DECLINE_TEXT.get(slot_key)
    if decline:
        _add(out, seen, Option(decline, "an explicit non-claim: nothing will be stated",
                               "decline"))
    return out


def options_for_all(slot_keys: tuple[str, ...], ev: Evidence) -> dict[str, list[Option]]:
    """``options_for`` across a dossier's slots."""
    return {key: options_for(key, ev) for key in slot_keys}


def evidence_from(
    *,
    client: dict[str, object] | None = None,
    source_pack: dict[str, object] | None = None,
    site_copy: tuple[str, ...] = (),
    prior: tuple[PriorAnswer, ...] = (),
    review_count: int | None = None,
    review_rating: float | None = None,
    review_platform: str = "",
) -> Evidence:
    """Build :class:`Evidence` from the rows the caller already holds.

    Tolerant by construction: every field is optional and a missing one simply produces
    fewer options. A caller that can only see the client row still gets the record-based
    options, which is better than the empty dropdown the alternative would give.
    """
    client = client or {}
    pack = source_pack or {}
    raw_facts = pack.get("facts")
    # `source_pack["facts"]` is operator-seeded jsonb, so it may be anything at all.
    # Narrowed here once rather than trusted at each read below.
    facts: dict[str, object] = raw_facts if isinstance(raw_facts, dict) else {}

    def _strs(value: object) -> tuple[str, ...]:
        if isinstance(value, (list, tuple)):
            return tuple(_clean(str(v)) for v in value if _clean(str(v)))
        return ()

    site_url = _clean(str(pack.get("site_url") or pack.get("wp_site_url") or ""))
    return Evidence(
        client_name=_clean(str(client.get("name") or pack.get("client_name") or "")),
        city=_clean(str(client.get("city") or "")),
        site_url=site_url,
        industry=_clean(str(client.get("industry") or facts.get("industry") or "")),
        since_year=_clean(str(client.get("since_year") or facts.get("founded") or "")),
        contact_name=_clean(str(client.get("contact_name") or facts.get("primary_contact") or "")),
        contact_role=_clean(str(client.get("contact_role") or facts.get("contact_role") or "")),
        services=_strs(pack.get("services")),
        proof_points=_strs(pack.get("proof_points")),
        testimonials=_strs(pack.get("testimonials")),
        unique_data=_strs(pack.get("unique_data")),
        site_copy=tuple(_clean(s) for s in site_copy if _clean(s)),
        prior=prior,
        review_count=review_count,
        review_rating=review_rating,
        review_platform=_clean(review_platform),
    )
