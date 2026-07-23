// ============================================================
// AIOS · Cost Controls mock data — swap for FastAPI/Postgres later.
// "Cost is a dial." Every external provider call passes a cost gate:
//   tier allows? → cached? → under cap? → call + log cost, else skip/stub/halt.
// Three controls live here: the per-feature cost dial, per-client
// budget caps (on the job queue) and the global daily spend-stop.
// Shapes mirror the §8 data model (jobs, cost_log, budgets).
// ============================================================
import { SERIES, type SubTier } from "@/lib/data";

// Mirrors the full backend `Provider` set (app/services/cost_gate.py dial features) —
// Voyage (embeddings) + Google (Search Console/GA4) were added by later parts and
// must stay in sync here, or a dial/log row naming either crashes every lookup below.
export type Provider = "Serper" | "DataForSEO" | "Anthropic" | "PageSpeed" | "Places" | "Voyage" | "Google";
export type JobType = "audit" | "content" | "backlinks";
export type DialMode = "api" | "byhand" | "off";

// Paid providers behind the cost gate + what each call buys.
export const PROVIDERS: Record<Provider, { c: string; use: string; unit: string; paid: boolean }> = {
  Serper:     { c: SERIES.c2, use: "SERP + keyword pulls",        unit: "$0.30 / search",  paid: true },
  DataForSEO: { c: SERIES.c4, use: "Rank tracking + audit data",  unit: "$0.75 / task",    paid: true },
  Anthropic:  { c: SERIES.c1, use: "Content drafting (Claude)",   unit: "~$0.90 / page",   paid: true },
  Places:     { c: SERIES.c5, use: "Local / GBP lookups",         unit: "$0.17 / lookup",  paid: true },
  PageSpeed:  { c: SERIES.c3, use: "Core Web Vitals",             unit: "free tier",       paid: false },
  Voyage:     { c: SERIES.c1, use: "Context embeddings",          unit: "~$0.02 / 1k tok", paid: true },
  Google:     { c: SERIES.c5, use: "Search Console + GA4",        unit: "free tier",       paid: false },
};

export const JOB_TYPE_META: Record<JobType, { label: string; cls: string; icon: string }> = {
  audit:     { label: "Audit",     cls: "info", icon: "fact_check" },
  content:   { label: "Content",   cls: "warn", icon: "article" },
  backlinks: { label: "Backlinks", cls: "ok",   icon: "hub" },
};

// ---------------------------------------------------------------------------
// TOLERANT lookups. The backend cost log stores FREE-FORM provider/job-type
// strings (audit_engine, serper, google_search_console, context, ai_assist, …)
// — CostEntryResponse types them `str`, not our narrow unions. Indexing the
// exact-key maps above with an unknown string crashed the whole Cost screen
// (`Cannot read properties of undefined (reading 'c')`). Every component must
// resolve through these helpers instead: recognized names (any casing) map to
// canonical meta, anything else gets a neutral fallback — never a crash.
// ---------------------------------------------------------------------------
export type ProviderMeta = { c: string; use: string; unit: string; paid: boolean };

const PROVIDER_ALIASES: Record<string, Provider> = {
  serper: "Serper",
  dataforseo: "DataForSEO",
  anthropic: "Anthropic",
  claude: "Anthropic",
  pagespeed: "PageSpeed",
  googlepagespeed: "PageSpeed",
  places: "Places",
  googleplaces: "Places",
  voyage: "Voyage",
  google: "Google",
  googlesearchconsole: "Google",
  googleanalytics: "Google",
  googleoauth: "Google",
};

// Extra spend sources that are real but not one of the 7 dial providers.
const PROVIDER_EXTRAS: Record<string, ProviderMeta> = {
  auditengine: { c: SERIES.c3, use: "Comprehensive audit run", unit: "~$1.50 / run", paid: true },
  fake: { c: "var(--muted)", use: "Deterministic fake (no key)", unit: "free", paid: false },
};

export function providerMeta(p: string): ProviderMeta {
  const direct = (PROVIDERS as Record<string, ProviderMeta>)[p];
  if (direct) return direct;
  const key = String(p).toLowerCase().replace(/[^a-z0-9]/g, "");
  const alias = PROVIDER_ALIASES[key];
  if (alias) return PROVIDERS[alias];
  const extra = PROVIDER_EXTRAS[key];
  if (extra) return extra;
  return { c: "var(--muted)", use: String(p || "Unknown provider"), unit: "", paid: true };
}

/** Human label for a raw provider string ("audit_engine" → "Audit Engine"). */
export function providerLabel(p: string): string {
  if ((PROVIDERS as Record<string, ProviderMeta>)[p]) return p;
  return String(p || "Unknown")
    .split(/[_\-\s]+/)
    .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
    .join(" ");
}

export function jobTypeMeta(t: string): { label: string; cls: string; icon: string } {
  const direct = (JOB_TYPE_META as Record<string, { label: string; cls: string; icon: string }>)[t];
  if (direct) return direct;
  return { label: providerLabel(t) || "Job", cls: "mut", icon: "receipt_long" };
}

// --- Per-client budget caps (live on the job queue) -------------------------
export type ClientBudget = {
  id: string;
  cn: string;    // client name
  tier: SubTier;
  cap: number;   // monthly spend ceiling (USD)
  spent: number; // month-to-date spend (USD)
  c: string;     // accent (SERIES slot)
};

export type BudgetStatus = "ok" | "warn" | "crit";
export function budgetPct(b: { cap: number; spent: number }): number {
  return b.cap === 0 ? 0 : Math.round((b.spent / b.cap) * 100);
}
export function budgetStatus(b: { cap: number; spent: number }): BudgetStatus {
  const pct = b.cap === 0 ? 0 : (b.spent / b.cap) * 100;
  if (pct >= 100) return "crit";
  if (pct >= 80) return "warn";
  return "ok";
}
export const BUDGET_STATUS_META: Record<BudgetStatus, { label: string; cls: string }> = {
  ok:   { label: "OK",       cls: "ok" },
  warn: { label: "Near cap", cls: "warn" },
  crit: { label: "Over cap", cls: "crit" },
};

// --- Per-job cost log (shown to the admin) ----------------------------------
export type CostEntry = {
  id: string;       // job id
  client: string;
  type: JobType;
  provider: Provider;
  cost: number;     // USD billed for this call (cached ≈ $0)
  cached: boolean;  // served from cache → cost avoided
  time: string;     // relative
};

// --- Cost dial (per-feature mode) -------------------------------------------
// The dial the admin turns: API = call the paid provider, By hand = queue for
// manual review before spend, Off = stub/skip the call entirely.
export type DialFeature = {
  key: string;
  label: string;
  icon: string;
  provider: Provider;
  mode: DialMode;
  note: string;
};

export const DIAL_MODE_META: Record<DialMode, { label: string; icon: string }> = {
  api:    { label: "API",     icon: "bolt" },
  byhand: { label: "By hand", icon: "back_hand" },
  off:    { label: "Off",     icon: "block" },
};
export const DIAL_MODES: DialMode[] = ["api", "byhand", "off"];

// --- Global settings --------------------------------------------------------
// Fallback shown only while GET /cost/spend-stop is loading; the live value
// (SpendStopResponse.dailyStop) is authoritative once the query resolves.
export const dailyStopDefault = 75; // daily spend-stop threshold (USD)

export const usd = (n: number, dp = 0) =>
  "$" + n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
