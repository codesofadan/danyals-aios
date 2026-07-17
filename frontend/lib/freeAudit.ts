// ============================================================
// AIOS · Free Audit — pure presentation helpers
// The public /free-audit page is now backed by the REAL FastAPI public
// funnel (lib/hooks/publicAudit.ts + app/routers/public.py). The old
// client-side PRNG report generator is GONE — the backend owns the score.
// What remains here is pure, honest presentation glue: domain cleaning,
// score bands, per-band verdict copy, and the mapping from the backend's
// thin `scores` map onto the category bars the report renders. Nothing is
// invented for data the backend doesn't return.
// ============================================================

import { SERIES } from "@/lib/data";

export type ScoreBand = "ok" | "warn" | "crit";

// Score bands mirror the admin audit table (AuditWorkspace.scoreClass):
// ≥80 healthy · 65–79 needs work · <65 at risk.
export function scoreBand(score: number): ScoreBand {
  if (score >= 80) return "ok";
  if (score >= 65) return "warn";
  return "crit";
}

// Strip protocol / trailing slash / www so the displayed domain stays clean —
// same cleanup AuditWorkspace uses.
export function cleanDomain(url: string): string {
  return url.trim().replace(/^https?:\/\//i, "").replace(/\/$/, "").replace(/^www\./i, "");
}

export const VERDICT: Record<ScoreBand, string> = {
  ok: "Strong foundations — a few refinements will push you further ahead.",
  warn: "A solid start, but several issues are holding your rankings back.",
  crit: "Significant gaps are limiting your search visibility right now.",
};

// The audit engine's run.json `scores` map is keyed by engine category
// (`overall` + on_page/technical/off_page/local, plus geo/backlink on paid
// runs). This is the display metadata for each — label, Material icon, accent
// color — so a known key renders on-brand and an unknown/future key still
// renders with a sane fallback.
type CategoryMeta = { label: string; icon: string; color: string };

const CATEGORY_META: Record<string, CategoryMeta> = {
  on_page: { label: "On-page", icon: "checklist", color: SERIES.c1 },
  technical: { label: "Technical", icon: "manage_search", color: SERIES.c4 },
  off_page: { label: "Off-page", icon: "hub", color: SERIES.c2 },
  local: { label: "Local & GBP", icon: "location_on", color: SERIES.c3 },
  geo: { label: "AI / GEO", icon: "auto_awesome", color: SERIES.c5 },
  backlink: { label: "Backlink", icon: "link", color: SERIES.c2 },
};

// `overall` is the composite (rendered as the big ring) — never a bar.
const NON_CATEGORY_KEYS = new Set(["overall"]);

function titleize(key: string): string {
  return key.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function metaFor(key: string): CategoryMeta {
  return CATEGORY_META[key] ?? { label: titleize(key), icon: "insights", color: SERIES.c4 };
}

// The per-category value may be a bare number OR a nested object — the backend
// types `scores` as `dict[str, Any]` and does not pin the shape, so we read a
// number directly or pull it from a `{score|overall|value}` field, and skip
// anything non-numeric rather than invent a bar.
function numericScore(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    for (const f of ["score", "overall", "value"]) {
      const n = o[f];
      if (typeof n === "number" && Number.isFinite(n)) return n;
    }
  }
  return null;
}

export type CategoryBar = {
  key: string;
  label: string;
  icon: string;
  color: string;
  score: number;
  band: ScoreBand;
};

// Turn the backend `scores` map into ordered category bars. Only numeric,
// non-`overall` entries become bars — nothing is invented for missing data.
export function toCategoryBars(scores: Record<string, unknown>): CategoryBar[] {
  const known = Object.keys(CATEGORY_META);
  const rank = (k: string) => {
    const i = known.indexOf(k);
    return i === -1 ? known.length : i;
  };
  return Object.entries(scores)
    .filter(([k]) => !NON_CATEGORY_KEYS.has(k))
    .map(([k, v]) => ({ k, n: numericScore(v) }))
    .filter((e): e is { k: string; n: number } => e.n !== null)
    .map(({ k, n }) => {
      const score = Math.round(n);
      const meta = metaFor(k);
      return { key: k, label: meta.label, icon: meta.icon, color: meta.color, score, band: scoreBand(score) };
    })
    .sort((a, b) => rank(a.key) - rank(b.key));
}
