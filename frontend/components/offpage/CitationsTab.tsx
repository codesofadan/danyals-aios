"use client";

import { useMemo, useState } from "react";
import { NAP_META, SUBMIT_STATUS_META, type Citation, type NapStatus } from "@/lib/offpage";
import { useActOnCitation, useBulkUpdateCitations, useCitations, useCitationGap, useRunCitationAudit, useClearCitations } from "@/lib/hooks/offpage";
import { useClients } from "@/lib/hooks/clients";
import CitationCampaignModal from "./CitationCampaignModal";
import AuditPlanPanel from "./AuditPlanPanel";
import w from "./Wave4.module.css";

const NAP_SOURCE_LABEL: Record<string, string> = {
  submission_profile: "a saved submission profile",
  client_profile: "the client's own NAP (auto-derived)",
  none: "none captured yet",
};

type FilterKey = "all" | NapStatus;

const FILTERS: { key: FilterKey; label: string }[] = [
  { key: "all", label: "All" },
  { key: "consistent", label: "Consistent" },
  { key: "inconsistent", label: "Inconsistent" },
  { key: "missing", label: "Missing" },
];

export default function CitationsTab() {
  const [filter, setFilter] = useState<FilterKey>("all");
  const citationsQ = useCitations();
  const list: Citation[] = citationsQ.data ?? [];
  const bulk = useBulkUpdateCitations();
  const act = useActOnCitation();
  const [flash, setFlash] = useState<string | null>(null);
  const [showCampaign, setShowCampaign] = useState(false);
  const [gapClient, setGapClient] = useState("");
  const clientsQ = useClients();
  const gapQ = useCitationGap(gapClient || undefined);
  const gap = gapQ.data;
  const runAudit = useRunCitationAudit();
  const clearCitations = useClearCitations();

  // Audit-first: discover which directories already list this business vs which are
  // missing. Populates the board + gap analysis; build then targets the missing.
  function auditClient() {
    if (!gapClient || runAudit.isPending) return;
    runAudit.mutate(gapClient, {
      onSuccess: (r) => {
        setFlash(r?.detail ?? "Citation audit queued — discovering existing vs missing.");
        window.setTimeout(() => setFlash(null), 4200);
      },
      onError: (err) => {
        setFlash(`Audit couldn't start — ${(err as Error)?.message ?? "add the client's NAP first"}.`);
        window.setTimeout(() => setFlash(null), 4200);
      },
    });
  }

  // Clear a client's citations so it can be re-audited from a clean slate.
  function clearForClient() {
    if (!gapClient || clearCitations.isPending) return;
    if (!window.confirm("Remove ALL citation rows for this client? It can then be re-audited fresh.")) return;
    clearCitations.mutate(gapClient, {
      onSuccess: (r) => {
        setFlash(`Cleared ${r?.removed ?? 0} citation row(s) — run an audit to rediscover.`);
        window.setTimeout(() => setFlash(null), 4200);
      },
      onError: (err) => {
        setFlash(`Clear failed — ${(err as Error)?.message ?? "try again"}.`);
        window.setTimeout(() => setFlash(null), 4200);
      },
    });
  }

  // Mark ONE listing handled — Submit a missing one or Update a drifted one.
  function actOnRow(c: Citation) {
    if (act.isPending) return;
    act.mutate(
      { id: c.id, action: c.action },
      {
        onSuccess: () => {
          setFlash(`${c.action === "Submit" ? "Submitted" : "Updated"} ${c.directory} — NAP synced.`);
          window.setTimeout(() => setFlash(null), 3200);
        },
        onError: (err) => {
          setFlash(`${c.action} failed — ${(err as Error)?.message ?? "try again"}.`);
          window.setTimeout(() => setFlash(null), 3200);
        },
      },
    );
  }

  const rows = useMemo(
    () => list.filter((c) => filter === "all" || c.nap === filter),
    [list, filter],
  );

  const inconsistentCount = list.filter((c) => c.nap === "inconsistent").length;

  // The handoff queue: accounts the bot created + prepared that a human finishes in
  // the browser with one click (directories that can't be fully auto-published).
  const readyToFinish = useMemo(
    () => list.filter((c) => c.submitStatus === "ready_for_human"),
    [list],
  );

  // Bulk update — push every drifted listing back to consistent (human-approved run).
  // Backend resolves each id to `consistent`, then the list refetches for fresh state.
  function bulkUpdate() {
    if (inconsistentCount === 0 || bulk.isPending) return;
    const ids = list.filter((c) => c.nap === "inconsistent").map((c) => c.id);
    bulk.mutate(ids, {
      onSuccess: () => {
        setFlash(`Reconciled ${inconsistentCount} inconsistent listing${inconsistentCount > 1 ? "s" : ""} — NAP synced.`);
        window.setTimeout(() => setFlash(null), 3200);
      },
      onError: (err) => {
        setFlash(`Bulk update failed — ${(err as Error)?.message ?? "try again"}.`);
        window.setTimeout(() => setFlash(null), 3200);
      },
    });
  }

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">storefront</span>
          Citations — audit a client, build the missing listings, and monitor the live ones. Listings are
          built locally; any that need a human step are finished on your machine, and only completed listings appear here.
        </div>
      </div>

      {showCampaign && (
        <CitationCampaignModal onClose={() => setShowCampaign(false)} initialClientId={gapClient || undefined} />
      )}

      {flash && (
        <div className="op-flash">
          <span className="material-symbols-rounded">task_alt</span>{flash}
        </div>
      )}

      {/* ───────── STEP 1 — Audit a client ───────── */}
      <div className={w.step}>
        <div className={w.stepH}><span className={w.stepN}>1</span> Audit a client — what&apos;s already built vs missing</div>
        <div className="fld" style={{ marginTop: 4 }}>
          <select value={gapClient} onChange={(e) => setGapClient(e.target.value)}>
            <option value="">Choose a client…</option>
            {(clientsQ.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>{c.cn}</option>
            ))}
          </select>
        </div>
        {gapClient && (
          <div className="op-toolset" style={{ marginBottom: 2 }}>
            <button className="primary-btn" onClick={auditClient} disabled={runAudit.isPending}>
              <span className="material-symbols-rounded">search_check</span>
              {runAudit.isPending ? "Auditing…" : "Run citation audit"}
            </button>
            <button className="ghostbtn co-reject" onClick={clearForClient} disabled={clearCitations.isPending}>
              <span className="material-symbols-rounded">delete_sweep</span>
              {clearCitations.isPending ? "Clearing…" : "Clear citations"}
            </button>
          </div>
        )}
        {!gapClient && (
          <div className="op-muted" style={{ fontSize: 13 }}>Pick a client to see its citation coverage and build the gaps.</div>
        )}
      </div>

      {/* ───────── Ready to finish — the handoff queue ───────── */}
      {readyToFinish.length > 0 && (
        <div className={w.step} style={{ background: "var(--blush, #f8ecee)", borderColor: "var(--rose, #b85c6b)" }}>
          <div className={w.stepH}>
            <span className="material-symbols-rounded" style={{ color: "var(--maroon-2, #8c1d2e)" }}>touch_app</span>
            {readyToFinish.length} ready to finish locally
          </div>
          <div className="cs" style={{ marginBottom: 10 }}>
            These are finished on your machine, not here: run <code>python tools/finish_citation.py</code> locally
            and Claude Code opens each directory in a browser — logged in and pre-filled — so you do the one human
            step (category / captcha), click <b>Publish</b>, then mark it done. Only completed listings stay on the dashboard.
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {readyToFinish.map((c) => {
              const login = /Login:\s*([^\s|]+)/.exec(c.note)?.[1] ?? "";
              const pass = /password:\s*([^\s|]+)/.exec(c.note)?.[1] ?? "";
              return (
                <div key={c.id} style={{
                  display: "flex", alignItems: "center", gap: 10, padding: "10px 12px",
                  background: "var(--white, #fff)", border: "1px solid var(--line)", borderRadius: 8, flexWrap: "wrap",
                }}>
                  <span style={{ fontWeight: 700, minWidth: 150 }}>{c.directory}</span>
                  {login && (
                    <span className="cs" style={{ fontFamily: "monospace", flex: 1, minWidth: 200 }}>
                      {login} <span className="op-muted">/</span> {pass}
                      <button className="ghostbtn" style={{ padding: "2px 6px", marginLeft: 6 }}
                        onClick={() => navigator.clipboard?.writeText(`${login}\t${pass}`)}
                        title="Copy login">
                        <span className="material-symbols-rounded" style={{ fontSize: 15 }}>content_copy</span>
                      </button>
                    </span>
                  )}
                  {c.handoffUrl && (
                    <a className="ghostbtn" href={c.handoffUrl} target="_blank" rel="noopener noreferrer"
                      style={{ textDecoration: "none" }}>
                      <span className="material-symbols-rounded">open_in_new</span>Open directory
                    </a>
                  )}
                  <button className="primary-btn" onClick={() => actOnRow(c)} disabled={act.isPending}>
                    <span className="material-symbols-rounded">check</span>Mark published
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {gapClient && gapQ.isLoading && <div className="op-muted">Analysing citations…</div>}
      {gapClient && gapQ.isError && (
        <div className="op-muted">Couldn&apos;t run gap analysis - {(gapQ.error as Error)?.message ?? "try again"}.</div>
      )}
      {gap && (
        <div>
          <div className={w.rollup}>
            <span>
              NAP source: <b>{NAP_SOURCE_LABEL[gap.napSource] ?? gap.napSource}</b>
            </span>
            <span>Vertical: <b>{gap.resolvedVertical ?? "general only"}</b></span>
            {!gap.hasNap && (
              <span className="status-pill warn">
                No business profile yet - add its NAP (Clients &gt; Edit) so a build has real data.
              </span>
            )}
          </div>
          <div className={w.stats}>
            <div className={w.stat}>
              <div className={w.statNum}>{gap.existingCount}</div>
              <div className={w.statLbl}>Existing citations</div>
            </div>
            <div className={w.stat}>
              <div className={w.statNum}>{gap.coveredCount}</div>
              <div className={w.statLbl}>Covered (in-flight or live)</div>
            </div>
            <div className={w.stat}>
              <div className={w.statNum}>{gap.missingCount}</div>
              <div className={w.statLbl}>Missing from the catalog</div>
            </div>
            <div className={w.stat}>
              <div className={w.statNum}>{gap.liveUrls.length}</div>
              <div className={w.statLbl}>Live listing URLs</div>
            </div>
          </div>

          {gap.missing.length > 0 && (
            <>
              <div className="op-muted" style={{ marginTop: 10 }}>
                Missing directories (build order - the exact target a campaign queues):
              </div>
              <div className={w.missList}>
                {gap.missing.slice(0, 24).map((d) => (
                  <span key={d.id} className={w.chip}>{d.name}</span>
                ))}
                {gap.missing.length > 24 && <span className={w.chip}>+{gap.missing.length - 24} more</span>}
              </div>
            </>
          )}

          {gap.liveUrls.length > 0 && (
            <>
              <div className="op-muted" style={{ marginTop: 10 }}>Live listings already earned:</div>
              {gap.liveUrls.slice(0, 12).map((u, i) => (
                <div key={i} className={w.urlRow}>
                  <span className="status-pill ok">{u.status}</span>
                  <a className="op-url" href={u.url} target="_blank" rel="noreferrer">
                    {u.directory} <span className="material-symbols-rounded">open_in_new</span>
                  </a>
                </div>
              ))}
            </>
          )}

          <div className="op-toolset" style={{ marginTop: 12 }}>
            <button className="primary-btn" onClick={() => setShowCampaign(true)}>
              <span className="material-symbols-rounded">rocket_launch</span>
              Build the {gap.missingCount} missing
            </button>
          </div>
        </div>
      )}

      {/* The prioritized audit plan (generic → country → niche) for the chosen client. */}
      <AuditPlanPanel clientId={gapClient || undefined} />

      {/* ───────── Monitor — all listings ───────── */}
      <div className={w.stepH} style={{ marginTop: 8, flexWrap: "wrap" }}>
        <span className="material-symbols-rounded">table_rows</span> All listings
        <div className="op-toolset" style={{ marginLeft: "auto" }}>
          <div className="seg">
            {FILTERS.map((f) => (
              <button key={f.key} className={filter === f.key ? "on" : undefined} onClick={() => setFilter(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
          <button className="ghostbtn" onClick={bulkUpdate} disabled={inconsistentCount === 0 || bulk.isPending}>
            <span className="material-symbols-rounded">sync</span>
            {bulk.isPending ? "Syncing…" : `Bulk update (${inconsistentCount})`}
          </button>
        </div>
      </div>

      <div className="tbl-wrap">
        <table className="tbl op-tbl">
          <thead>
            <tr>
              <th>Client</th>
              <th>Directory</th>
              <th>NAP status</th>
              <th>Detail</th>
              <th>State / action</th>
              <th>Submission</th>
            </tr>
          </thead>
          <tbody>
            {citationsQ.isLoading && (
              <tr><td colSpan={6} className="op-empty">Loading citations…</td></tr>
            )}
            {citationsQ.isError && !citationsQ.isLoading && (
              <tr><td colSpan={6} className="op-empty">Couldn&apos;t load citations — {(citationsQ.error as Error)?.message ?? "try again"}.</td></tr>
            )}
            {!citationsQ.isLoading && !citationsQ.isError && rows.map((c) => {
              const meta = NAP_META[c.nap];
              const submitMeta = SUBMIT_STATUS_META[c.submitStatus];
              return (
                <tr key={c.id}>
                  <td className="op-strong">{c.client}</td>
                  <td>
                    <span className="op-dir">
                      <span className="material-symbols-rounded">location_on</span>{c.directory}
                    </span>
                  </td>
                  <td><span className={`status-pill ${meta.cls}`}>{meta.label}</span></td>
                  <td className="op-muted">{c.note}</td>
                  <td>
                    <button
                      className={c.action === "Submit" ? "op-act submit" : "op-act update"}
                      onClick={() => actOnRow(c)}
                      disabled={act.isPending}
                    >
                      <span className="material-symbols-rounded">
                        {c.action === "Submit" ? "add_location_alt" : "edit_location_alt"}
                      </span>{c.action}
                    </button>
                  </td>
                  <td>
                    <span className={`status-pill ${submitMeta.cls}`}>{submitMeta.label}</span>
                    {c.proofUrl && (
                      <a className="op-url" href={c.proofUrl} target="_blank" rel="noreferrer" style={{ marginLeft: 6 }}>
                        <span className="material-symbols-rounded">image</span>
                      </a>
                    )}
                  </td>
                </tr>
              );
            })}
            {!citationsQ.isLoading && !citationsQ.isError && rows.length === 0 && (
              <tr><td colSpan={6} className="op-empty">No citations match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
