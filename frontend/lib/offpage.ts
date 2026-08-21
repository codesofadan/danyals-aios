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
  | "not_started" | "queued" | "submitting" | "submitted" | "verified" | "failed" | "blocked"
  // ready_for_human: the bot created the account + prepared the listing - a human
  // finishes with one click in the browser at handoffUrl.
  | "ready_for_human";

export const SUBMIT_STATUS_META: Record<CitationSubmitStatus, { label: string; cls: string }> = {
  not_started: { label: "Not started", cls: "mut" },
  queued: { label: "Queued", cls: "info" },
  submitting: { label: "Submitting", cls: "info" },
  submitted: { label: "Submitted", cls: "ok" },
  verified: { label: "Verified", cls: "ok" },
  failed: { label: "Failed", cls: "op-crit" },
  blocked: { label: "Blocked", cls: "warn" },
  ready_for_human: { label: "Ready to finish", cls: "info" },
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
  handoffUrl: string; // ready_for_human: the page a human opens to finish the listing
};

// --- Web 2.0 automation -----------------------------------------------------
// Branded article → published via official platform API → link verified live.
// 7B-4: grew from 4 to 17 platforms — every one the reference plan tags API-post:
// Yes, not deprecated, and not a blockchain/brand-risk case (see
// integrations/web2_publishers.py's module docstring for what was deliberately left
// out and why). Medium stays draft-only (its publish API is retired). Grew again to
// 21 with Webflow / HubSpot CMS / Drupal / Joomla (real CMS/site-builder adapters),
// then to 40 with a third pass (pastes/gists/static-hosts, ATProto/fediverse, and
// Disqus/Gravatar as honest thin profile placements). Evernote, Issuu, and Nostr
// long-form were investigated and deliberately skipped — see the backend module
// docstring + the batch3 migration header for the historical record. Grew again
// to 50 with a fourth pass (research repositories, a static-host + a Gitea-based
// pages host, two legacy AtomPub/metaWeblog blog hosts, and Farcaster/Warpcast) —
// CodeSandbox, GitBook, Read the Docs, Hive, and Steemit were investigated and
// deliberately skipped this pass too — see the backend module docstring + the
// batch4 migration header for the historical record.
export type Web2Platform =
  | "WordPress.com" | "Blogger" | "Tumblr" | "Medium"
  | "dev.to" | "Write.as" | "Telegra.ph" | "Mataroa" | "Ghost" | "Mastodon"
  | "GitHub Pages" | "GitLab Pages" | "Micro.blog" | "Hashnode" | "Hatena Blog"
  | "LiveJournal" | "Dreamwidth"
  | "Webflow" | "HubSpot CMS" | "Drupal" | "Joomla"
  | "HackMD" | "GitHub Gist" | "GitLab Snippets" | "paste.ee" | "Pastebin.com"
  | "Netlify" | "Neocities" | "rentry.co" | "dpaste.org"
  | "Misskey" | "Lemmy" | "Bluesky" | "WhiteWind"
  | "Disqus" | "Plurk" | "Pixelfed" | "Notion" | "Gravatar" | "Minds"
  | "Zenodo" | "Internet Archive" | "OSF" | "Figshare" | "Codeberg Pages"
  | "Livedoor Blog" | "FC2 Blog" | "Seesaa Blog" | "Warpcast" | "Sourcehut Pages";
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
  Webflow: { icon: "web_stories", c: SERIES.c2 },
  "HubSpot CMS": { icon: "hub", c: SERIES.c3 },
  Drupal: { icon: "water_drop", c: SERIES.c4 },
  Joomla: { icon: "widgets", c: SERIES.c1 },
  HackMD: { icon: "description", c: SERIES.c2 },
  "GitHub Gist": { icon: "code", c: SERIES.c3 },
  "GitLab Snippets": { icon: "code", c: SERIES.c4 },
  "paste.ee": { icon: "content_paste", c: SERIES.c1 },
  "Pastebin.com": { icon: "content_paste", c: SERIES.c2 },
  Netlify: { icon: "cloud", c: SERIES.c3 },
  Neocities: { icon: "public", c: SERIES.c4 },
  "rentry.co": { icon: "edit_note", c: SERIES.c1 },
  "dpaste.org": { icon: "content_paste", c: SERIES.c2 },
  Misskey: { icon: "alternate_email", c: SERIES.c3 },
  Lemmy: { icon: "forum", c: SERIES.c4 },
  Bluesky: { icon: "cloud", c: SERIES.c1 },
  WhiteWind: { icon: "history_edu", c: SERIES.c2 },
  Disqus: { icon: "chat_bubble", c: SERIES.c3 },
  Plurk: { icon: "alternate_email", c: SERIES.c4 },
  Pixelfed: { icon: "image", c: SERIES.c1 },
  Notion: { icon: "description", c: SERIES.c2 },
  Gravatar: { icon: "face", c: SERIES.c3 },
  Minds: { icon: "hub", c: SERIES.c4 },
  Zenodo: { icon: "science", c: SERIES.c1 },
  "Internet Archive": { icon: "archive", c: SERIES.c2 },
  OSF: { icon: "science", c: SERIES.c3 },
  Figshare: { icon: "bar_chart", c: SERIES.c4 },
  "Codeberg Pages": { icon: "hub", c: SERIES.c1 },
  "Livedoor Blog": { icon: "public", c: SERIES.c2 },
  "FC2 Blog": { icon: "rss_feed", c: SERIES.c3 },
  "Seesaa Blog": { icon: "rss_feed", c: SERIES.c4 },
  Warpcast: { icon: "alternate_email", c: SERIES.c1 },
  "Sourcehut Pages": { icon: "web_stories", c: SERIES.c2 },
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
  // Richer identity beyond NAP (0060) — what a real directory form also asks for.
  description: string;
  email: string;
  logoUrl: string;
  facebookUrl: string;
  instagramUrl: string;
  linkedinUrl: string;
  yearFounded: number | null;
  paymentTypes: string[];
  tagline: string;
  serviceArea: string;
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
  // Richer identity beyond NAP (0060). All optional (camelCase = the server aliases).
  description?: string;
  email?: string;
  logoUrl?: string;
  facebookUrl?: string;
  instagramUrl?: string;
  linkedinUrl?: string;
  yearFounded?: number | null;
  paymentTypes?: string[];
  tagline?: string;
  serviceArea?: string;
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

// --- Wave 4: gap analysis ----------------------------------------------------
// Where the NAP a campaign submits against came from: an existing submission
// profile, DERIVED from the client's own NAP (0051), or none captured yet.
export type NapSource = "submission_profile" | "client_profile" | "none";

export type CitationLiveUrl = { directory: string; url: string; status: string };

export type CitationGap = {
  client: string;
  hasNap: boolean;
  napSource: NapSource;
  businessProfileId: string | null;
  resolvedVertical: string | null;
  existingCount: number;
  coveredCount: number;
  missingCount: number;
  missing: Directory[];
  liveUrls: CitationLiveUrl[];
  bySubmitStatus: Record<string, number>;
  byNapStatus: Record<string, number>;
};

// --- audit plan (generic → country → niche) ----------------------------------
// GET /citation-builder/clients/{id}/audit-plan — the geo/niche/generic citation
// audit, PRIORITIZED Generic → Country → Niche. Each directory is tagged built|missing
// (the same covering rule gap-analysis uses). Read-only, degrade-safe server-side.
export type AuditPlanStatus = "built" | "missing";

export type AuditPlanItem = {
  directoryName: string;
  market: BusinessMarket;
  tier: DirectoryTier;
  url: string;
  status: AuditPlanStatus;
};

export type AuditPlan = {
  client: string;
  resolvedVertical: string | null;
  market: BusinessMarket;
  generic: AuditPlanItem[];
  country: AuditPlanItem[];
  niche: AuditPlanItem[];
};

// The three prioritized buckets, in build order, for rendering.
export const AUDIT_PLAN_BUCKETS: { key: "generic" | "country" | "niche"; label: string; hint: string }[] = [
  { key: "generic", label: "Generic", hint: "Global core, aggregators & APIs every market builds first." },
  { key: "country", label: "Country", hint: "The client's own-market general directories." },
  { key: "niche", label: "Niche", hint: "Vertical-specific directories for the client's industry." },
];

// --- Wave 4: client business profile (NAP captured at creation) --------------
export type ClientBusinessProfile = {
  id: string;
  client: string;
  businessName: string;
  addressLine1: string;
  addressLine2: string;
  city: string;
  region: string;
  postalCode: string;
  market: BusinessMarket;
  phone: string;
  websiteUrl: string;
  primaryCategory: string;
  extraCategories: string[];
  hours: Record<string, string>;
  description: string;
};

export type ClientBusinessProfileInput = {
  businessName?: string;
  addressLine1?: string;
  addressLine2?: string;
  city?: string;
  region?: string;
  postalCode?: string;
  market?: BusinessMarket;
  phone?: string;
  websiteUrl?: string;
  primaryCategory?: string;
  extraCategories?: string[];
  hours?: Record<string, string>;
  description?: string;
};

// --- Wave 4: API status boards ----------------------------------------------
export type Web2PlatformStatus = {
  platform: string;
  connected: boolean;
  draftOnly: boolean;
  configuredCount: number;
  requiredFields: string[];
  vaultProvider: string;
  reason: string;
  externalNote: string;
};

export type Web2Status = {
  connectedCount: number;
  liveCount: number;
  totalCount: number;
  platforms: Web2PlatformStatus[];
};

export type CitationEngineStatus = {
  key: string;
  label: string;
  connected: boolean;
  reason: string;
  requiredConfig: string[];
  externalNote: string;
};

export type CitationEngineBoard = {
  connectedCount: number;
  totalCount: number;
  engines: CitationEngineStatus[];
};
