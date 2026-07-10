// ============================================================
// AIOS · Milestones module — mock data layer.
// Milestones are the client-facing project timeline. They are
// AUTO-ADVANCED from job/audit status (an audit completing or
// content publishing pushes the project to the next stage) —
// never edited by hand. Admin watches & manages them here.
// Shapes mirror the §8 data model (clients, jobs, activity_log)
// and cross-reference the job IDs in lib/data.ts (tasks_seed).
// Swap these arrays for FastAPI / Postgres queries later.
// ============================================================
import { SERIES } from "@/lib/data";

// --- Lifecycle --------------------------------------------------------------
// The fixed SEO-engagement lifecycle every client project moves through.
export type StageKey = "onboarding" | "baseline" | "content" | "authority" | "reporting";

export const LIFECYCLE: { key: StageKey; label: string; short: string; icon: string }[] = [
  { key: "onboarding", label: "Onboarding", short: "Onboarding", icon: "person_add" },
  { key: "baseline", label: "Baseline Audit", short: "Baseline", icon: "fact_check" },
  { key: "content", label: "Content Sprint", short: "Content", icon: "article" },
  { key: "authority", label: "Off-page / Authority", short: "Off-page", icon: "hub" },
  { key: "reporting", label: "Reporting & Review", short: "Reporting", icon: "summarize" },
];

// --- Stage status -----------------------------------------------------------
export type StageStatus = "completed" | "in_progress" | "upcoming" | "blocked";

// cls maps to the shared .status-pill variants; color drives the stepper node.
export const STAGE_STATUS_META: Record<StageStatus, { label: string; cls: string; icon: string; color: string }> = {
  completed: { label: "Completed", cls: "ok", icon: "check", color: "var(--ok)" },
  in_progress: { label: "In progress", cls: "info", icon: "sync", color: SERIES.c4 },
  upcoming: { label: "Upcoming", cls: "mut", icon: "schedule", color: "var(--muted)" },
  blocked: { label: "Blocked", cls: "warn", icon: "block", color: "var(--crit)" },
};

// Weight each stage carries toward the % progress bar.
export const STAGE_WEIGHT: Record<StageStatus, number> = {
  completed: 1, in_progress: 0.5, blocked: 0.25, upcoming: 0,
};

export type Stage = {
  key: StageKey;
  status: StageStatus;
  auto_source: string; // what job/audit advances (or is blocking) this stage
  updated_at: string; // relative timestamp of the last auto-advance
};

// --- Project health ---------------------------------------------------------
export type Health = "on_track" | "at_risk" | "completed";

// Health maps to a shared .status-pill variant + a label.
export const HEALTH_META: Record<Health, { label: string; cls: string; icon: string }> = {
  on_track: { label: "On-track", cls: "ok", icon: "trending_up" },
  at_risk: { label: "At-risk", cls: "warn", icon: "warning" },
  completed: { label: "Completed", cls: "info", icon: "verified" },
};

export type ClientProject = {
  id: string;
  client: string; // reuse existing client names
  site: string; // primary domain
  init: string;
  c: string; // avatar accent (SERIES slot)
  health: Health;
  stages: Stage[]; // always the 5 LIFECYCLE stages, in order
};

// Derived % completion — honest, from the stage weights above.
export function projectProgress(p: ClientProject): number {
  const sum = p.stages.reduce((s, st) => s + STAGE_WEIGHT[st.status], 0);
  return Math.round((sum / p.stages.length) * 100);
}

// The stage a project is currently sitting on (first non-done, else the last).
export function currentStage(p: ClientProject): Stage {
  return p.stages.find((s) => s.status === "in_progress" || s.status === "blocked")
    ?? p.stages.find((s) => s.status === "upcoming")
    ?? p.stages[p.stages.length - 1];
}

// --- Seed: 6 client projects with varied stage progress --------------------
const done = (auto_source: string, updated_at: string): Omit<Stage, "key"> => ({ status: "completed", auto_source, updated_at });

export const projects: ClientProject[] = [
  {
    id: "mp-northpeak", client: "NorthPeak Dental", site: "northpeakdental.com", init: "ND", c: SERIES.c1, health: "on_track",
    stages: [
      { key: "onboarding", ...done("Intake form & CMS access received", "6d ago") },
      { key: "baseline", ...done("J-2025 technical audit completed", "4d ago") },
      { key: "content", status: "in_progress", auto_source: "advances when J-2041 audit completes & content sprint publishes", updated_at: "8m ago" },
      { key: "authority", status: "upcoming", auto_source: "starts once the content sprint is live", updated_at: "—" },
      { key: "reporting", status: "upcoming", auto_source: "auto-sends the first monthly report", updated_at: "—" },
    ],
  },
  {
    id: "mp-lumen", client: "Lumen Realty", site: "lumenrealty.co", init: "LR", c: SERIES.c2, health: "on_track",
    stages: [
      { key: "onboarding", ...done("Portal provisioned · 4 seats", "9d ago") },
      { key: "baseline", ...done("Technical + actionable audit signed off", "7d ago") },
      { key: "content", status: "in_progress", auto_source: "advances when 6-page sprint J-2039 publishes", updated_at: "26m ago" },
      { key: "authority", status: "upcoming", auto_source: "backlink outreach queues after publish", updated_at: "—" },
      { key: "reporting", status: "upcoming", auto_source: "auto-sends the first monthly report", updated_at: "—" },
    ],
  },
  {
    id: "mp-brighthvac", client: "BrightHVAC", site: "brighthvac.com", init: "BH", c: SERIES.c3, health: "completed",
    stages: [
      { key: "onboarding", ...done("Onboarding wizard finished", "62d ago") },
      { key: "baseline", ...done("Baseline audit fixes verified", "48d ago") },
      { key: "content", ...done("J-2030 · 4 posts published to WordPress", "9h ago") },
      { key: "authority", ...done("Backlink batch cleared review", "12d ago") },
      { key: "reporting", ...done("Quarterly report sent & approved", "2d ago") },
    ],
  },
  {
    id: "mp-coastline", client: "Coastline Fit", site: "coastlinefit.com", init: "CF", c: SERIES.c2, health: "on_track",
    stages: [
      { key: "onboarding", ...done("GBP & analytics access linked", "40d ago") },
      { key: "baseline", ...done("J-2028 local SEO audit completed", "18d ago") },
      { key: "content", ...done("Service-page content published", "10d ago") },
      { key: "authority", status: "in_progress", auto_source: "advances when citation & map-pack batch finishes", updated_at: "3h ago" },
      { key: "reporting", status: "upcoming", auto_source: "auto-sends the monthly report", updated_at: "—" },
    ],
  },
  {
    id: "mp-verde", client: "Verde Cafe", site: "verdecafe.pk", init: "VC", c: SERIES.c5, health: "at_risk",
    stages: [
      { key: "onboarding", ...done("Trial account set up", "14d ago") },
      { key: "baseline", status: "in_progress", auto_source: "stalled — J-2037 local SEO audit awaiting NAP data from client", updated_at: "3d ago" },
      { key: "content", status: "upcoming", auto_source: "starts after the baseline audit signs off", updated_at: "—" },
      { key: "authority", status: "upcoming", auto_source: "starts once content is live", updated_at: "—" },
      { key: "reporting", status: "upcoming", auto_source: "auto-sends the first monthly report", updated_at: "—" },
    ],
  },
  {
    id: "mp-atlas", client: "Atlas Legal", site: "atlaslegal.com", init: "AL", c: SERIES.c4, health: "at_risk",
    stages: [
      { key: "onboarding", ...done("Access collected · portal live", "21d ago") },
      { key: "baseline", status: "blocked", auto_source: "blocked — J-2032 audit paused, renewal past due (T-4821)", updated_at: "22m ago" },
      { key: "content", status: "upcoming", auto_source: "resumes when billing clears & audit completes", updated_at: "—" },
      { key: "authority", status: "upcoming", auto_source: "starts once content is live", updated_at: "—" },
      { key: "reporting", status: "upcoming", auto_source: "auto-sends the first monthly report", updated_at: "—" },
    ],
  },
];

// --- Recently auto-advanced feed -------------------------------------------
// Each entry is a milestone the system moved on its own when a job/audit
// changed state. `trigger` is the event that fired the advance.
export type AutoAdvance = {
  id: string;
  client: string;
  init: string;
  c: string;
  milestone: string; // the stage the project advanced TO (or was flagged on)
  trigger: string; // what fired it — a job id / audit / publish / payment
  icon: string;
  ago: string;
  flag?: boolean; // true = a block/at-risk flag rather than a forward advance
};

export const autoAdvances: AutoAdvance[] = [
  { id: "aa-01", client: "NorthPeak Dental", init: "ND", c: SERIES.c1, milestone: "Content Sprint", trigger: "J-2025 technical audit marked complete", icon: "fact_check", ago: "8m ago" },
  { id: "aa-02", client: "Atlas Legal", init: "AL", c: SERIES.c4, milestone: "Baseline Audit", trigger: "renewal past due — J-2032 audit auto-paused", icon: "block", ago: "22m ago", flag: true },
  { id: "aa-03", client: "Lumen Realty", init: "LR", c: SERIES.c2, milestone: "Content Sprint", trigger: "6-page sprint J-2039 entered publishing", icon: "article", ago: "26m ago" },
  { id: "aa-04", client: "Coastline Fit", init: "CF", c: SERIES.c2, milestone: "Off-page / Authority", trigger: "content sprint published to CMS", icon: "rocket_launch", ago: "3h ago" },
  { id: "aa-05", client: "BrightHVAC", init: "BH", c: SERIES.c3, milestone: "Content Sprint", trigger: "J-2030 · 4 posts published to WordPress", icon: "rocket_launch", ago: "9h ago" },
  { id: "aa-06", client: "Verde Cafe", init: "VC", c: SERIES.c5, milestone: "Baseline Audit", trigger: "J-2037 audit stalled — awaiting NAP data", icon: "pause_circle", ago: "3d ago", flag: true },
  { id: "aa-07", client: "BrightHVAC", init: "BH", c: SERIES.c3, milestone: "Reporting & Review", trigger: "quarterly report sent & client-approved", icon: "summarize", ago: "2d ago" },
];

// --- Filters ----------------------------------------------------------------
export type ProjectFilter = "all" | "on_track" | "at_risk" | "completed";
export const PROJECT_FILTERS: { key: ProjectFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "on_track", label: "On-track" },
  { key: "at_risk", label: "At-risk" },
  { key: "completed", label: "Completed" },
];
