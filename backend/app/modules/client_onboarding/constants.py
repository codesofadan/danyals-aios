"""The client-onboarding TEMPLATE - the 11-step local-SEO activation, in CODE.

The template is a versioned CONSTANT, not DB rows and not a template builder UI.
That is a deliberate design choice: the checklist IS the agency's delivery
methodology, so it belongs in git where a change is reviewed, diffed and shipped
like any other behaviour change - not edited live in a table where it silently
drifts per-client and nobody can answer "what did we promise in March?".
``onboarding_runs.template_key`` records which template seeded a run, so an old
run stays readable after this list evolves.

WHY THESE ELEVEN STEPS (the researched local-SEO activation order):

1.  ``kickoff``             - goals + SMART targets FIRST. Everything downstream
    (which keywords matter, what "done" looks like, what the report proves) is
    unanswerable without it, and a kickoff is the cheapest place to discover the
    client's real objective is not the one on the contract.
2.  ``collect_gbp``         - Google Business Profile ownership/manager access.
    The single highest-leverage local asset, and the one most likely to be a
    fight: an ex-agency, a franchise HQ or a long-gone employee often still owns
    it. Starting it early means the ownership-transfer clock starts early.
3.  ``collect_website_cms`` - CMS + hosting + DNS. Three distinct doors that are
    routinely with three distinct parties; DNS in particular is the one nobody
    can find on the day it is urgently needed.
4.  ``collect_analytics``   - GA4 + GTM. Without it there is no baseline, and
    without a baseline nothing that follows can be proven to have worked.
5.  ``collect_search_console`` - GSC + Bing. The only first-party source of query
    and indexation truth; property verification can take days, so it is collected
    with the rest of the access rather than when it is first needed.
6.  ``brand_assets``        - logo, guidelines, voice, photos. The content sprint
    stalls without them, and real photography is a genuine local-pack ranking and
    conversion asset, not decoration.
7.  ``competitor_list``     - 3-5 REAL local competitors, named by the client. The
    people who answer the phones know who actually takes their business; a
    tool-derived list frequently names national aggregators instead.
8.  ``keyword_seeds``       - the seed list by location + intent. Feeds the
    keyword_research module; a local engagement is location x intent, so seeding
    on both axes is what stops the plan drifting national.
9.  ``baseline_audit``      - ties to the audit module. The before-photo: run it
    while the engagement is young, because after the first fix it can never be
    taken again.
10. ``content_plan``        - the sprint plan, derived from 7 + 8 + 9.
11. ``reporting_setup``     - cadence, recipients and report access. Last, because
    it reports on everything above; done at all, because "when do I hear from
    you?" is the question that quietly ends engagements.

The five ``collect_*`` steps are the credential-bearing ones: advancing one with a
credential SEALS it into the key vault (``kind='client_access'``) and stores only
the returned reference on the step. ``DEFAULT_OWNER_ROLE`` is the role that
typically carries the step - guidance for the assigning lead, NOT an access
control (the RBAC gate is ``manage_clients`` + the 0040 RLS policies).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# The template this module seeds from. Stored on every run (see 0040) so a run
# outlives the template it was cut from.
DEFAULT_TEMPLATE_KEY: Final = "local_seo_default"


@dataclass(frozen=True)
class StepTemplate:
    """One step of the versioned onboarding template.

    ``key`` is the stable identifier (unique per run - the 0040 unique index);
    ``label`` is the display text snapshotted onto the step row; ``sort_order`` is
    the fixed checklist order; ``owner_role`` is the default-owner hint.
    """

    key: str
    label: str
    sort_order: int
    owner_role: str


# The 11-step local-SEO activation, in order. ``sort_order`` is explicit rather
# than derived from the tuple index so the intent survives a future reorder.
LOCAL_SEO_TEMPLATE: Final[tuple[StepTemplate, ...]] = (
    StepTemplate("kickoff", "Kickoff call & goals", 1, "manager"),
    StepTemplate("collect_gbp", "Collect GBP access", 2, "specialist"),
    StepTemplate("collect_website_cms", "Collect website / CMS access", 3, "specialist"),
    StepTemplate("collect_analytics", "Collect analytics access", 4, "analyst"),
    StepTemplate("collect_search_console", "Collect Search Console access", 5, "analyst"),
    StepTemplate("brand_assets", "Collect brand assets", 6, "manager"),
    StepTemplate("competitor_list", "Confirm local competitors", 7, "analyst"),
    StepTemplate("keyword_seeds", "Build keyword seed list", 8, "specialist"),
    StepTemplate("baseline_audit", "Run baseline audit", 9, "specialist"),
    StepTemplate("content_plan", "Agree content plan", 10, "manager"),
    StepTemplate("reporting_setup", "Set up reporting", 11, "manager"),
)

# Every template this module can seed, by key. One entry today; the dict is the
# seam a second vertical (e-commerce, national SEO) plugs into without touching
# the seeding logic.
TEMPLATES: Final[dict[str, tuple[StepTemplate, ...]]] = {
    DEFAULT_TEMPLATE_KEY: LOCAL_SEO_TEMPLATE,
}

# The credential-bearing steps: advancing one of these with a credential seals it
# into the vault. Derived from the key prefix so a new collect_* step is covered
# automatically - and asserted against the template by a unit test, so the
# convention can never quietly stop matching reality.
COLLECT_PREFIX: Final = "collect_"


def is_collect_step(step_key: str) -> bool:
    """Whether ``step_key`` is a credential-collecting step (``collect_*``).

    Only these may carry a credential to seal; a credential offered for any other
    step is a caller error (the router rejects it) rather than something to
    quietly seal under a misleading label.
    """
    return step_key.startswith(COLLECT_PREFIX)


def template_for(template_key: str) -> tuple[StepTemplate, ...]:
    """The step template for ``template_key``, falling back to the local-SEO default.

    An unknown key degrades to the default rather than seeding an EMPTY checklist:
    a run with no steps would look 100% complete and silently skip the entire
    activation, which is the worst possible failure mode here.
    """
    return TEMPLATES.get(template_key, LOCAL_SEO_TEMPLATE)
