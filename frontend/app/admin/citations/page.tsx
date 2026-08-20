import TopBar from "@/components/TopBar";
import "../off-page/offpage.css";

// LOCKED: the citation engine is disabled while we finalize a reliable data
// source (the free-directory automation is blocked by captcha/dead forms; a paid
// aggregator is being evaluated). Re-enable by restoring the CitationsTab render
// below (see git history) once the engine is ready.
export default function CitationsPage() {
  return (
    <>
      <TopBar
        eyebrow="Local SEO · Citations & NAP"
        title="Citations"
        searchPlaceholder="Search directories, citations, NAP…"
      />
      <section className="card" style={{ maxWidth: 560, margin: "48px auto", textAlign: "center" }}>
        <div style={{ padding: "24px 20px 28px" }}>
          <span
            className="material-symbols-rounded"
            style={{ fontSize: 44, color: "var(--maroon-2, #8c1d2e)" }}
          >
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
    </>
  );
}
