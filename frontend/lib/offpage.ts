// ============================================================
// AIOS · Off-page module types — Module 03 (Backlinks, Citations
// & Web 2.0). Paid tier; every Web 2.0 placement is human-
// approved, never link spam. Backlink signals originate from
// DataForSEO (new/lost alerts); Web 2.0 posts publish through
// official platform APIs; citations SUBMIT via the legitimate
// direct APIs (Data Axle / Apple) or the operator queue — the
// Playwright form bot is retired (Phase 3); earned directory
// specs power extension AUTOFILL, a person always submits.
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
  // ready_for_human: an operator's queue item. TWO paths reach it, and since 2026-08-30
  // the second is by far the common one:
  //   1. the bot created the account and prepared the listing, and a human finishes it
  //      from the operator queue (the original 0064 handoff, column dropped in 0121);
  //   2. the machine could not act at all - no engine, or no EARNED form spec - so the
  //      row becomes human work instead of parking in `blocked`. With zero active specs
  //      in the catalogue this is nearly every bot-tier directory, and it is what gives
  //      the operator queue and the browser extension anything to read.
  // `blocked` now means the opposite: nobody should act (terms prohibit it, an aggregator
  // already feeds it, there is no NAP, or a lead must approve an unpriced spend).
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

// 0129: how much a DISCOVERY verdict is actually worth. "" = a pre-tier row;
// confirmed = fetched w/ NAP match OR >=2 independent sources corroborated it;
// inconsistent_nap = the listing exists but its NAP drifted; uncertain = a hit exists
// but nothing fetched/corroborated it (verify first); no_evidence = zero hits across
// ALL sources — a *candidate* gap, because absence of evidence is never proof.
export type CitationEvidenceLevel =
  | "" | "confirmed" | "inconsistent_nap" | "uncertain" | "no_evidence";

export const EVIDENCE_LEVEL_META: Record<CitationEvidenceLevel, { label: string; cls: string }> = {
  "": { label: "Not judged", cls: "mut" },
  confirmed: { label: "Confirmed", cls: "ok" },
  inconsistent_nap: { label: "NAP drifted", cls: "warn" },
  uncertain: { label: "Verify first", cls: "info" },
  no_evidence: { label: "No evidence found", cls: "mut" },
};

export type Citation = {
  id: string;
  client: string;
  directory: string;
  nap: NapStatus;
  action: CitationAction;
  note: string; // what drifted / listing detail
  submitStatus: CitationSubmitStatus;
  // The API path of the proof reader (GET .../citations/{id}/proof), blank if none.
  // It used to carry the raw storage KEY, which rendered as a link that 404'd forever.
  proofUrl: string;
  // The public listing URL — set only after a fetch-verified completion. THE deliverable.
  liveUrl: string;
  // 0129: the URL discovery FOUND. Never a claim of liveness — only the liveness probe
  // promotes it into liveUrl (verification_method = "discovery").
  discoveredUrl: string;
  // 0129: the evidence tier behind the discovery verdict.
  evidenceLevel: CitationEvidenceLevel;
  // Machine-readable hold reason ("" unless on hold) → sentence via lib/citationStatus.ts.
  blockedReason: string;
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

/** Which lane publishes a placement (0135/0136): `api` = the publish worker,
 *  `extension` = an operator places it in their own logged-in session (a row parked
 *  at `publishing` with this value is waiting for a placement session, not a
 *  worker), `manual` = placed by hand with the evidence URL recorded. */
export type Web2PublishMethod = "api" | "extension" | "manual";

export type Web2Property = {
  id: string;
  client: string;
  platform: Web2Platform;
  postUrl: string;
  anchor: string;
  verified: Web2Verified;
  published: string;
  status: Web2PipelineStatus;
  publishMethod: Web2PublishMethod;
};

// --- Web 2.0 campaigns + the per-client platform board -------------------------

/**
 * One row of the five-state platform board.
 *
 * `not_connected` and `not_eligible` are deliberately different states: the first is a
 * missing credential an operator can go and fix, the second is a judgement about this
 * client that no credential changes. Collapsing them into one "unavailable" would send
 * someone hunting for a token that could not help. `not_reviewed` (nobody has read the
 * platform's terms yet — a safe default, not a verdict) and `not_supported` (no
 * publisher code) are split out of `not_eligible` for the same honesty reason.
 */
/** What `POST /offpage/web2/anchor-check` accepts — an anchor can be checked before a
 *  platform or any proof has been decided. */
export type Web2AnchorCheckInput = {
  clientId: string;
  anchor: string;
  targetUrl?: string;
  topic?: string;
};

/** The anchor verdict, shaped so a form field can render it directly. */
export type Web2AnchorCheck = {
  allowed: boolean;
  verdict: string;
  reason: string;
  suggestion: string;
};

export type Web2PlatformStatusRow = {
  name: string;
  platform: string | null;
  // eligible_extension (0135): the extension-assisted lane's own state — the platform
  // is real and usable, but an OPERATOR publishes there in their own logged-in session
  // (Phase 7 placement sessions). Kept separate from `eligible` so it is never offered
  // as an API campaign target, and so placement routing can key off it.
  status:
    | "eligible"
    | "eligible_extension"
    | "not_connected"
    | "not_eligible"
    | "not_reviewed"
    | "not_supported";
  reason: string;
  authorityTier: string;
  /** ISO date the platform's terms were last read ("" = never) and the source read. */
  termsCheckedOn?: string;
  termsSourceUrl?: string;
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

// --- 0135: the capability matrix -------------------------------------------
// BY WHAT MECHANISM a placement happens on a platform. "" = a catalogue row the
// matrix has not classified yet (the DB default for future inserts).
export type Web2Mechanism = "" | "api" | "extension" | "human" | "unsupported";

export const MECHANISM_META: Record<Web2Mechanism, { label: string; cls: string }> = {
  "": { label: "Unclassified", cls: "mut" },
  api: { label: "API", cls: "ok" },
  extension: { label: "Extension-assisted", cls: "info" },
  human: { label: "Human", cls: "mut" },
  unsupported: { label: "Do not use", cls: "warn" },
};

/** One catalogue row (mirrors `Web2PlatformCatalogResponse` 1:1).
 *
 *  `linkVerifiable` / `mediaSupport` are TRI-state: `null` means "not assessed",
 *  which must render as unmeasured — never as a false. `lastTestedAt` is "" until a
 *  real credential/publish check has passed (0135 seeds nothing, honestly). */
export type Web2CatalogPlatform = {
  id: string;
  name: string;
  homepageUrl: string;
  signupUrl: string;
  publishMethod: string;
  authType: string;
  authorityTier: string;
  market: string;
  automationReady: boolean;
  notes: string;
  mechanism: Web2Mechanism;
  lastTestedAt: string;
  adapterStatus: string;
  linkVerifiable: boolean | null;
  mediaSupport: boolean | null;
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
  /** 0135: rows per capability-matrix lane — the honest headline next to
   *  `automationReady` (adapters that exist vs what each lane can be used for). */
  byMechanism: Record<string, number>;
  platforms: Web2CatalogPlatform[];
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

/** The DRAFTED ARTICLE, for the review step of the write flow.
 *
 *  `blocks` is the paste-ready text - the same extraction the extension's placement
 *  lane uses, so the reviewer reads exactly what an operator would paste. `needs` are
 *  the writer's own unfilled grounding gaps: a draft carrying them looks publishable
 *  and is not. `lane` says which route approval takes by default. */
export type Web2Draft = {
  id: string;
  platform: string;
  status: string;
  reason: string;
  blocks: { key: string; label: string; value: string }[];
  needs: string[];
  lane: string;
};

export type Web2CampaignInput = {
  clientId: string;
  title?: string;
  articleCount: number;
  /** ONE DISTINCT TOPIC PER ARTICLE. The server refuses a campaign that reuses a topic:
   *  one topic across N platforms produces N identical articles. */
  topics: string[];
  /** OPTIONAL since 2026-09-12. Omitted, the server spreads the campaign across the
   *  platforms actually open for this client - best authority first, API lane before
   *  extension lane, one article per platform (the footprint diversification a campaign
   *  exists for). Eligibility is per client and moves as accounts are connected, which
   *  is why choosing by hand from a grid of ninety went wrong. */
  platforms?: string[];
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
  // Audit-first "build only these": explicit missing-directory ids from the approval
  // list. Bypasses the cap/authority filters — an explicit choice is not second-guessed.
  directoryIds?: string[];
};

export type CitationCampaignResult = {
  // The campaign's durable id (0120) — what the Track board polls.
  campaignId: string;
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

// 0129: one DISCOVERED listing whose evidence is `uncertain` — a hit exists but
// nothing fetched or corroborated it. Deduped from `missing` (never rebuilt while
// unverified) yet NOT counted covered: the operator verifies it first.
export type CitationVerifyFirst = {
  directory: string;
  url: string;
  evidenceLevel: CitationEvidenceLevel;
};

export type CitationGap = {
  client: string;
  hasNap: boolean;
  napSource: NapSource;
  businessProfileId: string | null;
  resolvedVertical: string | null;
  existingCount: number;
  coveredCount: number;
  // In-flight (queued/submitting, fresh) dedupes from missing but is NOT covered;
  // stale in-flight rows are listed in `stuck` by directory — the no-worker signal.
  inFlightCount: number;
  stuck: { directory: string; status: string }[];
  missingCount: number;
  missing: Directory[];
  liveUrls: CitationLiveUrl[];
  // 0129: `uncertain` discoveries to verify before building — neither covered nor a gap.
  verifyFirst: CitationVerifyFirst[];
  skipped: CitationSkip[];
  bySubmitStatus: Record<string, number>;
  byNapStatus: Record<string, number>;
  // 0129: tier tallies over rows that HAVE a tier (pre-tier "" rows are not counted).
  byEvidenceLevel: Record<string, number>;
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
// in_flight = an attempt is pending (deduped, not built); stuck = it sat unmoved
// past the staleness threshold; verify_first = an `uncertain` discovery hit awaiting
// verification (0129). None of these may ever render as "built" (2026-09-01).
export type AuditPlanStatus = "built" | "missing" | "in_flight" | "stuck" | "verify_first";

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

// (AUDIT_PLAN_BUCKETS lived here until its last importer left in 8a24228 — the
// workspace now shows three build-order counts instead of the bucket dump. The
// backend truth-guard sweep flags unreferenced seed arrays, so it was removed.)

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
  // The binding constraint, first: how many directories a machine may submit to today
  // (= active earned specs). Engines below are transport.
  machineSubmittableDirectories: number;
  whitelistNote: string;
  connectedCount: number;
  totalCount: number;
  engines: CitationEngineStatus[];
};

// --- the earned whitelist (0108/0110): specs, and what each has earned ---------
// A directory becomes machine-submittable ONLY here: a dated human DOM check
// (verify) + one submission that produced a public listing URL (first-live) =
// activate. The queue's "teach the bot" flow files these.

export type DirectorySpec = {
  id: string;
  directoryId: string;
  directoryName: string;
  url: string;
  fieldCount: number;
  active: boolean;
  verified: boolean;
  verifiedAt: string | null;
  hasFirstLiveUrl: boolean;
  firstLiveUrl: string;
  successCount: number;
  failureCount: number;
  drifted: boolean;
  driftSelector: string;
  deactivatedReason: string;
  /** What still has to happen before this spec may run. Empty when active. */
  blocking: string[];
};

export type SpecBoard = {
  active: number;
  verifiedNotLive: number;
  unverified: number;
  drifted: number;
  specs: DirectorySpec[];
};

export type SpecFieldInput = { selector: string; valueKey: string };

export type SpecCreateInput = {
  directoryId: string;
  url: string;
  fields: SpecFieldInput[];
  submitSelector: string;
  successIndicator?: string;
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
  /** The catalog row this item builds — what "teach the bot" files a spec against. */
  directoryId: string;
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

// --- operator sessions (0130) -------------------------------------------------
// Batch-based citation building through the extension: one operator, one client,
// batches of up to 25; the next batch releases server-side when the last task of the
// current one goes terminal. `uiState` is TELEMETRY with zero authority — evidence
// stays on the citation row (`live`/`drifted`/... via the probe path).
// These shapes mirror app/modules/citations/schemas.py's session models 1:1 and are
// server-authoritative until the contract lock covers them (the module's existing
// convention for a new surface) — move them together with any backend key change.

export type OperatorSessionStatus = "active" | "paused" | "completed" | "abandoned";

export type SessionTaskState =
  | "pending"
  | "released"
  | "opened"
  | "form_detected"
  | "filled"
  | "awaiting_submit"
  | "submitted"
  | "skipped"
  | "deferred"
  | "blocked";

export const SESSION_TASK_STATE_META: Record<SessionTaskState, { label: string; cls: string }> = {
  pending: { label: "Waiting", cls: "mut" },
  released: { label: "Ready", cls: "info" },
  opened: { label: "Tab open", cls: "info" },
  form_detected: { label: "Form found", cls: "info" },
  filled: { label: "Filled", cls: "info" },
  awaiting_submit: { label: "Review & submit", cls: "warn" },
  submitted: { label: "Submitted", cls: "ok" },
  skipped: { label: "Skipped", cls: "mut" },
  deferred: { label: "Deferred", cls: "mut" },
  blocked: { label: "Blocked", cls: "warn" },
};

export type SessionTaskCard = {
  taskId: string;
  citationId: string;
  batchNo: number;
  position: number;
  uiState: SessionTaskState;
  directory: string;
  directoryId: string;
  directoryUrl: string;
  addUrl: string;
  /** Fail-closed: false whenever no ACTIVE earned spec exists — the extension then
   *  offers click-to-copy, never a fabricated Fill. */
  hasSpec: boolean;
  fields: QueueFieldValue[];
  queuedBecause: string;
  prohibitedWarning: string;
  /** The catalogue's cost note (e.g. "Free", "Free; paid upsells") so an operator
   *  sees whether submission costs money before working the directory. */
  priceNote: string;
};

export type OperatorSession = {
  id: string;
  client: string;
  clientId: string;
  status: OperatorSessionStatus;
  kind: "citation" | "web2_placement";
  batchSize: number;
  currentBatch: number;
  totalBatches: number;
  taskCount: number;
  byUiState: Record<string, number>;
  createdAt: string;
  updatedAt: string;
  closedAt: string | null;
};

/** One paste-ready value from an approved web2 draft (0136). Copy-blocks are the
 *  placement lane's default and its fail-closed fallback. */
export type Web2CopyBlock = {
  key: string;
  label: string;
  value: string;
};

/** One web2_placement task (0136): the approved draft as copy-blocks, where the
 *  editor lives, and - only under an ACTIVE earned placement spec - selector fill
 *  fields. `hasSpec` is fail-closed exactly like the citation card's. */
export type Web2PlacementTaskCard = {
  taskId: string;
  web2Id: string;
  batchNo: number;
  position: number;
  uiState: SessionTaskState;
  platform: string;
  title: string;
  /** Spec editor_url when an active spec exists (host-pinned server-side), else the
   *  platform homepage, else "" - shown honestly as "no URL on file". */
  editorUrl: string;
  anchor: string;
  targetUrl: string;
  hasSpec: boolean;
  copyBlocks: Web2CopyBlock[];
  fields: QueueFieldValue[];
};

/** Kind-split task lists: a citation session fills `tasks`, a web2_placement
 *  session fills `web2Tasks` - the shapes differ and a union would make every
 *  consumer guess. */
export type OperatorSessionDetail = OperatorSession & {
  tasks: SessionTaskCard[];
  web2Tasks: Web2PlacementTaskCard[];
};
