"use client";

// ============================================================
// THE PLAN - what to do first, and what the next twelve months look like.
//
// RELATIVE WINDOWS, NEVER DATES. `p1_90d` means "the second and third months of
// work", not a calendar quarter. Nothing an audit measures supports a date, so
// none is shown unless an operator has set a start date.
//
// The capacity assumption is printed at the top on purpose. Every timeline
// number in this board derives from that ONE operator input; presenting the
// schedule without it would let a reader take it for a measurement.
//
// EACH COLUMN SHOWS ITS FIRST FEW ITEMS. Rendering all 322 planned items at once
// produced a 17,000px page whose "Later" column alone held 160 cards - the same
// wall-of-data failure the whole altitude model exists to end. A plan is read
// front-to-back: what matters is the next handful, and the rest is reference. The
// count is always on the expander, so nothing is hidden without saying so.
//
// Backlog stays visible as its own block. On the real audit 299 of 461 items do
// not fit a year at the default capacity, and saying so is the point.
// ============================================================

import { useState } from "react";
import type { RoadmapItem, RoadmapPhaseKey, RoadmapResponse } from "@/lib/auditAltitude";
import {
  ROADMAP_PHASE_SHORT,
  ROADMAP_PHASE_WINDOW,
  ROLE_LABEL,
  severityTone,
} from "@/lib/auditAltitude";

/** How many cards a column shows before it asks. Enough to plan a sprint from. */
const PREVIEW = 8;

function Item({ item }: { item: RoadmapItem }) {
  return (
    <div className={`rm-item t-${severityTone(item.severity)}`}>
      <div className="rm-item-top">
        <span className="rm-seq">{item.sequence}</span>
        <span className="rm-title">{item.title}</span>
      </div>
      <div className="rm-item-meta">
        <span className="rm-role">{ROLE_LABEL[item.owner_role] ?? item.owner_role}</span>
        {item.effort_points !== null ? <span>{item.effort_points} pts</span> : null}
        <span className="rm-check">{item.check_id}</span>
      </div>
      {item.exit_criterion ? (
        <div className="rm-exit" title="How to prove this is done">
          <span className="material-symbols-rounded">check_circle</span>
          {item.exit_criterion}
        </div>
      ) : null}
    </div>
  );
}

function Column({ phase, items }: { phase: RoadmapPhaseKey; items: RoadmapItem[] }) {
  const [open, setOpen] = useState(false);
  const shown = open ? items : items.slice(0, PREVIEW);
  const rest = items.length - shown.length;
  const points = items.reduce((n, i) => n + (i.effort_points ?? 0), 0);

  return (
    <section className="rm-col">
      <header className="rm-col-h">
        <span className="rm-col-name">{ROADMAP_PHASE_SHORT[phase]}</span>
        <span className="rm-col-win">{ROADMAP_PHASE_WINDOW[phase]}</span>
        <span className="rm-col-n" title={`${Math.round(points)} effort points`}>
          {items.length}
        </span>
      </header>
      <div className="rm-col-body">
        {shown.length ? (
          shown.map((i) => <Item key={i.id} item={i} />)
        ) : (
          <p className="rm-none">Nothing scheduled in this window.</p>
        )}
        {rest > 0 || open ? (
          <button type="button" className="rm-more" onClick={() => setOpen(!open)}>
            <span className="material-symbols-rounded">
              {open ? "unfold_less" : "unfold_more"}
            </span>
            {open ? "Show fewer" : `${rest} more in this window`}
          </button>
        ) : null}
      </div>
    </section>
  );
}

export default function RoadmapBoard({ data }: { data: RoadmapResponse }) {
  const { roadmap, phases } = data;
  const planned = phases.filter((p) => p.phase !== "backlog");
  const backlog = phases.find((p) => p.phase === "backlog");

  return (
    <div className="rm">
      <div
        className="rm-board"
        title={`Packed at ${roadmap.capacity_points_per_month} points per month. `
          + `Phases are relative windows, not calendar dates.`}
      >
        {planned.map((p) => (
          <Column key={p.phase} phase={p.phase as RoadmapPhaseKey} items={p.items} />
        ))}
      </div>

      {backlog && backlog.items.length > 0 ? (
        <section className="rm-backlog">
          <header>
            <span className="material-symbols-rounded">inbox</span>
            <b>{backlog.items.length.toLocaleString()} items beyond the planned horizon</b>
            <span className="rm-backlog-note">
              Not dropped - this is more than twelve months of work at the stated capacity.
              Raise the capacity, or narrow the scope.
            </span>
          </header>
          <div className="rm-backlog-list">
            {backlog.items.slice(0, 12).map((i) => (
              <span key={i.id} className={`rm-pill t-${severityTone(i.severity)}`}>
                {i.title}
              </span>
            ))}
            {backlog.items.length > 12 ? (
              <span className="rm-pill more">
                +{(backlog.items.length - 12).toLocaleString()} more - see roadmap.csv
              </span>
            ) : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}
