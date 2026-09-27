"use client";

import Link from "next/link";

import FiverrUpsells from "@/components/free-audit/FiverrUpsells";
import ReportViewer from "@/components/report/ReportViewer";
import { cleanDomain, scoreBand, VERDICT } from "@/lib/freeAudit";
import {
  fetchPublicPageReportHtml,
  publicPageReportPdfUrl,
  usePublicPage,
  type PublicFinding,
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

// Severity in a business owner's words. The engine's own vocabulary ("major") reads as a
// grade rather than a consequence, and this page is read by somebody deciding whether to
// spend money on it.
const SEV_LABEL: Record<string, string> = {
  critical: "Critical",
  major: "Important",
  minor: "Minor",
};

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
  const findings = page.top_findings ?? [];
  const notChecked = page.not_checked ?? [];

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

      {/* WHAT WE FOUND, before the report. The page used to be a score and an embedded
          document: a reader who did not open the report learned nothing they could act on,
          and this is the page that gets forwarded to the person who decides. */}
      {findings.length > 0 && (
        <section className="pa-block">
          <h2 className="pa-h2">What we found</h2>
          <p className="pa-sub">
            The {findings.length === 1 ? "issue" : `${findings.length} issues`} costing this
            site the most, worst first. The full list is in the report below.
          </p>
          <ul className="pa-finds">
            {findings.map((f: PublicFinding) => (
              <li key={f.title} className={`pa-find pa-find--${f.severity}`}>
                <span className="pa-find-sev">{SEV_LABEL[f.severity] ?? f.severity}</span>
                <span className="pa-find-t">{f.title}</span>
                {f.pages > 0 && (
                  <span className="pa-find-n">
                    {f.pages.toLocaleString()} {f.pages === 1 ? "page" : "pages"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* WHAT THIS DID NOT CHECK. The honest half, and the one a free audit cannot leave
          out: silence on off-page or local reads exactly like a clean bill of health, and
          a prospect who believes their backlink profile was reviewed has been misled by
          omission. It is also, truthfully, the reason to buy the full audit. */}
      {notChecked.length > 0 && (
        <section className="pa-block pa-gaps">
          <h2 className="pa-h2">
            What this {page.kind === "paid" ? "audit" : "free audit"} did not check
          </h2>
          <p className="pa-sub">
            These were not measured, which is not the same as clean - nothing above or below
            says anything about them either way.
          </p>
          <ul className="pa-gap-list">
            {notChecked.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </section>
      )}

      {page.crawl_note ? (
        <section className="pa-block pa-gaps">
          <h2 className="pa-h2">About the score</h2>
          <p className="pa-sub" style={{ marginBottom: 0 }}>{page.crawl_note}</p>
        </section>
      ) : null}

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

      {/* THE THREE GIGS, the same component the free-audit funnel ends on.
          This page carried a single "Explore our SEO services" link to the Fiverr
          PROFILE, so a reader who had just been shown their own problems was handed
          a directory and left to work out which service addressed them. The funnel
          already ends on three named gigs; the shared page did not, and the shared
          page is the one that gets forwarded.

          Rendered UNCONDITIONALLY, unlike the link it replaces. The gigs are a
          frontend constant (lib/freeAuditGigs), so they do not depend on the
          backend's `fiverr_url` - which gated the old block and hid the whole
          section whenever it was unset. `fiverr_url` now only powers the
          section's own "Explore all services" link, which FiverrUpsells already
          renders conditionally. */}
      <footer className="pa-block pa-upsell">
        <FiverrUpsells fiverrUrl={page.fiverr_url} />
      </footer>
    </Shell>
  );
}
