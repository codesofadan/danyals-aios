// ============================================================
// AIOS · mock data layer
// Swap these arrays for FastAPI / Postgres queries when the
// backend is wired. Shapes mirror the data model in
// aios/context-docs/ARCHITECTURE-AND-PLAN.md §8.
// ============================================================

export type AuditPoint = { w: string; v: number };
export type TrafficPoint = { m: string; v: number };
export type TeamMember = { nm: string; init: string; c: string; jobs: number };
export type Client = { cn: string; cd: string; p: number };

// Categorical palette — mirrors the Avant-Garde theme tokens (--c1…--c5)
// so JS-drawn charts match the CSS-driven surfaces.
export const SERIES = {
  c1: "#C6FF3C", // acid-lime (accent)
  c2: "#22E0C0", // teal
  c3: "#FF9F1C", // amber
  c4: "#4CC9F0", // cyan
  c5: "#FF4D9D", // magenta
} as const;

export const audits: AuditPoint[] = [
  { w: "W1", v: 64 }, { w: "W2", v: 78 }, { w: "W3", v: 71 }, { w: "W4", v: 92 },
  { w: "W5", v: 85 }, { w: "W6", v: 104 }, { w: "W7", v: 97 }, { w: "W8", v: 126 },
  { w: "W9", v: 118 }, { w: "W10", v: 141 }, { w: "W11", v: 133 }, { w: "W12", v: 158 },
];

export const traffic: TrafficPoint[] = [
  { m: "Aug", v: 214 }, { m: "Sep", v: 229 }, { m: "Oct", v: 238 }, { m: "Nov", v: 256 },
  { m: "Dec", v: 247 }, { m: "Jan", v: 271 }, { m: "Feb", v: 284 }, { m: "Mar", v: 279 },
  { m: "Apr", v: 298 }, { m: "May", v: 307 }, { m: "Jun", v: 312 }, { m: "Jul", v: 318 },
];

export const team: TeamMember[] = [
  { nm: "Ayesha", init: "AY", c: SERIES.c1, jobs: 48 },
  { nm: "Bilal", init: "BI", c: SERIES.c2, jobs: 41 },
  { nm: "Hina", init: "HI", c: SERIES.c4, jobs: 37 },
  { nm: "Usman", init: "US", c: SERIES.c3, jobs: 29 },
  { nm: "Zoya", init: "ZO", c: SERIES.c5, jobs: 22 },
];

export const clients: Client[] = [
  { cn: "NorthPeak Dental", cd: "Actionable audit", p: 92 },
  { cn: "Lumen Realty", cd: "Content sprint", p: 78 },
  { cn: "Verde Cafe", cd: "Technical audit", p: 64 },
  { cn: "Atlas Legal", cd: "Onboarding", p: 45 },
  { cn: "BrightHVAC", cd: "WordPress push", p: 83 },
  { cn: "Coastline Fit", cd: "Local SEO", p: 57 },
];

// ============================================================
// Client Info module — directory, growth, subscriptions,
// contacts and support activity. Shapes mirror §8 data model
// (clients, users, activity_log). Mock values are demo-only.
// ============================================================

export type SubTier = "Starter" | "Growth" | "Scale";
export type SubStatus = "active" | "trial" | "past_due" | "paused";

export type Contact = {
  name: string;
  role: string;
  email: string;
  init: string;
  c: string; // avatar accent (SERIES slot)
};

// Portal access — the agency-provisioned super/client admin login.
export type PortalAccess = {
  admin: string; // admin username / login email
  pass: string; // admin pass (masked in UI; reveal on demand)
  seats: number; // provisioned user logins for the account
  twoFA: boolean;
  lastLogin: string; // relative
};

export type ClientRecord = {
  id: string;
  cn: string; // client name
  industry: string;
  sites: number;
  since: string; // client since (year)
  contact: Contact;
  tier: SubTier;
  status: SubStatus;
  renews: string; // next renewal date
  mrr: number; // monthly recurring revenue (USD)
  portal: PortalAccess;
};

// Total active accounts on the platform, month over month.
export type GrowthPoint = { m: string; v: number };
// No fabricated growth series — a live analytics source is not wired yet.
export const clientGrowth: GrowthPoint[] = [];

// Plan pricing (USD / month) — drives MRR + subscription mix.
export const TIER_PRICE: Record<SubTier, number> = { Starter: 290, Growth: 690, Scale: 1490 };
export const TIER_COLOR: Record<SubTier, string> = { Starter: SERIES.c4, Growth: SERIES.c1, Scale: SERIES.c3 };

// Aggregate subscription mix across the full 42-account base
// (the directory below lists a featured/recent subset).
// No fabricated subscription mix — billing data is not wired yet.
export const subStatusMix: { status: SubStatus; label: string; count: number; c: string }[] = [];
export const subTierMix: { tier: SubTier; count: number }[] = [];

export const clientDirectory: ClientRecord[] = [
  {
    id: "cl-northpeak", cn: "NorthPeak Dental", industry: "Healthcare", sites: 2, since: "2023",
    contact: { name: "Dr. Sana Malik", role: "Practice Owner", email: "sana@northpeakdental.com", init: "SM", c: SERIES.c1 },
    tier: "Scale", status: "active", renews: "Aug 14, 2026", mrr: 1490,
    portal: { admin: "admin@northpeakdental.com", pass: "Np!Dental#2026", seats: 6, twoFA: true, lastLogin: "2h ago" },
  },
  {
    id: "cl-lumen", cn: "Lumen Realty", industry: "Real Estate", sites: 3, since: "2024",
    contact: { name: "Hamza Iqbal", role: "Marketing Lead", email: "hamza@lumenrealty.co", init: "HI", c: SERIES.c2 },
    tier: "Growth", status: "active", renews: "Sep 02, 2026", mrr: 690,
    portal: { admin: "hamza@lumenrealty.co", pass: "Lumen$Realty7", seats: 4, twoFA: true, lastLogin: "1d ago" },
  },
  {
    id: "cl-verde", cn: "Verde Cafe", industry: "Hospitality", sites: 1, since: "2025",
    contact: { name: "Nadia Rehman", role: "Founder", email: "nadia@verdecafe.pk", init: "NR", c: SERIES.c5 },
    tier: "Starter", status: "trial", renews: "Jul 21, 2026", mrr: 290,
    portal: { admin: "nadia@verdecafe.pk", pass: "Verde@Cafe1", seats: 2, twoFA: false, lastLogin: "5h ago" },
  },
  {
    id: "cl-atlas", cn: "Atlas Legal", industry: "Legal Services", sites: 1, since: "2025",
    contact: { name: "Omar Sheikh", role: "Managing Partner", email: "omar@atlaslegal.com", init: "OS", c: SERIES.c4 },
    tier: "Growth", status: "past_due", renews: "Jul 05, 2026", mrr: 690,
    portal: { admin: "omar@atlaslegal.com", pass: "Atlas!Legal9", seats: 3, twoFA: true, lastLogin: "3d ago" },
  },
  {
    id: "cl-brighthvac", cn: "BrightHVAC", industry: "Home Services", sites: 2, since: "2024",
    contact: { name: "Farah Yousaf", role: "Operations Manager", email: "farah@brighthvac.com", init: "FY", c: SERIES.c3 },
    tier: "Growth", status: "active", renews: "Oct 18, 2026", mrr: 690,
    portal: { admin: "farah@brighthvac.com", pass: "Bright#HVAC22", seats: 5, twoFA: true, lastLogin: "6h ago" },
  },
  {
    id: "cl-coastline", cn: "Coastline Fit", industry: "Fitness", sites: 1, since: "2025",
    contact: { name: "Bilal Anwar", role: "Owner", email: "bilal@coastlinefit.com", init: "BA", c: SERIES.c2 },
    tier: "Starter", status: "active", renews: "Nov 30, 2026", mrr: 290,
    portal: { admin: "bilal@coastlinefit.com", pass: "Coast$Fit44", seats: 2, twoFA: false, lastLogin: "12h ago" },
  },
  {
    id: "cl-meridian", cn: "Meridian Wealth", industry: "Finance", sites: 2, since: "2023",
    contact: { name: "Zara Khan", role: "CMO", email: "zara@meridianwealth.com", init: "ZK", c: SERIES.c1 },
    tier: "Scale", status: "active", renews: "Aug 27, 2026", mrr: 1490,
    portal: { admin: "zara@meridianwealth.com", pass: "Merid!an88", seats: 8, twoFA: true, lastLogin: "40m ago" },
  },
  {
    id: "cl-orchard", cn: "Orchard Pediatrics", industry: "Healthcare", sites: 1, since: "2026",
    contact: { name: "Dr. Imran Ali", role: "Clinic Director", email: "imran@orchardpeds.com", init: "IA", c: SERIES.c5 },
    tier: "Starter", status: "paused", renews: "—", mrr: 0,
    portal: { admin: "imran@orchardpeds.com", pass: "Orchard@Peds3", seats: 2, twoFA: false, lastLogin: "18d ago" },
  },
];

export type Ticket = {
  id: string;
  client: string;
  subject: string;
  channel: "Email" | "Portal" | "Call" | "Chat";
  priority: "urgent" | "high" | "med" | "low";
  status: "open" | "pending" | "resolved";
  ago: string;
};

// No fabricated tickets — the support feed is not wired into this view yet.
export const tickets: Ticket[] = [];

// ============================================================
// Client report access — what each client is allowed to SEE.
// Unlike team members (who get feature/role grants), a client
// is granted visibility into specific charts, graphs & reports.
// The client portal renders ONLY the reports whose key is in
// clientReportGrants[clientId]; everything else is hidden and
// its data is never sent. The admin can revise these grants at
// any time from the Client Directory → Report Access view.
// Mock values are demo-only — swap for the FastAPI/Postgres
// row-level-security policy when the backend is wired.
// ============================================================

// Reports are grouped for the grant grid, colour-coded by area.
export type ReportGroup = "Performance" | "Off-Page" | "Content" | "Delivery";

export const REPORT_GROUP_COLOR: Record<ReportGroup, string> = {
  Performance: SERIES.c4, // blue
  "Off-Page": SERIES.c5, // magenta
  Content: SERIES.c3, // amber
  Delivery: SERIES.c1, // lime
};

// A single grantable chart / graph / report surface.
export type ClientReport = {
  key: string;
  label: string; // full name
  short: string; // bubble / chip label
  icon: string; // Material Symbols
  group: ReportGroup;
  desc: string; // what the client sees when it's granted
};

// The reports & graphs an admin can expose to a client. Each maps
// to a dashboard surface the client portal would render.
export const clientReports: ClientReport[] = [
  { key: "audit_scores", label: "Audit Scores", short: "Audit Scores", icon: "fact_check", group: "Performance", desc: "Site-health scores per category, trended over time" },
  { key: "rank_tracker", label: "Keyword Rankings", short: "Rankings", icon: "trending_up", group: "Performance", desc: "Tracked keyword positions & ranking history" },
  { key: "traffic", label: "Organic Traffic", short: "Traffic", icon: "show_chart", group: "Performance", desc: "Organic sessions & clicks month over month" },
  { key: "core_web_vitals", label: "Core Web Vitals", short: "Web Vitals", icon: "speed", group: "Performance", desc: "LCP / INP / CLS field data per page" },
  { key: "backlinks", label: "Backlink Profile", short: "Backlinks", icon: "hub", group: "Off-Page", desc: "Referring domains, new & lost links, toxicity" },
  { key: "competitor", label: "Competitor Benchmark", short: "Competitors", icon: "insights", group: "Off-Page", desc: "Share-of-voice & gap analysis vs rivals" },
  { key: "local_seo", label: "Local & Map Pack", short: "Local SEO", icon: "storefront", group: "Off-Page", desc: "Local grid rankings & map-pack visibility" },
  { key: "content_status", label: "Content Status", short: "Content", icon: "article", group: "Content", desc: "Content pipeline — drafts, review & published" },
  { key: "keyword_map", label: "Keyword Coverage", short: "Keywords", icon: "search", group: "Content", desc: "Target keywords mapped to pages & intent" },
  { key: "milestones", label: "Milestones & Delivery", short: "Milestones", icon: "flag", group: "Delivery", desc: "Onboarding & delivery milestone timeline" },
  { key: "progress_dashboard", label: "Progress Dashboard", short: "Progress", icon: "donut_large", group: "Delivery", desc: "At-a-glance engagement progress rings" },
  { key: "monthly_report", label: "Monthly SEO Report", short: "Monthly Report", icon: "summarize", group: "Delivery", desc: "The branded monthly performance report" },
  { key: "roi_summary", label: "ROI & Growth Summary", short: "ROI Summary", icon: "payments", group: "Delivery", desc: "Revenue-attributed growth & ROI headline" },
];

const ALL_REPORT_KEYS = clientReports.map((r) => r.key);

// Ready-made access bundles — a starting point the admin can then
// customise per client (mirrors the team role templates).
export type ReportBundle = {
  key: string;
  label: string; // dropdown label
  tagline: string;
  icon: string;
  color: string;
  grants: string[]; // clientReports.key[] switched on
};

export const reportBundles: ReportBundle[] = [
  {
    key: "full", label: "Full Dashboard", tagline: "Every chart & report", icon: "dashboard",
    color: SERIES.c1, grants: ALL_REPORT_KEYS,
  },
  {
    key: "performance", label: "Performance Only", tagline: "Rankings, traffic & audits", icon: "monitoring",
    color: SERIES.c4, grants: ["audit_scores", "rank_tracker", "traffic", "core_web_vitals", "local_seo"],
  },
  {
    key: "exec", label: "Executive Summary", tagline: "Headline progress & ROI", icon: "summarize",
    color: SERIES.c1, grants: ["progress_dashboard", "monthly_report", "roi_summary", "milestones"],
  },
  {
    key: "content", label: "Content Client", tagline: "Content pipeline & keywords", icon: "edit_note",
    color: SERIES.c3, grants: ["content_status", "keyword_map", "rank_tracker", "monthly_report"],
  },
];

// Per-client report visibility, keyed by clientDirectory.id. This is
// the map the client portal reads to decide what to render — a report
// NOT in this list is hidden and its data is never returned.
export const clientReportGrants: Record<string, string[]> = {
  "cl-northpeak": ["audit_scores", "rank_tracker", "traffic", "core_web_vitals", "content_status", "milestones", "progress_dashboard", "monthly_report", "roi_summary"],
  "cl-lumen": ["audit_scores", "rank_tracker", "traffic", "content_status", "keyword_map", "milestones", "monthly_report"],
  "cl-verde": ["audit_scores", "rank_tracker", "local_seo", "monthly_report"],
  "cl-atlas": ["progress_dashboard", "monthly_report", "milestones"],
  "cl-brighthvac": ["audit_scores", "rank_tracker", "traffic", "content_status", "milestones", "progress_dashboard", "monthly_report"],
  "cl-coastline": ["audit_scores", "rank_tracker", "local_seo", "monthly_report"],
  "cl-meridian": ALL_REPORT_KEYS,
  "cl-orchard": ["milestones", "monthly_report"],
};

// The payload the Add-Client wizard emits back to the directory.
export type NewClient = {
  cn: string; // client name
  industry: string;
  tier: SubTier;
  contactName: string;
  contactEmail: string;
  adminLogin: string;
  adminPass: string;
  bundle: string; // bundle label, or "Custom"
  reports: string[]; // clientReports.key[] granted
};

// ============================================================
// Team Management module — roster, task assignment, activity
// log, per-member performance and role-based access control.
// Shapes mirror the §8 data model (users, roles, jobs,
// activity_log). Mock values are demo-only; swap for the
// FastAPI/Postgres queries when the backend is wired.
// ============================================================

// --- Roles & access control -------------------------------------------------
// Ordered most-privileged → least. Owner is the agency super-admin.
export type TeamRole = "Owner" | "Admin" | "Manager" | "Specialist" | "Analyst" | "Viewer";

export const ROLE_ORDER: TeamRole[] = ["Owner", "Admin", "Manager", "Specialist", "Analyst", "Viewer"];

export const ROLE_META: Record<TeamRole, { desc: string; c: string }> = {
  Owner: { desc: "Full control across the platform — billing, access & data.", c: SERIES.c1 },
  Admin: { desc: "Manage team, clients & delivery. No access-control changes.", c: SERIES.c4 },
  Manager: { desc: "Assign work, run audits & publish across a client book.", c: SERIES.c2 },
  Specialist: { desc: "Deliver audits & content on assigned jobs.", c: SERIES.c3 },
  Analyst: { desc: "Run audits and read reports — no publishing.", c: SERIES.c5 },
  Viewer: { desc: "Read-only access to reports and dashboards.", c: "var(--muted)" },
};

// Granular capabilities the RBAC matrix toggles per role.
export type PermKey =
  | "run_audits" | "publish_content" | "manage_clients" | "assign_tasks"
  | "manage_team" | "access_control" | "manage_vault" | "view_reports";

export const permissions: { key: PermKey; label: string; desc: string; icon: string }[] = [
  { key: "run_audits", label: "Run audits", desc: "Trigger free & paid audits", icon: "fact_check" },
  { key: "publish_content", label: "Publish content", desc: "Push content live past the review gate", icon: "rocket_launch" },
  { key: "manage_clients", label: "Manage clients", desc: "Edit accounts, contacts & subscriptions", icon: "diversity_3" },
  { key: "assign_tasks", label: "Assign tasks", desc: "Create & route jobs to the team", icon: "assignment_ind" },
  { key: "manage_team", label: "Manage team", desc: "Add, edit & deactivate members", icon: "group_add" },
  { key: "access_control", label: "Access control", desc: "Edit roles & permissions", icon: "admin_panel_settings" },
  { key: "manage_vault", label: "Key vault", desc: "View & rotate API keys and creds", icon: "key" },
  { key: "view_reports", label: "View reports", desc: "Open audits, dashboards & metrics", icon: "summarize" },
];

// Default capability grants per role. Owner is implicitly all-on and locked.
export const defaultRolePerms: Record<TeamRole, PermKey[]> = {
  Owner: permissions.map((p) => p.key),
  Admin: ["run_audits", "publish_content", "manage_clients", "assign_tasks", "manage_team", "manage_vault", "view_reports"],
  Manager: ["run_audits", "publish_content", "manage_clients", "assign_tasks", "view_reports"],
  Specialist: ["run_audits", "publish_content", "view_reports"],
  Analyst: ["run_audits", "view_reports"],
  Viewer: ["view_reports"],
};

// --- Members ----------------------------------------------------------------
export type MemberStatus = "active" | "away" | "invited" | "offline";

export const STATUS_META: Record<MemberStatus, { label: string; c: string }> = {
  active: { label: "Active", c: "var(--ok)" },
  away: { label: "Away", c: "var(--warn)" },
  invited: { label: "Invited", c: SERIES.c4 },
  offline: { label: "Offline", c: "var(--muted)" },
};

export type TeamMemberRecord = {
  id: string;
  name: string;
  init: string;
  c: string; // avatar accent (SERIES slot)
  title: string; // job title
  email: string;
  role: TeamRole;
  status: MemberStatus;
  activeTasks: number;
  completed: number; // jobs delivered this cycle
  onTime: number; // on-time delivery %
  utilization: number; // capacity used %
  quality: number; // QA pass rate %
  joined: string; // month + year
};

export const teamMembers: TeamMemberRecord[] = [
  { id: "u-danyal", name: "Danyal Ahmed", init: "DA", c: SERIES.c1, title: "Founder / Super Admin", email: "danyal@xegents.ai", role: "Owner", status: "active", activeTasks: 3, completed: 61, onTime: 98, utilization: 72, quality: 99, joined: "Jan 2023" },
  { id: "u-ayesha", name: "Ayesha Raza", init: "AY", c: SERIES.c1, title: "Content Lead", email: "ayesha@xegents.ai", role: "Manager", status: "active", activeTasks: 6, completed: 48, onTime: 94, utilization: 88, quality: 96, joined: "Mar 2023" },
  { id: "u-bilal", name: "Bilal Anwar", init: "BI", c: SERIES.c2, title: "Technical SEO Specialist", email: "bilal@xegents.ai", role: "Specialist", status: "active", activeTasks: 5, completed: 41, onTime: 91, utilization: 84, quality: 93, joined: "May 2023" },
  { id: "u-hina", name: "Hina Shah", init: "HI", c: SERIES.c4, title: "Content Writer", email: "hina@xegents.ai", role: "Specialist", status: "away", activeTasks: 4, completed: 37, onTime: 89, utilization: 76, quality: 95, joined: "Aug 2023" },
  { id: "u-usman", name: "Usman Tariq", init: "US", c: SERIES.c3, title: "Backlink Analyst", email: "usman@xegents.ai", role: "Analyst", status: "active", activeTasks: 3, completed: 29, onTime: 92, utilization: 68, quality: 90, joined: "Nov 2023" },
  { id: "u-zoya", name: "Zoya Kamal", init: "ZO", c: SERIES.c5, title: "Local SEO Specialist", email: "zoya@xegents.ai", role: "Specialist", status: "active", activeTasks: 4, completed: 22, onTime: 88, utilization: 71, quality: 92, joined: "Feb 2024" },
  { id: "u-sara", name: "Sara Naveed", init: "SN", c: SERIES.c2, title: "Operations Admin", email: "sara@xegents.ai", role: "Admin", status: "active", activeTasks: 2, completed: 34, onTime: 96, utilization: 63, quality: 97, joined: "Jun 2024" },
  { id: "u-imran", name: "Imran Qureshi", init: "IQ", c: SERIES.c4, title: "Client Success", email: "imran@xegents.ai", role: "Viewer", status: "invited", activeTasks: 0, completed: 0, onTime: 0, utilization: 0, quality: 0, joined: "Jul 2026" },
];

// --- Tasks ------------------------------------------------------------------
export type TaskType = "Technical Audit" | "Actionable Audit" | "Content Sprint" | "Backlink Audit" | "Local SEO" | "Publishing";
export type TaskPriority = "urgent" | "high" | "med" | "low";
export type TaskStatus = "todo" | "in_progress" | "review" | "done";

export const TASK_STATUS_META: Record<TaskStatus, { label: string; cls: string }> = {
  todo: { label: "To do", cls: "mut" },
  in_progress: { label: "In progress", cls: "info" },
  review: { label: "In review", cls: "warn" },
  done: { label: "Done", cls: "ok" },
};

export const TASK_TYPES: TaskType[] = ["Technical Audit", "Actionable Audit", "Content Sprint", "Backlink Audit", "Local SEO", "Publishing"];

export type Task = {
  id: string;
  title: string;
  client: string;
  type: TaskType;
  assignee: string; // teamMembers.id
  priority: TaskPriority;
  status: TaskStatus;
  due: string;
};

export const tasks_seed: Task[] = [
  { id: "J-2041", title: "Full technical crawl + CWV pass", client: "NorthPeak Dental", type: "Technical Audit", assignee: "u-bilal", priority: "high", status: "in_progress", due: "Jul 12" },
  { id: "J-2039", title: "Service-page content sprint (6 pages)", client: "Lumen Realty", type: "Content Sprint", assignee: "u-hina", priority: "high", status: "in_progress", due: "Jul 14" },
  { id: "J-2037", title: "Map-pack + NAP consistency fixes", client: "Verde Cafe", type: "Local SEO", assignee: "u-zoya", priority: "med", status: "todo", due: "Jul 15" },
  { id: "J-2035", title: "Backlink profile + toxic-link sweep", client: "Meridian Wealth", type: "Backlink Audit", assignee: "u-usman", priority: "med", status: "review", due: "Jul 11" },
  { id: "J-2032", title: "Actionable audit — per-page fixes", client: "Atlas Legal", type: "Actionable Audit", assignee: "u-bilal", priority: "urgent", status: "todo", due: "Jul 10" },
  { id: "J-2030", title: "WordPress publish — 4 blog posts", client: "BrightHVAC", type: "Publishing", assignee: "u-ayesha", priority: "low", status: "review", due: "Jul 13" },
  { id: "J-2028", title: "Local SEO audit + GBP categories", client: "Coastline Fit", type: "Local SEO", assignee: "u-zoya", priority: "low", status: "done", due: "Jul 08" },
  { id: "J-2025", title: "Technical audit — second site", client: "NorthPeak Dental", type: "Technical Audit", assignee: "u-bilal", priority: "med", status: "done", due: "Jul 07" },
];

// --- Activity log -----------------------------------------------------------
export type ActivityKind = "task" | "member" | "audit" | "content" | "access" | "login" | "client";

export const ACTIVITY_META: Record<ActivityKind, { icon: string; c: string }> = {
  task: { icon: "assignment_turned_in", c: SERIES.c1 },
  member: { icon: "group_add", c: SERIES.c2 },
  audit: { icon: "fact_check", c: SERIES.c4 },
  content: { icon: "article", c: SERIES.c3 },
  access: { icon: "admin_panel_settings", c: SERIES.c5 },
  login: { icon: "login", c: "var(--muted)" },
  client: { icon: "diversity_3", c: SERIES.c2 },
};

export type Activity = {
  id: string;
  kind: ActivityKind;
  actorInit: string;
  actorName: string;
  actorColor: string;
  action: string; // verb phrase, e.g. "assigned"
  target: string; // object of the action
  meta?: string; // client / context
  ago: string;
};

export const activity_seed: Activity[] = [
  { id: "a-01", kind: "audit", actorInit: "BI", actorName: "Bilal Anwar", actorColor: SERIES.c2, action: "started a technical audit", target: "J-2041", meta: "NorthPeak Dental", ago: "8m ago" },
  { id: "a-02", kind: "content", actorInit: "HI", actorName: "Hina Shah", actorColor: SERIES.c4, action: "submitted for review", target: "Service-page sprint", meta: "Lumen Realty", ago: "26m ago" },
  { id: "a-03", kind: "access", actorInit: "DA", actorName: "Danyal Ahmed", actorColor: SERIES.c1, action: "granted publish access to", target: "Manager role", meta: "Access control", ago: "1h ago" },
  { id: "a-04", kind: "task", actorInit: "AY", actorName: "Ayesha Raza", actorColor: SERIES.c1, action: "assigned", target: "J-2030 · Publishing", meta: "BrightHVAC", ago: "2h ago" },
  { id: "a-05", kind: "member", actorInit: "DA", actorName: "Danyal Ahmed", actorColor: SERIES.c1, action: "invited", target: "Imran Qureshi", meta: "Viewer", ago: "3h ago" },
  { id: "a-06", kind: "audit", actorInit: "US", actorName: "Usman Tariq", actorColor: SERIES.c3, action: "flagged 3 toxic links on", target: "J-2035", meta: "Meridian Wealth", ago: "4h ago" },
  { id: "a-07", kind: "task", actorInit: "ZO", actorName: "Zoya Kamal", actorColor: SERIES.c5, action: "completed", target: "J-2028 · Local SEO", meta: "Coastline Fit", ago: "6h ago" },
  { id: "a-08", kind: "login", actorInit: "SN", actorName: "Sara Naveed", actorColor: SERIES.c2, action: "signed in from", target: "Karachi, PK", ago: "7h ago" },
  { id: "a-09", kind: "content", actorInit: "AY", actorName: "Ayesha Raza", actorColor: SERIES.c1, action: "approved 4 posts at the review gate for", target: "J-2030", meta: "BrightHVAC", ago: "9h ago" },
  { id: "a-10", kind: "access", actorInit: "DA", actorName: "Danyal Ahmed", actorColor: SERIES.c1, action: "enabled 2FA requirement for", target: "all Admin logins", meta: "Security", ago: "1d ago" },
];

// ============================================================
// Add Team Member — access model
// Grounded in danyal-AIOS-Roles-and-Access-Control.pdf:
// 17 switchable features + 3 ready-made role templates
// (SEO Specialist, Content Creator, Virtual Assistant) plus
// the all-access Super Admin. Grants below mirror the doc's
// "Full Access Matrix" (§07) — a feature is granted when the
// role has any access (Full or View); Off features are ungranted.
// ============================================================

export type FeatureGroup = "Analytics" | "Content" | "Delivery" | "Admin";

export const GROUP_COLOR: Record<FeatureGroup, string> = {
  Analytics: SERIES.c4, // blue
  Content: SERIES.c3, // amber
  Delivery: SERIES.c1, // lime
  Admin: SERIES.c5, // magenta — the sensitive, Super-Admin-only tools
};

export type AccessFeature = {
  key: string;
  label: string; // full name
  short: string; // bubble label
  icon: string; // Material Symbols
  group: FeatureGroup;
  desc: string; // what it unlocks
};

// The 17 features you switch on or off (doc §01 / §07).
export const accessFeatures: AccessFeature[] = [
  { key: "rank_tracker", label: "Rank Tracker", short: "Rank Tracker", icon: "trending_up", group: "Analytics", desc: "Track keyword positions & ranking history" },
  { key: "technical_audit", label: "Technical Audit", short: "Tech Audit", icon: "troubleshoot", group: "Analytics", desc: "Run site audits, review & mark issues fixed" },
  { key: "on_page", label: "On-Page Optimizer", short: "On-Page", icon: "tune", group: "Analytics", desc: "Review & apply on-page recommendations" },
  { key: "keyword_research", label: "Keyword Research", short: "Keywords", icon: "search", group: "Analytics", desc: "Find, group & assign keywords" },
  { key: "backlink_manager", label: "Backlink Manager", short: "Backlinks", icon: "hub", group: "Analytics", desc: "Monitor profile, flag lost or toxic links" },
  { key: "competitor_intel", label: "Competitor Intel", short: "Competitors", icon: "insights", group: "Analytics", desc: "Compare clients & read gap analysis" },
  { key: "local_seo", label: "Local SEO", short: "Local SEO", icon: "storefront", group: "Analytics", desc: "Track local & map-pack rankings" },
  { key: "content_pipeline", label: "Content Pipeline", short: "Content", icon: "article", group: "Content", desc: "Briefs, AI drafting, edit & review" },
  { key: "publishing", label: "Publishing", short: "Publishing", icon: "rocket_launch", group: "Content", desc: "Send approved content live to the CMS" },
  { key: "reporting", label: "Reporting", short: "Reporting", icon: "summarize", group: "Delivery", desc: "Build, schedule & send client reports" },
  { key: "task_board", label: "Task / Workflow Board", short: "Task Board", icon: "checklist", group: "Delivery", desc: "Create, assign & track team tasks" },
  { key: "client_onboarding", label: "Client Onboarding", short: "Onboarding", icon: "person_add", group: "Delivery", desc: "Run the onboarding wizard & collect access" },
  { key: "client_setup", label: "Client & Website Setup", short: "Client Setup", icon: "add_business", group: "Delivery", desc: "Add & edit clients and their websites" },
  { key: "data_import", label: "Data Import", short: "Imports", icon: "upload_file", group: "Delivery", desc: "Upload & map CSV/Excel exports" },
  { key: "key_vault", label: "Integrations & Key Vault", short: "Key Vault", icon: "key", group: "Admin", desc: "API keys & integrations — Super Admin only" },
  { key: "billing", label: "Billing", short: "Billing", icon: "payments", group: "Admin", desc: "Plans, invoices & payment settings" },
  { key: "team_access", label: "Team & Access", short: "Team & Access", icon: "admin_panel_settings", group: "Admin", desc: "Manage members, roles & permissions" },
];

export type RoleTemplate = {
  key: string;
  label: string; // dropdown label
  tagline: string;
  icon: string;
  role: TeamRole; // governance role stamped on the roster record
  color: string; // avatar accent for the new member
  grants: string[]; // accessFeatures.key[] switched on by this template
};

const ALL_KEYS = accessFeatures.map((f) => f.key);

// Grants transcribed from the Full Access Matrix (§07). "Off" cells are omitted.
export const roleTemplates: RoleTemplate[] = [
  {
    key: "seo", label: "SEO Specialist", tagline: "Analytics & optimization", icon: "query_stats",
    role: "Specialist", color: SERIES.c4,
    grants: ["rank_tracker", "technical_audit", "on_page", "keyword_research", "backlink_manager", "competitor_intel", "local_seo", "content_pipeline", "reporting", "task_board", "client_onboarding", "client_setup", "data_import"],
  },
  {
    key: "content", label: "Content Creator", tagline: "Copywriting & publishing", icon: "edit_note",
    role: "Specialist", color: SERIES.c3,
    grants: ["rank_tracker", "on_page", "keyword_research", "competitor_intel", "content_pipeline", "publishing", "reporting", "task_board", "client_setup"],
  },
  {
    key: "va", label: "Virtual Assistant", tagline: "Coordination & admin", icon: "support_agent",
    role: "Manager", color: SERIES.c1,
    grants: ["rank_tracker", "content_pipeline", "local_seo", "reporting", "task_board", "client_onboarding", "client_setup", "data_import"],
  },
  {
    key: "super", label: "Super Admin", tagline: "Full access — everything on", icon: "shield_person",
    role: "Owner", color: SERIES.c1,
    grants: ALL_KEYS,
  },
];

// ============================================================
// Settings module — the admin control panel. Credentials,
// role/access management and platform-wide policy. Password
// values are demo-only; in production these live behind the
// FastAPI auth service + encrypted vault, never in the client
// bundle. Reuses the RBAC matrix (rolePerms) and members above.
// ============================================================

// The signed-in operator (agency super-admin). Own-profile tab edits this.
export type OperatorProfile = {
  id: string;
  name: string;
  init: string;
  c: string;
  title: string;
  email: string;
  role: TeamRole;
  twoFA: boolean;
  phone: string;
};

export const operatorProfile: OperatorProfile = {
  id: "u-danyal", name: "Danyal Ahmed", init: "DA", c: SERIES.c1,
  title: "Founder / Super Admin", email: "danyal@xegents.ai", role: "Owner",
  twoFA: true, phone: "+92 300 1234567",
};

// Login credentials, keyed by teamMembers.id. The Team Access tab
// resets these; passwords are shown masked and revealed on demand.
export type Credential = { pass: string; twoFA: boolean; mustReset: boolean; lastChanged: string };
export const teamCredentials: Record<string, Credential> = {
  "u-danyal": { pass: "Xg!Danyal#2026", twoFA: true, mustReset: false, lastChanged: "Jun 2026" },
  "u-ayesha": { pass: "Ayesha@Content4", twoFA: true, mustReset: false, lastChanged: "May 2026" },
  "u-bilal": { pass: "Bilal$Tech88", twoFA: false, mustReset: false, lastChanged: "Apr 2026" },
  "u-hina": { pass: "Hina!Write21", twoFA: false, mustReset: true, lastChanged: "Feb 2026" },
  "u-usman": { pass: "Usman#Links7", twoFA: true, mustReset: false, lastChanged: "Jun 2026" },
  "u-zoya": { pass: "Zoya@Local55", twoFA: false, mustReset: false, lastChanged: "Mar 2026" },
  "u-sara": { pass: "Sara!Ops2026", twoFA: true, mustReset: false, lastChanged: "Jul 2026" },
  "u-imran": { pass: "Imran@Temp01", twoFA: false, mustReset: true, lastChanged: "—" },
};

// Platform-wide security policy (Security tab).
export type SecurityPolicy = {
  enforce2FA: boolean;
  strongPasswords: boolean;
  minPassLength: number;
  rotationDays: number; // 0 = never
  sessionTimeout: number; // minutes
  singleSession: boolean;
  ipAllowlist: boolean;
  auditLogging: boolean;
};

export const securityDefaults: SecurityPolicy = {
  enforce2FA: true, strongPasswords: true, minPassLength: 12, rotationDays: 90,
  sessionTimeout: 30, singleSession: false, ipAllowlist: false, auditLogging: true,
};

export const PASS_LENGTHS = [8, 10, 12, 16] as const;
export const ROTATION_OPTIONS: { v: number; label: string }[] = [
  { v: 30, label: "Every 30 days" }, { v: 60, label: "Every 60 days" },
  { v: 90, label: "Every 90 days" }, { v: 180, label: "Every 180 days" }, { v: 0, label: "Never" },
];
export const SESSION_OPTIONS = [15, 30, 60, 120, 480];

// Notification preferences (Notifications tab).
export type NotifPref = { key: string; label: string; desc: string; icon: string; email: boolean; inApp: boolean };
export const notificationDefaults: NotifPref[] = [
  { key: "audit_done", label: "Audit completed", desc: "A free or paid audit finishes and the report is ready", icon: "fact_check", email: true, inApp: true },
  { key: "content_review", label: "Content ready for review", desc: "A draft hits the review gate awaiting approval", icon: "rocket_launch", email: true, inApp: true },
  { key: "new_ticket", label: "New support ticket", desc: "A client opens or escalates a support ticket", icon: "confirmation_number", email: true, inApp: true },
  { key: "past_due", label: "Subscription past due", desc: "A client's renewal payment fails or lapses", icon: "payments", email: true, inApp: false },
  { key: "member_login", label: "New sign-in", desc: "A team member signs in from a new device or location", icon: "login", email: false, inApp: true },
  { key: "access_change", label: "Access changed", desc: "Roles or permissions are granted or revoked", icon: "admin_panel_settings", email: true, inApp: true },
  { key: "weekly_digest", label: "Weekly digest", desc: "Monday summary of audits, jobs and client health", icon: "summarize", email: true, inApp: false },
];

// General workspace settings (Workspace tab).
export type WorkspaceSettingsData = {
  agencyName: string;
  supportEmail: string;
  timezone: string;
  language: string;
  weekStart: "Monday" | "Sunday";
  defaultTier: SubTier;
  brandColor: string;
};

export const workspaceDefaults: WorkspaceSettingsData = {
  agencyName: "Xegents AI", supportEmail: "support@xegents.ai",
  timezone: "Asia/Karachi (PKT)", language: "English (US)", weekStart: "Monday",
  defaultTier: "Growth", brandColor: SERIES.c1,
};

export const TIMEZONES = [
  "Asia/Karachi (PKT)", "Asia/Dubai (GST)", "Europe/London (GMT)",
  "America/New_York (EST)", "America/Los_Angeles (PST)", "Asia/Singapore (SGT)",
];
export const LANGUAGES = ["English (US)", "English (UK)", "Urdu", "Arabic", "French", "Spanish"];
export const BRAND_COLORS = [SERIES.c1, SERIES.c2, SERIES.c4, SERIES.c3, SERIES.c5];

// ============================================================
// Team Portal — the member-facing view (Module 3 · §5).
// A signed-in specialist sees ONLY their own queue, deliverables,
// review items, granted features and activity. It reads the same
// roster + task board the admin Team Management module writes to,
// scoped to a single teamMembers.id. Swap for the /me + /tasks?
// assignee=<id> API calls when the backend is wired.
// ============================================================

// The member currently signed in to the portal (demo default —
// Bilal, an active Technical SEO Specialist with a live queue).
// The portal lets you switch this to preview any member's view.
export const PORTAL_MEMBER_ID = "u-bilal";

// Features each member has been granted by the admin
// (accessFeatures.key[]) — mirrors the Add-Member wizard output,
// keyed by teamMembers.id. Drives the "My Access" view honestly.
export const memberGrants: Record<string, string[]> = {
  "u-danyal": ALL_KEYS, // Owner — everything on
  "u-ayesha": ["rank_tracker", "on_page", "keyword_research", "competitor_intel", "content_pipeline", "publishing", "reporting", "task_board", "client_setup", "client_onboarding"], // Content Lead
  "u-bilal": ["rank_tracker", "technical_audit", "on_page", "keyword_research", "backlink_manager", "competitor_intel", "local_seo", "reporting", "task_board", "data_import"], // Technical SEO
  "u-hina": ["rank_tracker", "on_page", "keyword_research", "content_pipeline", "reporting", "task_board"], // Content Writer
  "u-usman": ["rank_tracker", "technical_audit", "backlink_manager", "competitor_intel", "reporting", "task_board"], // Backlink Analyst
  "u-zoya": ["rank_tracker", "on_page", "keyword_research", "local_seo", "content_pipeline", "reporting", "task_board", "client_setup"], // Local SEO
  "u-sara": ["reporting", "task_board", "client_onboarding", "client_setup", "data_import", "billing"], // Operations Admin
  "u-imran": ["reporting"], // Client Success (Viewer, invited)
};

// Roles allowed to sign off the content review checkpoint.
export const CAN_REVIEW: TeamRole[] = ["Owner", "Admin", "Manager"];

// The type-appropriate primary action a member runs to deliver a task.
export const TASK_ACTION: Record<TaskType, { run: string; icon: string; deliver: string }> = {
  "Technical Audit": { run: "Run crawl", icon: "fact_check", deliver: "Deliver audit" },
  "Actionable Audit": { run: "Run audit", icon: "checklist_rtl", deliver: "Deliver report" },
  "Content Sprint": { run: "Open editor", icon: "edit_note", deliver: "Submit for review" },
  "Backlink Audit": { run: "Run link sweep", icon: "hub", deliver: "Deliver findings" },
  "Local SEO": { run: "Run local audit", icon: "storefront", deliver: "Deliver report" },
  "Publishing": { run: "Open publisher", icon: "rocket_launch", deliver: "Publish live" },
};

// Portal's frame of reference for "due" math — matches the demo
// clock (today = Jul 10, 2026). Parses the "Mon DD" due strings
// on tasks_seed into an at-a-glance urgency without a real Date.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const PORTAL_TODAY = { m: 6, d: 10 }; // month index 6 = Jul

export type DueInfo = { label: string; days: number; tone: "overdue" | "today" | "soon" | "ok" };

export function dueInfo(due: string): DueInfo {
  const [mon, dayStr] = due.trim().split(/\s+/);
  const m = MONTHS.indexOf(mon);
  const d = parseInt(dayStr, 10);
  if (m < 0 || Number.isNaN(d)) return { label: due, days: 99, tone: "ok" };
  // crude day-of-year delta — fine within the demo's July window.
  const days = (m - PORTAL_TODAY.m) * 30 + (d - PORTAL_TODAY.d);
  if (days < 0) return { label: `${Math.abs(days)}d overdue`, days, tone: "overdue" };
  if (days === 0) return { label: "Due today", days, tone: "today" };
  if (days <= 2) return { label: `Due in ${days}d`, days, tone: "soon" };
  return { label: `Due ${due}`, days, tone: "ok" };
}
