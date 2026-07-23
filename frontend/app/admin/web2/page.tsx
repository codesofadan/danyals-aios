import TopBar from "@/components/TopBar";
import "../off-page/offpage.css";
import Web2Tab from "@/components/offpage/Web2Tab";
import { blockIfLockedInProd } from "@/lib/lockedInProd";

export default function Web2Page() {
  blockIfLockedInProd();
  return (
    <>
      <TopBar
        eyebrow="Off-page · Web 2.0 placements"
        title="Web 2.0"
        searchPlaceholder="Search platforms, placements, anchors…"
      />
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
