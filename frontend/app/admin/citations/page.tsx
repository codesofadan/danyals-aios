"use client";

import TopBar from "@/components/TopBar";
import "../web2/offpage.css";
import CitationsTab from "@/components/offpage/CitationsTab";

// Citations: the NAP/directory listing module. Its own screen, not a tab — it is one of
// the execution modules, and it was previously unreachable: twelve endpoints, fourteen
// hooks and three finished components with no route rendering any of them.
//
// It was locked for a real reason. The gap report used to populate its "live listing
// URLs" from `proof_url` — a screenshot key, and for a while an absolute server path —
// so the module could report a screenshot as a listing a client had earned. Migration
// 0106 gave a listing a real `live_url`, a liveness check that fetches it, and a
// `submitted` status that stops meaning done. That is what re-opened this page.
export default function CitationsPage() {
  return (
    <>
      <TopBar
        eyebrow="Admin · SEO Engine"
        title="Citations"
        searchPlaceholder="Search directories, listings, NAP…"
      />
      <section className="card" style={{ marginBottom: 16 }}>
        <div className="card-h">
          <div>
            <div className="ct">
              <span
                className="material-symbols-rounded"
                style={{ verticalAlign: "middle", marginRight: 8 }}
              >
                fact_check
              </span>
              A listing counts as live only when we have fetched it
            </div>
            <div className="cs">
              &ldquo;Sent&rdquo; and &ldquo;live&rdquo; are counted separately. A citation
              reaches <b>Live</b> only when its public URL was fetched and found to carry
              this business&apos;s name and its phone or address — every other state says
              what it actually is. Directories whose terms forbid automated submission are
              never queued, and are listed with the clause instead.
            </div>
          </div>
        </div>
      </section>
      <section className="card">
        <div className="card-h">
          <div>
            <div className="ct">Citations &amp; NAP</div>
            <div className="cs">
              Audit what already exists, build only what is missing, then re-check that it
              stayed live.
            </div>
          </div>
        </div>
        <CitationsTab />
      </section>
    </>
  );
}
