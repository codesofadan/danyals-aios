"use client";

import ReportViewer from "@/components/report/ReportViewer";
import { cleanDomain, scoreBand, VERDICT } from "@/lib/freeAudit";
import {
  fetchPublicPageReportHtml,
  publicPageReportPdfUrl,
  usePublicPage,
} from "@/lib/hooks/publicAudit";

// The shareable public audit report behind /leads/<slug>.
//
// One component serves BOTH kinds. That is the point: a free audit and a paid
// audit previously produced different documents from the same 176-finding
// artifact — the free page rendered the engine's condensed HTML (one table) while
// the paid page rendered the built consulting report (thirteen). They now resolve
// to the same file server-side, so this page does not branch on `kind` for
// anything except the label it prints.

function formatWhen(when: string | null): string {
  if (!when) return "";
  const d = new Date(when);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

export default function PublicAuditPage({ slug }: { slug: string }) {
  const q = usePublicPage(slug);

  if (q.isLoading) {
    return (
      <main className="fa-wrap">
        <div className="fa-card" style={{ textAlign: "center", padding: "64px 28px" }}>
          <span className="material-symbols-rounded" aria-hidden>hourglass_top</span>
          <p>Loading the report…</p>
        </div>
      </main>
    );
  }

  // A 404 here is the normal "wrong link" case, not an error state to apologise
  // for — an unpublished paid page returns 404 on purpose so the URL space says
  // nothing about which reports exist.
  if (q.isError || !q.data) {
    return (
      <main className="fa-wrap">
        <div className="fa-card" style={{ textAlign: "center", padding: "64px 28px" }}>
          <span className="material-symbols-rounded" aria-hidden>link_off</span>
          <h1 style={{ fontSize: 22, margin: "12px 0 6px" }}>This report isn’t available</h1>
          <p style={{ opacity: 0.75 }}>
            The link may have expired, or the report may not have been shared yet.
          </p>
          <a className="fa-cta" href="/" style={{ marginTop: 18, display: "inline-block" }}>
            Run a free audit
          </a>
        </div>
      </main>
    );
  }

  const page = q.data;
  const domain = cleanDomain(page.url);
  const verdict = page.score != null ? VERDICT[scoreBand(page.score)] : null;
  const when = formatWhen(page.when);

  return (
    <main className="fa-wrap">
      <header className="fa-card" style={{ display: "grid", gap: 14, padding: "26px 28px" }}>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "baseline" }}>
          <h1 style={{ fontSize: 26, margin: 0, letterSpacing: "-0.02em" }}>
            SEO audit — {domain}
          </h1>
          <span style={{ fontSize: 13, opacity: 0.7 }}>
            {page.kind === "paid" ? "Full audit" : "Free audit"}
            {when ? ` · ${when}` : ""}
          </span>
        </div>

        {page.score != null && (
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <strong style={{ fontSize: 46, lineHeight: 1, letterSpacing: "-0.03em" }}>
              {page.score}
            </strong>
            <span style={{ fontSize: 15, opacity: 0.7 }}>/ 100</span>
            
          </div>
        )}

        {verdict && <p style={{ margin: 0, opacity: 0.8, maxWidth: "62ch" }}>{verdict}</p>}

        {page.has_pdf && (
          <div>
            <a className="fa-cta" href={publicPageReportPdfUrl(page.slug)} download>
              Download the PDF report
            </a>
          </div>
        )}
      </header>

      {page.has_report ? (
        <div className="fa-card" style={{ padding: 0, overflow: "hidden" }}>
          <ReportViewer
            label={domain}
            load={() => fetchPublicPageReportHtml(page.slug)}
            reloadKey={page.slug}
            pdfHref={page.has_pdf ? publicPageReportPdfUrl(page.slug) : undefined}
          />
        </div>
      ) : (
        <div className="fa-card" style={{ padding: "28px" }}>
          <p style={{ margin: 0, opacity: 0.8 }}>
            The full report for this audit isn’t on file. The score above is still accurate.
          </p>
        </div>
      )}

      {page.fiverr_url && (
        <footer className="fa-card" style={{ padding: "22px 28px" }}>
          <p style={{ margin: "0 0 10px" }}>Want a hand fixing what this audit surfaced?</p>
          <a className="fa-cta" href={page.fiverr_url} target="_blank" rel="noopener noreferrer">
            Explore our SEO services
          </a>
        </footer>
      )}
    </main>
  );
}
