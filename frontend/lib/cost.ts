// ============================================================
// AIOS · Cost Controls mock data — swap for FastAPI/Postgres later.
// "Cost is a dial." Every external provider call passes a cost gate:
//   tier allows? → cached? → under cap? → call + log cost, else skip/stub/halt.
// Three controls live here: the per-feature cost dial, per-client
// budget caps (on the job queue) and the global daily spend-stop.
// Shapes mirror the §8 data model (jobs, cost_log, budgets).
// ============================================================
import { SERIES, type SubTier } from "@/lib/data";

export type Provider = "Serper" | "DataForSEO" | "Anthropic" | "PageSpeed" | "Places";
export type JobType = "audit" | "content" | "backlinks";
export type DialMode = "api" | "byhand" | "off";

// Paid providers behind the cost gate + what each call buys.
export const PROVIDERS: Record<Provider, { c: string; use: string; unit: string; paid: boolean }> = {
  Serper:     { c: SERIES.c2, use: "SERP + keyword pulls",        unit: "$0.30 / search",  paid: true },
  DataForSEO: { c: SERIES.c4, use: "Rank tracking + audit data",  unit: "$0.75 / task",    paid: true },
  Anthropic:  { c: SERIES.c1, use: "Content drafting (Claude)",   unit: "~$0.90 / page",   paid: true },
  Places:     { c: SERIES.c5, use: "Local / GBP lookups",         unit: "$0.17 / lookup",  paid: true },
  PageSpeed:  { c: SERIES.c3, use: "Core Web Vitals",             unit: "free tier",       paid: false },
};

export const JOB_TYPE_META: Record<JobType, { label: string; cls: string; icon: string }> = {
  audit:     { label: "Audit",     cls: "info", icon: "fact_check" },
  content:   { label: "Content",   cls: "warn", icon: "article" },
  backlinks: { label: "Backlinks", cls: "ok",   icon: "hub" },
};

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
