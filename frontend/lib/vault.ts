// ============================================================
// AIOS · Key Vault — PROVIDER CATALOGUE + display metadata only.
//
// This file contains NO secrets and no seeded keys. Every vault entry
// is fetched from the API (`lib/hooks/vault`), stays masked in the list
// response, and is decrypted server-side only on an owner-authorised
// reveal. Never add a literal key, secret or example credential here:
// anything in this module ships inside the client bundle.
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
  | "foursquare" | "capmonster" | "resend"
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

// --- Key status ------------------------------------------------------------
export type KeyStatus = "active" | "expiring" | "rotate";

export const STATUS_META: Record<KeyStatus, { label: string; cls: "ok" | "warn" | "crit" }> = {
  active: { label: "Active", cls: "ok" },
  expiring: { label: "Expiring soon", cls: "warn" },
  rotate: { label: "Rotate now", cls: "crit" },
};

export type Scope = "Agency-global" | "Per-site";

// --- Vault entries ---------------------------------------------------------
// `masked` is what the list endpoint returns — the plaintext never leaves the
// server on a list. `secret` is populated ONLY by an owner-authorised reveal
// (POST /vault/{id}/reveal), held in memory for that one row, and never seeded.
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
