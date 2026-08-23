import TopBar from "@/components/TopBar";
import "../off-page/offpage.css";
import Web2Tab from "@/components/offpage/Web2Tab";

export default function Web2Page() {
  return (
    <>
      <TopBar
        eyebrow="Off-page · Web 2.0 placements"
        title="Web 2.0"
        searchPlaceholder="Search platforms, placements, anchors…"
      />
      {/* This module was previously wrapped in a <TestGate> that compared against a
          shared username/password COMPILED INTO THE CLIENT BUNDLE, so the credential
          was readable by anyone who opened devtools. It protected nothing while
          implying that it did, which is worse than no lock at all. /admin is already
          behind AuthGuard role="admin", and every /offpage/web2 endpoint is authorized
          server-side, so the real boundary is unchanged by its removal. What the gate
          genuinely carried — "this module is not validated yet" — is now stated
          plainly instead. */}
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-h">
          <div>
            <div className="ct">
              <span
                className="material-symbols-rounded"
                style={{ verticalAlign: "middle", marginRight: 8 }}
              >
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
