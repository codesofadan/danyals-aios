// ============================================================
// AIOS · the three audit altitudes
//
// An audit is readable at three heights, and the whole UI hangs off this:
//
//   MACRO   a pillar verdict + THE COVERAGE THAT QUALIFIES IT
//           "Technical 88.7 - ran 25 of 100"
//   MICRO   one CAUSE, N instances
//           "Image alt text optimization - 121 pages"
//   NANO    one occurrence, one URL
//           "/about-us/  images=23, missing_alt=6"
//
// On a real 197-page audit that is 6 rows, 461 rows and 8,077 rows. Showing the
// 8,077 first is what produced an 833-page PDF nobody could act on.
//
// THE ONE RULE THIS FILE EXISTS TO ENFORCE. `score` is `null` when nothing ran,
// and null is NOT zero. A dimension we could not measure and a dimension that
// scored zero are opposite claims about a client's site. Every helper here keeps
// them apart, and `scoreDisplay` is the only sanctioned way to render a score -
// `score ?? 0` anywhere in a component is a bug.
// ============================================================

import type { AuditTypeKey } from "@/lib/audit";

export type RollupLevel = "site" | "dimension" | "pillar" | "subpoint";
export type Severity = "critical" | "major" | "minor" | "info";
export type LocusKind = "site" | "template" | "url" | "entity";

/** MACRO. One verdict, with the coverage that qualifies it. */
export type Rollup = {
  level: RollupLevel;
  key: string;
  label: string;
  /** null = NOT MEASURED. Never render as 0. */
  score: number | null;
  checks_applicable: number;
  checks_planned: number;
  checks_ran: number;
  checks_skipped: number;
  skip_reasons: Record<string, number>;
  findings_open: number;
  instances_open: number;
  pages_affected: number;
  pages_crawled: number;
  severity_counts: Partial<Record<Severity, number>>;
  /** Denominator is PAGES, so this one IS comparable across tiers. Site level only. */
  url_health_pct: number | null;
  basis_hash: string;
  scoring_model_version: string;
};

/** MICRO. One problem with one fix. */
export type Finding = {
  id: string;
  check_id: string;
  check_name: string;
  pillar: string;
  subcategory: string;
  dimension: AuditTypeKey | string;
  owner_agent: string;
  automation: string;
  severity: Severity;
  status: string;
  confidence: number | null;
  locus_kind: LocusKind;
  locus_value: string;
  /** What we OBSERVED. */
  instance_count: number;
  /** What we KEPT. Lower than instance_count only when a cap applied. */
  instances_stored: number;
  pages_affected: number;
  remediation: string;
  evidence: Record<string, unknown>;
  fingerprint: string;
  first_seen_at: string | null;
  last_seen_at: string | null;
};

/** NANO. One occurrence. */
export type FindingInstance = {
  id: string;
  url: string;
  instance_kind: string;
  template_id: string;
  observed: string;
  detail: string;
  evidence: Record<string, unknown>;
  severity_override: string;
  check_id: string;
  check_name: string;
  fingerprint: string;
};

export type AuditPage = {
  url: string;
  template_id: string;
  page_type: string | null;
  http_status: number | null;
  indexable: boolean | null;
  crawl_depth: number | null;
  word_count: number | null;
  is_orphan: boolean;
  issues_total: number;
  issues_critical: number;
  issues_major: number;
  issues_minor: number;
  issues_info: number;
  health_pass: boolean;
};

export type RoadmapPhaseKey = "p0_30d" | "p1_90d" | "p2_180d" | "p3_365d" | "backlog";

export type RoadmapItem = {
  id: string;
  finding_id: string | null;
  phase: RoadmapPhaseKey;
  sequence: number;
  title: string;
  check_id: string;
  pillar: string;
  subcategory: string;
  dimension: string;
  owner_role: string;
  severity: Severity;
  instance_count: number;
  pages_affected: number;
  impact_score: number | null;
  effort_points: number | null;
  priority: number | null;
  exit_criterion: string;
  verification_check: string;
};

export type RoadmapResponse = {
  roadmap: {
    id: string;
    capacity_points_per_month: number;
    /** null = the plan is in RELATIVE windows only, which is the default and the
     * honest posture. Dates exist only when an operator sets this. */
    start_date: string | null;
    items_total: number;
    items_planned: number;
    items_backlog: number;
    basis_hash: string;
  };
  effort_model: Record<string, unknown>;
  phases: { phase: RoadmapPhaseKey; label: string; items: RoadmapItem[] }[];
};

export type Paged<T> = { total: number; limit: number; offset: number; items: T[] };

// --------------------------------------------------------------------------- //
// Presentation
// --------------------------------------------------------------------------- //

export const NOT_MEASURED = "Not measured";

/** The ONLY sanctioned way to render a score. */
export function scoreDisplay(r: Pick<Rollup, "score" | "checks_ran">): string {
  if (r.score === null || r.checks_ran === 0) return NOT_MEASURED;
  return String(r.score);
}

export function isMeasured(r: Pick<Rollup, "score" | "checks_ran">): boolean {
  return r.score !== null && r.checks_ran > 0;
}

/** "25 of 100" - a score without this is not a fact a client can use. */
export function coverageLabel(r: Pick<Rollup, "checks_ran" | "checks_applicable">): string {
  return `${r.checks_ran} of ${r.checks_applicable}`;
}

/**
 * Below this share of a subpoint's checks, a score is not a usable verdict.
 *
 * MEASURED: on the real run `technical/performance` ran 1 of 7 checks, that one
 * check failed, and the subpoint therefore scored 0 - which reads as "your
 * performance is catastrophic" when the honest statement is "we looked at one
 * seventh of it and that part failed". `off-page/authority` did the same at 1 of 5.
 *
 * The score is still shown - hiding it would lose a real signal - but it is
 * marked INDICATIVE, so a single failing check cannot masquerade as a full verdict.
 */
export const LOW_COVERAGE_PCT = 50;

/** True when too little of a subpoint ran for its score to stand on its own. */
export function isLowCoverage(
  r: Pick<Rollup, "checks_ran" | "checks_applicable">,
): boolean {
  if (!r.checks_applicable || !r.checks_ran) return false;
  return coveragePct(r) < LOW_COVERAGE_PCT;
}

export function coveragePct(r: Pick<Rollup, "checks_ran" | "checks_applicable">): number {
  if (!r.checks_applicable) return 0;
  return Math.round((r.checks_ran / r.checks_applicable) * 100);
}

/**
 * Why a dimension is unmeasured, in the operator's language. The remedies differ
 * completely, so collapsing them into "no data" would hide the actionable one.
 */
export function notMeasuredReason(r: Pick<Rollup, "skip_reasons">): string {
  const s = r.skip_reasons || {};
  if (s.source_not_permitted) return "this tier does not run the required data source";
  if (s.analyzer_path_unresolved) return "no working analyzer for these checks";
  if (s.not_in_selected_dimensions) return "not part of the selected audit types";
  if (s.no_finding_emitted) return "checks ran but returned nothing";
  return "not run";
}

/** Score bands, matching the existing workspace (>=80 ok, 65-79 warn, <65 crit). */
export function scoreTone(score: number | null): "ok" | "warn" | "crit" | "none" {
  if (score === null) return "none";
  if (score >= 80) return "ok";
  if (score >= 65) return "warn";
  return "crit";
}

export const SEVERITY_ORDER: Severity[] = ["critical", "major", "minor", "info"];

export function severityTone(s: Severity | string): "crit" | "warn" | "ok" | "none" {
  if (s === "critical") return "crit";
  if (s === "major") return "warn";
  if (s === "minor") return "ok";
  return "none";
}

/**
 * The blast radius, phrased as an SEO lead would say it. This is the sentence
 * that replaces 8,077 undifferentiated rows.
 */
export function blastRadius(f: Pick<Finding, "instance_count" | "locus_kind">): string {
  if (f.locus_kind === "site") return "site-wide";
  if (f.locus_kind === "entity") return "off-site profile";
  const n = f.instance_count;
  return n === 1 ? "1 page" : `${n.toLocaleString()} pages`;
}

/** Where the fix goes - the reason a cause is a cause. */
export function fixScope(f: Pick<Finding, "locus_kind" | "locus_value">): string {
  switch (f.locus_kind) {
    case "site":
      return "One site-level change";
    case "template":
      return `One template: ${f.locus_value}`;
    case "entity":
      return "An off-site listing";
    default:
      return "This page only";
  }
}

/** True when a cap kept fewer instances than were observed. Must be surfaced. */
export function isTruncated(f: Pick<Finding, "instance_count" | "instances_stored">): boolean {
  return f.instances_stored < f.instance_count;
}

export const ROADMAP_PHASE_ORDER: RoadmapPhaseKey[] = [
  "p0_30d", "p1_90d", "p2_180d", "p3_365d", "backlog",
];

export const ROADMAP_PHASE_SHORT: Record<RoadmapPhaseKey, string> = {
  p0_30d: "Now",
  p1_90d: "Next",
  p2_180d: "Then",
  p3_365d: "Later",
  backlog: "Backlog",
};

/**
 * The window a phase covers, in MONTHS of the operator's stated throughput.
 * Deliberately not dates: nothing an audit measures supports a calendar claim.
 */
export const ROADMAP_PHASE_WINDOW: Record<RoadmapPhaseKey, string> = {
  p0_30d: "first 30 days",
  p1_90d: "through 90 days",
  p2_180d: "through 6 months",
  p3_365d: "through 12 months",
  backlog: "beyond the planned horizon",
};

export const ROLE_LABEL: Record<string, string> = {
  seo_specialist: "SEO Specialist",
  content_writer: "Content Writer",
  blog_writer: "Blog Writer",
  developer: "Developer",
  local_specialist: "Local Specialist",
};

/**
 * Dimension -> the owning role, mirroring the backend's own mapping so the UI,
 * the workbook and the roadmap all name the same person for the same work.
 *
 * NOTE this is keyed on DIMENSION, not on `owner_agent`. A finding carries an
 * agent code like "A3" or "B1", which is an internal engine identity and means
 * nothing to an operator - showing it raw reads as a serial number where a job
 * title belongs.
 */
export const DIMENSION_ROLE: Record<string, string> = {
  onpage: "seo_specialist",
  technical: "developer",
  offpage: "seo_specialist",
  local: "local_specialist",
  geo: "blog_writer",
  strategy: "seo_specialist",
};

/** The human job title that owns a finding. Falls back to the agent code only
 *  when the dimension is unknown, so nothing renders blank. */
export function ownerLabel(f: { dimension: string; owner_agent: string }): string {
  const role = DIMENSION_ROLE[f.dimension];
  return (role ? ROLE_LABEL[role] : undefined) ?? f.owner_agent ?? "-";
}

/** The four checklist files, in operator language rather than filenames. */
export const PILLAR_LABEL: Record<string, string> = {
  "on-page": "On-Page",
  technical: "Technical",
  "off-page": "Off-Page",
  "local-seo": "Local SEO",
};

export function pillarLabel(pillar: string): string {
  return PILLAR_LABEL[pillar] ?? pillar;
}

export const DIMENSION_ICON: Record<string, string> = {
  onpage: "checklist",
  technical: "build",
  offpage: "hub",
  local: "storefront",
  geo: "smart_toy",
  strategy: "flag",
};

/** The downloadable pack, mirroring the backend allow-list. */
export const DOWNLOADS: { name: string; label: string; hint: string }[] = [
  { name: "report", label: "Client report", hint: "the readable document - 11 pages, not 833" },
  { name: "workbook", label: "Workbook (XLSX)", hint: "9 sheets, every occurrence, filterable" },
  { name: "bundle", label: "Full pack (ZIP)", hint: "workbook + every CSV" },
  { name: "instances.csv", label: "Every occurrence (CSV)", hint: "uncapped - the complete record" },
  { name: "findings.csv", label: "Findings (CSV)", hint: "one row per problem" },
  { name: "roadmap.csv", label: "Roadmap (CSV)", hint: "the plan, in order" },
  { name: "coverage.csv", label: "Coverage (CSV)", hint: "every check, incl. what did not run" },
  { name: "pages.csv", label: "Pages (CSV)", hint: "every crawled URL" },
];
