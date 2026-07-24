import Link from "next/link";
import { MODULE_META } from "@/lib/policy";
import type { Recommendation } from "@/lib/policy";

// Command Center surface for the main dashboard: the top open Policy Radar
// recommendations. Read-only digest — the full recommendation queue lives in
// /policy-radar (refreshed daily). The list is fed from GET /command-center
// (`digest` — already the top-4 OPEN recs).
//
// Severity is intentionally NOT shown here: the digest items (RecommendationResponse)
// carry no `severity` field and the /command-center payload has no KB entries to
// resolve one, so any severity chip would be a fabricated constant. Severity + the
// "N critical" count live on the full /admin/policy-radar queue instead.
export default function CommandDigest({ digest }: { digest: Recommendation[] }) {
  return (
    <section className="card pr-digest">
      <div className="card-h">
        <div className="pr-head">
          <span className="pr-pulse" aria-hidden />
          <div>
            <div className="ct">Policy Radar</div>
            <div className="cs">{digest.length} awaiting confirmation</div>
          </div>
        </div>
        <div className="tools">
          <Link href="/admin/policy-radar" className="ghostbtn">
            Open Radar<span className="material-symbols-rounded">arrow_forward</span>
          </Link>
        </div>
      </div>

      <ul className="pr-list">
        {digest.map((r) => {
          // Guard: an unrecognized target_module from a future backend must
          // degrade to a generic chip, never white-screen the admin home.
          const mod = MODULE_META[r.target] ?? { icon: "extension", label: String(r.target || "module") };
          return (
            <li key={r.id} className="pr-item" style={{ ["--sev" as any]: "var(--muted)" }}>
              <Link href="/admin/policy-radar" className="pr-link">
                <span className="pr-spine" />
                <span className="pr-medallion">
                  <span className="material-symbols-rounded">{mod.icon}</span>
                </span>
                <div className="pr-body">
                  <div className="pr-meta">
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
