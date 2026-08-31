// ============================================================
// AIOS · what kind of page am I making — asked ONCE
//
// The content flow used to ask this question three times, in three different
// vocabularies, with different members each time:
//
//   step 1  "Content type"  — 6 options, including "Service × Location"
//   step 2  "Template"      — 7 options, with no such entry
//   the board "page type"   — 4 options, so the finished job read "Service"
//
// An operator picked a thing on the first screen that did not exist on the
// second and was not what the third reported. Plus a fourth axis (the
// copywriting framework) layered on top. That is the single biggest reason the
// flow read as incoherent.
//
// They are not, however, one thing wearing three hats. They are three real
// concerns: what the operator wants, which layout blueprint builds it, and which
// value the backend's enum stores. So the operator chooses ONCE, here, and the
// other two are DERIVED - which is what stops them drifting apart again.
// ============================================================

import type { PageTemplate, PageType, ResearchContentType } from "@/lib/content";

export type PageKindKey =
  | "service" | "service_location" | "service_area" | "location" | "blog" | "faq";

export type PageKind = {
  key: PageKindKey;
  /** What the operator sees. Written as the thing being made, not a category. */
  label: string;
  /** When to reach for it, in the operator's terms. */
  bestFor: string;
  icon: string;
  /** DERIVED: what the recommender researches for. */
  research: ResearchContentType;
  /** DERIVED: the layout blueprint the page is built to. */
  template: PageTemplate;
  /** DERIVED: the backend's coarser stored enum (content_jobs.page_type). */
  pageType: PageType;
};

export const PAGE_KINDS: PageKind[] = [
  {
    key: "service", label: "Service page", icon: "home_repair_service",
    bestFor: "One service you sell — what it covers, how it works, proof, pricing, FAQ.",
    research: "service", template: "service", pageType: "service",
  },
  {
    key: "service_location", label: "Service in a city", icon: "location_city",
    bestFor: "The same service, targeted at one city or suburb. The bulk local play.",
    research: "service_location", template: "location", pageType: "local",
  },
  {
    key: "service_area", label: "Service across an area", icon: "map",
    bestFor: "One service over a region you cover — named areas and local proof.",
    research: "service_area", template: "service_area", pageType: "local",
  },
  {
    key: "location", label: "Location page", icon: "storefront",
    bestFor: "A physical premises — address, hours, directions, reviews, map.",
    research: "location", template: "location", pageType: "local",
  },
  {
    key: "blog", label: "Blog article", icon: "article",
    bestFor: "An informational post that answers a question and earns links.",
    research: "blog", template: "blog", pageType: "blog",
  },
  {
    key: "faq", label: "FAQ page", icon: "quiz",
    bestFor: "A question hub — the questions people actually ask, answered plainly.",
    research: "faq", template: "faq", pageType: "blog",
  },
];

export const pageKind = (key: string): PageKind =>
  PAGE_KINDS.find((k) => k.key === key) ?? PAGE_KINDS[0];

/** The operator-facing name for a job the backend stored as a coarse page_type.
 *  Several kinds collapse onto one stored value, so this names the STORED thing
 *  honestly rather than guessing which kind produced it. */
export const storedTypeLabel = (pageType: PageType): string =>
  ({ service: "Service", blog: "Blog", local: "Local", gbp_post: "GMB post" })[pageType] ??
  pageType;
