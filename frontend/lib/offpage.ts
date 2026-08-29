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
  | "ready_for_human"
  // 0106. `submitted` STOPS meaning done — every write path returns it honestly and none
  // can promise more, so only `live` means a listing exists.
  | "live"       // live_url was fetched and the business was found on the page
  | "drifted"    // the listing exists but its NAP drifted — correct it, don't rebuild
  | "delisted";  // it was live and now it is gone

export const SUBMIT_STATUS_META: Record<CitationSubmitStatus, { label: string; cls: string }> = {
  not_started: { label: "Not started", cls: "mut" },
  queued: { label: "Queued", cls: "info" },
  submitting: { label: "Submitting", cls: "info" },
  // "Sent", not "Submitted-and-done": nothing has confirmed a listing came back yet, so
  // this is deliberately NOT styled as a success.
  submitted: { label: "Sent — unconfirmed", cls: "info" },
  verified: { label: "Verified", cls: "ok" },
  failed: { label: "Failed", cls: "op-crit" },
  blocked: { label: "Blocked", cls: "warn" },
  ready_for_human: { label: "Ready to finish", cls: "info" },
  live: { label: "Live", cls: "ok" },
  drifted: { label: "Drifted — needs correcting", cls: "warn" },
  delisted: { label: "Delisted", cls: "op-crit" },
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
  | "Livedoor Blog" | "FC2 Blog" | "Seesaa Blog" | "Warpcast" | "Sourcehut Pages"
  | "Sanity" | "Storyblok" | "Hygraph" | "WriteFreely";
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
  Sanity: { icon: "dataset", c: SERIES.c3 },
  Storyblok: { icon: "widgets", c: SERIES.c4 },
  Hygraph: { icon: "dataset", c: SERIES.c1 },
  WriteFreely: { icon: "edit_note", c: SERIES.c2 },
};

// Every platform NOT draft-only can be planned/approved through the pipeline.
export const LIVE_WEB2_PLATFORMS: Web2Platform[] = (
  Object.keys(PLATFORM_META) as Web2Platform[]
).filter((p) => p !== "Medium");

// House account created, but the platform can't actually publish yet - a payment,
// business-verification, or app-review step outside our control is unresolved. The
// dashboard flags these with a small red asterisk rather than hiding them, so a lead
// knows to chase the underlying account issue rather than assume it's simply unbuilt.
export const PLATFORM_ISSUES: Partial<Record<Web2Platform, string>> = {
  Blogger: "Google OAuth consent not completed - only a client id/secret exist, no user token yet",
  Drupal: "No login on the target Drupal site yet (still a Tugboat QA preview, not a live host)",
  "Hatena Blog": "Hatena account created, but no blog id / AtomPub API key issued yet",
  "HubSpot CMS": "Private app token exists, but no target blog (content group) configured yet",
  Notion: "Integration created, but not yet shared with a parent page to publish under",
  Storyblok: "Management token exists, but no target space configured yet",
};

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

// --- Web 2.0 campaigns + the per-client platform board -------------------------

/**
 * One row of the three-state platform board.
 *
 * `not_connected` and `not_eligible` are deliberately different states: the first is a
 * missing credential an operator can go and fix, the second is a judgement about this
 * client that no credential changes. Collapsing them into one "unavailable" would send
 * someone hunting for a token that could not help.
 */
export type Web2PlatformStatusRow = {
  name: string;
  platform: string | null;
  status: "eligible" | "not_connected" | "not_eligible";
  reason: string;
  authorityTier: string;
  //: How to connect it, carried on the row that says it is not connected. A board that
  //: reports a gap without saying how to close it is a dead end wearing a call to action.
  setupUrl?: string;
  setupSteps?: string;
  setupCost?: string;
  setupBlocker?: string;
  accountNeeded?: string;
  credentialFields?: string[];
};

export type Web2CampaignStatus =
  | "draft" | "planning" | "needs_approval" | "scheduled"
  | "running" | "completed" | "degraded" | "cancelled";

export type Web2PacingMode = "immediate" | "drip";

/** One property a campaign approval refused to wave through, named so the operator can
 *  redraft that one rather than being told "something failed". */
/** A publishing account on the connection board.
 *
 *  `complete` means the sealed credential has every required field (a publisher can be
 *  built). `health` means a platform was actually ASKED and answered. They are different
 *  claims and the board shows both, because a structurally complete credential can still
 *  be revoked.
 */
export type Web2Account = {
  id: string;
  platform: string;
  ownership: string;
  client: string;
  handle: string;
  propertyUrl: string;
  email: string;
  health: string;
  checked: string;
  properties: number;
  maxProperties: number;
  required: string[];
  complete: boolean;
};

/** The catalogue rollup, including each platform's credential shape.
 *
 *  `credentialFields` is served rather than duplicated here on purpose: a hand-copied
 *  list drifts the first time a platform changes its auth, and the operator then fills
 *  fields that seal into a credential the publisher rejects. */
export type Web2Catalog = {
  total: number;
  automationReady: number;
  byAuthType: Record<string, number>;
  credentialFields: Record<string, string[]>;
};

/** What the operator supplies to register an account.
 *
 *  `credential` is field -> value for THIS platform's shape; `Web2Account.required`
 *  says which fields that is, so a new platform needs no frontend change. It is sealed
 *  server-side and never comes back. */
export type Web2AccountCreate = {
  platform: string;
  ownership: "per_client" | "house";
  clientId?: string;
  handle: string;
  email?: string;
  propertyUrl?: string;
  maxProperties?: number;
  credential: Record<string, string>;
};

/** The result of asking a platform whether a credential still works. */
export type Web2AccountCheck = {
  accountId: string;
  state: "ok" | "bad" | "unknown";
  detail: string;
  identity: string;
  health: string;
};

/** One Web 2.0 placement in full — the deliverable record.
 *
 *  `linkFound` / `linkRel` are the honest part: "published" only means the platform
 *  accepted the post. Whether OUR link is actually on the page, and whether it is
 *  followed, is a separate measured fact — reporting a placement as delivered without
 *  it is how an agency invoices for a link a platform quietly stripped.
 */
export type Web2Placement = {
  id: string;
  client: string;
  platform: string;
  topic: string;
  framework: string;
  anchor: string;
  targetUrl: string;
  postUrl: string;
  status: Web2PipelineStatus;
  verified: string;
  linkRel: string;
  linkFound: boolean | null;
  linkChecked: string;
  scheduledFor: string;
  published: string;
  created: string;
  account: string;
  accountOwnership: string;
  sharedOrigin: boolean;
  note: string;
};

export type Web2CampaignHold = {
  web2Id: string;
  topic: string;
  platform: string;
  reason: string;
};

/** What one campaign-level decision actually did. Approved / held / rejected are kept
 *  separate on purpose: an approval that published 27 of 30 and held 3 is not a clean
 *  approval, and collapsing it to "ok" is the partial-delivery-as-success defect. */
export type Web2CampaignApproval = {
  campaignId: string;
  status: Web2CampaignStatus;
  approved: number;
  held: Web2CampaignHold[];
  rejected: number;
};

export type Web2Campaign = {
  id: string;
  client: string;
  title: string;
  status: Web2CampaignStatus;
  articleCount: number;
  platforms: string[];
  pacing: Web2PacingMode;
  estimatedCostUsd: number;
  spentUsd: number;
  /** How many properties have actually gone live. */
  published: number;
  total: number;
  nextPublish: string;
};

export type Web2PlannedProperty = {
  platform: string;
  topic: string;
  anchor: string;
  framework: string;
  scheduledFor: string;
};

/** The pre-commit quote: what it would create, what it costs, when it finishes. */
export type Web2CampaignEstimate = {
  count: number;
  estimatedCostUsd: number;
  projectedCompletion: string;
  properties: Web2PlannedProperty[];
  /** Human-readable caveats: dropped platforms with reasons, cap notes, the timeline. */
  notes: string[];
};

export type Web2CampaignInput = {
  clientId: string;
  title?: string;
  articleCount: number;
  /** ONE DISTINCT TOPIC PER ARTICLE. The server refuses a campaign that reuses a topic:
   *  one topic across N platforms produces N identical articles. */
  topics: string[];
  platforms: string[];
  anchors: string[];
  targetUrl: string;
  pacing: Web2PacingMode;
  dripWindowDays?: number;
  costCeilingUsd?: number;
  proofPoints?: string[];
  //: The differentiation grounding. The generator gaps on this SEPARATELY from
  //: `proofPoints`, so a campaign that supplies only proof still holds at review.
  uniqueData?: string[];
  testimonials?: string[];
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
  skipped: CitationSkip[];
  bySubmitStatus: Record<string, number>;
  byNapStatus: Record<string, number>;
};

// One catalog directory NOT built for this client, and why. A required output: without
// it, a shorter-than-promised list is indistinguishable from a system that quietly
// failed. `clause` carries the exact terms text when `reason` is "prohibited_by_terms".
export type CitationSkip = {
  directory: string;
  reason: CitationSkipReason;
  detail: string;
  clause: string;
};

export type CitationSkipReason =
  | "prohibited_by_terms"
  | "fed_by_aggregator"
  | "not_automatable"
  | "off_vertical"
  | "marketplace_not_opted_in"
  | "below_authority_floor"
  | "over_campaign_cap";

// Mirrors SKIP_REASON_LABELS in backend/app/modules/citations/service.py. A reason code
// with no label reaches a client report as a raw enum string.
export const SKIP_REASON_LABEL: Record<CitationSkipReason, string> = {
  prohibited_by_terms: "the directory's terms forbid automated submission",
  fed_by_aggregator: "covered by an aggregator we already submit to — no separate listing",
  not_automatable: "no automated submission path; handled by a human",
  off_vertical: "serves industries this client is not in",
  marketplace_not_opted_in: "a paid lead-gen marketplace; not built without opt-in",
  below_authority_floor: "authority below the floor we build to",
  over_campaign_cap: "beyond this campaign's size cap; queued in a later one",
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

// --- the human work queue (0110) ---------------------------------------------
// Route C — a human working a directory by hand — is ~200 of the 226 catalogue rows and
// 56% of the loaded cost per live citation. The queue exists to make the minutes per item
// smaller and, for the first time, to measure them.

export type QueueFieldValue = {
  key: string;
  label: string;
  value: string;
};

export type QueueItem = {
  citationId: string;
  client: string;
  directory: string;
  directoryUrl: string;
  /** The verified deep link to the add-listing form. Empty when the catalogue has never
   *  had one probed — the UI must say so rather than render an empty link. */
  addUrl: string;
  fields: QueueFieldValue[];
  queuedBecause: string;
  claimExpiresAt: string | null;
  humanAttempts: number;
  workedSeconds: number;
  /** Non-empty only if a directory whose terms forbid automation somehow reached the
   *  queue. That should be impossible; if it happens the UI refuses to help. */
  prohibitedWarning: string;
};

export type QueueBoard = {
  waiting: number;
  inProgress: number;
  /** MEDIAN seconds per finished item. `null` until something has been finished — an
   *  unmeasured number must read as unmeasured, never as zero. */
  medianSeconds: number | null;
  mine: QueueItem[];
};

export type QueueCompleteResult = {
  accepted: boolean;
  submitStatus: string;
  liveUrl: string;
  reason: string;
  matchedFields: string[];
};

/** Why an item could not be finished. A closed vocabulary so the board can answer
 *  "which directories are wasting our time?" — which is what eventually removes one. */
export type QueueBlockReason =
  | "captcha_wall"
  | "account_required"
  | "paid_only"
  | "form_changed"
  | "duplicate_listing"
  | "directory_dead"
  | "phone_verification"
  | "postcard_verification"
  | "other";

export const QUEUE_BLOCK_LABEL: Record<QueueBlockReason, string> = {
  captcha_wall: "CAPTCHA I couldn't clear",
  account_required: "Needs an account we don't have",
  paid_only: "Paid listing only",
  form_changed: "The form isn't what we expected",
  duplicate_listing: "Already listed",
  directory_dead: "Directory is dead / not accepting",
  phone_verification: "Wants to phone the business",
  postcard_verification: "Wants to post a card to the business",
  other: "Something else (see note)",
};
