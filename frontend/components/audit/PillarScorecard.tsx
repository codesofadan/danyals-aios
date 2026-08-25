"use client";

// ============================================================
// MACRO - where the site is weak, and whether we actually looked.
//
// Every card shows a score AND its coverage, because the two are one fact. The
// engine once reported technical 97.2 having run 25 of 100 technical checks; a
// client reading "97/100" was reading a number computed over a quarter of the
// checklist. A score without a denominator is not a fact they can use.
//
// An unmeasured dimension renders as "Not measured", never 0, and says WHY.
// Those are opposite claims about a client's site, and the remedies differ.
// It is styled ABSENT (muted, dashed) rather than BAD (red) for the same reason.
// ============================================================

import type { Rollup } from "@/lib/auditAltitude";
import {
  DIMENSION_ICON,
  coverageLabel,
  coveragePct,
  isMeasured,
  notMeasuredReason,
  scoreDisplay,
  scoreTone,
} from "@/lib/auditAltitude";

type Props = {
  rollups: Rollup[];
  selected: string | null;
  onSelect: (dimension: string | null) => void;
};

export default function PillarScorecard({ rollups, selected, onSelect }: Props) {
  const dims = rollups.filter((r) => r.level === "dimension");
  if (!dims.length) return null;

  return (
    <div className="alt-pillars">
      {dims.map((r) => {
        const measured = isMeasured(r);
        const tone = scoreTone(measured ? r.score : null);
        const on = selected === r.key;
        return (
          <button
            key={r.key}
            type="button"
            className={`alt-pillar ${on ? "on" : ""} t-${tone}`}
            onClick={() => onSelect(on ? null : r.key)}
            aria-pressed={on}
            title={
              measured
                ? `${r.label}: ${r.score} over ${coverageLabel(r)} checks`
                : `${r.label}: not measured - ${notMeasuredReason(r)}`
            }
          >
            <span className="alt-pillar-top">
              <span className="material-symbols-rounded">
                {DIMENSION_ICON[r.key] ?? "category"}
              </span>
              <span className="alt-pillar-name">{r.label}</span>
            </span>

            <span className={`alt-pillar-score ${measured ? "" : "unmeasured"}`}>
              {scoreDisplay(r)}
            </span>

            {/* The denominator travels with the number, always. */}
            <span className="alt-pillar-cov">
              <span className="alt-cov-bar" aria-hidden="true">
                <i style={{ width: `${coveragePct(r)}%` }} />
              </span>
              <span className="alt-cov-text">ran {coverageLabel(r)} checks</span>
            </span>

            {measured ? (
              <span className="alt-pillar-foot">
                {r.findings_open.toLocaleString()} issue{r.findings_open === 1 ? "" : "s"}
                {r.instances_open > r.findings_open
                  ? ` · ${r.instances_open.toLocaleString()} occurrences`
                  : ""}
              </span>
            ) : (
              <span className="alt-pillar-foot why">{notMeasuredReason(r)}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
