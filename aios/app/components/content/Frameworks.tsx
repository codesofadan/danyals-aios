import { FRAMEWORKS } from "@/lib/content";

export default function Frameworks() {
  return (
    <section className="card co-fw-card">
      <div className="card-h">
        <div>
          <div className="ct">Copywriting frameworks</div>
          <div className="cs">7 frameworks, auto-selected by content type + search intent.</div>
        </div>
        <div className="tools">
          <span className="pill-tag info"><span className="material-symbols-rounded">category</span>7 frameworks</span>
        </div>
      </div>

      <div className="co-fw-grid">
        {FRAMEWORKS.map((f) => (
          <div className="co-fw-item" key={f.key}>
            <div className="co-fw-key">{f.key}</div>
            <div className="co-fw-exp">{f.expansion}</div>
            <div className="co-fw-best">
              <span className="material-symbols-rounded">check_circle</span>
              {f.bestFor}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
