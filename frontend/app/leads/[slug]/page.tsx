import type { Metadata } from "next";
import PublicAuditPage from "@/components/public-audit/PublicAuditPage";
import "../../freeaudit.css";   // .fa-cta (the shared button)
import "../../publicaudit.css"; // the full-width report layout

// The readable public audit page: /leads/<brand>.
//
// This is the page the platform never had. A free audit's report existed only in
// the React state of the landing-page flow — refreshing lost it — and a paid audit
// had no public address at all. Both are now addressed by a slug that is minted
// when the run completes (db/migrations/0126), and both render the SAME consulting
// report, so the free page can no longer look empty next to the paid one.
//
// Standalone, outside every app shell (like /login and the free-audit landing) —
// a prospect opening this link is not signed in and must not meet app chrome.

type Params = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { slug } = await params;
  // The brand is the slug minus a paid page's random suffix; good enough for a
  // title without a round trip, and the page itself shows the verified value.
  const brand = slug.replace(/-[0-9a-f]{8}$/, "");
  const pretty = brand.charAt(0).toUpperCase() + brand.slice(1);
  return {
    title: `${pretty} · SEO Audit Report`,
    description: `The full SEO audit report for ${pretty} — technical health, on-page findings, and a prioritised plan.`,
    // A shared report is meant to be opened by a person, not indexed: the URL is
    // readable by design, so search engines must not turn that into a directory
    // of every client we have audited.
    robots: { index: false, follow: false },
  };
}

export default async function LeadReportPage({ params }: Params) {
  const { slug } = await params;
  return <PublicAuditPage slug={slug} />;
}
