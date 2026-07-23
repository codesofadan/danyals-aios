// ============================================================
// AIOS · GMB (Google Business Profile) post types (Wave 5)
// Mirrors the backend GmbPostResponse / policy report shapes. Kept here (a new
// domain file, like lib/content.ts) rather than in the reserved data.ts.
// ============================================================

export type GmbPostType = "update" | "offer" | "event" | "product";
export type GmbCtaType = "book" | "order" | "shop" | "learn_more" | "sign_up" | "call" | "none";
export type GmbStatus = "draft" | "needs_review" | "approved" | "posted" | "rejected";

export type GmbPolicyIssue = {
  code: string;
  message: string;
  severity: "violation" | "warning";
};

export type GmbPolicy = {
  ok: boolean;
  charCount: number;
  violations: GmbPolicyIssue[];
  warnings: GmbPolicyIssue[];
};

export type GmbPost = {
  id: string; // public GMB-#### code
  client: string;
  color: string;
  topic: string;
  postType: GmbPostType;
  status: GmbStatus;
  title: string;
  body: string;
  ctaType: GmbCtaType;
  ctaUrl: string;
  charCount: number;
  policyOk: boolean;
  policy: GmbPolicy;
  cost: number;
  stage: string;
  ago: string;
};

export type GmbStats = {
  total: number;
  awaitingReview: number;
  approved: number;
  needsFix: number;
};

export type GmbPublishResult = {
  code: string;
  posted: boolean;
  url: string;
  message: string;
};

export const POST_TYPES: { key: GmbPostType; label: string }[] = [
  { key: "update", label: "What's new" },
  { key: "offer", label: "Offer" },
  { key: "event", label: "Event" },
  { key: "product", label: "Product" },
];

// CTA button labels + whether the button needs a destination URL (mirrors the
// backend CTA_NEEDS_URL - a phone call needs none).
export const CTA_TYPES: { key: GmbCtaType; label: string; needsUrl: boolean }[] = [
  { key: "learn_more", label: "Learn more", needsUrl: true },
  { key: "book", label: "Book", needsUrl: true },
  { key: "order", label: "Order online", needsUrl: true },
  { key: "shop", label: "Shop", needsUrl: true },
  { key: "sign_up", label: "Sign up", needsUrl: true },
  { key: "call", label: "Call now", needsUrl: false },
  { key: "none", label: "No button", needsUrl: false },
];

export const POST_TYPE_LABELS: Record<GmbPostType, string> = {
  update: "What's new", offer: "Offer", event: "Event", product: "Product",
};

export const GBP_MAX_CHARS = 1500;
export const GBP_RECOMMENDED_MAX = 300;

export function ctaNeedsUrl(cta: GmbCtaType): boolean {
  return CTA_TYPES.find((c) => c.key === cta)?.needsUrl ?? false;
}
