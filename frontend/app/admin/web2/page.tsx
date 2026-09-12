"use client";

import TopBar from "@/components/TopBar";
import "./offpage.css";
import Web2Tab from "@/components/offpage/Web2Tab";

// Web 2.0 properties: branded articles on high-authority platforms. Its own
// screen, not a tab - it is one of the execution modules, and publishing runs
// behind a human approval gate with per-client account ownership.
export default function Web2Page() {
  return (
    <>
      <TopBar
        eyebrow="Admin · SEO Engine"
        title="Web 2.0"
        searchPlaceholder="Search platforms, placements, anchors…"
      />
      {/* The "In testing — not validated for client delivery" banner was removed on
          owner instruction (2026-09-12). The guarantees it described are not notices,
          they are enforced: publishing still passes a lead's approval gate, accounts
          are still per-client by ownership constraint in `0100`, and the similarity
          gate still records a verdict on every placement. Nothing was relaxed by
          taking the banner down. */}
      <section className="card">
        <div className="card-h">
          <div>
            <div className="ct">Web 2.0 Properties</div>
            <div className="cs">Branded articles on high-authority platforms — human-approved, footprint-diversified, never spam.</div>
          </div>
        </div>
        <Web2Tab />
      </section>
    </>
  );
}
