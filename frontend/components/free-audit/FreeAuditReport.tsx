"use client";

import { useEffect, useRef, type CSSProperties } from "react";
import anime from "animejs";
import type { CheckStatus, FreeReport } from "@/lib/freeAudit";

const STATUS_META: Record<CheckStatus, { pill: string; icon: string; label: string }> = {
  pass: { pill: "ok", icon: "check_circle", label: "Pass" },
  warn: { pill: "warn", icon: "warning", label: "Review" },
  fail: { pill: "crit", icon: "cancel", label: "Fix" },
};

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

export default function FreeAuditReport({ report }: { report: FreeReport }) {
  const scoreRef = useCountUp(report.score);
  const bodyRef = useRef<HTMLDivElement>(null);

  // Report assembly: the major sections glide into place from different
  // Z-depths (parallax finale of the 3D audit), then the inner check rows /
  // KPI tiles fade up within them. Both honor reduced motion.
  useEffect(() => {
    const node = bodyRef.current;
    if (!node) return;
    const layers = node.querySelectorAll<HTMLElement>(".fa-layer");
    const rows = node.querySelectorAll<HTMLElement>(".fa-reveal");
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      [...layers, ...rows].forEach((r) => {
        r.style.opacity = "1";
        r.style.transform = "none";
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
    return () => {
      depth.pause();
      inner.pause();
    };
  }, [report]);

  return (
    <div className="fa-report" ref={bodyRef}>
      {/* Score header */}
      <section className={`fa-score-hero fa-layer band-${report.band}`}>
        <div className="fa-score-ring" style={{ "--pct": report.score } as CSSProperties}>
          <span className="fa-score-num" ref={scoreRef}>
            0
          </span>
          <span className="fa-score-out">/ 100</span>
        </div>
        <div className="fa-score-meta">
          <div className="fa-score-eyebrow">
            <span className="material-symbols-rounded">public</span>
            {report.domain}
            <span className="fa-score-when">· scanned just now</span>
          </div>
          <h1 className="fa-score-title">Your free SEO audit is ready</h1>
          <p className="fa-score-verdict">{report.verdict}</p>
        </div>
      </section>

      {/* KPI strip */}
      <section className="fa-kpis fa-layer">
        {[
          { icon: "check_circle", label: "Checks run", value: report.checksRun, tone: "" },
          { icon: "error", label: "Issues found", value: report.issues, tone: "warn" },
          { icon: "bolt", label: "Quick wins", value: report.quickWins, tone: "ok" },
        ].map((k) => (
          <div key={k.label} className={`fa-kpi fa-reveal ${k.tone}`}>
            <span className="fa-kpi-ic material-symbols-rounded">{k.icon}</span>
            <div className="fa-kpi-val">{k.value}</div>
            <div className="fa-kpi-lab">{k.label}</div>
          </div>
        ))}
      </section>

      {/* Category breakdowns */}
      <div className="fa-cats fa-layer">
        {report.categories.map((cat) => (
          <section key={cat.key} className="fa-cat fa-reveal">
            <div className="fa-cat-h">
              <span className="fa-cat-ic" style={{ background: `${cat.color}22`, color: cat.color }}>
                <span className="material-symbols-rounded">{cat.icon}</span>
              </span>
              <div className="fa-cat-title">{cat.label}</div>
              <span className={`fa-cat-score band-${scoreBandOf(cat.score)}`}>{cat.score}</span>
            </div>
            <ul className="fa-checks">
              {cat.checks.map((c) => {
                const m = STATUS_META[c.status];
                return (
                  <li key={c.label} className="fa-check">
                    <span className={`fa-check-pill ${m.pill}`}>
                      <span className="material-symbols-rounded">{m.icon}</span>
                    </span>
                    <div className="fa-check-body">
                      <div className="fa-check-label">{c.label}</div>
                      <div className="fa-check-note">{c.note}</div>
                    </div>
                    <span className={`fa-check-tag ${m.pill}`}>{m.label}</span>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>

      <div className="fa-report-note fa-layer">
        <span className="material-symbols-rounded">mail</span>
        A house-styled PDF copy of this report has been sent to your inbox.
      </div>
    </div>
  );
}

// Local band helper for per-category chips (kept inline to avoid importing
// the whole builder into a presentational component).
function scoreBandOf(score: number) {
  if (score >= 80) return "ok";
  if (score >= 65) return "warn";
  return "crit";
}
