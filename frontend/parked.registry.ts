// ============================================================
// AIOS · the parked-component registry
//
// Lives at the package root, NOT under lib/: this is build metadata read by
// `parked.registry.test.ts`, not application code, and nothing in the app imports it.
// `test_frontend_truth_guard.py` correctly flags an unreferenced exported array inside
// lib/ - anything there is app code that ships to a browser, and this is neither.
//
// A component under `components/` that no route can reach is one of two completely
// different things, and NOTHING in the tree used to say which:
//
//   • PARKED — finished work, deliberately unmounted, waiting on a decision or a
//     dependency. Deleting it destroys the option it was preserved for.
//   • DEAD   — genuinely abandoned.
//
// Reachability alone cannot tell them apart, and guessing has already gone wrong:
// `CitationsTab` is unreachable AND was edited days before this file was written, and
// the audit report viewer is unreachable because an operator deliberately removed its
// entry point. Both read as "dead code" to any mechanical sweep.
//
// So every unreachable component is recorded here with its provenance: what unmounted
// it, why, and what would bring it back. `parked.test.ts` asserts this list and the
// real reachability set agree EXACTLY - so a newly-orphaned component fails CI, and a
// component that was quietly re-mounted stops being listed as parked.
//
// Adding an entry is a decision, not a formality. If you cannot state the re-enable
// condition, the honest status is `unknown` and it needs an owner's answer.
// ============================================================

/** Why a component is not reachable from any route. */
export type ParkedStatus =
  /** Active work, deliberately locked behind a gate. NEVER delete or "repair". */
  | "active-parked"
  /** An operator removed the surface; the component was kept on purpose. */
  | "operator-removed"
  /** Belongs to the audit/content modules; their owner decides, not the portal work. */
  | "module-owned"
  /** No recorded rationale. Needs a decision before anything is done with it. */
  | "unknown";

export type ParkedEntry = {
  /** Path relative to `components/`. */
  path: string;
  status: ParkedStatus;
  /** The commit (or stated source) that unmounted it. */
  unmountedBy: string;
  /** Why, in the words of whoever decided it. */
  reason: string;
  /** What would put it back on a route. */
  reEnableWhen: string;
};

export const PARKED: ParkedEntry[] = [
  // --- Phase-1 screen grammar: built ahead of the screens that mount them ----
  // The approved Screen & Hierarchy Specification (plan of 2026-08-27) builds the
  // shared vocabulary FIRST, then migrates screens onto it phase by phase. These
  // are that vocabulary: finished, tested (components/ui/primitives.test.tsx),
  // and waiting for Phases 2-5 to give them callers. Staged work, not options
  // preserved from a removal - nothing unmounted them; their mounts are next.
  ...(
    [
      ["ui/Modal.tsx", "any screen migrating off a hand-rolled modal (11 exist)"],
      ["ui/PageHeader.tsx", "the first LIST-archetype screen migration"],
      ["ui/useCountUp.ts", "the first KPI strip migrated off its local copy (11 exist)"],
    ] as const
  ).map(([path, when]): ParkedEntry => ({
    path,
    status: "active-parked",
    unmountedBy: "never mounted - Phase 1 of the Screen & Hierarchy Specification (2026-08-27)",
    reason:
      "The screen grammar is built and tested before the screens that use it, so " +
      "each later phase is a migration onto a proven primitive rather than an " +
      "invention inside a feature branch.",
    reEnableWhen: when,
  })),

  // --- The 2026-08-28 revert: Backlinks loses its surface again ---------------
  // The one-day "Off-Page" screen (backlinks | citations | web 2.0 tabs) was the
  // only route BacklinksTab ever had. The owner rejected that consolidation and
  // restored Web 2.0 as its own execution module, so this returns to the state it
  // sat in for the months before: built, hook-wired, and unmounted. It is NOT
  // dead code - `useBacklinks` and the toxic-link flow work - it simply has no
  // screen the owner wants it on.
  {
    path: "offpage/BacklinksTab.tsx",
    status: "active-parked",
    unmountedBy: "the 2026-08-28 nav revert (app/admin/off-page removed)",
    reason:
      "Backlinks was never one of the owner's execution modules; it only became " +
      "reachable as a tab on the consolidated Off-Page screen, which was reverted.",
    reEnableWhen:
      "The owner asks for a backlink surface - then it mounts on its own route, " +
      "not as a tab, and needs server pagination first (the hook fetches unbounded).",
  },

  // --- Citations: ACTIVE work, locked pending a data source -------------------
  // `app/admin/citations/page.tsx` renders a lock card that says so in plain words:
  // "Re-enable by restoring the CitationsTab render below (see git history) once the
  // engine is ready." Edited 2026-08-20. Do not touch these while the lock stands.
  ...(
    ["offpage/CitationsTab.tsx", "offpage/CitationCampaignModal.tsx", "offpage/AuditPlanPanel.tsx"] as const
  ).map((path): ParkedEntry => ({
    path,
    status: "active-parked",
    unmountedBy: "fd1bf2a -> 5ba93b7 -> the lock card in app/admin/citations/page.tsx",
    reason:
      "Directory auto-submission is blocked by captcha/dead forms and does not produce " +
      "dependable live listings; the module is locked rather than shipping misleading data.",
    reEnableWhen: "A verified citation data aggregator is wired in.",
  })),

  // --- The 158c204 batch: six admin tabs removed, components kept -------------
  // "fix(admin): remove Milestones/Upsells/Backups/Service Tiers/Off-page/GMB tabs"
  // (2026-07-25). It deleted the routes and their CSS but left every component in
  // place - a preserved option, not abandoned code.
  ...(
    [
      ["offpage/OffpageWorkspace.tsx", "Off-page hub"],
      ["charts/BacklinkScatter.tsx", "Off-page hub"],
      ["upsells/UpsellsWorkspace.tsx", "Upsells"],
      ["upsells/UpsellManager.tsx", "Upsells"],
      ["upsells/UpsellStats.tsx", "Upsells"],
      ["upsells/AddUpsellModal.tsx", "Upsells"],
      ["upsells/ClientPreview.tsx", "Upsells"],
      ["tiers/TiersWorkspace.tsx", "Service Tiers"],
      ["tiers/TierCards.tsx", "Service Tiers"],
      ["tiers/FeatureMatrix.tsx", "Service Tiers"],
      ["tiers/ClientAssignment.tsx", "Service Tiers"],
      ["gmb/GmbWorkspace.tsx", "GMB"],
      ["gmb/GmbComposer.tsx", "GMB"],
      ["gmb/GmbReview.tsx", "GMB"],
    ] as const
  ).map(([path, tab]): ParkedEntry => ({
    path,
    status: "operator-removed",
    unmountedBy: "158c204",
    reason: `The ${tab} tab was removed from the admin dashboard; the components were kept deliberately.`,
    reEnableWhen:
      tab === "GMB"
        ? "GMB post generation is scheduled - it is backlog item J, wanted but not yet built."
        : tab === "Upsells"
          ? "The operator asks for it back; backlog item N says 'remove the Upsells section (for now)'."
          : `The operator restores the ${tab} tab.`,
  })),

  // --- Audit-module residue: the audit module's owner decides -----------------
  {
    path: "audit/AuditCoverage.tsx",
    status: "module-owned",
    unmountedBy: "backlog item H ('remove the Audit Coverage section at the bottom')",
    reason: "The operator asked for the Audit Coverage section to go; it renders 'Coming soon'.",
    reEnableWhen: "Never, unless the audit module's owner reverses item H. Portal work does not touch components/audit/.",
  },

  // --- No recorded rationale: these need a decision ---------------------------
  ...(
    [
      ["settings/TeamCredentials.tsx", "Roster-shaped; the capability now lives per-member on /admin/team/[memberId] (Sign-in access tab)."],
      ["settings/ClientCredentials.tsx", "Settings was trimmed to My Account only."],
      ["overview/SiteAnalyticsCard.tsx", "The whole GSC/GA4 connect flow; it links to /admin/settings, which no longer contains it."],
      ["policy/KnowledgeBase.tsx", "Policy Radar renders only AskBox, Recommendations and ChangeFeed."],
    ] as const
  ).map(([path, reason]): ParkedEntry => ({
    path,
    status: "unknown",
    unmountedBy: "no recorded commit or rationale",
    reason,
    reEnableWhen: "Needs an owner decision - do not delete on inference alone.",
  })),
];

export const PARKED_PATHS: ReadonlySet<string> = new Set(PARKED.map((e) => e.path));
