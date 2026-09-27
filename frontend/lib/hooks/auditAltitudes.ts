"use client";

// ============================================================
// AIOS · audit altitude hooks
//
// One hook per altitude, mirroring the six endpoints the backend exposes.
// Every one is READ-ONLY: the altitude tables are written by the worker's ingest
// on the service_role seam, never through a user JWT.
//
// All the READS are `staleTime: Infinity` and never poll. A completed audit's
// findings do not change until it is RE-RUN, and re-running creates a new audit
// row - so refetching on an interval would be pure waste. This is deliberately
// the opposite of `useAudits`, which polls while a job is in flight.
// ============================================================

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type {
  AuditPage,
  Finding,
  FindingInstance,
  Paged,
  RoadmapResponse,
  Rollup,
  RollupLevel,
} from "@/lib/auditAltitude";

export type FindingFilters = {
  dimension?: string;
  pillar?: string;
  subcategory?: string;
  severity?: string;
  check_id?: string;
  limit?: number;
  offset?: number;
};

export const altitudeKey = {
  rollups: (id: string, level?: RollupLevel) => ["audit", id, "rollups", level ?? "all"] as const,
  findings: (id: string, f: FindingFilters) => ["audit", id, "findings", f] as const,
  instances: (id: string, fid: string, offset: number) =>
    ["audit", id, "instances", fid, offset] as const,
  pages: (id: string) => ["audit", id, "pages"] as const,
  roadmap: (id: string) => ["audit", id, "roadmap"] as const,
};

const FOREVER = { staleTime: Infinity, refetchOnWindowFocus: false } as const;

function qs(params: Record<string, string | number | undefined>): string {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== "" && v !== null)
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

/** MACRO. Pillar / subpoint verdicts, each carrying its own coverage. */
export function useAuditRollups(auditId: string, level?: RollupLevel) {
  return useQuery({
    queryKey: altitudeKey.rollups(auditId, level),
    queryFn: () => api.get<Rollup[]>(`/audits/${auditId}/rollups${qs({ level })}`),
    enabled: Boolean(auditId),
    ...FOREVER,
  });
}

/** MICRO. One row per PROBLEM - not per occurrence. */
export function useAuditFindings(auditId: string, filters: FindingFilters = {}) {
  return useQuery({
    queryKey: altitudeKey.findings(auditId, filters),
    queryFn: () => api.get<Paged<Finding>>(`/audits/${auditId}/findings${qs({ ...filters })}`),
    enabled: Boolean(auditId),
    ...FOREVER,
  });
}

/**
 * NANO. Every occurrence of ONE cause.
 *
 * `enabled` is gated on the caller actually opening a finding: a page showing 50
 * findings must not fire 50 instance requests for cards nobody expanded.
 */
export function useFindingInstances(
  auditId: string,
  findingId: string | null,
  offset = 0,
  limit = 200,
) {
  return useQuery({
    queryKey: altitudeKey.instances(auditId, findingId ?? "", offset),
    queryFn: () =>
      api.get<Paged<FindingInstance>>(
        `/audits/${auditId}/findings/${findingId}/instances${qs({ limit, offset })}`,
      ),
    enabled: Boolean(auditId && findingId),
    ...FOREVER,
  });
}

export function useAuditPages(auditId: string, limit = 500) {
  return useQuery({
    queryKey: altitudeKey.pages(auditId),
    queryFn: () => api.get<AuditPage[]>(`/audits/${auditId}/pages${qs({ limit })}`),
    enabled: Boolean(auditId),
    ...FOREVER,
  });
}

/**
 * The plan. 404s when an audit predates the roadmap generator or produced no
 * findings, which the caller renders as an empty state rather than an error -
 * "no plan yet" is a legitimate state, not a failure.
 */
export function useAuditRoadmap(auditId: string) {
  return useQuery({
    queryKey: altitudeKey.roadmap(auditId),
    queryFn: () => api.get<RoadmapResponse>(`/audits/${auditId}/roadmap`),
    enabled: Boolean(auditId),
    retry: false,
    ...FOREVER,
  });
}


/** What POST /audits/{id}/reingest reports having rebuilt. */
export type ReingestResult = {
  auditId: string;
  pages: number;
  findings: number;
  instances: number;
  roadmapItems: number;
  workbookBuilt: boolean;
  reportBuilt: boolean;
  notes: string[];
};

/**
 * Rebuild a completed audit's findings from the artifacts it already produced.
 *
 * The one WRITE in this module, and it writes no new evidence: it re-runs the
 * same transform the worker runs, against the run's own stored artifact_dir. An
 * audit whose ingest failed - or that predates the altitude tables - has a report
 * on disk and no rows behind it, which the detail page could only report as "no
 * altitude data" and a link back to the list. This is the way out of that.
 *
 * It does not re-run the audit and spends nothing. A run whose artifacts are gone
 * returns 409 with the reason, rather than an empty rebuild reported as success.
 *
 * Invalidates every altitude query for the audit, so the page redraws with the
 * rebuilt rows instead of asking the operator to refresh.
 */
export function useReingestAudit(auditId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<ReingestResult>(`/audits/${auditId}/reingest`, {}),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["audit", auditId] });
      void qc.invalidateQueries({ queryKey: ["audits"] });
    },
  });
}

// --- DELTA: what changed since the previous audit of this site ----------------
//
// The most valuable thing the audit module can say, and the module could not say it until
// now. Everything it needs was already stored: a finding is keyed on a fingerprint that
// deliberately excludes the URL, the count and the run id (migration 0094) precisely so it
// stays stable while the site changes, and the migration's own comment says those columns
// exist to make a delta possible. Nothing read them.
//
// TWO THINGS THE UI MUST RESPECT, both decided server-side and carried in this payload:
//   * `unchecked` is NOT `fixed`. A finding that vanished because the later run did not
//     measure its dimension (a shallower depth, a lapsed provider key) must never be shown
//     as work completed.
//   * `scoreDelta` is null when the two runs measured different check sets, and `reason`
//     then says so. Render the reason, not a zero.
export type CompareFinding = {
  checkId: string;
  title: string;
  severity: string;
  dimension: string;
  pages: number;
  pagesDelta?: number;
};

export type CompareDimension = {
  key: string;
  label: string;
  scoreBefore: number | null;
  scoreAfter: number | null;
  scoreDelta: number | null;
  scoreWithheld: string;
  healthBefore: number | null;
  healthAfter: number | null;
  fixed: number;
  new: number;
  persisting: number;
};

export type AuditComparison = {
  /** False when this is the site's first completed audit - a calm empty state, not an error. */
  available?: boolean;
  reason: string;
  headline: string;
  comparable?: boolean;
  counts?: { fixed: number; new: number; persisting: number; unchecked: number };
  fixed?: CompareFinding[];
  new?: CompareFinding[];
  persisting?: CompareFinding[];
  unchecked?: CompareFinding[];
  dimensions?: CompareDimension[];
  scoreBefore?: number | null;
  scoreAfter?: number | null;
  scoreDelta?: number | null;
  healthBefore?: number | null;
  healthAfter?: number | null;
  baseline?: { id: string; when: string; depth: string };
  /** Every completed audit of this site, newest first - the "compare with" picker. */
  runs?: { id: string; when: string; depth: string; score: number | null }[];
};

export const auditCompareKey = (auditId: string, to?: string) =>
  ["audit", "compare", auditId, to ?? "previous"] as const;

export function useAuditCompare(auditId: string, to?: string) {
  return useQuery({
    queryKey: auditCompareKey(auditId, to),
    queryFn: () =>
      api.get<AuditComparison>(
        `/audits/${auditId}/compare${to ? `?to=${encodeURIComponent(to)}` : ""}`,
      ),
    enabled: Boolean(auditId),
  });
}
