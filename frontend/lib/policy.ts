// ============================================================
// AIOS · Policy Radar (Module 05) mock data layer
// The platform's always-on brain: Watch → Detect → Research →
// Flag (KB) → Recommend → human-confirm → closed loop into
// audit checks / content guidance / client advisories.
// Swap these arrays for FastAPI / Postgres + the crawler jobs
// when the backend is wired.
// ============================================================
import { SERIES } from "@/lib/data";

// ---- taxonomy -------------------------------------------------
export type Severity = "critical" | "major" | "minor" | "info";
export type Category = "algorithm" | "policy" | "technical" | "content" | "local" | "geo";
export type Region = "global" | "national";
export type TargetModule = "audit" | "content" | "portal";
export type Scope = "global" | "client" | "site";
export type RecStatus = "new" | "acknowledged" | "applied" | "dismissed";
export type SourceStatus = "ok" | "change";

// severity badge classes: critical=crit, major=warn, minor=info, info=mut
export const SEV_META: Record<Severity, { label: string; cls: string; color: string }> = {
  critical: { label: "Critical", cls: "crit", color: "var(--crit)" },
  major: { label: "Major", cls: "warn", color: "var(--warn)" },
  minor: { label: "Minor", cls: "info", color: "var(--c4)" },
  info: { label: "Info", cls: "mut", color: "var(--muted)" },
};

export const CAT_META: Record<Category, { label: string; icon: string; color: string }> = {
  algorithm: { label: "Algorithm", icon: "hub", color: SERIES.c1 },
  policy: { label: "Policy", icon: "gavel", color: SERIES.c5 },
  technical: { label: "Technical", icon: "code", color: SERIES.c4 },
  content: { label: "Content", icon: "article", color: SERIES.c2 },
  local: { label: "Local", icon: "location_on", color: SERIES.c3 },
  geo: { label: "GEO", icon: "auto_awesome", color: SERIES.c1 },
};

export const MODULE_META: Record<TargetModule, { label: string; icon: string }> = {
  audit: { label: "Audit Engine", icon: "fact_check" },
  content: { label: "Content Studio", icon: "edit_note" },
  portal: { label: "Client Portal", icon: "supervisor_account" },
};

// ---- watched sources -----------------------------------------
export type Source = {
  id: string;
  name: string;
  kind: string;
  url: string;
  icon: string;
  lastChecked: string;
  lastHash: string;
  status: SourceStatus;
  note: string;
};

// ---- detected change events ----------------------------------
export type ChangeEvent = {
  id: string;
  sourceId: string;
  sourceName: string;
  summary: string;
  severity: Severity;
  detected: string;
};

// ---- knowledge base entries (versioned, deduped, cited) ------
export type KBEntry = {
  id: string;
  title: string;
  summary: string;
  severity: Severity;
  category: Category;
  region: Region;
  regionLabel: string;
  sourceName: string;
  sourceUrl: string;
  version: string;
  detected: string;
};

// ---- recommendations (Command Center) ------------------------
export type Recommendation = {
  id: string;
  kbId: string;
  title: string;        // what changed
  why: string;          // why it matters
  action: string;       // recommended action
  scope: Scope;
  target: TargetModule;
  region: Region;
  regionLabel: string;
  status: RecStatus;
  clients?: string;     // affected clients, when scoped
};

// ---- KPI helpers ---------------------------------------------
export const REC_OPEN: RecStatus[] = ["new", "acknowledged"];
