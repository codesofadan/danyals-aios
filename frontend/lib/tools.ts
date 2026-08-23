// ============================================================
// Team Portal — tool catalog.
// Every access feature the admin can grant maps to a real, usable
// tool workspace here. A member only reaches a tool if their grant
// (memberGrants) includes its key — the portal gates on that.
//
// This file carries ONLY static product copy: labels, icons, table headers,
// group, the primary-action label and the capability bullets. It carries NO
// numbers and NO rows. Every live KPI value and table row comes from
// GET /<slug>/workspace (see lib/hooks/tools.ts · useToolWorkspace), and the 8
// Part-8 modules additionally render an interactive action panel wired to their
// real endpoints (see components/portal/tools/*).
//
// The KPI values and table rows that used to sit in EXTRAS ("MRR $28.4k", named
// clients with invoice amounts, named staff with utilisation figures) were
// already zeroed at render time, so they never reached a screen — but they still
// shipped inside the client bundle. They are now deleted at the source. The KPI
// LABELS stay: backend workspace adapters are pinned to them by
// backend/tests/test_tool_workspace_contract.py, so a label is contract.
// ============================================================
import { accessFeatures, type AccessFeature } from "@/lib/data";

// A KPI tile. `label` is static product copy and is CONTRACT — backend
// `GET /<slug>/workspace` adapters are pinned to these labels by
// backend/tests/test_tool_workspace_contract.py. `value`/`delta`/`dir` are
// OPTIONAL and arrive only from that live response: this file never states a
// number, so a tile with no live data renders blank rather than stale.
export type ToolKpi = { label: string; value?: string; delta?: string; dir?: "up" | "down" };
export type CellTone = "ok" | "info" | "warn" | "mut" | "crit";
export type Cell = string | { v: string; tone: CellTone };
export type ToolTable = { title: string; icon: string; cols: string[]; rows: Cell[][] };
export type ToolExtra = {
  kpis: ToolKpi[];
  table?: ToolTable;
  primary?: { label: string; icon: string };
  bullets: string[];
};
export type Tool = AccessFeature & ToolExtra & { slug: string };

export const toolSlug = (key: string): string => key.replace(/_/g, "-");

// Per-feature workspace content, keyed by accessFeatures.key.
const EXTRAS: Record<string, ToolExtra> = {
  rank_tracker: {
    kpis: [
      { label: "Tracked keywords" },
      { label: "Avg. position" },
      { label: "Top-3 keywords" },
    ],
    primary: { label: "Add keywords", icon: "add" },
    bullets: ["Track keyword positions daily", "See ranking history & trends", "Group keywords by client & intent"],
    table: {
      title: "Keyword movements", icon: "trending_up",
      cols: ["Keyword", "Client", "Position", "Change"],
      rows: [],
    },
  },
  technical_audit: {
    kpis: [
      { label: "Sites monitored" },
      { label: "Open issues" },
      { label: "Avg. health" },
    ],
    primary: { label: "Run crawl", icon: "fact_check" },
    bullets: ["Run full technical crawls", "Review & mark issues fixed", "Track Core Web Vitals over time"],
    table: {
      title: "Recent crawls", icon: "troubleshoot",
      cols: ["Site", "Client", "Score", "Issues"],
      rows: [],
    },
  },
  on_page: {
    kpis: [
      { label: "Pages analyzed" },
      { label: "Open suggestions" },
      { label: "Applied" },
    ],
    primary: { label: "Analyze page", icon: "tune" },
    bullets: ["Review on-page recommendations", "Apply title, meta & heading fixes", "Score content against target keywords"],
    table: {
      title: "Top recommendations", icon: "tune",
      cols: ["Page", "Issue", "Impact", "Status"],
      rows: [],
    },
  },
  keyword_research: {
    kpis: [
      { label: "Saved keywords" },
      { label: "Clusters" },
      { label: "Avg. difficulty" },
    ],
    primary: { label: "Research keywords", icon: "search" },
    bullets: ["Find & group keyword opportunities", "See volume, difficulty & intent", "Assign keywords to clients"],
    table: {
      title: "Opportunity keywords", icon: "search",
      cols: ["Keyword", "Volume", "Difficulty", "Intent"],
      rows: [],
    },
  },
  backlink_manager: {
    kpis: [
      { label: "Referring domains" },
      { label: "New links (30d)" },
      { label: "Toxic flagged" },
    ],
    primary: { label: "Run link sweep", icon: "hub" },
    bullets: ["Monitor the backlink profile", "Flag lost or toxic links", "Track referring-domain growth"],
    table: {
      title: "Recent links", icon: "hub",
      cols: ["Domain", "Client", "DR", "Status"],
      rows: [],
    },
  },
  competitor_intel: {
    kpis: [
      { label: "Competitors tracked" },
      { label: "Keyword gaps" },
      { label: "Share of voice" },
    ],
    primary: { label: "Compare", icon: "insights" },
    bullets: ["Compare clients to competitors", "Read keyword & content gap analysis", "Track share of voice"],
    table: {
      title: "Gap analysis", icon: "insights",
      cols: ["Competitor", "Client", "Keyword gaps", "Overlap"],
      rows: [],
    },
  },
  local_seo: {
    kpis: [
      { label: "GBP profiles" },
      { label: "Avg. map rank" },
      { label: "Citations" },
    ],
    primary: { label: "Run local audit", icon: "storefront" },
    bullets: ["Track local & map-pack rankings", "Audit GBP categories & NAP", "Monitor citation consistency"],
    table: {
      title: "Map-pack rankings", icon: "storefront",
      cols: ["Location", "Client", "Keyword", "Rank"],
      rows: [],
    },
  },
  content_pipeline: {
    kpis: [
      { label: "In pipeline" },
      { label: "Drafting" },
      { label: "Ready for review" },
    ],
    primary: { label: "New content brief", icon: "article" },
    bullets: ["Create briefs & AI drafts", "Edit and refine copy", "Send drafts to the review gate"],
    table: {
      title: "Content jobs", icon: "article",
      cols: ["Topic", "Client", "Stage", "Words"],
      rows: [],
    },
  },
  publishing: {
    kpis: [
      { label: "Published (30d)" },
      { label: "Scheduled" },
      { label: "Failed" },
    ],
    primary: { label: "Publish", icon: "rocket_launch" },
    bullets: ["Push approved content live", "Publish to WordPress or export", "Schedule and track publishes"],
    table: {
      title: "Publish queue", icon: "rocket_launch",
      cols: ["Title", "Client", "Target", "Status"],
      rows: [],
    },
  },
  reporting: {
    kpis: [
      { label: "Reports sent (30d)" },
      { label: "Scheduled" },
      { label: "Sheets synced" },
    ],
    primary: { label: "Build report", icon: "summarize" },
    bullets: ["Build & schedule client reports", "Sync scores to Google Sheets", "Send web + PDF reports"],
    table: {
      title: "Recent reports", icon: "summarize",
      cols: ["Report", "Client", "Period", "Status"],
      rows: [],
    },
  },
  task_board: {
    kpis: [
      { label: "Open tasks" },
      { label: "In progress" },
      { label: "Done (30d)" },
    ],
    primary: { label: "New task", icon: "add_task" },
    bullets: ["Create, assign & track tasks", "Move work across the board", "See team throughput"],
    table: {
      title: "Team tasks", icon: "checklist",
      cols: ["Task", "Client", "Assignee", "Status"],
      rows: [],
    },
  },
  client_onboarding: {
    kpis: [
      { label: "In onboarding" },
      { label: "Steps pending" },
      { label: "Completed (30d)" },
    ],
    primary: { label: "Start onboarding", icon: "person_add" },
    bullets: ["Run the onboarding wizard", "Collect access & assets", "Track onboarding progress"],
    table: {
      title: "Onboarding", icon: "person_add",
      cols: ["Client", "Step", "Owner", "Status"],
      rows: [],
    },
  },
  client_setup: {
    kpis: [
      { label: "Clients" },
      { label: "Websites" },
      { label: "Pending setup" },
    ],
    primary: { label: "Add website", icon: "add_business" },
    bullets: ["Add & edit clients", "Register websites & CMS", "Set up tracking & integrations"],
    table: {
      title: "Websites", icon: "add_business",
      cols: ["Website", "Client", "CMS", "Status"],
      rows: [],
    },
  },
  data_import: {
    kpis: [
      { label: "Imports (30d)" },
      { label: "Rows mapped" },
      { label: "Errors" },
    ],
    primary: { label: "Upload file", icon: "upload_file" },
    bullets: ["Upload CSV / Excel exports", "Map columns to fields", "Validate & import in bulk"],
    table: {
      title: "Recent imports", icon: "upload_file",
      cols: ["File", "Type", "Rows", "Status"],
      rows: [],
    },
  },
  key_vault: {
    kpis: [
      { label: "Keys stored" },
      { label: "Integrations" },
      { label: "Rotating soon" },
    ],
    primary: { label: "Add key", icon: "key" },
    bullets: ["Manage API keys & integrations", "Rotate credentials safely", "Super-Admin scoped access"],
    table: {
      title: "Keys & integrations", icon: "key",
      cols: ["Provider", "Scope", "Last rotated", "Status"],
      rows: [],
    },
  },
  billing: {
    kpis: [
      { label: "MRR" },
      { label: "Open invoices" },
      { label: "Past due" },
    ],
    primary: { label: "New invoice", icon: "payments" },
    bullets: ["View plans & invoices", "Track payments & renewals", "Manage payment settings"],
    table: {
      title: "Invoices", icon: "payments",
      cols: ["Client", "Amount", "Due", "Status"],
      rows: [],
    },
  },
  team_access: {
    kpis: [
      { label: "Members" },
      { label: "Roles" },
      { label: "Pending invites" },
    ],
    primary: { label: "Invite member", icon: "group_add" },
    bullets: ["Manage members & roles", "Grant or revoke permissions", "Review the access audit trail"],
    table: {
      title: "Members", icon: "admin_panel_settings",
      cols: ["Member", "Role", "Status", "Tasks"],
      rows: [],
    },
  },
};

// All tools, in the same order as the feature list.
//
// A tool starts with NO data: label-only KPIs and an empty table under its real
// headers, so an unwired or failing workspace endpoint reads as "no current
// data" rather than as a healthy screen. `ToolPage` merges the live
// GET /<slug>/workspace response over this base once it arrives.
//
// `kpis` is emptied here ON PURPOSE, and it is not redundant with EXTRAS now
// carrying label-only tiles. `ToolWorkspace` renders a labelled KPI GRID when
// `kpis` is non-empty and an explicit EmptyState when it is empty. Passing
// label-only tiles through would replace that honest "no current data yet"
// state with a row of labelled tiles holding blank values — which reads as a
// broken screen, not as an absent one.
//
// So the EXTRAS labels exist for one reason: they are the canonical spec the
// backend workspace adapters are pinned to (test_tool_workspace_contract.py).
// The live response supplies both label and value together.
export const tools: Tool[] = accessFeatures.map((f) => {
  const extra: ToolExtra = EXTRAS[f.key] ?? { kpis: [], bullets: [] };
  return { ...f, ...extra, kpis: [], slug: toolSlug(f.key) };
});

export function getToolBySlug(slug: string): Tool | undefined {
  return tools.find((t) => t.slug === slug);
}

export function toolForKey(key: string): Tool | undefined {
  return tools.find((t) => t.key === key);
}
