"use client";

import { useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { buildFreeReport, type FreeReport } from "@/lib/freeAudit";
import FreeAuditReport from "./FreeAuditReport";
import FiverrUpsells from "./FiverrUpsells";

// The 3D visualizer is a client-only WebGL surface — load it without SSR so
// three.js never touches the server render (and it stays out of the initial
// bundle until a prospect actually runs an audit).
const AuditVisualizer = dynamic(() => import("./AuditVisualizer"), { ssr: false });

type Stage = "landing" | "form" | "generating" | "report";

// The agency's public Fiverr profile — the deliberate conversion path
// (see lib/upsells.ts). Kept prominent before the report, then expanded
// into gig cards after it.
const FIVERR_PROFILE = "https://www.fiverr.com/xegents";

// Each step now maps to one cinematic phase of the 3D audit visualizer
// (see AuditVisualizer.tsx): neural crawl → AI signal exchange → globe
// synthesis → report assembly. The caption narrates what the scene shows.
const GEN_STEPS = [
  { icon: "hub", label: "Crawling your site", caption: "Mapping pages and wiring up the neural graph…" },
  { icon: "forum", label: "Analyzing on-page signals", caption: "AI agents exchanging and cross-checking signals…" },
  { icon: "public", label: "Scoring foundations", caption: "Condensing the data into your site model…" },
  { icon: "dashboard", label: "Compiling your report", caption: "Assembling your dashboard…" },
];

const EMAIL_RE = /\S+@\S+\.\S+/;

export default function FreeAuditFlow() {
  const [stage, setStage] = useState<Stage>("landing");
  const [url, setUrl] = useState("");
  const [email, setEmail] = useState("");
  const [report, setReport] = useState<FreeReport | null>(null);
  const [genStep, setGenStep] = useState(0);
  const timers = useRef<number[]>([]);

  const urlValid = url.trim().length > 3 && /\.[a-z]{2,}/i.test(url);
  const emailValid = EMAIL_RE.test(email);
  const canSubmit = urlValid && emailValid;

  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), []);

  const submit = () => {
    if (!canSubmit) return;
    setStage("generating");
    setGenStep(0);
    // Simulated job lifecycle — mirrors AuditWorkspace's queued→running→done
    // staged setTimeouts. Steps advance, then the report resolves.
    timers.current.forEach((t) => window.clearTimeout(t));
    // ~5s per beat so each 3D phase (neural → bots → globe) plays its
    // signature animation two or three times over before advancing.
    timers.current = [
      window.setTimeout(() => setGenStep(1), 5000),
      window.setTimeout(() => setGenStep(2), 10000),
      window.setTimeout(() => setGenStep(3), 15000),
      window.setTimeout(() => {
        setReport(buildFreeReport(url));
        setStage("report");
      }, 18500),
    ];
  };

  const showFiverrBar = stage !== "report";

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
              <div className="fa-brand-s">by Xegents</div>
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

      {stage === "landing" && (
        <main className="fa-hero">
          <span className="fa-eyebrow">
            <span className="material-symbols-rounded">bolt</span>
            Free SEO Audit
          </span>
          <h1 className="fa-hero-h">
            See exactly what&apos;s holding your <span className="fa-hi">rankings</span> back.
          </h1>
          <p className="fa-hero-sub">
            Get a free, instant SEO audit of your website — technical health and on-page fixes,
            scored and explained. No login, no sales call.
          </p>
          <div className="fa-trust">
            <span><span className="material-symbols-rounded">lock_open</span>No login required</span>
            <span><span className="material-symbols-rounded">timer</span>Ready in ~2 minutes</span>
            <span><span className="material-symbols-rounded">insights</span>10 checks scored</span>
          </div>

          {/* Fiverr link surfaced above the button, per the brief. */}
          <a className="fa-fiverr-line" href={FIVERR_PROFILE} target="_blank" rel="noopener noreferrer">
            <span className="material-symbols-rounded">verified</span>
            Prefer we handle it end-to-end? See our gigs on Fiverr
            <span className="material-symbols-rounded">arrow_outward</span>
          </a>

          <button className="primary-btn fa-cta" onClick={() => setStage("form")}>
            <span className="material-symbols-rounded">rocket_launch</span>
            Get Your Free Audit
          </button>
        </main>
      )}

      {stage === "form" && (
        <main className="fa-form-wrap">
          <div className="fa-card">
            <button className="fa-back" onClick={() => setStage("landing")} type="button">
              <span className="material-symbols-rounded">arrow_back</span>
              Back
            </button>
            <h1 className="fa-card-h">Where should we look?</h1>
            <p className="fa-card-sub">Enter your site and email — your report is generated on the spot and a copy is sent to you.</p>

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
              Demo build — the report is generated locally and no email is actually sent.
            </div>
          </div>
        </main>
      )}

      {stage === "generating" && (
        <main className="fa-gen">
          {/* Immersive WebGL stage — the audit "runs" as a 3D visualization,
              driven by genStep. A live-region HUD narrates each phase. */}
          <div className="fa-viz">
            <AuditVisualizer phase={genStep} />
            <div className="fa-viz-vignette" aria-hidden />
            <div className="fa-viz-grid" aria-hidden />
            <div className="fa-viz-hud">
              <div className="fa-viz-tag">
                <span className="fa-viz-dot" />
                AIOS engine · live
              </div>
              {/* Bottom console — caption + progress kept clear of the
                  centered 3D scene so nothing covers the animation. */}
              <div className="fa-viz-console">
                <div className="fa-viz-caption" role="status" aria-live="polite">
                  <span className="fa-viz-step"><span className="material-symbols-rounded">{GEN_STEPS[genStep].icon}</span></span>
                  <div className="fa-viz-caption-txt">
                    <div className="fa-viz-label">{GEN_STEPS[genStep].label}</div>
                    <div className="fa-viz-sub">{GEN_STEPS[genStep].caption}</div>
                  </div>
                  <span className="fa-viz-count">{genStep + 1}<i>/ {GEN_STEPS.length}</i></span>
                </div>
                <ol className="fa-viz-track" aria-hidden>
                  {GEN_STEPS.map((s, i) => (
                    <li
                      key={s.label}
                      className={`fa-viz-seg ${i < genStep ? "done" : i === genStep ? "on" : ""}`}
                    />
                  ))}
                </ol>
              </div>
            </div>
          </div>
          <h1 className="fa-gen-h">Auditing your site…</h1>
          <p className="fa-gen-sub">Hang tight — our engine is crawling, cross-checking and scoring your pages in real time.</p>
        </main>
      )}

      {stage === "report" && report && (
        <main className="fa-report-wrap">
          <FreeAuditReport report={report} />
          <FiverrUpsells />
          <div className="fa-report-foot">
            Built by Xegents AI · <a href={FIVERR_PROFILE} target="_blank" rel="noopener noreferrer">See all our services on Fiverr →</a>
          </div>
        </main>
      )}
    </div>
  );
}
