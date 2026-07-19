// ============================================================
// Team Portal — tool catalog.
// Every access feature the admin can grant maps to a real, usable
// tool workspace here. A member only reaches a tool if their grant
// (memberGrants) includes its key — the portal gates on that. Content
// is demo data; swap for the per-tool API calls when the backend lands.
// ============================================================
import { accessFeatures, type AccessFeature } from "@/lib/data";

export type ToolKpi = { label: string; value: string; delta?: string; dir?: "up" | "down" };
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
      { label: "Tracked keywords", value: "128" },
      { label: "Avg. position", value: "8.4", delta: "1.2", dir: "up" },
      { label: "Top-3 keywords", value: "34", delta: "5", dir: "up" },
    ],
    primary: { label: "Add keywords", icon: "add" },
    bullets: ["Track keyword positions daily", "See ranking history & trends", "Group keywords by client & intent"],
    table: {
      title: "Keyword movements", icon: "trending_up",
      cols: ["Keyword", "Client", "Position", "Change"],
      rows: [
        ["dental implants karachi", "NorthPeak Dental", "3", { v: "▲ 4", tone: "ok" }],
        ["luxury apartments dubai", "Lumen Realty", "7", { v: "▲ 2", tone: "ok" }],
        ["best cafe near me", "Verde Cafe", "12", { v: "▼ 3", tone: "crit" }],
        ["family law firm", "Atlas Legal", "5", { v: "▲ 1", tone: "ok" }],
      ],
    },
  },
  technical_audit: {
    kpis: [
      { label: "Sites monitored", value: "6" },
      { label: "Open issues", value: "23", delta: "8", dir: "down" },
      { label: "Avg. health", value: "82%", delta: "3%", dir: "up" },
    ],
    primary: { label: "Run crawl", icon: "fact_check" },
    bullets: ["Run full technical crawls", "Review & mark issues fixed", "Track Core Web Vitals over time"],
    table: {
      title: "Recent crawls", icon: "troubleshoot",
      cols: ["Site", "Client", "Score", "Issues"],
      rows: [
        ["northpeakdental.com", "NorthPeak Dental", "88", { v: "6 open", tone: "warn" }],
        ["lumenrealty.co", "Lumen Realty", "79", { v: "11 open", tone: "warn" }],
        ["atlaslegal.com", "Atlas Legal", "71", { v: "14 open", tone: "crit" }],
        ["brighthvac.com", "BrightHVAC", "91", { v: "2 open", tone: "ok" }],
      ],
    },
  },
  on_page: {
    kpis: [
      { label: "Pages analyzed", value: "214" },
      { label: "Open suggestions", value: "41" },
      { label: "Applied", value: "178", delta: "12", dir: "up" },
    ],
    primary: { label: "Analyze page", icon: "tune" },
    bullets: ["Review on-page recommendations", "Apply title, meta & heading fixes", "Score content against target keywords"],
    table: {
      title: "Top recommendations", icon: "tune",
      cols: ["Page", "Issue", "Impact", "Status"],
      rows: [
        ["/services/implants", "Missing meta description", { v: "High", tone: "crit" }, { v: "Open", tone: "warn" }],
        ["/about", "Thin content", { v: "Med", tone: "warn" }, { v: "Open", tone: "warn" }],
        ["/blog/whitening", "H1 not keyword-aligned", { v: "Med", tone: "warn" }, { v: "Applied", tone: "ok" }],
        ["/contact", "No schema markup", { v: "Low", tone: "info" }, { v: "Applied", tone: "ok" }],
      ],
    },
  },
  keyword_research: {
    kpis: [
      { label: "Saved keywords", value: "640" },
      { label: "Clusters", value: "28" },
      { label: "Avg. difficulty", value: "34" },
    ],
    primary: { label: "Research keywords", icon: "search" },
    bullets: ["Find & group keyword opportunities", "See volume, difficulty & intent", "Assign keywords to clients"],
    table: {
      title: "Opportunity keywords", icon: "search",
      cols: ["Keyword", "Volume", "Difficulty", "Intent"],
      rows: [
        ["invisalign cost", "8,100", { v: "KD 42", tone: "warn" }, { v: "Commercial", tone: "info" }],
        ["realtor near me", "12,400", { v: "KD 55", tone: "crit" }, { v: "Local", tone: "ok" }],
        ["vegan brunch spots", "3,600", { v: "KD 21", tone: "ok" }, { v: "Local", tone: "ok" }],
        ["divorce lawyer fees", "2,900", { v: "KD 38", tone: "warn" }, { v: "Commercial", tone: "info" }],
      ],
    },
  },
  backlink_manager: {
    kpis: [
      { label: "Referring domains", value: "1,240" },
      { label: "New links (30d)", value: "34", delta: "9", dir: "up" },
      { label: "Toxic flagged", value: "5", delta: "2", dir: "down" },
    ],
    primary: { label: "Run link sweep", icon: "hub" },
    bullets: ["Monitor the backlink profile", "Flag lost or toxic links", "Track referring-domain growth"],
    table: {
      title: "Recent links", icon: "hub",
      cols: ["Domain", "Client", "DR", "Status"],
      rows: [
        ["healthline.com", "NorthPeak Dental", "91", { v: "New", tone: "ok" }],
        ["realtor.com", "Lumen Realty", "88", { v: "New", tone: "ok" }],
        ["spam-links.biz", "Verde Cafe", "6", { v: "Toxic", tone: "crit" }],
        ["localnews.pk", "Atlas Legal", "54", { v: "Lost", tone: "warn" }],
      ],
    },
  },
  competitor_intel: {
    kpis: [
      { label: "Competitors tracked", value: "18" },
      { label: "Keyword gaps", value: "92" },
      { label: "Share of voice", value: "41%", delta: "4%", dir: "up" },
    ],
    primary: { label: "Compare", icon: "insights" },
    bullets: ["Compare clients to competitors", "Read keyword & content gap analysis", "Track share of voice"],
    table: {
      title: "Gap analysis", icon: "insights",
      cols: ["Competitor", "Client", "Keyword gaps", "Overlap"],
      rows: [
        ["brightsmile.com", "NorthPeak Dental", "24", { v: "38%", tone: "info" }],
        ["cityrealty.co", "Lumen Realty", "31", { v: "45%", tone: "info" }],
        ["urbaneats.pk", "Verde Cafe", "12", { v: "22%", tone: "mut" }],
        ["legalpros.com", "Atlas Legal", "25", { v: "40%", tone: "info" }],
      ],
    },
  },
  local_seo: {
    kpis: [
      { label: "GBP profiles", value: "9" },
      { label: "Avg. map rank", value: "3.2", delta: "0.6", dir: "up" },
      { label: "Citations", value: "210" },
    ],
    primary: { label: "Run local audit", icon: "storefront" },
    bullets: ["Track local & map-pack rankings", "Audit GBP categories & NAP", "Monitor citation consistency"],
    table: {
      title: "Map-pack rankings", icon: "storefront",
      cols: ["Location", "Client", "Keyword", "Rank"],
      rows: [
        ["Karachi", "Verde Cafe", "cafe near me", { v: "2", tone: "ok" }],
        ["Lahore", "Coastline Fit", "gym membership", { v: "4", tone: "warn" }],
        ["Islamabad", "NorthPeak Dental", "dentist", { v: "3", tone: "ok" }],
        ["Dubai", "Lumen Realty", "apartments", { v: "6", tone: "warn" }],
      ],
    },
  },
  content_pipeline: {
    kpis: [
      { label: "In pipeline", value: "12" },
      { label: "Drafting", value: "5" },
      { label: "Ready for review", value: "3", delta: "1", dir: "up" },
    ],
    primary: { label: "New content brief", icon: "article" },
    bullets: ["Create briefs & AI drafts", "Edit and refine copy", "Send drafts to the review gate"],
    table: {
      title: "Content jobs", icon: "article",
      cols: ["Topic", "Client", "Stage", "Words"],
      rows: [
        ["Teeth whitening guide", "NorthPeak Dental", { v: "Drafting", tone: "info" }, "1,850"],
        ["Buying your first home", "Lumen Realty", { v: "Review", tone: "warn" }, "2,100"],
        ["Seasonal menu launch", "Verde Cafe", { v: "Editing", tone: "info" }, "1,200"],
        ["What to expect at trial", "Atlas Legal", { v: "Queued", tone: "mut" }, "—"],
      ],
    },
  },
  publishing: {
    kpis: [
      { label: "Published (30d)", value: "24" },
      { label: "Scheduled", value: "6" },
      { label: "Failed", value: "0", delta: "0", dir: "up" },
    ],
    primary: { label: "Publish", icon: "rocket_launch" },
    bullets: ["Push approved content live", "Publish to WordPress or export", "Schedule and track publishes"],
    table: {
      title: "Publish queue", icon: "rocket_launch",
      cols: ["Title", "Client", "Target", "Status"],
      rows: [
        ["Teeth whitening guide", "NorthPeak Dental", "WordPress", { v: "Scheduled", tone: "info" }],
        ["Buying your first home", "Lumen Realty", "WordPress", { v: "Live", tone: "ok" }],
        ["Seasonal menu launch", "Verde Cafe", "PDF/Markdown", { v: "Draft", tone: "mut" }],
        ["Q3 HVAC checklist", "BrightHVAC", "WordPress", { v: "Live", tone: "ok" }],
      ],
    },
  },
  reporting: {
    kpis: [
      { label: "Reports sent (30d)", value: "48" },
      { label: "Scheduled", value: "12" },
      { label: "Sheets synced", value: "6" },
    ],
    primary: { label: "Build report", icon: "summarize" },
    bullets: ["Build & schedule client reports", "Sync scores to Google Sheets", "Send web + PDF reports"],
    table: {
      title: "Recent reports", icon: "summarize",
      cols: ["Report", "Client", "Period", "Status"],
      rows: [
        ["Monthly SEO summary", "NorthPeak Dental", "June", { v: "Sent", tone: "ok" }],
        ["Content performance", "Lumen Realty", "June", { v: "Sent", tone: "ok" }],
        ["Local ranking report", "Verde Cafe", "June", { v: "Scheduled", tone: "info" }],
        ["Backlink health", "Meridian Wealth", "Q2", { v: "Draft", tone: "mut" }],
      ],
    },
  },
  task_board: {
    kpis: [
      { label: "Open tasks", value: "18" },
      { label: "In progress", value: "7" },
      { label: "Done (30d)", value: "42", delta: "6", dir: "up" },
    ],
    primary: { label: "New task", icon: "add_task" },
    bullets: ["Create, assign & track tasks", "Move work across the board", "See team throughput"],
    table: {
      title: "Team tasks", icon: "checklist",
      cols: ["Task", "Client", "Assignee", "Status"],
      rows: [
        ["Technical crawl + CWV", "NorthPeak Dental", "Bilal", { v: "In progress", tone: "info" }],
        ["Service-page sprint", "Lumen Realty", "Hina", { v: "In progress", tone: "info" }],
        ["Map-pack fixes", "Verde Cafe", "Zoya", { v: "To do", tone: "mut" }],
        ["Backlink sweep", "Meridian Wealth", "Usman", { v: "In review", tone: "warn" }],
      ],
    },
  },
  client_onboarding: {
    kpis: [
      { label: "In onboarding", value: "3" },
      { label: "Steps pending", value: "7" },
      { label: "Completed (30d)", value: "12" },
    ],
    primary: { label: "Start onboarding", icon: "person_add" },
    bullets: ["Run the onboarding wizard", "Collect access & assets", "Track onboarding progress"],
    table: {
      title: "Onboarding", icon: "person_add",
      cols: ["Client", "Step", "Owner", "Status"],
      rows: [
        ["Orchard Pediatrics", "Collect GBP access", "Sara", { v: "Pending", tone: "warn" }],
        ["Coastline Fit", "Add website", "Sara", { v: "Done", tone: "ok" }],
        ["Meridian Wealth", "Kickoff call", "Ayesha", { v: "Scheduled", tone: "info" }],
      ],
    },
  },
  client_setup: {
    kpis: [
      { label: "Clients", value: "42" },
      { label: "Websites", value: "61" },
      { label: "Pending setup", value: "2", delta: "1", dir: "down" },
    ],
    primary: { label: "Add website", icon: "add_business" },
    bullets: ["Add & edit clients", "Register websites & CMS", "Set up tracking & integrations"],
    table: {
      title: "Websites", icon: "add_business",
      cols: ["Website", "Client", "CMS", "Status"],
      rows: [
        ["northpeakdental.com", "NorthPeak Dental", "WordPress", { v: "Active", tone: "ok" }],
        ["lumenrealty.co", "Lumen Realty", "Webflow", { v: "Active", tone: "ok" }],
        ["orchardpeds.com", "Orchard Pediatrics", "WordPress", { v: "Setup", tone: "warn" }],
      ],
    },
  },
  data_import: {
    kpis: [
      { label: "Imports (30d)", value: "18" },
      { label: "Rows mapped", value: "42k" },
      { label: "Errors", value: "3", delta: "1", dir: "down" },
    ],
    primary: { label: "Upload file", icon: "upload_file" },
    bullets: ["Upload CSV / Excel exports", "Map columns to fields", "Validate & import in bulk"],
    table: {
      title: "Recent imports", icon: "upload_file",
      cols: ["File", "Type", "Rows", "Status"],
      rows: [
        ["gsc-export-june.csv", "Search Console", "12,400", { v: "Imported", tone: "ok" }],
        ["keywords-batch.xlsx", "Keywords", "3,200", { v: "Imported", tone: "ok" }],
        ["backlinks.csv", "Backlinks", "1,050", { v: "3 errors", tone: "warn" }],
      ],
    },
  },
  key_vault: {
    kpis: [
      { label: "Keys stored", value: "14" },
      { label: "Integrations", value: "8" },
      { label: "Rotating soon", value: "2", delta: "2", dir: "down" },
    ],
    primary: { label: "Add key", icon: "key" },
    bullets: ["Manage API keys & integrations", "Rotate credentials safely", "Super-Admin scoped access"],
    table: {
      title: "Keys & integrations", icon: "key",
      cols: ["Provider", "Scope", "Last rotated", "Status"],
      rows: [
        ["Serper.dev", "Search", "May 2026", { v: "Active", tone: "ok" }],
        ["Google Cloud", "PageSpeed", "Jun 2026", { v: "Active", tone: "ok" }],
        ["Anthropic", "Content AI", "Apr 2026", { v: "Rotate soon", tone: "warn" }],
      ],
    },
  },
  billing: {
    kpis: [
      { label: "MRR", value: "$28.4k", delta: "3.1%", dir: "up" },
      { label: "Open invoices", value: "3" },
      { label: "Past due", value: "1", delta: "1", dir: "down" },
    ],
    primary: { label: "New invoice", icon: "payments" },
    bullets: ["View plans & invoices", "Track payments & renewals", "Manage payment settings"],
    table: {
      title: "Invoices", icon: "payments",
      cols: ["Client", "Amount", "Due", "Status"],
      rows: [
        ["Meridian Wealth", "$1,490", "Aug 27", { v: "Paid", tone: "ok" }],
        ["NorthPeak Dental", "$1,490", "Aug 14", { v: "Open", tone: "info" }],
        ["Atlas Legal", "$690", "Jul 05", { v: "Past due", tone: "crit" }],
      ],
    },
  },
  team_access: {
    kpis: [
      { label: "Members", value: "8" },
      { label: "Roles", value: "6" },
      { label: "Pending invites", value: "1" },
    ],
    primary: { label: "Invite member", icon: "group_add" },
    bullets: ["Manage members & roles", "Grant or revoke permissions", "Review the access audit trail"],
    table: {
      title: "Members", icon: "admin_panel_settings",
      cols: ["Member", "Role", "Status", "Tasks"],
      rows: [
        ["Ayesha Raza", "Manager", { v: "Active", tone: "ok" }, "6"],
        ["Bilal Anwar", "Specialist", { v: "Active", tone: "ok" }, "5"],
        ["Hina Shah", "Specialist", { v: "Away", tone: "warn" }, "4"],
        ["Imran Qureshi", "Viewer", { v: "Invited", tone: "info" }, "0"],
      ],
    },
  },
};

// All tools, in the same order as the feature list.
// The per-tool KPI numbers and table rows in EXTRAS were sample/demo data; they
// are STRIPPED here so each tool page shows an honest "no current data" state
// until it is wired to its live /workspace/{slug} endpoint. We keep the table
// headers and the capability bullets — those are product copy, not fabricated
// business data.
export const tools: Tool[] = accessFeatures.map((f) => {
  const extra: ToolExtra = EXTRAS[f.key] ?? { kpis: [], bullets: [] };
  return {
    ...f,
    ...extra,
    kpis: [],
    table: extra.table ? { ...extra.table, rows: [] } : undefined,
    slug: toolSlug(f.key),
  };
});

export function getToolBySlug(slug: string): Tool | undefined {
  return tools.find((t) => t.slug === slug);
}

export function toolForKey(key: string): Tool | undefined {
  return tools.find((t) => t.key === key);
}
