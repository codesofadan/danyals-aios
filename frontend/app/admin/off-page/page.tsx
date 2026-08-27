"use client";

import TopBar from "@/components/TopBar";
import "./offpage.css";
import TabBar, { useUrlTab, type TabDef } from "@/components/ui/TabBar";
import BacklinksTab from "@/components/offpage/BacklinksTab";
import Web2Tab from "@/components/offpage/Web2Tab";

// Off-Page, finally in one place. The backend module is ONE router
// (backlinks + citations + web2), and the workspace component has defined the
// three as sibling tabs since it was written - but only Web 2.0 ever got a
// route, this directory sat here containing nothing but a stylesheet, and
// Backlinks had no surface at all. One page, three tabs, the URL owning which.
const TABS: TabDef[] = [
  { key: "backlinks", label: "Backlinks", icon: "link" },
  { key: "citations", label: "Citations", icon: "storefront" },
  { key: "web2", label: "Web 2.0", icon: "rocket_launch" },
];

export default function OffPage() {
  const [tab, setTab] = useUrlTab(TABS);
  return (
    <>
      <TopBar
        eyebrow="Work · Off-Page"
        title="Off-Page"
        searchPlaceholder="Search domains, anchors, placements…"
      />
      <div style={{ marginBottom: "var(--s-7)" }}>
        <TabBar tabs={TABS} active={tab} onSelect={setTab} />
      </div>

      {tab === "backlinks" && (
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Referring domains &amp; links</div>
              <div className="cs">The link profile per client — new, lost, and toxic-flagged.</div>
            </div>
          </div>
          <BacklinksTab />
        </section>
      )}

      {tab === "citations" && (
        // LOCKED, deliberately - the lock moved here with the tab. The citation
        // builder ships no data rather than misleading data: free-directory
        // automation is blocked by captcha/dead forms, and the module stays off
        // until a verified aggregator is wired in. CitationsTab remains in the
        // parked registry; restoring it here is the re-enable step.
        <section className="card" style={{ maxWidth: 560, margin: "48px auto", textAlign: "center" }}>
          <div style={{ padding: "24px 20px 28px" }}>
            <span className="material-symbols-rounded" style={{ fontSize: 44, color: "var(--crit)" }}>
              lock
            </span>
            <div className="ct" style={{ marginTop: 10 }}>Citations — temporarily disabled</div>
            <div className="cs" style={{ marginTop: 8, lineHeight: 1.5 }}>
              The citation builder is off while we finalize a reliable submission source.
              Directory auto-submission isn&apos;t producing dependable live listings yet, so
              the module is locked to avoid misleading data. It&apos;ll be re-enabled once a
              verified data aggregator is wired in.
            </div>
          </div>
        </section>
      )}

      {tab === "web2" && (
        <>
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
      )}
    </>
  );
}
