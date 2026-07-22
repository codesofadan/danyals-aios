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

// Shared base cost runs ~$44–64/mo; content adds ~$10–50/page, so caps
// scale with tier. Spend below drives the near-cap / over states.
export const budgets_seed: ClientBudget[] = [
  { id: "b-northpeak",   cn: "NorthPeak Dental",   tier: "Scale",   cap: 500, spent: 312, c: SERIES.c1 },
  { id: "b-meridian",    cn: "Meridian Wealth",    tier: "Scale",   cap: 500, spent: 356, c: SERIES.c1 },
  { id: "b-lumen",       cn: "Lumen Realty",       tier: "Growth",  cap: 250, spent: 214, c: SERIES.c2 },
  { id: "b-atlas",       cn: "Atlas Legal",        tier: "Growth",  cap: 250, spent: 261, c: SERIES.c4 },
  { id: "b-brighthvac",  cn: "BrightHVAC",         tier: "Growth",  cap: 250, spent: 138, c: SERIES.c3 },
  { id: "b-coastline",   cn: "Coastline Fit",      tier: "Starter", cap: 120, spent: 103, c: SERIES.c2 },
  { id: "b-verde",       cn: "Verde Cafe",         tier: "Starter", cap: 120, spent:  47, c: SERIES.c5 },
  { id: "b-orchard",     cn: "Orchard Pediatrics", tier: "Starter", cap: 120, spent:   8, c: SERIES.c5 },
];

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

export const costLog_seed: CostEntry[] = [
  { id: "J-2041", client: "NorthPeak Dental",  type: "audit",     provider: "DataForSEO", cost: 0.75, cached: false, time: "6m ago" },
  { id: "J-2041", client: "NorthPeak Dental",  type: "audit",     provider: "PageSpeed",  cost: 0.00, cached: false, time: "6m ago" },
  { id: "J-2039", client: "Lumen Realty",      type: "content",   provider: "Anthropic",  cost: 1.28, cached: false, time: "24m ago" },
  { id: "J-2038", client: "Meridian Wealth",   type: "backlinks", provider: "Serper",     cost: 0.30, cached: false, time: "38m ago" },
  { id: "J-2037", client: "Verde Cafe",        type: "audit",     provider: "DataForSEO", cost: 0.00, cached: true,  time: "52m ago" },
  { id: "J-2036", client: "BrightHVAC",        type: "content",   provider: "Anthropic",  cost: 0.94, cached: false, time: "1h ago" },
  { id: "J-2035", client: "Coastline Fit",     type: "backlinks", provider: "Places",     cost: 0.17, cached: false, time: "1h ago" },
  { id: "J-2034", client: "Atlas Legal",       type: "audit",     provider: "Serper",     cost: 0.00, cached: true,  time: "2h ago" },
  { id: "J-2033", client: "Lumen Realty",      type: "audit",     provider: "DataForSEO", cost: 0.75, cached: false, time: "2h ago" },
  { id: "J-2032", client: "NorthPeak Dental",  type: "content",   provider: "Anthropic",  cost: 1.12, cached: false, time: "3h ago" },
  { id: "J-2031", client: "Verde Cafe",        type: "backlinks", provider: "Serper",     cost: 0.30, cached: false, time: "4h ago" },
  { id: "J-2030", client: "Meridian Wealth",   type: "audit",     provider: "DataForSEO", cost: 0.00, cached: true,  time: "5h ago" },
];

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

export const dial_seed: DialFeature[] = [
  { key: "tech_audit", label: "Technical Audit",  icon: "troubleshoot", provider: "DataForSEO", mode: "api",    note: "Live crawl + rank data" },
  { key: "cwv",        label: "Core Web Vitals",  icon: "speed",        provider: "PageSpeed",  mode: "api",    note: "Free tier — always on" },
  { key: "content",    label: "Content Pipeline", icon: "article",      provider: "Anthropic",  mode: "api",    note: "Claude drafting, ~$0.90/pg" },
  { key: "backlinks",  label: "Backlink Manager", icon: "hub",          provider: "Serper",     mode: "byhand", note: "Paid — review before pull" },
  { key: "local_seo",  label: "Local SEO",        icon: "storefront",   provider: "Places",     mode: "byhand", note: "GBP + map-pack lookups" },
  { key: "keywords",   label: "Keyword Research", icon: "search",       provider: "Serper",     mode: "off",    note: "Paused this cycle" },
];

export const DIAL_MODE_META: Record<DialMode, { label: string; icon: string }> = {
  api:    { label: "API",     icon: "bolt" },
  byhand: { label: "By hand", icon: "back_hand" },
  off:    { label: "Off",     icon: "block" },
};
export const DIAL_MODES: DialMode[] = ["api", "byhand", "off"];

// --- Spend by provider, month-to-date (USD) ---------------------------------
export const providerSpend_seed: { provider: Provider; amount: number }[] = [
  { provider: "Anthropic",  amount: 612 },
  { provider: "DataForSEO", amount: 428 },
  { provider: "Serper",     amount: 236 },
  { provider: "Places",     amount: 148 },
  { provider: "PageSpeed",  amount: 15 },
];

// --- Global settings --------------------------------------------------------
export const jobsThisMonth = 247;
export const dailyStopDefault = 75; // daily spend-stop threshold (USD)

export const usd = (n: number, dp = 0) =>
  "$" + n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
