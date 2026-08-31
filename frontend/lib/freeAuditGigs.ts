// Real Fiverr gigs shown on the public free-audit report page (below the score),
// as a "want hands-on help fixing this?" upsell. These are the agency's actual
// live gigs — not mock/placeholder data (see lib/upsells.ts for that, a separate
// module used by the client-portal Upsells admin screen).
//
// `image` is intentionally left unset until real gig thumbnail URLs are supplied —
// Fiverr blocks automated scraping (Cloudflare 403 on every fetch attempt), so we
// are NOT guessing/fabricating a CDN image URL here; a wrong guess would 404 or
// show the wrong gig's photo. The card renders a clean icon fallback until an
// `image` value is added per entry.
export type FreeAuditGig = {
  id: string;
  title: string;
  description: string;
  fiverrUrl: string;
  icon: string; // material symbol, used until `image` is set
  color: string;
  image?: string; // gig thumbnail URL — TODO: fill in once available
};

export const freeAuditGigs: FreeAuditGig[] = [
  {
    id: "fa-gig-gmb",
    title: "Optimize Your GMB Listing for Local SEO",
    description: "Full Google Business Profile setup and optimization to help your listing rank higher in the local map pack.",
    fiverrUrl: "https://www.fiverr.com/iamdaani/optimize-your-gmb-listing-for-local-seo?ref_ctx_id=4efcb67efe90483d9a5ebfd2230150fe&pckg_id=1&source=seller_page",
    icon: "storefront",
    color: "#1DBF73",
  },
  {
    id: "fa-gig-citations-145",
    title: "145 Directory Citations for USA, UK & Canada",
    description: "Accurate NAP citations across 145 top local directories in the US, UK and Canada to strengthen local rankings.",
    fiverrUrl: "https://www.fiverr.com/iamdaani/do-145-directory-citations-for-usa-uk-canada-local-seo-65552aba-0842-4857-8154-5f493507ca40?ref_ctx_id=4efcb67efe90483d9a5ebfd2230150fe&pckg_id=1&source=seller_page",
    icon: "location_on",
    color: "#7B69EE",
  },
  {
    id: "fa-gig-citations-350",
    title: "350 Map Citations for Google Local SEO",
    description: "350 map-based citations built to strengthen your map-pack visibility and local search presence.",
    fiverrUrl: "https://www.fiverr.com/iamdaani/do-350-map-citations-for-google-local-seo?ref_ctx_id=4efcb67efe90483d9a5ebfd2230150fe&pckg_id=1&source=seller_page",
    icon: "map",
    color: "#F5A623",
  },
];
