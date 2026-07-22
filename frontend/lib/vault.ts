// ============================================================
// AIOS · Key Vault mock data — swap for FastAPI + Supabase Vault
// later. In production every value below lives encrypted at rest
// in the Vault, is decrypted server-side only, and is NEVER shipped
// in the client bundle or written to logs. These fake demo strings
// exist purely so the Super-Admin UI has something to mask/reveal.
// ============================================================
import { SERIES } from "@/lib/data";

// --- Providers the platform integrates -------------------------------------
// The agency-global providers (paid APIs the platform itself calls) PLUS the
// per-client credential kinds the onboarding wizard collects (backend
// `client_onboarding/constants.py`'s 4 `collect_*` steps seal a vault_keys row
// with `provider` = the step key minus its `collect_` prefix — "gbp",
// "website_cms", "analytics", "search_console"). The backend field is plain
// `str` (not DB-enum-constrained — see 0041_vault_kind.sql), so this union can
// never be provably exhaustive; VaultTable falls back to a generic entry for
// anything not listed here rather than crashing on an unknown value.
export type ProviderId =
  | "serper" | "dataforseo" | "google" | "anthropic" | "imagegen" | "gsheets" | "wordpress"
  | "foursquare" | "apify" | "capmonster" | "resend"
  | "gbp" | "website_cms" | "analytics" | "search_console";

export type Category = "Rankings" | "Google APIs" | "AI / Content" | "Publishing" | "Sheets" | "Off-page" | "Delivery" | "Client Access";

export type Provider = {
  id: ProviderId;
  name: string;
  icon: string; // Material Symbols Rounded
  category: Category;
  c: string; // accent (SERIES slot)
  desc: string;
};

export const providers: Provider[] = [
  { id: "serper", name: "Serper.dev", icon: "travel_explore", category: "Rankings", c: SERIES.c4, desc: "SERP & rankings API" },
  { id: "dataforseo", name: "DataForSEO", icon: "leaderboard", category: "Rankings", c: SERIES.c4, desc: "Rankings & backlinks API" },
  { id: "google", name: "Google", icon: "public", category: "Google APIs", c: SERIES.c2, desc: "Search Console · Analytics · Places · PageSpeed" },
  { id: "anthropic", name: "Anthropic", icon: "auto_awesome", category: "AI / Content", c: SERIES.c1, desc: "Claude content generation" },
  { id: "imagegen", name: "Image Generation", icon: "image", category: "AI / Content", c: SERIES.c1, desc: "AI image generation API" },
  { id: "gsheets", name: "Google Sheets", icon: "grid_on", category: "Sheets", c: SERIES.c5, desc: "Service-account exports" },
  { id: "wordpress", name: "WordPress", icon: "language", category: "Publishing", c: SERIES.c3, desc: "Per-site application passwords" },
  { id: "foursquare", name: "Foursquare", icon: "place", category: "Off-page", c: SERIES.c4, desc: "Citation submissions (Places API)" },
  { id: "apify", name: "Apify", icon: "smart_toy", category: "Off-page", c: SERIES.c4, desc: "Citation-builder fallback actor" },
  { id: "capmonster", name: "CapMonster", icon: "security", category: "Off-page", c: SERIES.c4, desc: "CAPTCHA solver for the citation bot" },
  { id: "resend", name: "Resend", icon: "mail", category: "Delivery", c: SERIES.c3, desc: "Transactional email" },
  { id: "gbp", name: "Google Business Profile", icon: "storefront", category: "Client Access", c: SERIES.c2, desc: "A client's GBP access, collected at onboarding" },
  { id: "website_cms", name: "Website / CMS", icon: "language", category: "Client Access", c: SERIES.c3, desc: "A client's CMS login, collected at onboarding" },
  { id: "analytics", name: "Analytics", icon: "query_stats", category: "Client Access", c: SERIES.c2, desc: "A client's Analytics access, collected at onboarding" },
  { id: "search_console", name: "Search Console", icon: "travel_explore", category: "Client Access", c: SERIES.c4, desc: "A client's Search Console access, collected at onboarding" },
];

export const providerById: Record<ProviderId, Provider> = Object.fromEntries(
  providers.map((p) => [p.id, p])
) as Record<ProviderId, Provider>;

// A never-crash fallback for any provider string outside the list above (the
// backend field is unvalidated `str`, so this is a real, reachable case).
export const FALLBACK_PROVIDER: Provider = {
  id: "serper", name: "Other", icon: "key", category: "Client Access", c: SERIES.c5, desc: "Unrecognized provider",
};

// Category grouping for the providers-overview card. The Rankings note
// surfaces the platform's still-open decision: Serper.dev vs DataForSEO.
export const CATEGORIES: { key: Category; icon: string; c: string; note?: string }[] = [
  { key: "Rankings", icon: "leaderboard", c: SERIES.c4, note: "Source decision pending — Serper.dev vs DataForSEO" },
  { key: "Google APIs", icon: "public", c: SERIES.c2 },
  { key: "AI / Content", icon: "auto_awesome", c: SERIES.c1 },
  { key: "Publishing", icon: "language", c: SERIES.c3 },
  { key: "Sheets", icon: "grid_on", c: SERIES.c5 },
  { key: "Off-page", icon: "hub", c: SERIES.c4 },
  { key: "Delivery", icon: "mail", c: SERIES.c3 },
  { key: "Client Access", icon: "badge", c: SERIES.c2 },
];

// --- Key status ------------------------------------------------------------
export type KeyStatus = "active" | "expiring" | "rotate";

export const STATUS_META: Record<KeyStatus, { label: string; cls: "ok" | "warn" | "crit" }> = {
  active: { label: "Active", cls: "ok" },
  expiring: { label: "Expiring soon", cls: "warn" },
  rotate: { label: "Rotate now", cls: "crit" },
};

export type Scope = "Agency-global" | "Per-site";

// --- Vault entries ---------------------------------------------------------
// `masked` is the default display (secret hidden). `secret` is the fake full
// value revealed client-side only when the Super-Admin toggles the eye.
export type VaultKey = {
  id: string;
  provider: ProviderId;
  label: string;
  masked: string;
  secret: string;
  scope: Scope;
  site?: string;
  status: KeyStatus;
  rotated: string; // last rotated, relative
};

export const vaultKeys: VaultKey[] = [
  { id: "k-serper", provider: "serper", label: "Serper.dev · Production", masked: "serper-live-••••••••3f0b", secret: "serper-live-9f2a4c7b8e1d3f0b", scope: "Agency-global", status: "active", rotated: "42 days ago" },
  { id: "k-dfs", provider: "dataforseo", label: "DataForSEO · Rankings & Backlinks", masked: "dfs_••••••••••c2a1", secret: "dfs_7b3e9a2c4d6f8100c2a1", scope: "Agency-global", status: "expiring", rotated: "78 days ago" },
  { id: "k-gsc", provider: "google", label: "Search Console · OAuth token", masked: "ya29.a0Af••••••••Kd12", secret: "ya29.a0AfB_byC3kD9eLm7Np2Kd12", scope: "Agency-global", status: "active", rotated: "12 days ago" },
  { id: "k-ga4", provider: "google", label: "Analytics GA4 · API key", masked: "AIzaSyD••••••••8Qk4", secret: "AIzaSyD4k2Lm9Qp7Rt1Vx8Qk4", scope: "Agency-global", status: "active", rotated: "20 days ago" },
  { id: "k-psi", provider: "google", label: "PageSpeed Insights · API key", masked: "AIzaSyB••••••••m2X9", secret: "AIzaSyB1n3Wc6Ee9Hh2Km2X9", scope: "Agency-global", status: "rotate", rotated: "184 days ago" },
  { id: "k-places", provider: "google", label: "Places / Business Profile · API key", masked: "AIzaSyC••••••••n5P0", secret: "AIzaSyC8r5Tf2Gg4Jj7Nn5P0", scope: "Agency-global", status: "active", rotated: "26 days ago" },
  { id: "k-anthropic", provider: "anthropic", label: "Anthropic · Content Generation", masked: "sk-ant-••••••••••3f9a", secret: "sk-ant-api03-Xy8K2mQ9Lp0Rt3f9a", scope: "Agency-global", status: "active", rotated: "8 days ago" },
  { id: "k-image", provider: "imagegen", label: "Image Generation · Production", masked: "img_live_••••••••8d5e", secret: "img_live_5c7d2e9f1a3b8d5e", scope: "Agency-global", status: "expiring", rotated: "61 days ago" },
  { id: "k-sheets", provider: "gsheets", label: "Sheets · Service Account", masked: "svc-sheets@•••••••ef27", secret: "svc-sheets@aios.iam · key b41aef27", scope: "Agency-global", status: "active", rotated: "30 days ago" },
  { id: "k-wp-np", provider: "wordpress", label: "NorthPeak Dental · App Password", masked: "•••• •••• •••• c3d4", secret: "9x2K aQ7m Lp4R 8dN0 a1b2 c3d4", scope: "Per-site", site: "northpeakdental.com", status: "active", rotated: "15 days ago" },
  { id: "k-wp-bh", provider: "wordpress", label: "BrightHVAC · App Password", masked: "•••• •••• •••• z6Y1", secret: "7f1M bT3n Kq9W 2vX5 e8H4 z6Y1", scope: "Per-site", site: "brighthvac.com", status: "rotate", rotated: "152 days ago" },
];

// Mask an arbitrary secret for display (used when a new key is added).
export function maskSecret(v: string): string {
  const s = v.trim();
  if (!s) return "";
  const last4 = s.slice(-4);
  const head = s.length > 10 ? s.slice(0, 6) : s.slice(0, 2);
  return `${head}••••••••${last4}`;
}
