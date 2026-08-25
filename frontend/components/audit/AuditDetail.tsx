"use client";

// ============================================================
// AIOS · one audit, read at three altitudes.
//
// The shape of this page IS the argument: an operator lands on six numbers, not
// on 8,077 rows. A real 197-page audit produced 15,617 findings; the same data
// here is 6 pillar cards -> 461 issue cards -> every occurrence on demand.
//
// "WHERE THIS SITE STANDS" IS PERSISTENT, not a tab. It is the frame every other
// view is read inside - which pillar you are looking at, and how much of it was
// actually measured - so it stays on screen while you move between the plan, the
// issues and the pages. Selecting a pillar filters the issues and STAYS selected
// when you come back; clicking it again clears it.
// ============================================================

import { useMemo, useState } from "react";
import Link from "next/link";
import { downloadFile } from "@/lib/api";
import { useAudit } from "@/lib/hooks/audits";
import {
  useAuditFindings,
  useAuditPages,
  useAuditRoadmap,
  useAuditRollups,
} from "@/lib/hooks/auditAltitudes";
import {
  DOWNLOADS,
  coverageLabel,
  isMeasured,
  pageRange,
  scoreDisplay,
  scoreTone,
} from "@/lib/auditAltitude";
import PillarScorecard from "@/components/audit/PillarScorecard";
import SubpointTable from "@/components/audit/SubpointTable";
import FindingList from "@/components/audit/FindingList";
import RoadmapBoard from "@/components/audit/RoadmapBoard";
import AuditPagesTable from "@/components/audit/AuditPagesTable";

type Tab = "overview" | "strategy" | "issues" | "pages" | "downloads";

const TABS: { key: Tab; label: string; icon: string }[] = [
  { key: "overview", label: "Overview", icon: "insights" },
  { key: "strategy", label: "Strategy", icon: "flag" },
  { key: "issues", label: "Issues", icon: "bug_report" },
  { key: "pages", label: "Pages", icon: "description" },
  { key: "downloads", label: "Downloads", icon: "download" },
];

//: Findings fetched per request. The endpoint caps at 500; 100 keeps the page
//: responsive and makes the pager's arithmetic legible to a reader.
const FINDINGS_PAGE = 100;

//: The severity vocabulary, in the order an operator triages. `null` is "all",
//: kept in the same list so the control has one code path.
const SEVERITIES: { key: string | null; label: string }[] = [
  { key: null, label: "All" },
  { key: "critical", label: "Critical" },
  { key: "major", label: "Major" },
  { key: "minor", label: "Minor" },
];

/** Server-side pager. Renders nothing when everything already fits on one page. */
function Pager({
  page,
  pageSize,
  total,
  onChange,
}: {
  page: number;
  pageSize: number;
  total: number;
  onChange: (next: number) => void;
}) {
  const { first, last, lastPage, needed } = pageRange(page, pageSize, total);
  if (!needed) return null;
  return (
    <div className="alt-pager">
      <button
        type="button"
        className="alt-pager-btn"
        disabled={page === 0}
        onClick={() => onChange(page - 1)}
      >
        <span className="material-symbols-rounded">chevron_left</span>
        Previous
      </button>
      <span className="alt-pager-count">
        {first.toLocaleString()} to {last.toLocaleString()} of {total.toLocaleString()}
      </span>
      <button
        type="button"
        className="alt-pager-btn"
        disabled={page >= lastPage}
        onClick={() => onChange(page + 1)}
      >
        Next
        <span className="material-symbols-rounded">chevron_right</span>
      </button>
    </div>
  );
}

export default function AuditDetail({ auditId }: { auditId: string }) {
  const [tab, setTab] = useState<Tab>("overview");
  const [dimension, setDimension] = useState<string | null>(null);
  const [severity, setSeverity] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  const rollups = useAuditRollups(auditId);
  // Server-side paging. This used to fetch a flat `limit: 200`, so on the real
  // 461-finding audit 261 problems were reachable only by downloading the CSV -
  // and the UI gave no sign they existed.
  const findings = useAuditFindings(auditId, {
    dimension: dimension ?? undefined,
    severity: severity ?? undefined,
    limit: FINDINGS_PAGE,
    offset: page * FINDINGS_PAGE,
  });
  const roadmap = useAuditRoadmap(auditId);
  const pages = useAuditPages(auditId);
  // The header used to scan the /audits list, which the server caps at 50 rows,
  // so any older audit opened with a placeholder title and a raw UUID.
  const audit = useAudit(auditId);
  const row = audit.data;
  const changeDimension = (next: string | null) => {
    setDimension(next);
    setPage(0);
  };
  const changeSeverity = (next: string | null) => {
    setSeverity(next);
    setPage(0);
  };

  const site = useMemo(
    () => (rollups.data ?? []).find((r) => r.level === "site") ?? null,
    [rollups.data],
  );

  // `name` already carries the artifact's extension (findings.csv, workbook.xlsx).
  // Building the filename from the route key alone saved three of the buttons'
  // files with no extension at all, so the operating system could not open them.
  const onDownload = (name: string) =>
    downloadFile(`/audits/${auditId}/download/${name}`, `audit-${auditId}-${name}`);

  if (rollups.isLoading) {
    return <div className="alt-loading">Loading audit...</div>;
  }

  // A failed request is not an empty audit. Without this branch a 404 or a
  // backend outage rendered as a successful audit with no data, and four of the
  // five tabs affirmatively stated the audit was empty.
  if (rollups.isError) {
    return (
      <div className="alt-empty big">
        <span className="material-symbols-rounded">error</span>
        <h2>This audit could not be loaded</h2>
        <p>
          The request failed, so nothing below would be trustworthy. This is not
          the same as an audit with no findings. Reload, and if it persists the
          run may have been removed.
        </p>
        <Link className="alt-back" href="/admin/audit">
          Back to audits
        </Link>
      </div>
    );
  }

  // An audit run before the altitude ingest existed has no rows to show. That is
  // a legitimate state, not an error - say so plainly and offer the old report.
  if ((rollups.data ?? []).length === 0) {
    return (
      <div className="alt-empty big">
        <span className="material-symbols-rounded">layers_clear</span>
        <h2>No altitude data for this audit</h2>
        <p>
          This run completed before findings were stored as rows, or produced no
          findings. The original report is still available from the audit list.
        </p>
        <Link className="alt-back" href="/admin/audit">
          Back to audits
        </Link>
      </div>
    );
  }

  return (
    <div className="alt">
      <header className="alt-head">
        <Link className="alt-back" href="/admin/audit">
          <span className="material-symbols-rounded">arrow_back</span>
          Audits
        </Link>
        <div className="alt-head-main">
          <h1>{row?.client || "Audit"}</h1>
          <p className="alt-head-url">{row?.url || auditId}</p>
        </div>
        {site ? (
          <div className="alt-head-stats">
            <div className={`alt-hero t-${scoreTone(isMeasured(site) ? site.score : null)}`}>
              <span className="alt-hero-lab">Site score</span>
              <span className="alt-hero-val">{scoreDisplay(site)}</span>
              <span className="alt-hero-sub">over {coverageLabel(site)} checks</span>
            </div>
            <div className="alt-hero">
              <span className="alt-hero-lab">Pages without a critical issue</span>
              <span className="alt-hero-val">
                {site.url_health_pct === null ? "-" : `${site.url_health_pct}%`}
              </span>
              <span className="alt-hero-sub">
                of {site.pages_crawled.toLocaleString()} crawled
              </span>
            </div>
            <div className="alt-hero">
              <span className="alt-hero-lab">Issues to fix</span>
              <span className="alt-hero-val">{site.findings_open.toLocaleString()}</span>
              <span className="alt-hero-sub">
                across {site.instances_open.toLocaleString()} occurrences
              </span>
            </div>
          </div>
        ) : null}
      </header>

      {/* Persistent across every tab: the frame the rest is read inside. */}
      <div className="card alt-stands">
        <div className="card-h">
          <div>
            <div className="ct">Where this site stands</div>
            <div className="cs">
              Every score carries the number of checks behind it. A pillar we could not
              measure says so - it never shows as zero. Select one to filter the issues.
            </div>
          </div>
        </div>
        <PillarScorecard
          rollups={rollups.data ?? []}
          selected={dimension}
          onSelect={(d) => {
            changeDimension(d);
            if (d) setTab("issues");
          }}
        />
      </div>

      <nav className="alt-tabs seg" role="tablist">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            className={tab === t.key ? "on" : ""}
            onClick={() => setTab(t.key)}
          >
            <span className="material-symbols-rounded">{t.icon}</span>
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "overview" ? (
        <div className="card">
          <div className="card-h">
            <div>
              <div className="ct">By subpoint</div>
              <div className="cs">
                The checklist&rsquo;s own vocabulary - worst measured first, unmeasured last.
              </div>
            </div>
          </div>
          <SubpointTable rollups={rollups.data ?? []} />
        </div>
      ) : null}

      {tab === "strategy" ? (
        <div className="card">
          <div className="card-h">
            <div>
              <div className="ct">Strategy</div>
              <div className="cs">Ordered by impact over effort.</div>
            </div>
          </div>
          {roadmap.isLoading ? <div className="alt-loading">Loading strategy...</div> : null}
          {roadmap.isError ? (
            <div className="alt-empty">
              <span className="material-symbols-rounded">flag</span>
              <p>No strategy has been generated for this audit yet.</p>
            </div>
          ) : null}
          {roadmap.data ? <RoadmapBoard data={roadmap.data} /> : null}
        </div>
      ) : null}

      {tab === "issues" ? (
        <div className="card">
          <div className="card-h">
            <div>
              <div className="ct">Issues</div>
              <div className="cs">
                One card per problem. Open one to see every page it affects.
              </div>
            </div>
            <div className="tools">
              {dimension ? (
                <>
                  <button
                    type="button"
                    className="alt-dlmini"
                    title={`Download only the ${dimension} issues`}
                    // The per-pillar file, not the whole 461-row export: the
                    // specialist who receives it should not be handed everyone
                    // else's work.
                    onClick={() => onDownload(`issues-${dimension}.csv`)}
                  >
                    <span className="material-symbols-rounded">download</span>
                    {dimension} CSV
                  </button>
                  <button type="button" className="alt-clear" onClick={() => changeDimension(null)}>
                    <span className="material-symbols-rounded">close</span>
                    {dimension}
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  className="alt-dlmini"
                  title="Download every issue as CSV"
                  onClick={() => onDownload("findings.csv")}
                >
                  <span className="material-symbols-rounded">download</span>
                  CSV
                </button>
              )}
            </div>
          </div>
          <div className="alt-filters">
            <span className="alt-filters-label">Severity</span>
            {SEVERITIES.map((s) => (
              <button
                key={s.key ?? "all"}
                type="button"
                className={`alt-chip${severity === s.key ? " on" : ""}`}
                onClick={() => changeSeverity(s.key)}
              >
                {s.label}
              </button>
            ))}
          </div>
          {findings.isLoading ? (
            <div className="alt-loading">Loading issues...</div>
          ) : findings.isError ? (
            <div className="alt-empty">
              <span className="material-symbols-rounded">error</span>
              <p>Issues could not be loaded. This is not an audit with no issues.</p>
            </div>
          ) : (
            <>
              <FindingList
                auditId={auditId}
                findings={findings.data?.items ?? []}
                total={findings.data?.total ?? 0}
              />
              <Pager
                page={page}
                pageSize={FINDINGS_PAGE}
                total={findings.data?.total ?? 0}
                onChange={setPage}
              />
            </>
          )}
        </div>
      ) : null}

      {tab === "pages" ? (
        <div className="card">
          <div className="card-h">
            <div>
              <div className="ct">Pages</div>
              <div className="cs">
                Every crawled URL, worst first. Health counts critical issues only.
              </div>
            </div>
          </div>
          {pages.isLoading ? (
            <div className="alt-loading">Loading pages...</div>
          ) : (
            <AuditPagesTable pages={pages.data ?? []} />
          )}
        </div>
      ) : null}

      {tab === "downloads" ? (
        <div className="card">
          <div className="card-h">
            <div>
              <div className="ct">Downloads</div>
              <div className="cs">
                The workbook is capped so it opens; the CSVs are the complete record.
              </div>
            </div>
          </div>
          <div className="alt-dl">
            {DOWNLOADS.map((d) => (
              <button
                key={d.name}
                type="button"
                className="alt-dl-item"
                onClick={() => onDownload(d.name)}
              >
                <span className="material-symbols-rounded">download</span>
                <span>
                  <b>{d.label}</b>
                  <em>{d.hint}</em>
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
