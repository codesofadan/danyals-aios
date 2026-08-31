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
  // --- The wizard the content flow replaced -----------------------------------
  // SUPERSEDED, not merely unmounted. `components/content/flow/` is the same job
  // done as four screens with the step in the URL; this was five steps mounted
  // INLINE on the board, so one scrolling page carried making, watching and
  // approving at once. The owner's verdict on that shape was explicit.
  //
  // Kept rather than deleted for one reason: it is the only remaining record of
  // two behaviours the flow has not re-implemented - the queued-jobs preview
  // strip on its final step, and its "start another" reset. If neither is
  // missed, delete it; nothing imports it.
  {
    path: "content/ContentWizard.tsx",
    status: "operator-removed",
    unmountedBy: "the 2026-08-29 content flow (components/content/flow/)",
    reason:
      "Replaced by a four-screen flow at /admin/content/new. The inline five-step " +
      "wizard is the shape the owner rejected: creating, watching and approving " +
      "stacked on one scrolling page.",
    reEnableWhen:
      "Never as-is. Salvage its queued-jobs preview strip into StepLaunch if that " +
      "turns out to be missed, then delete the file.",
  },

  // --- Phase-1 screen grammar: built ahead of the screens that mount them ----
  // The approved Screen & Hierarchy Specification (plan of 2026-08-27) builds the
  // shared vocabulary FIRST, then migrates screens onto it phase by phase. These
  // are that vocabulary: finished, tested (components/ui/primitives.test.tsx),
  // and waiting for Phases 2-5 to give them callers. Staged work, not options
  // preserved from a removal - nothing unmounted them; their mounts are next.
  ...(
    [
      // ui/Modal.tsx graduated: ContentJobDetail's "request edits" dialog mounts it,
      // which is exactly the migration this entry was waiting for. The reachability
      // guard fails on a registry that still calls a mounted component parked.
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

  // --- Citations: UNPARKED 2026-08-29 -----------------------------------------
  // CitationsTab / CitationCampaignModal / AuditPlanPanel were parked here with the
  // reason: "Directory auto-submission is blocked by captcha/dead forms and does not
  // produce dependable live listings; the module is locked rather than shipping
  // misleading data." That was the right call, and it is worth recording WHY it no
  // longer applies rather than deleting the entry silently:
  //
  //   * The specific misleading data was one mis-wired field. `CitationGap.live_urls`
  //     was populated from `proof_url` - a screenshot key, and for a while the absolute
  //     server path the Playwright bot returned - and rendered under a KPI tile reading
  //     "Live listing URLs". Migration 0106 gave a listing a real `live_url`, and
  //     `service.py` now reads that and only for `submit_status = 'live'`.
  //   * "Does not produce dependable live listings" is still TRUE of the automated
  //     route, and the module no longer claims otherwise: `submitted` is labelled
  //     "Sent - unconfirmed", only a fetched-and-matched listing reaches `live`, and
  //     every directory we do not build is listed with the reason.
  //   * The 16 directories whose terms forbid automated submission are route F and
  //     cannot be queued at all (0106), so the captcha/dead-form problem is now data
  //     the module reports rather than a trap it walks into.
  //
  // The page is `app/admin/citations/page.tsx` (created 2026-08-29 - the earlier
  // "lock card" this comment used to describe had itself been deleted, so the note was
  // pointing at a file that did not exist). Route B - real automated submission at
  // volume - is still gated on a verified aggregator; that is Phase 4, not this page.

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

  // --- The 2026-08-30 QA pass: surfaces removed, components kept --------------
  // A QA session over the portal produced 26 findings. Several were "this card /
  // tab / module is not required" - a decision about what the portal SURFACES, not
  // a judgement that the code is wrong. Every component below is working and was
  // deliberately unmounted; the endpoints behind them are untouched.
  ...(
    [
      ["charts/AuditVolumeChart.tsx", "Free Audit Volume", "The Free Audit Volume card was removed from the admin dashboard (QA 26). Free Audits themselves were verified working and keep their own module at /admin/leads."],
      ["overview/SpendSnapshot.tsx", "Platform Spend", "The Platform Spend / Cost Controls card was removed from the admin dashboard (QA 26). Spend still has its own module at /admin/cost, and the halt control there was verified working."],
      ["cost/CostLog.tsx", "Cost Log", "QA 11: the log showed $0.00 for work that did cost money, so it was removed rather than shown wrong. NOTE: the display was never the defect - the per-job cost attribution behind it is. Re-mount once a job's spend is recorded against it."],
      ["clients/MrrTreemap.tsx", "Revenue Treemap", "QA 16: not required on Client Info."],
      ["settings/SecurityTab.tsx", "Security", "QA 9: the Security section is not required in the admin portal. The agency-global /settings/security endpoints are untouched."],
      ["settings/DangerTab.tsx", "Danger zone", "QA 9: the Danger Zone is not required in the admin portal."],
      ["team/AccessControl.tsx", "Roles & Access", "QA 14: the Roles & Access tab is not required. RBAC itself is unchanged and still enforced server-side."],
      ["team/TeamPerformance.tsx", "Performance", "QA 14: the Performance tab's graphs are out of sync with the ledgers they summarise, so it was removed rather than left showing numbers an operator cannot trust."],
      ["team/TeamMetricBox.tsx", "Performance", "Only ever rendered by TeamPerformance; orphaned with it."],
      ["portal/ReviewCheckpoint.tsx", "Review", "QA 7: the Review tab was removed from the team member portal. POST /tasks/{code}/review is untouched and leads still review from the admin task surfaces."],
    ] as const
  ).map(([path, surface, reason]): ParkedEntry => ({
    path,
    status: "operator-removed",
    unmountedBy: "the 2026-08-30 QA remediation (wave 1)",
    reason,
    reEnableWhen: `An owner asks for the ${surface} surface back, or the reason above stops being true.`,
  })),

  // --- Milestones: the whole admin module (QA 15) -----------------------------
  // "Milestones module is not required. Remove the Milestones option/module from
  // the admin portal." Removed from ADMIN only: `/client/milestones` is a separate
  // surface built on components/client/ClientMilestones.tsx and still shipping, and
  // the /milestones endpoints still feed it. The module was read-only by design
  // (only the onboarding stage auto-advances), so nothing that wrote is lost.
  ...(
    [
      "milestones/MilestonesWorkspace.tsx",
      "milestones/MilestoneStats.tsx",
      "milestones/MilestoneDetail.tsx",
      "milestones/ProjectGantt.tsx",
      "milestones/ClientTimeline.tsx",
      "milestones/StagePipeline.tsx",
      "milestones/AutoAdvanceFeed.tsx",
    ] as const
  ).map((path): ParkedEntry => ({
    path,
    status: "operator-removed",
    unmountedBy: "the 2026-08-30 QA remediation (wave 1)",
    reason: "QA 15: the Milestones module is not required in the admin portal.",
    reEnableWhen:
      "An owner wants admin-side delivery timelines again. The client-facing /client/milestones is unaffected and still live.",
  })),
];

export const PARKED_PATHS: ReadonlySet<string> = new Set(PARKED.map((e) => e.path));
