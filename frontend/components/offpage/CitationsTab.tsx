"use client";

import { useMemo, useState } from "react";
import {
  NAP_META,
  SKIP_REASON_LABEL,
  SUBMIT_STATUS_META,
  type Citation,
  type CitationSkip,
  type CitationSkipReason,
  type NapStatus,
} from "@/lib/offpage";
import { useActOnCitation, useBulkUpdateCitations, useCitations, useCitationGap, useCitationAuditRuns, useRunCitationAudit, useClearCitations } from "@/lib/hooks/offpage";
import CitationAuditProgress from "./CitationAuditProgress";
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

  // The honest split of what "covered" contains. `submitted` means a form was sent and
  // nothing has confirmed a listing came back — Data Axle runs teleresearch for up to
  // three business days, Apple returns state SUBMITTED, GBP needs verification before it
  // appears at all — so it is shown as its own number rather than folded into "live".
  const byStatus = gap?.bySubmitStatus ?? {};
  const awaitingConfirmation =
    (byStatus.submitted ?? 0) + (byStatus.queued ?? 0) + (byStatus.submitting ?? 0);
  const needsAttention = (byStatus.drifted ?? 0) + (byStatus.delisted ?? 0);

  // Every catalog directory NOT built for this client, grouped by reason. Without this a
  // shorter-than-promised list is indistinguishable from a system that quietly failed.
  const skipsByReason = useMemo(() => {
    const out = new Map<CitationSkipReason, CitationSkip[]>();
    for (const s of gap?.skipped ?? []) {
      const bucket = out.get(s.reason);
      if (bucket) bucket.push(s);
      else out.set(s.reason, [s]);
    }
    return [...out.entries()].sort((a, b) => b[1].length - a[1].length);
  }, [gap?.skipped]);

  // Step 1 (the client picker) collapses to a one-line summary once an audit has been
  // run, so Step 2 (build) becomes the focus. Picking a different client — or hitting
  // "Change client / re-audit" — re-opens the full picker.
  const [auditCollapsed, setAuditCollapsed] = useState(false);

  // Audit-first: discover which directories already list this business vs which are
  // missing. Populates the board + gap analysis; build then targets the missing.
  function auditClient() {
    if (!gapClient || runAudit.isPending) return;
    runAudit.mutate(gapClient, {
      onSuccess: (r) => {
        setAuditCollapsed(true); // fold Step 1 away — the build flow is the next step
        // The run id is what the progress panel follows. The backend returns null
        // for it only when the ledger could not be read back - the sweep is still
        // queued, but nothing can report on it, and a panel that stays empty for
        // that reason must not read as "nothing is happening".
        setFlash(
          r?.jobRunId
            ? (r?.detail ?? "Citation audit queued — discovering existing vs missing.")
            : "Audit queued, but its run could not be recorded — there is nothing to follow here. Check Operations, or re-run it.",
        );
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

      {/* ───────── STEP 1 — Audit a client (collapses once an audit has run) ───────── */}
      {auditCollapsed ? (
        <div className={w.step} style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <span className="material-symbols-rounded" style={{ color: "var(--maroon-2, #8c1d2e)" }}>fact_check</span>
          <span className={w.stepH} style={{ margin: 0 }}>
            Audited&nbsp;<b>{gap?.client ?? "client"}</b>
          </span>
          <span className="op-muted" style={{ fontSize: 13 }}>
            {gap?.existingCount ?? 0} existing · {gap?.missingCount ?? 0} missing from catalog
          </span>
          <button className="ghostbtn" style={{ marginLeft: "auto" }} onClick={() => setAuditCollapsed(false)}>
            <span className="material-symbols-rounded">tune</span> Change client / re-audit
          </button>
        </div>
      ) : (
        <div className={w.step}>
          <div className={w.stepH}><span className={w.stepN}>1</span> Audit a client — what&apos;s already built vs missing</div>
          <div className="fld" style={{ marginTop: 4 }}>
            <select value={gapClient} onChange={(e) => { setGapClient(e.target.value); setAuditCollapsed(false); }}>
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
      )}

      {/* The audit's REAL state, for as long as it lasts - not a flash that fades
          after four seconds and leaves the operator guessing whether a sweep is
          still working, already finished, or never started.
          OUTSIDE the collapse ternary on purpose: starting an audit folds Step 1
          away (that is deliberate - the build flow is the next step), and while
          this panel lived INSIDE the expanded branch, pressing "Run citation
          audit" unmounted the one thing that says the audit is running. One
          instance rather than a copy in each branch, so it is not remounted by the
          fold - CitationAuditProgress holds a ref to fire the board refresh once
          per run, and a remount would re-fire it. */}
      {gapClient && <CitationAuditProgress clientId={gapClient} />}

      {/* ───────── Ready to finish — now handled by the work queue ─────────
          REPLACED 2026-08-29. This block used to tell operators to run
          `python tools/finish_citation.py` on their own machine, print the directory
          login and password IN THE PAGE (parsed out of the free-text note field), and
          offer a "Mark published" button that set the listing live on the operator's
          word alone.

          Three defects in one panel: a credential rendered into the DOM, a workflow that
          only existed on one person's laptop, and a completion that was asserted rather
          than checked. The queue at /admin/citations/queue does the same job with a
          claim, pre-computed values, measured time, and a completion that FETCHES the
          URL and looks for the business before it counts. */}
      {readyToFinish.length > 0 && (
        <div className={w.step}>
          <div className={w.stepH}>
            <span className="material-symbols-rounded">assignment_turned_in</span>
            {readyToFinish.length} listing{readyToFinish.length === 1 ? "" : "s"} ready for a human
          </div>
          <div className="cs" style={{ marginBottom: 10 }}>
            These need one human step each — a category choice, a CAPTCHA, a confirmation.
            The queue hands them out one at a time with every field already filled in, and
            checks the listing is really live before it counts.
          </div>
          <div className={w.missList}>
            {readyToFinish.slice(0, 12).map((c) => (
              <span key={c.id} className={w.chip}>{c.directory}</span>
            ))}
            {readyToFinish.length > 12 && (
              <span className={w.chip}>+{readyToFinish.length - 12} more</span>
            )}
          </div>
          <div className="op-toolset" style={{ marginTop: 10 }}>
            <a className="primary-btn" href="/admin/citations/queue" style={{ textDecoration: "none" }}>
              <span className="material-symbols-rounded">play_arrow</span>
              Work the queue
            </a>
          </div>
        </div>
      )}

      {gapClient && gapQ.isLoading && <div className="op-muted">Analysing citations…</div>}
      {gapClient && gapQ.isError && (
        <div className="op-muted">Couldn&apos;t run gap analysis - {(gapQ.error as Error)?.message ?? "try again"}.</div>
      )}
      {gap && (
        <div className={w.step}>
          <div className={w.stepH}><span className={w.stepN}>2</span> Build the missing listings</div>
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
            {/* LIVE and SUBMITTED are separate tiles because they are separate facts, and
                collapsing them is the defect this module is recovering from. A live count
                is only ever rows whose public URL was fetched and found to carry the
                business; everything sent-but-unconfirmed sits in the tile beside it. */}
            <div className={w.stat}>
              <div className={w.statNum}>{gap.liveUrls.length}</div>
              <div className={w.statLbl}>Live — verified on the page</div>
            </div>
            <div className={w.stat}>
              <div className={w.statNum}>{awaitingConfirmation}</div>
              <div className={w.statLbl}>Submitted, not yet confirmed</div>
            </div>
            {needsAttention > 0 && (
              <div className={w.stat}>
                <div className={w.statNum}>{needsAttention}</div>
                <div className={w.statLbl}>Drifted or delisted</div>
              </div>
            )}
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
              <div className="op-muted" style={{ marginTop: 10 }}>
                Live listings — each URL below was fetched and found to carry this
                business&apos;s name and its phone or address:
              </div>
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

          {/* THE SKIP LEDGER. A client comparing "100 promised" against "45 delivered"
              reads the other 55 here, by name and by reason — including the ones whose
              terms forbid automated submission, quoted with the clause we read. */}
          {skipsByReason.length > 0 && (
            <details style={{ marginTop: 12 }}>
              <summary style={{ cursor: "pointer" }} className="op-muted">
                Not built for this client: {gap.skipped.length} directories — and why
              </summary>
              <div style={{ marginTop: 8 }}>
                {skipsByReason.map(([reason, rows]) => (
                  <div key={reason} style={{ marginTop: 10 }}>
                    <div className={w.planLabel}>
                      {rows.length} × {SKIP_REASON_LABEL[reason] ?? reason}
                    </div>
                    <div className={w.missList}>
                      {rows.slice(0, 18).map((s, i) => (
                        <span
                          key={`${s.directory}-${i}`}
                          className={w.chip}
                          title={s.clause || s.detail || undefined}
                        >
                          {s.directory}
                        </span>
                      ))}
                      {rows.length > 18 && (
                        <span className={w.chip}>+{rows.length - 18} more</span>
                      )}
                    </div>
                    {reason === "prohibited_by_terms" && rows[0]?.detail && (
                      <div className="op-muted" style={{ marginTop: 4, fontSize: 12 }}>
                        We do not submit to these. Hover a name for the clause;{" "}
                        <a className="op-url" href={rows[0].detail} target="_blank" rel="noreferrer">
                          source terms
                        </a>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </details>
          )}

          <div className="op-toolset" style={{ marginTop: 12 }}>
            {gap.missingCount > 0 ? (
              <button className="primary-btn" onClick={() => setShowCampaign(true)}>
                <span className="material-symbols-rounded">rocket_launch</span>
                Build the {gap.missingCount} missing
              </button>
            ) : (
              <span className="status-pill ok" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                <span className="material-symbols-rounded">check_circle</span>
                All catalog directories covered — nothing to build
              </span>
            )}
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
                    {/* A settled listing (live/submitted or verified, NAP consistent) has no action —
                        show a done state, not a clickable "Submit". Only offer the action when there's
                        actually work: not yet submitted, or a drifted NAP to re-sync. */}
                    {(c.submitStatus === "submitted" || c.submitStatus === "verified") && c.nap !== "inconsistent" ? (
                      <span className="op-act done" aria-disabled="true">
                        <span className="material-symbols-rounded">check_circle</span>Done
                      </span>
                    ) : (
                      <button
                        className={c.action === "Submit" ? "op-act submit" : "op-act update"}
                        onClick={() => actOnRow(c)}
                        disabled={act.isPending}
                      >
                        <span className="material-symbols-rounded">
                          {c.action === "Submit" ? "add_location_alt" : "edit_location_alt"}
                        </span>{c.action}
                      </button>
                    )}
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
