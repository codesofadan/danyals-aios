import Link from "next/link";
import { SEV_META, MODULE_META, type Severity } from "@/lib/policy";
import type { Recommendation } from "@/lib/policy";

// Command Center surface for the main dashboard: the top open Policy Radar
// recommendations. Read-only digest — the full recommendation queue lives in
// /policy-radar (refreshed daily). The list is fed from GET /command-center
// (`digest` — already the top-4 OPEN recs).
//
// SEVERITY GAP (recorded for the orchestrator): the digest items are
// RecommendationResponse (11 keys, no `severity`), and the /command-center
// payload carries no KB entries to resolve `kbId → severity`. So severity here
// defaults to "info" (critical count is always 0) until the backend adds a
// `severity` field to each digest item.
export default function CommandDigest({ digest }: { digest: Recommendation[] }) {
  const open = digest.map((r) => ({ r, sev: "info" as Severity }));
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
          <Link href="/admin/policy-radar" className="ghostbtn">
            Open Radar<span className="material-symbols-rounded">arrow_forward</span>
          </Link>
        </div>
      </div>

      <ul className="pr-list">
        {open.map(({ r, sev }) => {
          const sm = SEV_META[sev];
          // Guard: an unrecognized target_module from a future backend must
          // degrade to a generic chip, never white-screen the admin home.
          const mod = MODULE_META[r.target] ?? { icon: "extension", label: String(r.target || "module") };
          return (
            <li key={r.id} className="pr-item" data-sev={sev} style={{ ["--sev" as any]: sm.color }}>
              <Link href="/admin/policy-radar" className="pr-link">
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
