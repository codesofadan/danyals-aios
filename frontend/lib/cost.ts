// ============================================================
// AIOS · Cost Controls — WIRE TYPES + display metadata.
// "Cost is a dial." Every external provider call passes a cost gate:
//   tier allows? → cached? → under cap? → call + log cost, else skip/stub/halt.
//
// NO PRICES LIVE IN THIS FILE. Unit prices come from GET /cost/pricing, which
// reads the same `Settings` values the cost gate bills at (see backend
// app/services/pricing.py). The hardcoded strings that used to sit here were
// wrong by two to three orders of magnitude against what the platform actually
// charges itself, and they could never track an env change. Do not reintroduce
// a literal price.
// ============================================================
import { SERIES, type SubTier } from "@/lib/data";

// Mirrors the full backend `Provider` set (app/services/cost_gate.py dial features) —
// Voyage (embeddings) + Google (Search Console/GA4) were added by later parts and
// must stay in sync here, or a dial/log row naming either crashes every lookup below.
export type Provider = "Serper" | "DataForSEO" | "Anthropic" | "PageSpeed" | "Places" | "Voyage" | "Google";
export type JobType = "audit" | "content" | "backlinks";
export type DialMode = "api" | "byhand" | "off";

// Providers behind the cost gate: accent colour + what each call buys.
// `paid` says whether the provider BILLS at all (a free-tier provider is still
// gated, for spend visibility and dial parity — it just commits $0). The unit
// PRICE is not here: read it from `useProviderPricing()`.
export const PROVIDERS: Record<Provider, { c: string; use: string; paid: boolean }> = {
  Serper:     { c: SERIES.c2, use: "SERP + keyword pulls",       paid: true },
  DataForSEO: { c: SERIES.c4, use: "Rank tracking + audit data", paid: true },
  Anthropic:  { c: SERIES.c1, use: "Content drafting (Claude)",  paid: true },
  Places:     { c: SERIES.c5, use: "Local / GBP lookups",        paid: true },
  PageSpeed:  { c: SERIES.c3, use: "Core Web Vitals",            paid: false },
  Voyage:     { c: SERIES.c1, use: "Context embeddings",         paid: true },
  Google:     { c: SERIES.c5, use: "Search Console + GA4",       paid: false },
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
export type ProviderMeta = { c: string; use: string; paid: boolean };

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
// The audit engine has NO flat per-run price: its cost is derived at runtime
// from what the run actually did (tokens, Serper queries, Places calls) — see
// backend app/services/pricing.py::audit_cost. Any "per run" figure here would
// be an invention, so there is none.
const PROVIDER_EXTRAS: Record<string, ProviderMeta> = {
  auditengine: { c: SERIES.c3, use: "Comprehensive audit run", paid: true },
  imagegen: { c: SERIES.c1, use: "AI image generation", paid: true },
  fake: { c: "var(--muted)", use: "Deterministic fake (no key)", paid: false },
};

export function providerMeta(p: string): ProviderMeta {
  const direct = (PROVIDERS as Record<string, ProviderMeta>)[p];
  if (direct) return direct;
  const key = String(p).toLowerCase().replace(/[^a-z0-9]/g, "");
  const alias = PROVIDER_ALIASES[key];
  if (alias) return PROVIDERS[alias];
  const extra = PROVIDER_EXTRAS[key];
  if (extra) return extra;
  // Unknown provider: assume it BILLS. Erring toward "paid" means an
  // unrecognised spend source is never shown to an operator as free.
  return { c: "var(--muted)", use: String(p || "Unknown provider"), paid: true };
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
  cap: number;   // spend ceiling (USD) - an all-time cap, not a monthly one
  spent: number; // ALL-TIME cumulative spend (USD) - client_budgets.spent only ever
                 // increments (no monthly reset), so this is NOT "this month"; use
                 // SpendStop.monthSpent for a real calendar-month figure
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
// The global API-spend HALT is a single agency-global kill-switch (owner/admin).
// There is no per-day dollar threshold any more. GET /cost/spend-stop returns
// { halted, todaySpent, monthSpent }.

export const usd = (n: number, dp = 0) =>
  "$" + n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });

// --- Live provider unit pricing (GET /cost/pricing) --------------------------
// The ONLY source of a unit price in the UI. Mirrors backend
// `ProviderPricingResponse`: `amount` is USD, `basis` names what one `amount`
// buys in the provider's own billing unit, and `source` names the Settings field
// the figure came from — so any price on screen is traceable to a live value.
export type ProviderPriceLine = { label: string; amount: number; basis: string };
export type ProviderPricing = {
  provider: string;
  paid: boolean;
  source: string;
  lines: ProviderPriceLine[];
};

/** Format a USD unit price at whatever precision it actually needs (max 6dp). */
export function unitPrice(amount: number): string {
  if (amount === 0) return "$0";
  const dp = Math.min(6, Math.max(2, Math.ceil(-Math.log10(Math.abs(amount))) + 2));
  return "$" + amount.toFixed(dp).replace(/0+$/, "").replace(/\.$/, "");
}

/** One-line summary of a provider's pricing, e.g. "$0.001 per query". */
export function pricingSummary(p: ProviderPricing | undefined): string {
  if (!p) return "";
  if (!p.paid) return "Free tier";
  const first = p.lines[0];
  if (!first) return "";
  const more = p.lines.length > 1 ? ` (+${p.lines.length - 1} more)` : "";
  return `${unitPrice(first.amount)} ${first.basis}${more}`;
}
