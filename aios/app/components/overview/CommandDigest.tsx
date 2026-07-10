import Link from "next/link";
import { recommendations, kbEntries, SEV_META, MODULE_META, REC_OPEN } from "@/lib/policy";

// Command Center surface for the main dashboard: the top open Policy Radar
// recommendations awaiting the Super Admin's confirmation. Read-only digest —
// full acknowledge/apply/dismiss actions live in /policy-radar.
export default function CommandDigest() {
  const open = recommendations.filter((r) => REC_OPEN.includes(r.status)).slice(0, 4);

  return (
    <section className="card">
      <div className="card-h">
        <div>
          <div className="ct">Command Center · Policy Radar</div>
          <div className="cs">{open.length} recommendations awaiting confirmation</div>
        </div>
        <div className="tools">
          <Link href="/policy-radar" className="ghostbtn">
            Open Radar<span className="material-symbols-rounded">arrow_forward</span>
          </Link>
        </div>
      </div>

      <div className="ov-recs">
        {open.map((r) => {
          const sev = kbEntries.find((k) => k.id === r.kbId)?.severity ?? "info";
          const sm = SEV_META[sev];
          const mod = MODULE_META[r.target];
          return (
            <Link key={r.id} href="/policy-radar" className="ov-rec">
              <span className="ov-rec-dot" style={{ background: sm.color, boxShadow: `0 0 8px ${sm.color}` }} />
              <div className="ov-rec-main">
                <div className="ov-rec-title">{r.title}</div>
                <div className="ov-rec-why">{r.why}</div>
                <div className="ov-rec-tags">
                  <span className="pill-tag sm"><span className="material-symbols-rounded">{mod.icon}</span>{mod.label}</span>
                  <span className="ov-rec-sev" style={{ color: sm.color }}>{sm.label}</span>
                  <span className="ov-rec-region">· {r.regionLabel}</span>
                </div>
              </div>
              <span className="status-pill mut">{r.status}</span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
