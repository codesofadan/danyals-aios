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

// --- Filters ----------------------------------------------------------------
export type ProjectFilter = "all" | "on_track" | "at_risk" | "completed";
export const PROJECT_FILTERS: { key: ProjectFilter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "on_track", label: "On-track" },
  { key: "at_risk", label: "At-risk" },
  { key: "completed", label: "Completed" },
];
