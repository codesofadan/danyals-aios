// ============================================================
// AIOS · shared client-side CATALOGUE + display metadata.
//
// This module holds ONLY static product catalogue data (role
// templates, feature lists, report definitions) and presentational
// metadata (palette, status labels, icons). It holds NO business
// data: every client, member, task, activity row and metric is
// fetched from the API through `lib/hooks/*`.
//
// Do not reintroduce seed arrays here. A number rendered to an
// operator must come from the API, never from this file.
// ============================================================

// Categorical palette — mirrors the Avant-Garde theme tokens (--c1…--c5)
// so JS-drawn charts match the CSS-driven surfaces.
export const SERIES = {
  c1: "#C6FF3C", // acid-lime (accent)
  c2: "#22E0C0", // teal
  c3: "#FF9F1C", // amber
  c4: "#4CC9F0", // cyan
  c5: "#FF4D9D", // magenta
} as const;

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
// Subscription-tier accent colours (presentation only). The tier itself and a
// client's MRR are real per-client columns served by GET /clients — there is no
// hardcoded price table here, because a plan price is not a platform constant.
export const TIER_COLOR: Record<SubTier, string> = { Starter: SERIES.c4, Growth: SERIES.c1, Scale: SERIES.c3 };

export type Ticket = {
  id: string;
  client: string;
  subject: string;
  channel: "Email" | "Portal" | "Call" | "Chat";
  priority: "urgent" | "high" | "med" | "low";
  status: "open" | "pending" | "resolved";
  ago: string;
};

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
  proofUrl: string; // proof-of-completion link (published URL / delivered report); "" when unset
  startedAt?: string | null; // ISO instant the assignee moved todo -> in_progress (real timer, set once)
  completedAt?: string | null; // ISO instant the task reached its terminal state (done)
};

// A team member's request to move a task's due date (public.task_deadline_requests).
// The assignee may file one within 12h of startedAt (fallback: the task's creation);
// only a lead's approve/reject decision ever moves the real due date.
export type DeadlineRequestStatus = "pending" | "approved" | "rejected";

export type DeadlineRequest = {
  id: string;
  taskCode: string;
  requestedBy: string;
  requestedDueDate: string; // ISO date (YYYY-MM-DD)
  reason: string;
  status: DeadlineRequestStatus;
  decidedBy: string;
  decidedAt: string;
  createdAt: string;
};

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

// ============================================================
// Add Team Member — access model
// Grounded in danyal-AIOS-Roles-and-Access-Control.pdf:
// 11 switchable features + 3 ready-made role templates
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

// The 11 features you switch on or off (doc §01 / §07).
export const accessFeatures: AccessFeature[] = [
  { key: "technical_audit", label: "Technical Audit", short: "Tech Audit", icon: "troubleshoot", group: "Analytics", desc: "Run site audits, review & mark issues fixed" },
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

// The avatar accent each role template stamps on a newly provisioned member.
//
// KEYED BY TEMPLATE KEY, and deliberately NOT carried on the template itself. The
// template catalogue (keys, labels, grants) is moving to the backend as the single
// source of truth — `GET /rbac/templates` — and that response has no `color`, because
// colour is a THEME token with no server-side reader.
//
// Without this map the swap is a silent data defect rather than a crash:
// `AddMemberWizard` sends `avatar_color` on to provisioning, which defaults it to
// `#7B69EE` — the pre-Avant-Garde violet — and writes it to `public.users`. Every new
// member would be stamped legacy violet, discovered months later as "why is everyone
// purple". Values below are exactly what the dashboard renders today.
export const TEMPLATE_COLOR: Record<string, string> = {
  seo: SERIES.c4,
  content: SERIES.c3,
  va: SERIES.c1,
  super: SERIES.c1,
};

// Grants transcribed from the Full Access Matrix (§07). "Off" cells are omitted.
export const roleTemplates: RoleTemplate[] = [
  {
    key: "seo", label: "SEO Specialist", tagline: "Analytics & optimization", icon: "query_stats",
    role: "Specialist", color: SERIES.c4,
    grants: ["technical_audit", "content_pipeline", "reporting", "task_board", "client_onboarding", "client_setup", "data_import"],
  },
  {
    key: "content", label: "Content Creator", tagline: "Copywriting & publishing", icon: "edit_note",
    role: "Specialist", color: SERIES.c3,
    grants: ["content_pipeline", "publishing", "reporting", "task_board", "client_setup"],
  },
  {
    key: "va", label: "Virtual Assistant", tagline: "Coordination & admin", icon: "support_agent",
    role: "Manager", color: SERIES.c1,
    grants: ["content_pipeline", "reporting", "task_board", "client_onboarding", "client_setup", "data_import"],
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

// --- Settings wire contracts ------------------------------------------------
// These types are the FRONTEND HALF OF A LOCKED API CONTRACT: backend
// `SecurityPolicyResponse` and `WorkspaceSettingsResponse` are pinned to them
// field-for-field by backend/tests/test_contract_lock.py. Change a field here
// only together with its backend model. They carry NO default values on
// purpose — every setting shown to an operator is the one the API returned.

// Platform-wide security policy (GET/PUT /settings/security).
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

// General workspace settings (GET/PUT /settings/workspace).
export type WorkspaceSettingsData = {
  agencyName: string;
  supportEmail: string;
  timezone: string;
  language: string;
  weekStart: "Monday" | "Sunday";
  defaultTier: SubTier;
  brandColor: string;
};

// Notification preferences (Notifications tab).
export type NotifPref = { key: string; label: string; desc: string; icon: string; email: boolean; inApp: boolean };
// ============================================================
// Team Portal — the member-facing view (Module 3 · §5).
// A signed-in specialist sees ONLY their own queue, deliverables,
// review items, granted features and activity. It reads the same
// roster + task board the admin Team Management module writes to,
// scoped to a single teamMembers.id. Swap for the /me + /tasks?
// assignee=<id> API calls when the backend is wired.
// ============================================================

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

// --- Due-date urgency -------------------------------------------------------
// Computed against the REAL clock. It previously compared every due date to a
// hardcoded demo "today" (Jul 10, 2026), so every "due today / Nd overdue" label
// in the portal was fabricated. Accepts either an ISO date (`YYYY-MM-DD`,
// authoritative) or the legacy year-less display string (`"Jul 12"`), for which
// the year is inferred as the nearest one — so a December task read in January
// is 3 weeks late, not 11 months early.
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MS_PER_DAY = 86_400_000;

/** Local midnight for `d` — so day deltas are whole days, not partial ones. */
function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

/** Parse a due string to a local-midnight Date, or null when unparseable. */
export function parseDue(due: string, now: Date = new Date()): Date | null {
  const raw = (due || "").trim();
  if (!raw) return null;

  const iso = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw);
  if (iso) {
    const dt = new Date(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3]));
    return Number.isNaN(dt.getTime()) ? null : dt;
  }

  const short = /^([A-Za-z]{3})\s+(\d{1,2})$/.exec(raw);
  if (!short) return null;
  const m = MONTHS.indexOf(short[1][0].toUpperCase() + short[1].slice(1, 3).toLowerCase());
  const d = parseInt(short[2], 10);
  if (m < 0 || Number.isNaN(d) || d < 1 || d > 31) return null;

  // Year-less input: pick whichever of {last, this, next} year lands closest to
  // today, so the label never silently jumps ~12 months across a year boundary.
  const today = startOfDay(now);
  let best: Date | null = null;
  for (const y of [today.getFullYear() - 1, today.getFullYear(), today.getFullYear() + 1]) {
    const cand = new Date(y, m, d);
    if (cand.getMonth() !== m) continue; // e.g. "Feb 30" in a non-leap year
    if (best === null || Math.abs(+cand - +today) < Math.abs(+best - +today)) best = cand;
  }
  return best;
}

export type DueInfo = { label: string; days: number; tone: "overdue" | "today" | "soon" | "ok" };

/** Whole-day urgency for a due date, measured from the real current date. */
export function dueInfo(due: string, now: Date = new Date()): DueInfo {
  const target = parseDue(due, now);
  // Unparseable / unset: show it verbatim and sort it last. Never guess.
  if (target === null) return { label: (due || "").trim() || "No due date", days: 99, tone: "ok" };

  const days = Math.round((+target - +startOfDay(now)) / MS_PER_DAY);
  const label = `${MONTHS[target.getMonth()]} ${String(target.getDate()).padStart(2, "0")}`;
  if (days < 0) return { label: `${Math.abs(days)}d overdue`, days, tone: "overdue" };
  if (days === 0) return { label: "Due today", days, tone: "today" };
  if (days <= 2) return { label: `Due in ${days}d`, days, tone: "soon" };
  return { label: `Due ${label}`, days, tone: "ok" };
}
