// ============================================================
// AIOS · Off-page module types — Module 03 (Backlinks, Citations
// & Web 2.0). Paid tier; every Web 2.0 placement is human-
// approved, never link spam. Backlink signals originate from
// DataForSEO (new/lost alerts); Web 2.0 posts publish through
// official platform APIs; citations SUBMIT via a direct API, an
// aggregator push, or the self-hosted Playwright bot (7B-4).
// Shapes mirror the live FastAPI response models 1:1 (contract-
// locked server-side by tests/test_contract_lock.py) — there is
// no mock data left in this file; every screen reads the backend.
// ============================================================

import { SERIES } from "@/lib/data";

// --- Backlink monitoring ----------------------------------------------------
// status: new = freshly discovered, lost = dropped since last crawl,
// toxic = high spam-score link flagged for a disavow review.
export type BacklinkStatus = "new" | "lost" | "toxic";

export const BACKLINK_META: Record<BacklinkStatus, { label: string; cls: string; icon: string }> = {
  new: { label: "New", cls: "ok", icon: "trending_up" },
  lost: { label: "Lost", cls: "warn", icon: "link_off" },
  toxic: { label: "Toxic", cls: "op-crit", icon: "gpp_bad" },
};

export type Backlink = {
  id: string;
  client: string;
  refDomain: string; // referring domain
  anchor: string;
  authority: number; // domain authority 0–100
  spam: number; // spam score 0–100
  firstSeen: string; // discovery date
  status: BacklinkStatus;
};

// --- Local citations / NAP --------------------------------------------------
// nap_status: consistent = name/address/phone match the source of truth,
// inconsistent = a field drifted, missing = no listing on that directory yet.
export type NapStatus = "consistent" | "inconsistent" | "missing";

export const NAP_META: Record<NapStatus, { label: string; cls: string }> = {
  consistent: { label: "Consistent", cls: "ok" },
  inconsistent: { label: "Inconsistent", cls: "warn" },
  missing: { label: "Missing", cls: "mut" },
};

// State/action derives from nap_status: missing → Submit, otherwise → Update.
export type CitationAction = "Submit" | "Update";

// 7B-4: the SUBMISSION pipeline state (as opposed to nap_status, which is the
// MONITORING verdict). not_started/queued/submitting are in-flight; submitted and
// verified are both "live" (verified = a human/re-check confirmed it, submitted =
// the engine reported success but it has not been re-verified yet); failed/blocked
// both need attention (blocked = a cost-gate hold or no engine configured, never a
// guess at a live result).
export type CitationSubmitStatus =
  | "not_started" | "queued" | "submitting" | "submitted" | "verified" | "failed" | "blocked";

export const SUBMIT_STATUS_META: Record<CitationSubmitStatus, { label: string; cls: string }> = {
  not_started: { label: "Not started", cls: "mut" },
  queued: { label: "Queued", cls: "info" },
  submitting: { label: "Submitting", cls: "info" },
  submitted: { label: "Submitted", cls: "ok" },
  verified: { label: "Verified", cls: "ok" },
  failed: { label: "Failed", cls: "op-crit" },
  blocked: { label: "Blocked", cls: "warn" },
};

export type Citation = {
  id: string;
  client: string;
  directory: string;
  nap: NapStatus;
  action: CitationAction;
  note: string; // what drifted / listing detail
  submitStatus: CitationSubmitStatus;
  proofUrl: string; // a submission's screenshot/receipt artifact (blank if none)
};

// --- Web 2.0 automation -----------------------------------------------------
// Branded article → published via official platform API → link verified live.
// 7B-4: grew from 4 to 17 platforms — every one the reference plan tags API-post:
// Yes, not deprecated, and not a blockchain/brand-risk case (see
// integrations/web2_publishers.py's module docstring for what was deliberately left
// out and why). Medium stays draft-only (its publish API is retired).
export type Web2Platform =
  | "WordPress.com" | "Blogger" | "Tumblr" | "Medium"
  | "dev.to" | "Write.as" | "Telegra.ph" | "Mataroa" | "Ghost" | "Mastodon"
  | "GitHub Pages" | "GitLab Pages" | "Micro.blog" | "Hashnode" | "Hatena Blog"
  | "LiveJournal" | "Dreamwidth";
export type Web2Verified = "verified" | "pending";

export const PLATFORM_META: Record<Web2Platform, { icon: string; c: string }> = {
  "WordPress.com": { icon: "web", c: SERIES.c4 },
  Blogger: { icon: "rss_feed", c: SERIES.c3 },
  Tumblr: { icon: "tag", c: SERIES.c1 },
  Medium: { icon: "article", c: SERIES.c2 },
  "dev.to": { icon: "code", c: SERIES.c1 },
  "Write.as": { icon: "edit_note", c: SERIES.c2 },
  "Telegra.ph": { icon: "send", c: SERIES.c3 },
  Mataroa: { icon: "draft", c: SERIES.c4 },
  Ghost: { icon: "history_edu", c: SERIES.c1 },
  Mastodon: { icon: "alternate_email", c: SERIES.c2 },
  "GitHub Pages": { icon: "hub", c: SERIES.c3 },
  "GitLab Pages": { icon: "hub", c: SERIES.c4 },
  "Micro.blog": { icon: "rss_feed", c: SERIES.c1 },
  Hashnode: { icon: "article", c: SERIES.c2 },
  "Hatena Blog": { icon: "public", c: SERIES.c3 },
  LiveJournal: { icon: "menu_book", c: SERIES.c4 },
  Dreamwidth: { icon: "menu_book", c: SERIES.c1 },
};

// Every platform NOT draft-only can be planned/approved through the pipeline.
export const LIVE_WEB2_PLATFORMS: Web2Platform[] = (
  Object.keys(PLATFORM_META) as Web2Platform[]
).filter((p) => p !== "Medium");

export type Web2Property = {
  id: string;
  client: string;
  platform: Web2Platform;
  postUrl: string;
  anchor: string;
  verified: Web2Verified;
  published: string;
  status: Web2PipelineStatus;
};

// The publish PIPELINE's state machine (0028) — distinct from `verified`, which is
// the live/indexable check on an ALREADY-published row. Drives the plan/approve UI:
// `needs_review` rows get an Approve/Reject action, everything else is read-only.
export type Web2PipelineStatus = "draft" | "needs_review" | "publishing" | "published" | "failed" | "rejected";

// --- Off-page KPIs -----------------------------------------------------------
export type OffpageKpis = {
  referringDomains: number;
  newLinks30d: number;
  lostLinks30d: number;
  toxicFlagged: number;
};

// --- 7B-4: business profiles (canonical NAP) --------------------------------
export type BusinessMarket = "US" | "UK" | "CA" | "AU" | "GLOBAL";

export type BusinessProfile = {
  id: string;
  client: string;
  label: string;
  businessName: string;
  addressLine1: string;
  addressLine2: string;
  city: string;
  region: string;
  postalCode: string;
  market: BusinessMarket;
  phone: string;
  websiteUrl: string;
  categories: string[];
  hours: Record<string, string>;
  isPrimary: boolean;
};

export type BusinessProfileInput = {
  clientId: string;
  label?: string;
  businessName: string;
  addressLine1?: string;
  addressLine2?: string;
  city?: string;
  region?: string;
  postalCode?: string;
  market?: BusinessMarket;
  phone?: string;
  websiteUrl?: string;
  categories?: string[];
  hours?: Record<string, string>;
  isPrimary?: boolean;
};

// --- 7B-4: the directory catalog (reference data) ---------------------------
export type DirectoryTier = "aggregator" | "api" | "bot_fillable" | "captcha_assisted" | "manual_only";
export type LinkRel = "dofollow" | "nofollow" | "mixed" | "unknown";

export const TIER_META: Record<DirectoryTier, { label: string; cls: string }> = {
  aggregator: { label: "Aggregator", cls: "info" },
  api: { label: "Direct API", cls: "ok" },
  bot_fillable: { label: "Bot-fillable", cls: "ok" },
  captcha_assisted: { label: "CAPTCHA-assisted", cls: "warn" },
  manual_only: { label: "Manual only", cls: "mut" },
};

// A campaign may target these four tiers; manual_only never queues (no worker path).
export const AUTOMATABLE_TIERS: DirectoryTier[] = ["aggregator", "api", "bot_fillable", "captcha_assisted"];

export type Directory = {
  id: string;
  name: string;
  url: string;
  market: BusinessMarket;
  tier: DirectoryTier;
  submitMethod: string;
  linkRel: LinkRel;
  priceNote: string;
  automationNote: string;
  active: boolean;
};

// --- 7B-4: campaign dispatch -------------------------------------------------
export type CitationCampaignInput = {
  clientId: string;
  businessProfileId: string;
  markets?: BusinessMarket[];
  tiers?: DirectoryTier[];
  // Strategy knobs (0048/P1): match the client's vertical, bound the batch, drop the
  // sub-DA spam tail, and opt into lead-gen marketplaces. All optional — the backend
  // applies reference-plan defaults (vertical from the client's industry, cap ~45,
  // min DA 30, marketplaces excluded).
  vertical?: string;
  cap?: number;
  minAuthority?: number;
  includeMarketplaces?: boolean;
};

export type CitationCampaignResult = {
  queued: number;
  alreadyQueued: number;
  skippedManualOnly: number;
  estimatedCost: number;
  citationIds: string[];
  // Strategy transparency (never a silent cap): what the selection resolved + excluded.
  resolvedVertical?: string | null;
  excludedOffVertical?: number;
  excludedLowAuthority?: number;
  excludedMarketplace?: number;
  capped?: number;
};
