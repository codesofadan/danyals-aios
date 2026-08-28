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
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-h">
          <div>
            <div className="ct">
              <span className="material-symbols-rounded" style={{ verticalAlign: "middle", marginRight: 8 }}>
                science
              </span>
              In testing — not validated for client delivery
            </div>
            <div className="cs">
              Publishing runs behind a human approval gate and per-client account
              ownership. Treat placements made here as test data until the module has
              passed its acceptance run.
            </div>
          </div>
        </div>
      </section>
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
