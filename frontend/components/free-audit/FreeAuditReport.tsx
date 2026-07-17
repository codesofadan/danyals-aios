"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import anime from "animejs";
import { cleanDomain, scoreBand, toCategoryBars, VERDICT } from "@/lib/freeAudit";
import { publicReportPdfUrl, type PublicReport } from "@/lib/hooks/publicAudit";

// Count-up for the composite score — same shape as AuditStats.useCountUp,
// reduced-motion safe. Colored by band via the parent's --fa-band var.
function useCountUp(target: number) {
  const ref = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      node.textContent = String(target);
      return;
    }
    const obj = { n: 0 };
    const anim = anime({
      targets: obj,
      n: target,
      duration: 1600,
      easing: "easeOutExpo",
      update: () => {
        node.textContent = String(Math.round(obj.n));
      },
    });
    return () => anim.pause();
  }, [target]);
  return ref;
}

// The report `when` is the audit's creation timestamp (ISO or null).
function formatWhen(when: string | null): string {
  if (!when) return "scanned just now";
  const d = new Date(when);
  if (Number.isNaN(d.getTime())) return "scanned just now";
  return `scanned ${d.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}

// Renders the REAL curated PublicReport — the overall score ring + per-category
// `scores` bars — with an honest PDF CTA (only when the backend has one). No
// fabricated per-check verdicts (the backend does not return them).
export default function FreeAuditReport({ report, token }: { report: PublicReport; token: string }) {
  const score = report.score ?? 0;
  const band = scoreBand(score);
  const bars = toCategoryBars(report.scores);
  const domain = cleanDomain(report.url) || "your site";

  const scoreRef = useCountUp(score);
  const bodyRef = useRef<HTMLDivElement>(null);

  const strong = bars.filter((b) => b.band === "ok").length;
  const attention = bars.filter((b) => b.band !== "ok").length;

  // Report assembly: the major sections glide into place from different
  // Z-depths (parallax finale of the 3D audit), then the inner rows / bars fade
  // + fill within them. Both honor reduced motion.
  useEffect(() => {
    const node = bodyRef.current;
    if (!node) return;
    const layers = node.querySelectorAll<HTMLElement>(".fa-layer");
    const rows = node.querySelectorAll<HTMLElement>(".fa-reveal");
    const fills = node.querySelectorAll<HTMLElement>(".fa-bar-fill");
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      [...layers, ...rows].forEach((r) => {
        r.style.opacity = "1";
        r.style.transform = "none";
      });
      fills.forEach((f) => {
        f.style.width = `${f.dataset.v ?? 0}%`;
      });
      return;
    }
    const depth = anime({
      targets: layers,
      opacity: [0, 1],
      translateZ: [-260, 0], // parallax depth glide (parent sets perspective)
      translateY: [54, 0],
      rotateX: [-7, 0],
      delay: anime.stagger(120, { start: 80 }),
      duration: 900,
      easing: "easeOutExpo",
    });
    const inner = anime({
      targets: rows,
      opacity: [0, 1],
      translateY: [14, 0],
      delay: anime.stagger(45, { start: 420 }),
      duration: 520,
      easing: "easeOutCubic",
    });
    const grow = anime({
      targets: fills,
      width: (el: HTMLElement) => `${el.dataset.v ?? 0}%`,
      delay: anime.stagger(60, { start: 520 }),
      duration: 900,
      easing: "easeOutExpo",
    });
    return () => {
      depth.pause();
      inner.pause();
      grow.pause();
    };
  }, [report]);

  return (
    <div className="fa-report" ref={bodyRef}>
      {/* Score header */}
      <section className={`fa-score-hero fa-layer band-${band}`}>
        <div className="fa-score-ring" style={{ "--pct": score } as CSSProperties}>
          <span className="fa-score-num" ref={scoreRef}>
            0
          </span>
          <span className="fa-score-out">/ 100</span>
        </div>
        <div className="fa-score-meta">
          <div className="fa-score-eyebrow">
            <span className="material-symbols-rounded">public</span>
            {domain}
            <span className="fa-score-when">· {formatWhen(report.when)}</span>
          </div>
          <h1 className="fa-score-title">Your free SEO audit is ready</h1>
          <p className="fa-score-verdict">{VERDICT[band]}</p>
          {report.has_pdf && (
            <a
              className="fa-pdf-cta"
              href={publicReportPdfUrl(token)}
              target="_blank"
              rel="noopener noreferrer"
            >
              <span className="material-symbols-rounded">picture_as_pdf</span>
              Download the full PDF report
              <span className="material-symbols-rounded">download</span>
            </a>
          )}
        </div>
      </section>

      {bars.length > 0 && (
        <>
          {/* KPI strip — honest counts DERIVED from the real per-category bands. */}
          <section className="fa-kpis fa-layer">
            {[
              { icon: "donut_large", label: "Categories scored", value: bars.length, tone: "" },
              { icon: "verified", label: "Strong areas", value: strong, tone: "ok" },
              { icon: "priority_high", label: "Need attention", value: attention, tone: "warn" },
            ].map((k) => (
              <div key={k.label} className={`fa-kpi fa-reveal ${k.tone}`}>
                <span className="fa-kpi-ic material-symbols-rounded">{k.icon}</span>
                <div className="fa-kpi-val">{k.value}</div>
                <div className="fa-kpi-lab">{k.label}</div>
              </div>
            ))}
          </section>

          {/* Per-category score bars (the real `scores` map). */}
          <section className="fa-bars fa-layer">
            <div className="fa-bars-h">
              <span className="material-symbols-rounded">bar_chart</span>
              Category breakdown
            </div>
            <ul className="fa-bar-list">
              {bars.map((b) => (
                <li key={b.key} className="fa-bar fa-reveal">
                  <span className="fa-bar-ic" style={{ background: `${b.color}22`, color: b.color }}>
                    <span className="material-symbols-rounded">{b.icon}</span>
                  </span>
                  <div className="fa-bar-main">
                    <div className="fa-bar-top">
                      <span className="fa-bar-label">{b.label}</span>
                      <span className={`fa-bar-score band-${b.band}`}>{b.score}</span>
                    </div>
                    <div className="fa-bar-track">
                      <span className="fa-bar-fill" data-v={b.score} style={{ background: b.color }} />
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}

      {bars.length === 0 && (
        <div className="fa-report-note fa-layer">
          <span className="material-symbols-rounded">insights</span>
          Your overall score is ready. The full category breakdown and per-page fixes are in the
          detailed report.
        </div>
      )}
    </div>
  );
}
