import TopBar from "@/components/TopBar";
import "../off-page/offpage.css";
import CitationsTab from "@/components/offpage/CitationsTab";

export default function CitationsPage() {
  return (
    <>
      <TopBar
        eyebrow="Local SEO · Citations & NAP"
        title="Citations"
        searchPlaceholder="Search directories, citations, NAP…"
      />
      <section className="card">
        <div className="card-h">
          <div>
            <div className="ct">Citation Builder</div>
            <div className="cs">Directory submissions + NAP consistency — Foursquare, aggregators &amp; the self-hosted bot.</div>
          </div>
        </div>
        <CitationsTab />
      </section>
    </>
  );
}
