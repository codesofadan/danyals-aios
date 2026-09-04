"use client";

import Link from "next/link";

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
//
// LAYOUT: its own `pa-*` classes (app/publicaudit.css), NOT the free-audit
// funnel's `fa-card`. That card is 460px wide because it holds an email + URL
// form; reusing it here clamped a 13-table consulting report into a narrow strip
// pinned to the left of the screen. This is a full-width, fluid reading layout.

function formatWhen(when: string | null): string {
  if (!when) return "";
  const d = new Date(when);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="pa-page">
      <div className="pa-wrap">{children}</div>
    </main>
  );
}

export default function PublicAuditPage({ slug }: { slug: string }) {
  const q = usePublicPage(slug);

  if (q.isLoading) {
    return (
      <Shell>
        <div className="pa-block pa-state">
          <span className="material-symbols-rounded" aria-hidden>hourglass_top</span>
          <p>Loading the report…</p>
        </div>
      </Shell>
    );
  }

  // A 404 here is the normal "wrong link" case, not an error state to apologise
  // for — an unpublished paid page returns 404 on purpose so the URL space says
  // nothing about which reports exist.
  if (q.isError || !q.data) {
    return (
      <Shell>
        <div className="pa-block pa-state">
          <span className="material-symbols-rounded" aria-hidden>link_off</span>
          <h1>This report isn’t available</h1>
          <p>The link may have expired, or the report may not have been shared yet.</p>
          {/* `next/link`, not a bare <a>: @next/next/no-html-link-for-pages is an
              ERROR in `next build`, so an anchor to an in-app route fails the
              production build outright - it does not merely warn. */}
          <Link className="primary-btn fa-cta" href="/" style={{ marginTop: 18, display: "inline-block" }}>
            Run a free audit
          </Link>
        </div>
      </Shell>
    );
  }

  const page = q.data;
  const domain = cleanDomain(page.url);
  const verdict = page.score != null ? VERDICT[scoreBand(page.score)] : null;
  const when = formatWhen(page.when);

  return (
    <Shell>
      <header className="pa-block">
        <div className="pa-head">
          <h1 className="pa-title">SEO audit — {domain}</h1>
          <span className="pa-meta">
            {page.kind === "paid" ? "Full audit" : "Free audit"}
            {when ? ` · ${when}` : ""}
          </span>
        </div>

        {page.score != null && (
          <div className="pa-score">
            <b>{page.score}</b>
            <span>/ 100</span>
          </div>
        )}

        {verdict && <p className="pa-verdict">{verdict}</p>}

        {page.has_pdf && (
          <div className="pa-actions">
            <a className="primary-btn fa-cta" href={publicPageReportPdfUrl(page.slug)} download>
              Download the PDF report
            </a>
          </div>
        )}
      </header>

      {page.has_report ? (
        <div className="pa-block pa-block--flush pa-viewer">
          <ReportViewer
            label={domain}
            load={() => fetchPublicPageReportHtml(page.slug)}
            reloadKey={page.slug}
            pdfHref={page.has_pdf ? publicPageReportPdfUrl(page.slug) : undefined}
          />
        </div>
      ) : (
        <div className="pa-block">
          <p style={{ margin: 0, opacity: 0.8 }}>
            The full report for this audit isn’t on file. The score above is still accurate.
          </p>
        </div>
      )}

      {page.fiverr_url && (
        <footer className="pa-block">
          <p style={{ margin: "0 0 10px" }}>Want a hand fixing what this audit surfaced?</p>
          <a className="primary-btn fa-cta" href={page.fiverr_url} target="_blank" rel="noopener noreferrer">
            Explore our SEO services
          </a>
        </footer>
      )}
    </Shell>
  );
}
