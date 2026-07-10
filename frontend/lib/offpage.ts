// ============================================================
// AIOS · Off-page module mock data — Module 03 (Backlinks,
// Citations & Web 2.0). Paid tier; every placement is human-
// approved, never link spam. Backlink signals originate from
// DataForSEO (new/lost alerts); Web 2.0 posts publish through
// the official platform APIs (WordPress.com / Blogger / Tumblr).
// Swap these arrays for FastAPI / Postgres queries when the
// backend is wired. Shapes mirror the §8 data model.
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

export const backlinks: Backlink[] = [
  { id: "bl-01", client: "NorthPeak Dental", refDomain: "healthgrades.com", anchor: "family dentist Bellevue", authority: 88, spam: 2, firstSeen: "Jul 08, 2026", status: "new" },
  { id: "bl-02", client: "Lumen Realty", refDomain: "realtor.com", anchor: "Lumen Realty listings", authority: 91, spam: 1, firstSeen: "Jul 07, 2026", status: "new" },
  { id: "bl-03", client: "Meridian Wealth", refDomain: "investopedia.com", anchor: "wealth management guide", authority: 93, spam: 3, firstSeen: "Jul 06, 2026", status: "new" },
  { id: "bl-04", client: "BrightHVAC", refDomain: "angi.com", anchor: "HVAC repair near me", authority: 82, spam: 4, firstSeen: "Jul 05, 2026", status: "new" },
  { id: "bl-05", client: "Verde Cafe", refDomain: "tripadvisor.com", anchor: "best brunch downtown", authority: 90, spam: 5, firstSeen: "Jul 04, 2026", status: "new" },
  { id: "bl-06", client: "Atlas Legal", refDomain: "justia.com", anchor: "corporate attorney", authority: 85, spam: 3, firstSeen: "Jul 02, 2026", status: "lost" },
  { id: "bl-07", client: "Coastline Fit", refDomain: "classpass.com", anchor: "coastal strength studio", authority: 79, spam: 6, firstSeen: "Jun 30, 2026", status: "lost" },
  { id: "bl-08", client: "Orchard Pediatrics", refDomain: "webmd.com", anchor: "pediatric care", authority: 92, spam: 2, firstSeen: "Jun 28, 2026", status: "lost" },
  { id: "bl-09", client: "NorthPeak Dental", refDomain: "cheap-seo-links.ru", anchor: "buy backlinks cheap", authority: 8, spam: 94, firstSeen: "Jun 26, 2026", status: "toxic" },
  { id: "bl-10", client: "Meridian Wealth", refDomain: "casino-payday-loans.biz", anchor: "fast cash loans", authority: 5, spam: 97, firstSeen: "Jun 24, 2026", status: "toxic" },
  { id: "bl-11", client: "BrightHVAC", refDomain: "link-farm-directory.net", anchor: "click here", authority: 11, spam: 88, firstSeen: "Jun 22, 2026", status: "toxic" },
  { id: "bl-12", client: "Lumen Realty", refDomain: "medium.com", anchor: "first-time buyer tips", authority: 95, spam: 4, firstSeen: "Jun 20, 2026", status: "new" },
  { id: "bl-13", client: "Coastline Fit", refDomain: "yelp.com", anchor: "Coastline Fit", authority: 89, spam: 3, firstSeen: "Jun 18, 2026", status: "new" },
  { id: "bl-14", client: "Atlas Legal", refDomain: "avvo.com", anchor: "business litigation", authority: 84, spam: 5, firstSeen: "Jun 16, 2026", status: "lost" },
];

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

export type Citation = {
  id: string;
  client: string;
  directory: string;
  nap: NapStatus;
  action: CitationAction;
  note: string; // what drifted / listing detail
};

export const citations: Citation[] = [
  { id: "ct-01", client: "NorthPeak Dental", directory: "Google Business", nap: "consistent", action: "Update", note: "Hours verified" },
  { id: "ct-02", client: "NorthPeak Dental", directory: "Yelp", nap: "inconsistent", action: "Update", note: "Suite # differs" },
  { id: "ct-03", client: "Lumen Realty", directory: "Bing Places", nap: "consistent", action: "Update", note: "Verified" },
  { id: "ct-04", client: "Lumen Realty", directory: "Apple Maps", nap: "missing", action: "Submit", note: "No listing yet" },
  { id: "ct-05", client: "Verde Cafe", directory: "Google Business", nap: "consistent", action: "Update", note: "Photos refreshed" },
  { id: "ct-06", client: "Verde Cafe", directory: "Yellow Pages", nap: "inconsistent", action: "Update", note: "Old phone number" },
  { id: "ct-07", client: "Atlas Legal", directory: "Yelp", nap: "missing", action: "Submit", note: "Category pending" },
  { id: "ct-08", client: "BrightHVAC", directory: "Google Business", nap: "consistent", action: "Update", note: "Service area set" },
  { id: "ct-09", client: "BrightHVAC", directory: "Apple Maps", nap: "inconsistent", action: "Update", note: "Address unit drift" },
  { id: "ct-10", client: "Coastline Fit", directory: "Bing Places", nap: "missing", action: "Submit", note: "Awaiting submit" },
  { id: "ct-11", client: "Meridian Wealth", directory: "Google Business", nap: "consistent", action: "Update", note: "Verified" },
  { id: "ct-12", client: "Orchard Pediatrics", directory: "Yellow Pages", nap: "missing", action: "Submit", note: "New account" },
];

// --- Web 2.0 automation -----------------------------------------------------
// Branded article → published via official platform API → link verified live.
export type Web2Platform = "WordPress.com" | "Blogger" | "Tumblr" | "Medium";
export type Web2Verified = "verified" | "pending";

export const PLATFORM_META: Record<Web2Platform, { icon: string; c: string }> = {
  "WordPress.com": { icon: "web", c: SERIES.c4 },
  Blogger: { icon: "rss_feed", c: SERIES.c3 },
  Tumblr: { icon: "tag", c: SERIES.c1 },
  Medium: { icon: "article", c: SERIES.c2 },
};

export type Web2Property = {
  id: string;
  client: string;
  platform: Web2Platform;
  postUrl: string;
  anchor: string;
  verified: Web2Verified;
  published: string;
};

export const web2Properties: Web2Property[] = [
  { id: "w2-01", client: "NorthPeak Dental", platform: "WordPress.com", postUrl: "northpeaksmiles.wordpress.com/gentle-cleanings", anchor: "gentle dental cleanings", verified: "verified", published: "Jul 06, 2026" },
  { id: "w2-02", client: "Lumen Realty", platform: "Medium", postUrl: "medium.com/@lumenrealty/2026-buyer-guide", anchor: "2026 home buyer guide", verified: "verified", published: "Jul 05, 2026" },
  { id: "w2-03", client: "Verde Cafe", platform: "Tumblr", postUrl: "verdecafe.tumblr.com/seasonal-menu", anchor: "seasonal brunch menu", verified: "pending", published: "Jul 04, 2026" },
  { id: "w2-04", client: "BrightHVAC", platform: "Blogger", postUrl: "brighthvac.blogspot.com/summer-tune-up", anchor: "summer AC tune-up", verified: "verified", published: "Jul 03, 2026" },
  { id: "w2-05", client: "Meridian Wealth", platform: "Medium", postUrl: "medium.com/@meridian/retirement-planning", anchor: "retirement planning basics", verified: "verified", published: "Jul 01, 2026" },
  { id: "w2-06", client: "Coastline Fit", platform: "WordPress.com", postUrl: "coastlinefit.wordpress.com/beginner-strength", anchor: "beginner strength program", verified: "pending", published: "Jun 29, 2026" },
  { id: "w2-07", client: "Atlas Legal", platform: "Blogger", postUrl: "atlaslegal.blogspot.com/contract-basics", anchor: "business contract basics", verified: "verified", published: "Jun 27, 2026" },
  { id: "w2-08", client: "Orchard Pediatrics", platform: "Tumblr", postUrl: "orchardpeds.tumblr.com/wellness-checks", anchor: "child wellness checks", verified: "pending", published: "Jun 25, 2026" },
];

// --- KPI summary ------------------------------------------------------------
// Referring-domain total is the live profile size; new/lost are the 30-day
// DataForSEO deltas; toxic is the disavow-review queue.
export const offpageKpis = {
  referringDomains: 1284,
  newLinks30d: 96,
  lostLinks30d: 23,
  toxicFlagged: backlinks.filter((b) => b.status === "toxic").length + 6, // queue incl. earlier flags
};
