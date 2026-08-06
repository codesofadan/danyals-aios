"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchPublicReportHtml,
  publicReportPdfUrl,
  useCreatePublicAudit,
  usePublicReport,
} from "@/lib/hooks/publicAudit";
import ReportViewer from "@/components/report/ReportViewer";
import FreeAuditReport from "./FreeAuditReport";
import FiverrUpsells from "./FiverrUpsells";

type View = "landing" | "form" | "working";

// A default Fiverr profile for the pre-report surfaces (before we hold a
// report, whose `fiverr_url` is the backend-owned source of truth).
const FIVERR_PROFILE = "https://www.fiverr.com/iamdaani";

// The free audit always runs one full-spectrum condensed audit (on-page,
// technical, AI/GEO and strategy) — there is no focus selector; the deterministic
// free engine run already covers every non-paid dimension.

// Decorative loading beats for the 3D stage — narration only. The REAL job
// status (queued/running) drives the copy below; these just animate the scene.
const GEN_STEPS = [
  { icon: "hub", label: "Crawling your site", caption: "Mapping pages and wiring up the neural graph…" },
  { icon: "forum", label: "Analyzing on-page signals", caption: "AI agents exchanging and cross-checking signals…" },
  { icon: "public", label: "Scoring foundations", caption: "Condensing the data into your site model…" },
];

const EMAIL_RE = /\S+@\S+\.\S+/;

// First-class copy for the create-mutation errors the backend surfaces.
function createErrorCopy(err: unknown): { title: string; body: string } {
  const status = (err as { status?: number } | null)?.status;
  const message = (err as { message?: string } | null)?.message ?? "";
  if (status === 409) {
    return {
      title: "You've already claimed a free audit",
      body: "It's one free audit per email. Work with us on Fiverr and we'll run a full deep-dive on your site.",
    };
  }
  if (status === 400) {
    return {
      title: "We can't audit that URL",
      body: message || "Enter a public website URL — the free audit covers on-page, technical, AI/GEO and strategy checks.",
    };
  }
  return {
    title: "Something went wrong",
    body: message || "We couldn't start your audit. Please try again in a moment.",
  };
}

export default function FreeAuditFlow() {
  const [view, setView] = useState<View>("landing");
  const [url, setUrl] = useState("");
  const [email, setEmail] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [genStep, setGenStep] = useState(0);

  const create = useCreatePublicAudit();
  const reportQ = usePublicReport(token);
  const report = reportQ.data;

  const urlValid = url.trim().length > 3 && /\.[a-z]{2,}/i.test(url);
  const emailValid = EMAIL_RE.test(email);
  const canSubmit = urlValid && emailValid;

  // Working sub-states, derived from the real mutation + query.
  const createFailed = view === "working" && create.isError;
  const reportFailed = view === "working" && !!token && (reportQ.isError || report?.status === "failed");
  const reportDone = view === "working" && !!token && report?.status === "done";
  const generating = view === "working" && !createFailed && !reportFailed && !reportDone;

  // Advance the decorative 3D scene while the job is genuinely pending. Purely
  // cosmetic (the canvas is aria-hidden) — it never claims completion; the
  // report only appears when the backend says `done`.
  useEffect(() => {
    if (!generating) return;
    const id = window.setInterval(() => setGenStep((s) => (s + 1) % GEN_STEPS.length), 4200);
    return () => window.clearInterval(id);
  }, [generating]);

  const submit = () => {
    if (!canSubmit || create.isPending) return;
    setGenStep(0);
    setView("working");
    create.mutate(
      { email: email.trim(), url: url.trim() },
      { onSuccess: (data) => setToken(data.report_token) }
    );
  };

  const restart = () => {
    setToken(null);
    create.reset();
    setView("form");
  };

  // The upsell link is backend-owned once a report exists.
  const fiverrUrl = report?.fiverr_url || FIVERR_PROFILE;
  const showFiverrBar = view !== "working" || !reportDone;

  // Unauthenticated fetch of the condensed report.html (the token in the path is
  // the capability) for the in-page viewer. Same condensed document the free PDF
  // is rendered from, so the on-screen report matches the download.
  const loadPublicReport = useCallback(() => fetchPublicReportHtml(token ?? ""), [token]);

  // Live HUD copy — reflects the REAL status, not a fake timeline.
  const hud = (() => {
    if (create.isPending || (token && !report)) {
      return { icon: "rocket_launch", label: "Starting your audit", caption: "Handing your site to the engine…" };
    }
    if (report?.status === "queued") {
      return { icon: "schedule", label: "Queued", caption: "Waiting for an audit worker to pick up your site…" };
    }
    return GEN_STEPS[genStep];
  })();

  return (
    <div className="fa-wrap">
      {/* Persistent brand + Fiverr bar (hidden once the report — with its own
          richer Fiverr surface — takes over). */}
      {showFiverrBar && (
        <header className="fa-topbar">
          <div className="fa-brand">
            <span className="fa-brand-logo" />
            <div>
              <div className="fa-brand-n">AIOS</div>
              <div className="fa-brand-s">by AIOS</div>
            </div>
          </div>
          <div className="fa-topbar-actions">
            <a className="fa-fiverr-link" href={FIVERR_PROFILE} target="_blank" rel="noopener noreferrer">
              <span className="material-symbols-rounded">storefront</span>
              Work with us on Fiverr
              <span className="material-symbols-rounded">arrow_outward</span>
            </a>
          </div>
        </header>
      )}

      {view === "landing" && (
        <main className="fa-hero">
          <span className="fa-eyebrow">
            <span className="material-symbols-rounded">bolt</span>
            Free SEO Audit
          </span>
          <h1 className="fa-hero-h">
            See exactly what&apos;s holding your <span className="fa-hi">rankings</span> back.
          </h1>
          <p className="fa-hero-sub">
            Get a free SEO audit of your website — technical health and on-page fixes, scored and
            explained by our engine. No login, no sales call.
          </p>
          <div className="fa-trust">
            <span><span className="material-symbols-rounded">lock_open</span>No login required</span>
            <span><span className="material-symbols-rounded">timer</span>Runs in the background</span>
            <span><span className="material-symbols-rounded">insights</span>Real engine score</span>
          </div>

          {/* Fiverr link surfaced above the button, per the brief. */}
          <a className="fa-fiverr-line" href={FIVERR_PROFILE} target="_blank" rel="noopener noreferrer">
            <span className="material-symbols-rounded">verified</span>
            Prefer we handle it end-to-end? See our gigs on Fiverr
            <span className="material-symbols-rounded">arrow_outward</span>
          </a>

          <button className="primary-btn fa-cta" onClick={() => setView("form")}>
            <span className="material-symbols-rounded">rocket_launch</span>
            Get Your Free Audit
          </button>
        </main>
      )}

      {view === "form" && (
        <main className="fa-form-wrap">
          <div className="fa-card">
            <button className="fa-back" onClick={() => setView("landing")} type="button">
              <span className="material-symbols-rounded">arrow_back</span>
              Back
            </button>
            <h1 className="fa-card-h">Where should we look?</h1>
            <p className="fa-card-sub">Enter your site and email — we run the audit and keep your report at a private link.</p>

            <form
              className="fa-form"
              onSubmit={(e) => {
                e.preventDefault();
                submit();
              }}
            >
              <label className="fa-fld">
                <span>Website URL</span>
                <div className="fa-input">
                  <span className="material-symbols-rounded">link</span>
                  <input
                    type="text"
                    inputMode="url"
                    placeholder="yourbusiness.com"
                    value={url}
                    onChange={(e) => setUrl(e.target.value)}
                    autoFocus
                  />
                </div>
              </label>

              <label className="fa-fld">
                <span>Work email</span>
                <div className="fa-input">
                  <span className="material-symbols-rounded">mail</span>
                  <input
                    type="email"
                    placeholder="you@yourbusiness.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    autoComplete="email"
                  />
                </div>
              </label>

              <button className="primary-btn wide" type="submit" disabled={!canSubmit}>
                <span className="material-symbols-rounded">rocket_launch</span>
                Run my free audit
              </button>
            </form>

            <div className="fa-note">
              <span className="material-symbols-rounded">info</span>
              One free audit per email. Your report opens at a private link the moment it's ready.
            </div>
          </div>
        </main>
      )}

      {generating && (
        <main className="fa-gen">
          {/* Lightweight CSS stage — the audit "runs" as a simple pulsing
              icon while we genuinely poll the backend. A live-region HUD
              narrates the real job status. */}
          <div className="fa-viz">
            <div className="fa-viz-core" aria-hidden>
              <span className="fa-viz-core-ring" />
              <span className="fa-viz-core-ring r2" />
              <span className="fa-viz-core-badge">
                <span className="material-symbols-rounded">{hud.icon}</span>
              </span>
            </div>
            <div className="fa-viz-vignette" aria-hidden />
            <div className="fa-viz-grid" aria-hidden />
            <div className="fa-viz-hud">
              <div className="fa-viz-tag">
                <span className="fa-viz-dot" />
                AIOS engine · live
              </div>
              {/* Bottom console — caption kept clear of the centered 3D scene. */}
              <div className="fa-viz-console">
                <div className="fa-viz-caption" role="status" aria-live="polite">
                  <span className="fa-viz-step"><span className="material-symbols-rounded">{hud.icon}</span></span>
                  <div className="fa-viz-caption-txt">
                    <div className="fa-viz-label">{hud.label}</div>
                    <div className="fa-viz-sub">{hud.caption}</div>
                  </div>
                </div>
                <ol className="fa-viz-track" aria-hidden>
                  {GEN_STEPS.map((s, i) => (
                    <li key={s.label} className={`fa-viz-seg ${i === genStep ? "on" : ""}`} />
                  ))}
                </ol>
              </div>
            </div>
          </div>
          <h1 className="fa-gen-h">Auditing your site…</h1>
          <p className="fa-gen-sub">Hang tight — our engine is crawling, cross-checking and scoring your pages. This runs in the background and updates live.</p>
        </main>
      )}

      {createFailed && (
        <main className="fa-fail">
          <FailCard {...createErrorCopy(create.error)} onRetry={restart} />
        </main>
      )}

      {reportFailed && !createFailed && (
        <main className="fa-fail">
          <FailCard
            title="Your audit didn't finish"
            body="The engine couldn't complete a scan of this site. Double-check the URL is reachable and try again."
            onRetry={restart}
          />
        </main>
      )}

      {reportDone && report && token && (
        <main className="fa-report-wrap">
          <FreeAuditReport report={report} token={token} />
          {/* The full condensed report, page by page — the SAME document as the PDF. */}
          <ReportViewer
            load={loadPublicReport}
            reloadKey={token}
            label="Your SEO audit report"
            pdfHref={report.has_pdf ? publicReportPdfUrl(token) : undefined}
          />
          <FiverrUpsells fiverrUrl={fiverrUrl} />
          <div className="fa-report-foot">
            Built by AIOS · <a href={fiverrUrl} target="_blank" rel="noopener noreferrer">See all our services on Fiverr →</a>
          </div>
        </main>
      )}
    </div>
  );
}

function FailCard({ title, body, onRetry }: { title: string; body: string; onRetry: () => void }) {
  return (
    <div className="fa-fail-card">
      <div className="fa-fail-ic">
        <span className="material-symbols-rounded">error</span>
      </div>
      <h1 className="fa-fail-h">{title}</h1>
      <p className="fa-fail-sub">{body}</p>
      <button className="primary-btn" onClick={onRetry} type="button">
        <span className="material-symbols-rounded">refresh</span>
        Try again
      </button>
    </div>
  );
}
