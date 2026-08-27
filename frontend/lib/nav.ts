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
    title: "Work",
    items: [
      { icon: "space_dashboard", label: "Dashboard", href: "/admin", keywords: "home overview command center" },
      { icon: "fact_check", label: "Audits", href: "/admin/audits", keywords: "seo scan report audit" },
      { icon: "article", label: "Content", href: "/admin/content", keywords: "articles writing draft publish wizard" },
      { icon: "hub", label: "Off-Page", href: "/admin/off-page", keywords: "backlinks links citations nap directories web 2.0 properties placements" },
      { icon: "auto_fix_high", label: "Site Builder", href: "/admin/site-builder", keywords: "wordpress publish connections replicate replica design elementor sites cms plugin" },
      { icon: "radar", label: "Policy Radar", href: "/admin/policy-radar", keywords: "google updates algorithm" },
    ],
  },
  {
    title: "Clients",
    items: [
      { icon: "diversity_3", label: "Clients", href: "/admin/clients", keywords: "accounts customers directory" },
      { icon: "contact_mail", label: "Pipeline", href: "/admin/pipeline", keywords: "leads free audits public prospects" },
      { icon: "flag", label: "Milestones", href: "/admin/milestones", keywords: "projects delivery timeline stages roadmap" },
      { icon: "summarize", label: "Reports", href: "/admin/reports", keywords: "workbooks sheets pdf downloads" },
    ],
  },
  {
    title: "Team",
    items: [
      { icon: "groups", label: "Team", href: "/admin/team", keywords: "members assignees staff management" },
      { icon: "task_alt", label: "Tasks", href: "/admin/tasks", keywords: "tasks progress proof assignee queue board manager" },
    ],
  },
  {
    title: "Platform",
    items: [
      // First in the group: Operations is the health surface. Every other item
      // here configures the platform; this one says whether it is working.
      { icon: "monitor_heart", label: "Operations", href: "/admin/operations", keywords: "jobs runs health failures dead letters queue logs retry cancel replay" },
      { icon: "savings", label: "Cost", href: "/admin/cost", keywords: "spend budget dials pricing controls" },
      { icon: "cable", label: "Integrations", href: "/admin/integrations", keywords: "api keys credentials secrets vault backups analytics gsc ga4" },
      { icon: "settings", label: "Settings", href: "/admin/settings", keywords: "config preferences workspace security" },
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
