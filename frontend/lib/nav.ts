// ============================================================
// AIOS · the navigation, once.
//
// Every place that renders or searches a destination reads THIS table. Before
// it existed the truth lived four times over - hardcoded in Sidebar.tsx,
// TeamSidebar.tsx and ClientSidebar.tsx, and duplicated with keywords in
// TopBar.tsx - and the copies had already drifted: /admin/operations, the
// sidebar's own "health surface", was missing from search, so typing "jobs" or
// "failures" returned nothing and nothing failed.
//
// One item, one entry. The sidebar renders it; the search box indexes it via
// `keywords`; lib/nav.test.ts asserts every href resolves to a real page and
// that no nav component declares an href literal of its own.
//
// RUNTIME state does not live here. Badge COUNTS (open queue items, unresolved
// requests) and per-member tool grants are attached by the components that have
// that context; this table is the static identity of the product's map.
// ============================================================

export type NavItem = {
  icon: string;
  label: string;
  href: string;
  /** Search terms beyond the label - what an operator might type. */
  keywords?: string;
  /** Static badge text ("off", "test"). Runtime counts are attached by the shell. */
  badge?: string;
};

export type NavGroup = { title: string; items: NavItem[] };

export const ADMIN_NAV: NavGroup[] = [
  {
    title: "Overview",
    items: [
      { icon: "space_dashboard", label: "Admin Dashboard", href: "/admin", keywords: "home overview command center main" },
    ],
  },
  {
    // THE EXECUTION MODULES - the work the agency actually delivers, in the
    // order it is delivered. This grouping is the owner's, restored 2026-08-28
    // after a four-group restructure ("Work / Clients / Team / Platform") that
    // folded WordPress and Web 2.0 into consolidated tabbed screens and added a
    // Search module. Those consolidations are reverted: each execution module
    // is its own destination again. Do not re-fold them.
    title: "SEO Engine",
    items: [
      { icon: "fact_check", label: "Audit", href: "/admin/audit", keywords: "seo scan report audit paid depth engine findings" },
      { icon: "contact_mail", label: "Free Audits", href: "/admin/leads", keywords: "leads free audits public prospects funnel pipeline" },
      { icon: "article", label: "Content", href: "/admin/content", keywords: "articles writing draft publish wizard" },
      { icon: "language", label: "WordPress", href: "/admin/wordpress", keywords: "wordpress publish connections replicate replica design elementor sites cms plugin" },
      { icon: "rocket_launch", label: "Web 2.0", href: "/admin/web2", keywords: "web2 properties placements platforms articles anchors", badge: "test" },
      { icon: "radar", label: "Google Updates", href: "/admin/policy-radar", keywords: "google updates algorithm policy radar changes core update guidance" },
    ],
  },
  {
    title: "Delivery",
    items: [
      { icon: "diversity_3", label: "Clients", href: "/admin/clients", keywords: "accounts customers directory" },
      { icon: "flag", label: "Milestones", href: "/admin/milestones", keywords: "projects delivery timeline stages roadmap" },
      { icon: "groups", label: "Team Management", href: "/admin/team", keywords: "members assignees staff management" },
      { icon: "task_alt", label: "Task Manager", href: "/admin/tasks", keywords: "tasks progress proof assignee queue board manager" },
      { icon: "summarize", label: "Reports", href: "/admin/reports", keywords: "workbooks sheets pdf downloads" },
    ],
  },
  {
    title: "Platform",
    items: [
      // Operations leads the group: everything else here CONFIGURES the
      // platform; this one says whether it is actually working.
      { icon: "monitor_heart", label: "Operations", href: "/admin/operations", keywords: "jobs runs failures dead letters queue health ledger" },
      { icon: "savings", label: "Cost Controls", href: "/admin/cost", keywords: "spend budget api money dial halt" },
      { icon: "key", label: "Key Vault", href: "/admin/vault", keywords: "keys secrets credentials api integrations backups" },
      { icon: "settings", label: "Settings", href: "/admin/settings", keywords: "account workspace security preferences notifications danger" },
    ],
  },
];

export const TEAM_NAV: NavItem[] = [
  { icon: "space_dashboard", label: "Team Dashboard", href: "/team", keywords: "home overview" },
  { icon: "view_kanban", label: "My Queue", href: "/team/queue", keywords: "tasks work inbox" },
  { icon: "play_circle", label: "Deliver", href: "/team/deliver", keywords: "handoff shipping" },
  { icon: "how_to_reg", label: "Review", href: "/team/review", keywords: "qa approve checkpoint" },
];

export const CLIENT_NAV: NavItem[] = [
  { icon: "insights", label: "Client Dashboard", href: "/client", keywords: "home overview dashboard" },
  { icon: "fact_check", label: "Audits", href: "/client/audits", keywords: "seo scan report pdf findings" },
  { icon: "flag", label: "Milestones", href: "/client/milestones", keywords: "roadmap progress" },
  { icon: "summarize", label: "Reports", href: "/client/reports", keywords: "deliverables pdf downloads" },
  { icon: "forum", label: "Requests", href: "/client/requests", keywords: "tickets edits support" },
];

/** The flat searchable list for a portal - what the top-bar search indexes. */
export function searchDestinations(portal: "admin" | "team" | "client"): NavItem[] {
  if (portal === "team") return TEAM_NAV;
  if (portal === "client") return CLIENT_NAV;
  return ADMIN_NAV.flatMap((g) => g.items);
}
