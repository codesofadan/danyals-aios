"use client";

import { useCallback, useState } from "react";
import {
  auditDepths,
  DEPTH_LABEL,
  TYPE_LABEL,
  type AuditDepth,
  type AuditRow,
  type JobStatus,
  type Tier,
} from "@/lib/audit";
import ConfirmDialog from "@/components/ui/ConfirmDialog";
import {
  AUDITS_PAGE,
  useAudits,
  useAuditEstimate,
  useAuditStats,
  useCreateAudit,
  useSetAuditVisibility,
  type AuditEstimate,
} from "@/lib/hooks/audits";
import { useClients } from "@/lib/hooks/clients";
import { useSpendHalted } from "@/lib/hooks/cost";
import Link from "next/link";
import { downloadFile, getReportHtml } from "@/lib/api";
import ReportViewer from "@/components/report/ReportViewer";
import AuditStats from "./AuditStats";

const STATUS_META: Record<JobStatus, { pill: string; label: string; icon: string }> = {
  queued: { pill: "mut", label: "Queued", icon: "schedule" },
  running: { pill: "info", label: "Running", icon: "progress_activity" },
  done: { pill: "ok", label: "Done", icon: "check_circle" },
  failed: { pill: "warn", label: "Failed", icon: "error" },
};

// A run that cost materially MORE than it was quoted. This is the comparison the
// platform could never make before: the estimate was a flat constant that left no
// trace on the row, so nobody could tell whether the cost model was any good.
// Flagged one way only - coming in under estimate is not a problem to chase.
const OVERSPEND_TOLERANCE = 1.15;

function overspent(r: { cost: number | null; estimatedCost: number | null }) {
  if (r.cost === null || r.estimatedCost === null || r.estimatedCost <= 0) return false;
  return r.cost > r.estimatedCost * OVERSPEND_TOLERANCE;
}

function scoreClass(score: number) {
  if (score >= 80) return "ok";
  if (score >= 65) return "warn";
  return "crit";
}

// Types that spend on a paid provider / the AI agents. A selection that touches
// any of these runs as a Paid audit (cost-gated); an empty or free-only selection
// stays Free. Derived from the single source of truth in lib/audit.ts.

export default function AuditWorkspace() {
  // How many server pages of history to hold. The list took the server default
  // of 50 with no way to ask for more, so an agency past its first fifty audits
  // had older runs no screen could reach - and the filters and search operated
  // on that window silently, so "failed" could render as "no failures".
  const [pages, setPages] = useState(1);
  const auditsQ = useAudits(pages); // live: GET /audits, polls while a job is in flight
  const statsQ = useAuditStats();
  const clientsQ = useClients();
  const createAudit = useCreateAudit();
  const setVisibility = useSetAuditVisibility();
  const { halted } = useSpendHalted(); // global API-spend kill-switch
  // The audit awaiting a "share this into the client's portal" confirmation.
  const [sharePrompt, setSharePrompt] = useState<AuditRow | null>(null);

  const rows = auditsQ.data ?? [];
  const clients = clientsQ.data ?? [];

  // Run-new-audit form state. DEPTH is the only scope control: every audit covers
  // every dimension, and depth decides how much paid corroboration it buys. The
  // audit-type picker that used to sit here was removed because it could not do
  // what its labels said - the engine has no per-dimension flag, so the
  // deterministic crawl always ran in full and a run scoped to "on-page +
  // technical" still came back with GEO and strategy findings.
  const [url, setUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [depth, setDepth] = useState<AuditDepth>("standard");
  // Off by default, matching the server. Sharing a report is a decision someone
  // makes, not a side effect of picking a client.
  const [shareWithClient, setShareWithClient] = useState(false);
  const effectiveClientId = clientId || clients[0]?.id || "";

  // The quote currently on screen, or null. Held in state (not react-query cache)
  // because a confirmation is bound to ONE figure: the moment any input changes,
  // the number the operator agreed to is no longer the number the run would cost,
  // so the quote is dropped rather than reused. The server enforces the same rule
  // independently - it compares the echoed figure against a freshly computed one
  // and returns 409 if they have drifted.
  const estimateM = useAuditEstimate();
  const [quote, setQuote] = useState<AuditEstimate | null>(null);

  // Table filters
  const [statusFilter, setStatusFilter] = useState<"all" | JobStatus>("all");
  // Filter by DEPTH, in one select. It replaced eight type chips that filtered on
  // a distinction the runs never actually had.
  const [depthFilter, setDepthFilter] = useState<"all" | AuditDepth>("all");
  const [search, setSearch] = useState("");

  // The audit whose report.html is open in the full-screen page-viewer (null = none).
  const [viewId, setViewId] = useState<string | null>(null);
  const viewRow = viewId ? rows.find((r) => r.id === viewId) ?? null : null;
  // Bearer-authed fetch of the self-contained report.html for the viewer. The SAME
  // document the PDF is rendered from, so the on-screen report matches the download.
  const loadReport = useCallback(() => getReportHtml(`/audits/${viewId}/report.html`), [viewId]);

  // A run at Standard or Advanced spends metered budget, so it is blocked while
  // the global API-spend halt is engaged.
  const canRun = url.trim().length > 3 && !!effectiveClientId && !createAudit.isPending && !halted;

  // TIER FOLLOWS DEPTH, and there is nothing else it could follow. Basic runs
  // `--mode free`, which the engine enforces by clearing every provider after
  // parsing; Standard and Advanced buy paid work. One control, one answer.
  //
  // It used to be derived from the type picker as `types.some(isPaid)` - false
  // for an empty array, which MEANT the full comprehensive run. So the most
  // expensive audit the platform can launch was sent as "Free" and skipped both
  // cost gates server-side. That combination is now unrepresentable rather than
  // merely refused: the value that names the run is the value that prices it.
  const tier: Tier = depth === "free" ? "Free" : "Paid";
  const effectiveDepth: AuditDepth = depth;
  const depthMeta = auditDepths.find((d) => d.key === effectiveDepth);
  const needsConfirm = depthMeta?.confirms ?? false;
  // A quote only counts for the request it was issued against.
  const confirmed =
    quote !== null && quote.depth === effectiveDepth && quote.tier === tier;

  const dropQuote = () => setQuote(null);

  const pickDepth = (k: AuditDepth) => {
    dropQuote();
    setDepth(k);
  };

  // The URL is sent so a deep quote can measure the site's own sitemap and price
  // the run it would actually make, rather than the depth's 300-page ceiling.
  const getEstimate = () =>
    estimateM.mutate(
      { tier, depth: effectiveDepth, url: url.trim() },
      { onSuccess: setQuote },
    );

  const runAudit = () => {
    if (!canRun) return;
    // A depth that requires confirmation cannot be launched until a quote for THIS
    // exact request has been shown and accepted. The server enforces it too; this
    // is the step that makes the number visible, which is the actual point.
    if (needsConfirm && !confirmed) return;
    const clean = url.trim().replace(/^https?:\/\//, "").replace(/\/$/, "");
    createAudit.mutate(
      {
        client_id: effectiveClientId,
        url: clean,
        tier,
        depth: effectiveDepth,
        visible_to_client: shareWithClient,
        // Echo the exact figure that was displayed. If unit prices or the depth's
        // page budget moved since the quote, the server returns 409 rather than
        // charging against a number the operator never saw.
        ...(needsConfirm && quote
          ? {
              // Echo BOTH: the budget the quote was priced for and the figure
              // itself. The server re-derives the price from the budget and
              // compares - so the confirmation is checked arithmetically rather
              // than by re-measuring a site that may have changed meanwhile.
              max_pages: quote.pages,
              confirmed_estimate: quote.estimatedCost,
            }
          : {}),
      },
      {
        onSuccess: () => {
          setUrl("");
          // Reset the share choice too: it applied to THAT audit, and leaving it
          // on would silently publish the next one.
          setShareWithClient(false);
          dropQuote();
        },
      },
    );
  };

  const q = search.trim().toLowerCase();
  const shown = rows.filter((r) => {
    if (statusFilter !== "all" && r.status !== statusFilter) return false;
    if (depthFilter !== "all" && r.depth !== depthFilter) return false;
    // Search matches the two things an operator actually remembers: who it was
    // for, and which site. Case-insensitive substring, no fuzzy matching - a
    // near-miss that silently returns the wrong client is worse than no match.
    if (q && !`${r.client} ${r.url}`.toLowerCase().includes(q)) return false;
    return true;
  });

  const runningCount = rows.filter((r) => r.status === "running").length;
  const createErr = createAudit.error instanceof Error ? createAudit.error.message : null;
  const estimateErr = estimateM.error instanceof Error ? estimateM.error.message : null;

  return (
    <>
      <AuditStats
        lifetime={statsQ.data?.lifetime ?? rows.length}
        thisMonth={statsQ.data?.thisMonth ?? rows.length}
        runningNow={runningCount}
        avgCostUsd={statsQ.data?.avgCostUsd ?? 0}
      />

      <div className="row">
        {/* Audit queue / history */}
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Audit Queue &amp; History</div>
            </div>
          </div>

          <div className="au-filters">
            <div className="seg">
              {(["all", "queued", "running", "done", "failed"] as const).map((s) => (
                <button key={s} className={statusFilter === s ? "on" : undefined} onClick={() => setStatusFilter(s)}>
                  {s === "all" ? "All" : STATUS_META[s].label}
                </button>
              ))}
            </div>
            <label className="au-search">
              <span className="material-symbols-rounded">search</span>
              <input
                type="search"
                placeholder="Search client or site…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Search audits by client or site"
              />
              {search ? (
                <button type="button" onClick={() => setSearch("")} aria-label="Clear search">
                  <span className="material-symbols-rounded">close</span>
                </button>
              ) : null}
            </label>
            {/* One select, not eight chips. The chips filtered by audit TYPE, a
                distinction the runs never actually had - every audit covers every
                dimension. Depth is the axis that does differ between runs. */}
            <label className="au-depthfilter">
              <span>Depth</span>
              <select
                value={depthFilter}
                onChange={(e) => setDepthFilter(e.target.value as "all" | AuditDepth)}
                aria-label="Filter audits by depth"
              >
                <option value="all">All depths</option>
                {auditDepths.map((d) => (
                  <option key={d.key} value={d.key}>{d.label}</option>
                ))}
              </select>
            </label>
          </div>

          {/* `au-tbl-wrap` is the query container. The fold below has to respond to
              the space the TABLE has, not the space the window has - inside the
              admin shell the rail takes 76-258px of it, so a viewport breakpoint
              folds at the wrong moment in both directions. */}
          <div className="tbl-wrap au-tbl-wrap">
            <table className="tbl au-tbl">
              <thead>
                {/* SEVEN columns, not ten. Nothing was dropped - the pairs that
                    only mean something together were merged into one cell, so each
                    column now answers exactly one question:

                      Client + Site/URL  -> Audit   (a URL is an attribute of the
                                                     audit, not a peer of the client)
                      Type + Tier + depth -> Scope  (all three answer "how much
                                                     audit is this")
                      Status + Run time  -> Status  (a duration means nothing except
                                                     next to what it was doing)

                    Ten columns did not fit, so the eye had nowhere to rest and the
                    numeric columns - the ones actually scanned - were pushed off
                    the right edge. */}
                <tr>
                  <th>Audit</th>
                  <th className="au-h-scope">Scope</th>
                  <th>Status</th>
                  <th className="num">Score</th>
                  <th className="num au-h-cost">Cost</th>
                  {/* Exposure a reviewer cannot see is exposure nobody reviews.
                      This was chosen once at creation and then invisible, so an
                      operator had no way to tell which of a client's audits that
                      client could already read. */}
                  <th>Client sees</th>
                  <th>Artifacts</th>
                </tr>
              </thead>
              <tbody>
                {auditsQ.isLoading && (
                  <tr><td colSpan={7} className="au-empty">Loading audits…</td></tr>
                )}
                {auditsQ.isError && !auditsQ.isLoading && (
                  <tr><td colSpan={7} className="au-empty">Couldn&apos;t load audits - {(auditsQ.error as Error)?.message ?? "try again"}.</td></tr>
                )}
                {!auditsQ.isLoading && !auditsQ.isError && shown.map((r) => {
                  const sm = STATUS_META[r.status];
                  return (
                    <tr key={r.id}>
                      <td className="au-c-audit">
                        {/* The row IS the way into the audit. The artifact column
                            carries downloads only, so the name has to be the link. */}
                        <Link className="au-client au-open" href={`/admin/audits/${r.id}`}>
                          {r.client}
                        </Link>
                        <span className="au-url" title={r.url}>
                          <span className="material-symbols-rounded">link</span>{r.url}
                        </span>
                        <div className="au-when">
                          {r.when}
                          {/* Shown only once the Scope column folds away below
                              1180px. Whether a run was billable is not something a
                              queue may quietly stop saying. */}
                          <span className={`au-tier au-tier-fold ${r.tier.toLowerCase()}`}>
                            {r.tier}
                          </span>
                        </div>
                      </td>
                      <td className="au-c-scope au-h-scope">
                        <div className="au-types">
                          <span className={`au-tier ${r.tier.toLowerCase()}`}>{r.tier}</span>
                          {/* The DEPTH label, which is what scope means now. A
                              "Full audit" tag on every row said nothing, because
                              every run is one. Historical rows created under the
                              audit-type picker still show what they were asked
                              for - that is a fact about them, not a claim about
                              how audits work today. */}
                          {r.depth ? (
                            <span className="au-type-tag au-type-full">
                              {DEPTH_LABEL[r.depth]}
                            </span>
                          ) : null}
                          {r.types.map((k) => (
                            <span key={k} className="au-type-tag">{TYPE_LABEL[k]}</span>
                          ))}
                        </div>
                        {/* Depth is null on runs created before it was recorded - that
                            is "breadth unknown", not "free", so it renders as a dash
                            rather than borrowing a default it never had. The depth
                            NAME is the chip above; this line carries only what the
                            chip cannot say, which is how many pages it covered. */}
                        <div className="au-when">
                          {r.depth === null
                            ? "breadth not recorded"
                            : r.maxPages
                              ? `up to ${r.maxPages} pages`
                              : ""}
                        </div>
                      </td>
                      <td className="au-c-status">
                        <span className={`status-pill ${sm.pill}`}>
                          <span className={`material-symbols-rounded${r.status === "running" ? " au-spin" : ""}`}>{sm.icon}</span>
                          {sm.label}
                        </span>
                        <div className="au-when au-runtime">{r.runtime}</div>
                      </td>
                      <td className="num">
                        {r.score === null ? (
                          <span className="au-dash">-</span>
                        ) : (
                          <span className={`au-score ${scoreClass(r.score)}`}>{r.score}</span>
                        )}
                      </td>
                      <td className="num au-h-cost au-c-cost">
                        {r.cost === null ? (
                          <span className="au-dash" title="Nothing spent yet - the engine has not started">-</span>
                        ) : (
                          <span className={overspent(r) ? "au-score crit" : undefined}>
                            ${r.cost.toFixed(2)}
                          </span>
                        )}
                        {r.estimatedCost !== null && (
                          <div className="au-when">est ${r.estimatedCost.toFixed(2)}</div>
                        )}
                      </td>
                      <td>
                        <button
                          className={`au-share${r.visibleToClient ? " is-on" : ""}`}
                          aria-pressed={r.visibleToClient}
                          disabled={setVisibility.isPending}
                          title={
                            r.visibleToClient
                              ? "This client can read this audit in their portal. Click to stop sharing it."
                              : "Internal only. Click to share it into the client's portal."
                          }
                          onClick={() => {
                            // Only SHARING asks. Publishing an audit into a
                            // tenant's portal discloses it, and un-sharing later
                            // cannot un-read it; withdrawing is the safe
                            // direction and stays one click.
                            if (r.visibleToClient) {
                              setVisibility.mutate({ id: r.id, visible: false });
                            } else {
                              setSharePrompt(r);
                            }
                          }}
                        >
                          <span className="material-symbols-rounded">
                            {r.visibleToClient ? "visibility" : "visibility_off"}
                          </span>
                          {/* Wrapped, not bare: the narrow-container rule drops the
                              word and keeps the icon, and a text node cannot be
                              selected. `aria-pressed` and `title` still carry the
                              state when the word is hidden. */}
                          <span className="au-share-t">
                            {r.visibleToClient ? "Shared" : "Internal"}
                          </span>
                        </button>
                      </td>
                      <td>
                        <div className="au-arts">
                          {/* FOUR different questions, not four ways to ask one.
                              The workspace first: it is the page an operator means
                              by "the audit" - Overview, Strategy, Issues, Pages and
                              Downloads under /admin/audits/<id>. It was reachable
                              only by clicking the client's name, which does not
                              read as a link, so the page people remembered became
                              one nobody could find their way back to. */}
                          <Link
                            className="au-art is-primary"
                            title="Open this audit - overview, issues, pages, downloads"
                            aria-label={`Open the ${r.client} audit`}
                            href={`/admin/audits/${r.id}`}
                          >
                            <span className="material-symbols-rounded">open_in_new</span>
                          </Link>
                          {/* The engine's narrative report, in the in-app page
                              viewer. Removed in a cleanup that left ReportViewer
                              mounted but unreachable - setViewId was only ever
                              called with null, so nothing could open it. Gated on
                              status, not on `pdf`: report.html is resolved by
                              convention and survives a failed PDF render. */}
                          <button
                            className="au-art"
                            title="Read the full report in the page viewer"
                            disabled={r.status !== "done"}
                            onClick={() => setViewId(r.id)}
                          >
                            <span className="material-symbols-rounded">menu_book</span>
                          </button>
                          <button
                            className="au-art"
                            title="Download the full PDF report"
                            disabled={!r.pdf}
                            onClick={() =>
                              downloadFile(`/audits/${r.id}/report.pdf`, `${r.client}-audit-${r.id}.pdf`)
                            }
                          >
                            <span className="material-symbols-rounded">picture_as_pdf</span>
                          </button>
                          <button
                            className="au-art"
                            title="Download the full workbook (every sheet, every occurrence)"
                            disabled={r.status !== "done"}
                            onClick={() =>
                              downloadFile(
                                `/audits/${r.id}/download/workbook`,
                                `${r.client}-audit-${r.id}.xlsx`,
                              )
                            }
                          >
                            <span className="material-symbols-rounded">table_view</span>
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {!auditsQ.isLoading && !auditsQ.isError && shown.length === 0 && (
                  <tr><td colSpan={7} className="au-empty">No audits match these filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {/* A full page means there is probably more history behind it. The
              count is the loaded window, stated plainly, so a filter that finds
              nothing cannot be mistaken for a site that has nothing. */}
          {rows.length >= pages * AUDITS_PAGE && (
            <div className="au-more">
              <span className="au-more-count">
                Showing the {rows.length.toLocaleString()} most recent audits
              </span>
              <button
                type="button"
                className="au-more-btn"
                disabled={auditsQ.isFetching}
                onClick={() => setPages(pages + 1)}
              >
                <span className="material-symbols-rounded">expand_more</span>
                {auditsQ.isFetching ? "Loading..." : "Load older audits"}
              </button>
            </div>
          )}
        </section>

        {/* Run new audit */}
        <section className="card au-run">
          <div className="card-h">
            <div>
              <div className="ct">Run New Audit</div>
              <div className="cs">A URL is all the engine needs - it runs as an async job</div>
            </div>
          </div>

          <div className="fld">
            <label>Site URL</label>
            <input
              placeholder="northpeakdental.com"
              value={url}
              // A deep quote is priced from THIS site's sitemap, so changing the
              // target invalidates it. Dropping the quote here is what stops a
              // price measured on one site being confirmed against another.
              onChange={(e) => { dropQuote(); setUrl(e.target.value); }}
              onKeyDown={(e) => e.key === "Enter" && runAudit()}
            />
          </div>

          <div className="fld">
            <label>Client</label>
            <select
              value={effectiveClientId}
              onChange={(e) => setClientId(e.target.value)}
              disabled={clients.length === 0}
            >
              {clients.length === 0 ? (
                <option value="">{clientsQ.isLoading ? "Loading clients…" : "No clients yet"}</option>
              ) : (
                clients.map((c) => <option key={c.id} value={c.id}>{c.cn}</option>)
              )}
            </select>
          </div>

          <label className="au-share">
            <input
              type="checkbox"
              checked={shareWithClient}
              onChange={(e) => setShareWithClient(e.target.checked)}
            />
            <span>
              <b>Show this audit in the client&rsquo;s portal</b>
              <em>
                Off by default. The client sees the report, score and downloads -
                never the cost, the error or the internal paths.
              </em>
            </span>
          </label>

          {/* THE control. Nothing is disabled here any more: depth used to fight
              a separately-derived tier, so half the options were greyed out with
              an explanation of a rule the operator had not knowingly set. Tier
              now follows depth, so every option is selectable and picking one
              says everything about what will run and what it costs. */}
          <div className="fld">
            <label>Depth</label>
            <div className="au-pick">
              {auditDepths.map((d) => (
                <button
                  key={d.key}
                  type="button"
                  className={`chip${effectiveDepth === d.key ? " on" : ""}`}
                  onClick={() => pickDepth(d.key)}
                  title={d.blurb}
                >
                  {d.label}
                  {d.confirms && <span className="au-pick-paid" aria-label="confirm required">!</span>}
                </button>
              ))}
            </div>
            <div className="fld-hint au-depthnote">{depthMeta?.blurb}</div>
          </div>

          {needsConfirm && (
            <div className="au-run-note" role="status">
              <span className="material-symbols-rounded">receipt_long</span>
              {confirmed && quote ? (
                <span>
                  Estimated <b>${quote.estimatedCost.toFixed(2)}</b> - up to{" "}
                  <b>{quote.pages}</b> pages
                  {quote.agents ? ", including the AI agent analysis" : ", no AI agents"}.{" "}
                  {quote.measuredPages === null ? (
                    <>
                      We could not read this site&apos;s sitemap, so this is the full
                      depth allowance - the real run may be smaller, and you are only
                      billed for what it crawls.
                    </>
                  ) : (
                    <>
                      Its sitemap lists <b>{quote.measuredPages}</b> page
                      {quote.measuredPages === 1 ? "" : "s"}
                      {quote.sizeTruncated ? " (at least - the sitemap is large)" : ""}.
                    </>
                  )}{" "}
                  Confirm to run at this price.
                </span>
              ) : (
                <span>
                  A deep audit is costed before it runs. Get the estimate, then confirm it.
                </span>
              )}
            </div>
          )}
          {estimateErr && (
            <div className="au-run-note" role="alert" style={{ color: "var(--warn, #A96913)" }}>
              <span className="material-symbols-rounded">error</span>
              {estimateErr}
            </div>
          )}

          {needsConfirm && !confirmed ? (
            <button
              className="primary-btn wide"
              onClick={getEstimate}
              disabled={!canRun || estimateM.isPending}
            >
              <span className="material-symbols-rounded">calculate</span>
              {halted
                ? "API spend is halted"
                : estimateM.isPending
                  ? "Estimating…"
                  : "Estimate cost"}
            </button>
          ) : (
            <button className="primary-btn wide" onClick={runAudit} disabled={!canRun}>
              <span className="material-symbols-rounded">rocket_launch</span>
              {halted
                ? "API spend is halted"
                : createAudit.isPending
                  ? "Starting…"
                  : needsConfirm && quote
                    ? `Confirm $${quote.estimatedCost.toFixed(2)} & run`
                    : `Run ${depthMeta?.label ?? "full"} audit`}
            </button>
          )}
          {halted && (
            <div className="au-run-note" role="status" style={{ color: "var(--warn, #A96913)" }}>
              <span className="material-symbols-rounded">block</span>
              API spend is halted. Resume it in Cost Controls to run audits.
            </div>
          )}
          {createErr && (
            <div className="au-run-note" role="alert" style={{ color: "var(--warn, #A96913)" }}>
              <span className="material-symbols-rounded">error</span>
              {createErr}
            </div>
          )}
          <div className="au-run-note">
            <span className="material-symbols-rounded">auto_awesome</span>
            On completion: PDF + JSON + scores, the milestone auto-advances and the client is notified.
          </div>
        </section>
      </div>

      {viewId && (
        <ReportViewer
          load={loadReport}
          reloadKey={viewId}
          label={viewRow ? `${viewRow.client} · ${viewRow.url}` : "Audit report"}
          onClose={() => setViewId(null)}
          onDownloadPdf={
            viewRow?.pdf
              ? () => downloadFile(`/audits/${viewId}/report.pdf`, `${viewRow.client}-audit-${viewId}.pdf`)
              : undefined
          }
        />
      )}

      <ConfirmDialog
        open={sharePrompt !== null}
        title="Share this audit with the client?"
        body={
          <>
            <b>{sharePrompt?.client}</b> will be able to open this audit of{" "}
            <b>{sharePrompt?.url}</b> - its score, findings and report - from their
            portal, immediately.
          </>
        }
        reassurance="You can stop sharing it again at any time, though that will not un-read what they have already seen."
        confirmLabel="Share with client"
        pending={setVisibility.isPending}
        onCancel={() => setSharePrompt(null)}
        onConfirm={() => {
          const target = sharePrompt;
          if (!target) return;
          setVisibility.mutate(
            { id: target.id, visible: true },
            { onSuccess: () => setSharePrompt(null) },
          );
        }}
      />
    </>
  );
}
