"use client";

import { useCallback, useState } from "react";
import {
  auditDepths,
  auditTypes,
  DEPTH_LABEL,
  TYPE_LABEL,
  type AuditDepth,
  type AuditTypeKey,
  type JobStatus,
  type Tier,
} from "@/lib/audit";
import {
  useAudits,
  useAuditEstimate,
  useAuditStats,
  useCreateAudit,
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
// Flagged one way only — coming in under estimate is not a problem to chase.
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
const PAID_TYPES = new Set<AuditTypeKey>(auditTypes.filter((t) => t.paid).map((t) => t.key));

export default function AuditWorkspace() {
  const auditsQ = useAudits(); // live: GET /audits, polls while a job is in flight
  const statsQ = useAuditStats();
  const clientsQ = useClients();
  const createAudit = useCreateAudit();
  const { halted } = useSpendHalted(); // global API-spend kill-switch

  const rows = auditsQ.data ?? [];
  const clients = clientsQ.data ?? [];

  // Run-new-audit form state. `types` is the audit-type picker: empty = a FULL
  // audit (every type); a subset scopes the run to only those dimensions.
  const [url, setUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [types, setTypes] = useState<AuditTypeKey[]>([]);
  const [depth, setDepth] = useState<AuditDepth>("standard");
  // Off by default, matching the server. Sharing a report is a decision someone
  // makes, not a side effect of picking a client.
  const [shareWithClient, setShareWithClient] = useState(false);
  const effectiveClientId = clientId || clients[0]?.id || "";

  // The quote currently on screen, or null. Held in state (not react-query cache)
  // because a confirmation is bound to ONE figure: the moment any input changes,
  // the number the operator agreed to is no longer the number the run would cost,
  // so the quote is dropped rather than reused. The server enforces the same rule
  // independently — it compares the echoed figure against a freshly computed one
  // and returns 409 if they have drifted.
  const estimateM = useAuditEstimate();
  const [quote, setQuote] = useState<AuditEstimate | null>(null);

  // Table filters
  const [statusFilter, setStatusFilter] = useState<"all" | JobStatus>("all");
  // "full" is its own filter: a run with an EMPTY types array ran every
  // dimension, so it also matches each individual type chip below - but an
  // operator asking "which of these were full audits" needs to ask that directly.
  const [typeFilter, setTypeFilter] = useState<"all" | "full" | AuditTypeKey>("all");
  const [search, setSearch] = useState("");

  // The audit whose report.html is open in the full-screen page-viewer (null = none).
  const [viewId, setViewId] = useState<string | null>(null);
  const viewRow = viewId ? rows.find((r) => r.id === viewId) ?? null : null;
  // Bearer-authed fetch of the self-contained report.html for the viewer. The SAME
  // document the PDF is rendered from, so the on-screen report matches the download.
  const loadReport = useCallback(() => getReportHtml(`/audits/${viewId}/report.html`), [viewId]);

  // A run spends metered budget (Paid types especially), so it is blocked while the
  // global API-spend halt is engaged.
  const canRun = url.trim().length > 3 && !!effectiveClientId && !createAudit.isPending && !halted;

  // A run's TIER is derived from what will actually execute, and an EMPTY
  // selection is the full comprehensive audit — every paid provider plus all 21
  // AI agents. This previously read `types.some(isPaid)`, which is false for an
  // empty array, so the most expensive run the platform can launch was sent as
  // "Free" and skipped both cost gates server-side. The server now refuses that
  // combination outright; this keeps the button sending a request it will accept.
  const tier: Tier = types.length === 0 || types.some((t) => PAID_TYPES.has(t)) ? "Paid" : "Free";

  // Free tier can only run at free depth: `--mode free` clears every paid provider
  // at the engine, so extra breadth would buy more pages of the same two
  // deterministic dimensions. Shown as a disabled option with the reason rather
  // than hidden, so the constraint is legible instead of mysterious.
  const effectiveDepth: AuditDepth =
    tier === "Free" ? "free" : depth === "free" ? "standard" : depth;
  const depthMeta = auditDepths.find((d) => d.key === effectiveDepth);
  const needsConfirm = depthMeta?.confirms ?? false;
  // A quote only counts for the request it was issued against.
  const confirmed =
    quote !== null && quote.depth === effectiveDepth && quote.tier === tier;

  const dropQuote = () => setQuote(null);

  const toggleType = (k: AuditTypeKey) => {
    dropQuote();
    setTypes((prev) => (prev.includes(k) ? prev.filter((x) => x !== k) : [...prev, k]));
  };

  const pickDepth = (k: AuditDepth) => {
    dropQuote();
    setDepth(k);
  };

  // The URL is sent so a deep quote can measure the site's own sitemap and price
  // the run it would actually make, rather than the depth's 300-page ceiling.
  const getEstimate = () =>
    estimateM.mutate(
      { tier, depth: effectiveDepth, types, url: url.trim() },
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
        types,
        depth: effectiveDepth,
        visible_to_client: shareWithClient,
        // Echo the exact figure that was displayed. If unit prices or the depth's
        // page budget moved since the quote, the server returns 409 rather than
        // charging against a number the operator never saw.
        ...(needsConfirm && quote
          ? {
              // Echo BOTH: the budget the quote was priced for and the figure
              // itself. The server re-derives the price from the budget and
              // compares — so the confirmation is checked arithmetically rather
              // than by re-measuring a site that may have changed meanwhile.
              max_pages: quote.pages,
              confirmed_estimate: quote.estimatedCost,
            }
          : {}),
      },
      {
        onSuccess: () => {
          setUrl("");
          setTypes([]);
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
    if (typeFilter === "full") {
      if (r.types.length !== 0) return false;
    } else if (typeFilter !== "all") {
      // A full audit (empty types) ran every dimension, so it matches every
      // individual type filter too.
      if (r.types.length !== 0 && !r.types.includes(typeFilter)) return false;
    }
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
              <div className="cs">queued → running → done · artifacts stored to the client&apos;s Google Sheet</div>
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
            <div className="au-chips">
              <button className={`chip${typeFilter === "all" ? " on" : ""}`} onClick={() => setTypeFilter("all")}>All types</button>
              <button className={`chip${typeFilter === "full" ? " on" : ""}`} onClick={() => setTypeFilter("full")}>Full</button>
              {auditTypes.map((t) => (
                <button key={t.key} className={`chip${typeFilter === t.key ? " on" : ""}`} onClick={() => setTypeFilter(t.key)}>
                  {t.short}
                </button>
              ))}
            </div>
          </div>

          <div className="tbl-wrap">
            <table className="tbl au-tbl">
              <thead>
                <tr>
                  <th>Client</th>
                  <th>Site / URL</th>
                  <th>Type</th>
                  <th>Tier</th>
                  <th>Status</th>
                  <th className="num">Score</th>
                  <th className="num">Cost</th>
                  <th>Artifacts</th>
                  <th className="num">Run time</th>
                </tr>
              </thead>
              <tbody>
                {auditsQ.isLoading && (
                  <tr><td colSpan={9} className="au-empty">Loading audits…</td></tr>
                )}
                {auditsQ.isError && !auditsQ.isLoading && (
                  <tr><td colSpan={9} className="au-empty">Couldn&apos;t load audits — {(auditsQ.error as Error)?.message ?? "try again"}.</td></tr>
                )}
                {!auditsQ.isLoading && !auditsQ.isError && shown.map((r) => {
                  const sm = STATUS_META[r.status];
                  return (
                    <tr key={r.id}>
                      <td>
                        {/* The row IS the way into the audit. The artifact column
                            carries downloads only, so the name has to be the link. */}
                        <Link className="au-client au-open" href={`/admin/audit/${r.id}`}>
                          {r.client}
                        </Link>
                        <div className="au-when">{r.when}</div>
                      </td>
                      <td><span className="au-url"><span className="material-symbols-rounded">link</span>{r.url}</span></td>
                      <td>
                        <div className="au-types">
                          {r.types.length === 0 ? (
                            <span className="au-type-tag au-type-full">Full audit</span>
                          ) : (
                            r.types.map((k) => (
                              <span key={k} className="au-type-tag">{TYPE_LABEL[k]}</span>
                            ))
                          )}
                        </div>
                      </td>
                      <td>
                        <span className={`au-tier ${r.tier.toLowerCase()}`}>{r.tier}</span>
                        {/* Depth is null on runs created before it was recorded — that
                            is "breadth unknown", not "free", so it renders as a dash
                            rather than borrowing a default it never had. */}
                        <div className="au-when">
                          {r.depth === null
                            ? "—"
                            : `${DEPTH_LABEL[r.depth]}${r.maxPages ? ` · ${r.maxPages}p` : ""}`}
                        </div>
                      </td>
                      <td>
                        <span className={`status-pill ${sm.pill}`}>
                          <span className={`material-symbols-rounded${r.status === "running" ? " au-spin" : ""}`}>{sm.icon}</span>
                          {sm.label}
                        </span>
                      </td>
                      <td className="num">
                        {r.score === null ? (
                          <span className="au-dash">—</span>
                        ) : (
                          <span className={`au-score ${scoreClass(r.score)}`}>{r.score}</span>
                        )}
                      </td>
                      <td className="num">
                        {r.cost === null ? (
                          <span className="au-dash" title="Nothing spent yet — the engine has not started">—</span>
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
                        <div className="au-arts">
                          {/* TWO downloads, and only two. The report and the
                              workbook are the deliverable; everything else about
                              this audit is reachable by opening it, so extra
                              icons here were four ways to ask the same question. */}
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
                      <td className="num au-runtime">{r.runtime}</td>
                    </tr>
                  );
                })}
                {!auditsQ.isLoading && !auditsQ.isError && shown.length === 0 && (
                  <tr><td colSpan={9} className="au-empty">No audits match these filters.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>

        {/* Run new audit */}
        <section className="card au-run">
          <div className="card-h">
            <div>
              <div className="ct">Run New Audit</div>
              <div className="cs">A URL is all the engine needs — it runs as an async job</div>
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
                Off by default. The client sees the report, score and downloads —
                never the cost, the error or the internal paths.
              </em>
            </span>
          </label>

          <div className="fld">
            <label>
              Audit types
              <span className="au-pick-tools">
                <button
                  type="button"
                  onClick={() => { dropQuote(); setTypes(auditTypes.map((t) => t.key)); }}
                >
                  Select all
                </button>
                {types.length > 0 ? (
                  <button type="button" onClick={() => { dropQuote(); setTypes([]); }}>
                    Clear
                  </button>
                ) : null}
              </span>
            </label>
            <div className="au-pick">
              {auditTypes.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  className={`chip${types.includes(t.key) ? " on" : ""}`}
                  onClick={() => toggleType(t.key)}
                  title={`${t.blurb}${t.paid ? " (paid data source)" : " (free)"}`}
                >
                  {t.short}
                  {t.paid && <span className="au-pick-paid" aria-label="paid">$</span>}
                </button>
              ))}
            </div>
          </div>

          {/* What the current selection actually buys. An operator picking
              "Local SEO" should not have to open the checklists to learn that it
              needs Google Places, or that Off-Page needs a backlink provider. */}
          {types.length > 0 ? (
            <div className="au-seldesc">
              {types.map((k) => {
                const t = auditTypes.find((x) => x.key === k);
                if (!t) return null;
                return (
                  <div key={k} className="au-seldesc-row">
                    <b>
                      {t.label}
                      {t.paid ? <em title="Uses a paid data source">paid</em> : null}
                    </b>
                    <span>{t.blurb}</span>
                    <span className="au-seldesc-checks">{t.checks.join(" · ")}</span>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="fld-hint" style={{ margin: "2px 0 10px" }}>
              <span className="material-symbols-rounded" style={{ verticalAlign: "middle", fontSize: "16px" }}>info</span>{" "}
              Nothing selected runs a <b>full audit</b> — every dimension, every paid
              provider and all 21 AI agents. That is the largest run the platform makes,
              so it goes through the cost gate as <b>Paid</b>. Use <b>Select all</b> to
              choose them explicitly, or pick a subset to scope it.
            </div>
          )}

          <div className="fld">
            <label>Depth</label>
            <div className="au-pick">
              {auditDepths.map((d) => {
                const blocked = tier === "Free" ? d.key !== "free" : d.key === "free";
                return (
                  <button
                    key={d.key}
                    type="button"
                    className={`chip${effectiveDepth === d.key ? " on" : ""}`}
                    onClick={() => pickDepth(d.key)}
                    disabled={blocked}
                    title={
                      blocked
                        ? tier === "Free"
                          ? "A Free run crawls at free depth — the engine clears every paid provider, so extra breadth buys more pages of the same two checks."
                          : "Free depth is the zero-spend lead-magnet crawl; this selection runs paid providers."
                        : d.blurb
                    }
                  >
                    {d.label}
                    {d.confirms && <span className="au-pick-paid" aria-label="confirm required">!</span>}
                  </button>
                );
              })}
            </div>
          </div>

          {needsConfirm && (
            <div className="au-run-note" role="status">
              <span className="material-symbols-rounded">receipt_long</span>
              {confirmed && quote ? (
                <span>
                  Estimated <b>${quote.estimatedCost.toFixed(2)}</b> — up to{" "}
                  <b>{quote.pages}</b> pages
                  {quote.agents ? ", including the AI agent analysis" : ", no AI agents"}.{" "}
                  {quote.measuredPages === null ? (
                    <>
                      We could not read this site&apos;s sitemap, so this is the full
                      depth allowance — the real run may be smaller, and you are only
                      billed for what it crawls.
                    </>
                  ) : (
                    <>
                      Its sitemap lists <b>{quote.measuredPages}</b> page
                      {quote.measuredPages === 1 ? "" : "s"}
                      {quote.sizeTruncated ? " (at least — the sitemap is large)" : ""}.
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
                    : types.length === 0
                      ? "Run full audit"
                      : `Run ${types.length}-type audit`}
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
    </>
  );
}
