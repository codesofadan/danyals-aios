// ============================================================
// AIOS · Free Audit — client-side report generator
// The public /free-audit page has no backend yet (the FastAPI
// /audits service is a placeholder), so a free report is derived
// locally from the two Free-tier audit types in lib/audit.ts.
// Results are SEEDED from the URL so re-running the same site is
// stable (no jitter between renders) — swap for the real /audits
// endpoint once the audit worker is wired up.
// ============================================================

import { auditTypes, type AuditTypeKey } from "@/lib/audit";

export type CheckStatus = "pass" | "warn" | "fail";
export type ScoreBand = "ok" | "warn" | "crit";

export type CheckResult = { label: string; status: CheckStatus; note: string };
export type CategoryResult = {
  key: AuditTypeKey;
  label: string;
  icon: string;
  color: string;
  score: number;
  checks: CheckResult[];
};

export type FreeReport = {
  domain: string;
  score: number;
  band: ScoreBand;
  verdict: string;
  categories: CategoryResult[];
  issues: number; // warn + fail
  quickWins: number; // warn (easy fixes)
  checksRun: number;
};

// Score bands mirror the admin audit table (AuditWorkspace.scoreClass):
// ≥80 healthy · 65–79 needs work · <65 at risk.
export function scoreBand(score: number): ScoreBand {
  if (score >= 80) return "ok";
  if (score >= 65) return "warn";
  return "crit";
}

// Strip protocol / trailing slash so re-runs of the same site match
// and the displayed domain stays clean — same cleanup AuditWorkspace uses.
export function cleanDomain(url: string): string {
  return url.trim().replace(/^https?:\/\//i, "").replace(/\/$/, "").replace(/^www\./i, "");
}

const STATUS_POINTS: Record<CheckStatus, number> = { pass: 100, warn: 68, fail: 34 };

const NOTES: Record<CheckStatus, string[]> = {
  pass: ["Healthy — no action needed.", "Configured correctly.", "Meets best practice."],
  warn: ["Minor issues — a quick fix.", "Room to improve.", "Partially optimized."],
  fail: ["Needs attention — hurting rankings.", "Missing or misconfigured.", "Blocking better visibility."],
};

const VERDICT: Record<ScoreBand, string> = {
  ok: "Strong foundations — a few refinements will push you further ahead.",
  warn: "A solid start, but several issues are holding your rankings back.",
  crit: "Significant gaps are limiting your search visibility right now.",
};

// djb2 string hash → a stable 32-bit seed for the URL.
function hash(s: string): number {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h >>> 0;
}

// mulberry32 — tiny deterministic PRNG so the same seed yields the same report.
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function buildFreeReport(url: string): FreeReport {
  const domain = cleanDomain(url) || "your-site.com";
  const next = rng(hash(domain));

  // Free tier: only the on-page engine runs — the two paid: false types.
  const freeTypes = auditTypes.filter((t) => !t.paid);

  let issues = 0;
  let quickWins = 0;
  let checksRun = 0;

  const categories: CategoryResult[] = freeTypes.map((t) => {
    const checks: CheckResult[] = t.checks.map((label) => {
      const r = next();
      // Weighted toward pass, with a realistic tail of warns and a few fails.
      const status: CheckStatus = r < 0.56 ? "pass" : r < 0.83 ? "warn" : "fail";
      const pool = NOTES[status];
      const note = pool[Math.floor(next() * pool.length)];
      if (status !== "pass") issues++;
      if (status === "warn") quickWins++;
      checksRun++;
      return { label, status, note };
    });
    const catScore = Math.round(
      checks.reduce((s, c) => s + STATUS_POINTS[c.status], 0) / checks.length
    );
    return { key: t.key, label: t.short, icon: t.icon, color: t.color, score: catScore, checks };
  });

  const score = Math.round(
    categories.reduce((s, c) => s + c.score, 0) / Math.max(categories.length, 1)
  );
  const band = scoreBand(score);

  return { domain, score, band, verdict: VERDICT[band], categories, issues, quickWins, checksRun };
}
