import Link from "next/link";
import { recommendations, kbEntries, SEV_META, MODULE_META, REC_OPEN } from "@/lib/policy";

// Command Center surface for the main dashboard: the top open Policy Radar
// recommendations awaiting the Super Admin's confirmation. Read-only digest —
// full acknowledge/apply/dismiss actions live in /policy-radar.
export default function CommandDigest() {
  const open = recommendations
    .filter((r) => REC_OPEN.includes(r.status))
    .slice(0, 4)
    .map((r) => ({ r, sev: kbEntries.find((k) => k.id === r.kbId)?.severity ?? "info" }));
  const critical = open.filter((x) => x.sev === "critical").length;

  return (
    <section className="card pr-digest">
      <div className="card-h">
        <div className="pr-head">
          <span className="pr-pulse" aria-hidden />
          <div>
            <div className="ct">Policy Radar</div>
            <div className="cs">
              {open.length} awaiting confirmation
              {critical > 0 && <span className="pr-crit-note"> · {critical} critical</span>}
            </div>
          </div>
        </div>
        <div className="tools">
          <Link href="/policy-radar" className="ghostbtn">
            Open Radar<span className="material-symbols-rounded">arrow_forward</span>
          </Link>
        </div>
      </div>

      <ul className="pr-list">
        {open.map(({ r, sev }) => {
          const sm = SEV_META[sev];
          const mod = MODULE_META[r.target];
          return (
            <li key={r.id} className="pr-item" data-sev={sev} style={{ ["--sev" as any]: sm.color }}>
              <Link href="/policy-radar" className="pr-link">
                <span className="pr-spine" />
                <span className="pr-medallion">
                  <span className="material-symbols-rounded">{mod.icon}</span>
                </span>
                <div className="pr-body">
                  <div className="pr-meta">
                    <span className="pr-sev">{sm.label}</span>
                    <span className="pr-mod">{mod.label}</span>
                    <span className="pr-region">{r.regionLabel}</span>
                    <span className={`pr-status pr-status-${r.status}`}>{r.status}</span>
                  </div>
                  <div className="pr-title">{r.title}</div>
                  <div className="pr-why">{r.why}</div>
                </div>
                <span className="pr-go material-symbols-rounded">chevron_right</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
