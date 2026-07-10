import { LIFECYCLE, projects } from "@/lib/milestones";
import { SERIES } from "@/lib/data";

const ACCENT = [SERIES.c1, SERIES.c4, SERIES.c3, SERIES.c2, SERIES.c5];

// How many projects have cleared (completed) each lifecycle stage — a funnel.
const funnel = LIFECYCLE.map((lc) => ({
  label: lc.label,
  icon: lc.icon,
  count: projects.filter((p) => p.stages.find((s) => s.key === lc.key)?.status === "completed").length,
}));

export default function StagePipeline() {
  const total = projects.length;
  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Stage pipeline</div>
          <div className="cs">Projects that have cleared each lifecycle stage.</div>
        </div>
        <span className="pill-tag"><span className="material-symbols-rounded">groups</span>{total} projects</span>
      </div>

      <div className="ms-funnel">
        {funnel.map((f, i) => (
          <div className="ms-fstage" key={f.label}>
            <div className="ms-ftop">
              <span className="ms-fl">
                <span className="material-symbols-rounded">{f.icon}</span>{f.label}
              </span>
              <span className="ms-fv">{f.count}<span className="ms-fo">/{total}</span></span>
            </div>
            <div className="ms-fbar">
              <span style={{ width: `${(f.count / total) * 100}%`, background: ACCENT[i] }} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
