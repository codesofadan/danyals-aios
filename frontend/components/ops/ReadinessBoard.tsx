"use client";

// What this deploy will really deliver - shown where the money gets spent.
//
// WHY IT SITS ON THE WORK SCREENS AND NOT ONLY IN SETTINGS. The API-Management screen
// answers "is this key present". The operator's question is never that; it is "if I queue
// thirty pages tonight, will they draft - or hold at $0?". That answer was previously only
// discoverable by running the job and reading the degrade note afterwards, one feature at
// a time, and on a paid depth, after the bill.
//
// TWO RULES THIS PANEL MUST KEEP:
//
//   * QUIET WHEN EVERYTHING IS READY. A banner that shouts on a healthy deploy is a
//     banner people stop reading, and then it is worthless on the day it matters. All
//     ready = one collapsed line.
//   * A BLOCK AND A DEGRADE READ DIFFERENTLY. "Images will be skipped" and "nothing will
//     draft" are not the same sentence. The severity comes from the server (it knows
//     which provider is load-bearing); this only has to not flatten it.

import { useState } from "react";
import { useReadiness, type PreflightCapability } from "@/lib/hooks/readiness";

const VERDICT_PILL: Record<string, string> = {
  ready: "ok",
  partial: "warn",
  blocked: "crit",
};

function Capability({ cap }: { cap: PreflightCapability }) {
  const [open, setOpen] = useState(cap.verdict === "blocked");
  return (
    <div style={{ borderTop: "1px solid var(--line)", padding: "10px 0" }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          width: "100%",
          background: "none",
          border: 0,
          padding: 0,
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <span className={`status-pill ${VERDICT_PILL[cap.verdict] ?? "mut"}`}>{cap.verdict}</span>
        <b>{cap.name}</b>
        <span className="cs" style={{ marginLeft: "auto" }}>
          {cap.summary}
        </span>
        <span className="material-symbols-rounded" aria-hidden="true">
          {open ? "expand_less" : "expand_more"}
        </span>
      </button>

      {open ? (
        <div style={{ marginTop: 8, paddingLeft: 4 }}>
          {cap.gaps.map((g) => (
            <div
              key={g.what}
              style={{
                borderLeft: `3px solid var(--${g.severity === "blocks" ? "crit" : "warn"})`,
                padding: "4px 0 4px 10px",
                marginBottom: 8,
              }}
            >
              <div>
                <b>{g.severity === "blocks" ? "Will not run: " : "Will be thinner: "}</b>
                {g.what}
              </div>
              <div className="cs">{g.why}.</div>
              <div className="cs">
                <b>Fix:</b> {g.fix}.
              </div>
            </div>
          ))}
          <div className="cs">
            {cap.gaps.length ? "What it still does: " : "What it does: "}
            {cap.measures.join(" · ")}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/**
 * The readiness board, optionally narrowed to one group ("Audit" / "Content") so each
 * work screen shows only the capabilities its operator is about to launch.
 */
export default function ReadinessBoard({ group, title }: { group?: string; title?: string }) {
  const q = useReadiness();
  const [open, setOpen] = useState(false);

  // A readiness panel that fails is not worth an error banner on someone else's screen:
  // the work screen it sits on still functions, and the server remains the boundary.
  if (q.isError || !q.data) return null;

  const caps = group ? q.data.capabilities.filter((c) => c.group === group) : q.data.capabilities;
  if (caps.length === 0) return null;

  const blocked = caps.filter((c) => c.verdict === "blocked").length;
  const partial = caps.filter((c) => c.verdict === "partial").length;
  const allReady = blocked === 0 && partial === 0;

  const headline = allReady
    ? "Everything here is ready to run"
    : blocked > 0
      ? `${blocked} thing${blocked === 1 ? "" : "s"} will not run on this setup`
      : `${partial} thing${partial === 1 ? "" : "s"} will run thinner than it should`;

  return (
    <section
      className="card"
      style={{
        padding: "12px 16px",
        marginTop: "var(--s-6)",
        borderLeft: `4px solid var(--${blocked ? "crit" : partial ? "warn" : "ok"})`,
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          width: "100%",
          background: "none",
          border: 0,
          padding: 0,
          cursor: "pointer",
          textAlign: "left",
        }}
      >
        <span className="material-symbols-rounded" aria-hidden="true">
          {allReady ? "check_circle" : "info"}
        </span>
        <div>
          <b>{title ?? "Before you run this"}</b>
          <div className="cs">{headline}</div>
        </div>
        <span className="material-symbols-rounded" style={{ marginLeft: "auto" }} aria-hidden="true">
          {open ? "expand_less" : "expand_more"}
        </span>
      </button>

      {open ? (
        <div style={{ marginTop: 6 }}>
          {caps.map((c) => (
            <Capability key={c.id} cap={c} />
          ))}
        </div>
      ) : null}
    </section>
  );
}
