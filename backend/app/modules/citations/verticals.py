"""The citation vertical taxonomy (the "match vertical + country" strategy layer).

The reference plan's central selection rule is *a niche directory only helps when it
matches the client's industry* - so a directory row can be tagged with the verticals
it serves (``public.directories.verticals``, 0048) and a campaign can filter to the
client's own vertical instead of blasting every automatable row at every client.

This module is the ONE canonical list of vertical keys (mirrored by the DB check is
NOT enforced - ``verticals`` is a free ``text[]`` so the catalog can carry a key this
list has not caught up to yet - but every WRITER should pull keys from here). It also
maps a client's free-text ``clients.industry`` onto a vertical key, since that field
is an unconstrained string today.

Verticals are grouped into the 5 categories the reference plan uses. A directory with
an EMPTY ``verticals`` array is *general* - it applies to every client regardless of
industry (YellowPages, BBB, the global core); a niche directory names its verticals.
"""

from __future__ import annotations

# category -> ordered vertical keys (the reference plan's 29 niches).
VERTICAL_CATEGORIES: dict[str, tuple[str, ...]] = {
    "Professional": ("legal", "financial", "insurance"),
    "Healthcare": ("medical", "dental", "chiropractic", "mental_health"),
    "Home Services": (
        "hvac", "plumbing", "roofing", "electrical", "general_contractor",
        "landscaping", "pest_control", "cleaning", "locksmith", "moving",
    ),
    "Food & Consumer": ("restaurants", "automotive", "real_estate", "hospitality"),
    "Personal & Events": (
        "beauty", "fitness", "photography", "wedding", "veterinary",
        "childcare", "funeral", "senior_care",
    ),
}

# The flat set of every valid vertical key (29).
VERTICAL_KEYS: frozenset[str] = frozenset(
    k for keys in VERTICAL_CATEGORIES.values() for k in keys
)

# Human labels for the UI / reporting (fall back to a title-cased key).
VERTICAL_LABELS: dict[str, str] = {
    "legal": "Legal / Attorneys",
    "financial": "Financial / Accounting",
    "insurance": "Insurance",
    "medical": "Medical / Doctors",
    "dental": "Dental",
    "chiropractic": "Chiropractic",
    "mental_health": "Mental Health / Therapy",
    "hvac": "HVAC",
    "plumbing": "Plumbing",
    "roofing": "Roofing",
    "electrical": "Electrical",
    "general_contractor": "General Contractor / Remodeling",
    "landscaping": "Landscaping / Lawn / Tree",
    "pest_control": "Pest Control",
    "cleaning": "Cleaning / Janitorial",
    "locksmith": "Locksmith / Security",
    "moving": "Moving / Storage",
    "restaurants": "Restaurants / Bars / Cafes",
    "automotive": "Automotive / Repair / Dealers",
    "real_estate": "Real Estate / Realtors",
    "hospitality": "Hotels / Hospitality / Travel",
    "beauty": "Beauty / Salon / Spa",
    "fitness": "Fitness / Gyms / Yoga",
    "photography": "Photography",
    "wedding": "Wedding / Events / Venues",
    "veterinary": "Veterinary / Pet Services",
    "childcare": "Childcare / Daycare / Tutoring",
    "funeral": "Funeral / Cremation",
    "senior_care": "Senior Care / Assisted Living",
}

# Keyword -> vertical key. A client's free-text industry is matched (case-insensitive
# substring) against these; the FIRST match wins, so more specific phrases lead. This
# is intentionally forgiving (an unmatched industry just means "general only", never
# an error) - the operator can always override the resolved vertical on the campaign.
_INDUSTRY_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("law", "legal"), ("attorney", "legal"), ("lawyer", "legal"), ("legal", "legal"),
    ("accounting", "financial"), ("accountant", "financial"), ("cpa", "financial"),
    ("financial", "financial"), ("wealth", "financial"), ("advisor", "financial"),
    ("insurance", "insurance"),
    ("dental", "dental"), ("dentist", "dental"), ("orthodont", "dental"),
    ("chiropract", "chiropractic"),
    ("therapy", "mental_health"), ("therapist", "mental_health"),
    ("psycholog", "mental_health"), ("counsel", "mental_health"), ("mental", "mental_health"),
    ("medical", "medical"), ("doctor", "medical"), ("physician", "medical"),
    ("clinic", "medical"), ("health", "medical"),
    ("hvac", "hvac"), ("heating", "hvac"), ("cooling", "hvac"), ("air condition", "hvac"),
    ("plumb", "plumbing"),
    ("roof", "roofing"),
    ("electric", "electrical"),
    ("remodel", "general_contractor"), ("contractor", "general_contractor"),
    ("construction", "general_contractor"), ("renovat", "general_contractor"),
    ("landscap", "landscaping"), ("lawn", "landscaping"), ("tree", "landscaping"),
    ("pest", "pest_control"), ("exterminat", "pest_control"),
    ("clean", "cleaning"), ("maid", "cleaning"), ("janitor", "cleaning"),
    ("locksmith", "locksmith"), ("security", "locksmith"),
    ("moving", "moving"), ("mover", "moving"), ("storage", "moving"),
    ("restaurant", "restaurants"), ("cafe", "restaurants"), ("bar", "restaurants"),
    ("food", "restaurants"), ("dining", "restaurants"),
    ("auto", "automotive"), ("car ", "automotive"), ("vehicle", "automotive"),
    ("mechanic", "automotive"), ("dealer", "automotive"),
    ("real estate", "real_estate"), ("realtor", "real_estate"), ("property", "real_estate"),
    ("hotel", "hospitality"), ("hospitality", "hospitality"), ("travel", "hospitality"),
    ("lodging", "hospitality"),
    ("salon", "beauty"), ("spa", "beauty"), ("beauty", "beauty"), ("barber", "beauty"),
    ("gym", "fitness"), ("fitness", "fitness"), ("yoga", "fitness"), ("crossfit", "fitness"),
    ("photograph", "photography"),
    ("wedding", "wedding"), ("event", "wedding"), ("venue", "wedding"),
    ("veterin", "veterinary"), ("pet", "veterinary"), ("animal", "veterinary"),
    ("childcare", "childcare"), ("daycare", "childcare"), ("tutor", "childcare"),
    ("funeral", "funeral"), ("cremation", "funeral"), ("cemetery", "funeral"),
    ("senior", "senior_care"), ("assisted living", "senior_care"), ("elder", "senior_care"),
)


def normalize_vertical(industry: str | None) -> str | None:
    """Map a client's free-text ``industry`` onto a vertical key, or ``None`` if it
    matches no known vertical (which the caller treats as "general directories only").
    Case-insensitive first-substring-match; an exact vertical key also matches itself.
    """
    if not industry:
        return None
    text = industry.strip().lower()
    if text in VERTICAL_KEYS:
        return text
    for needle, key in _INDUSTRY_KEYWORDS:
        if needle in text:
            return key
    return None
