"use client";

import type { Web2Placement } from "@/lib/offpage";

/**
 * The placement ledger — what was built, where it lives, and whether the link is real.
 *
 * This is the screen the module was missing. A campaign could be planned, drafted,
 * approved and published and there was still no way to answer a client asking "where
 * are my links?" — every fact below was already stored on the row and none of it was
 * reachable.
 *
 * The column that matters most is LINK. "Published" only means the platform accepted
 * the post; whether our link is actually on the page, and whether it is followed, is a
 * separate measured fact. Showing them as one number is how an agency ends up invoicing
 * for a link a platform quietly stripped — so a placement that published but whose link
 * has not been confirmed says exactly that, rather than borrowing the green tick.
 */
export default function Web2PlacementTable({
  placements,
  loading,
  emptyHint,
}: {
  placements: Web2Placement[];
  loading?: boolean;
  emptyHint?: string;
}) {
  if (loading) return <div className="op-empty">Loading placements…</div>;
  if (!placements.length) {
    return (
      <div className="op-empty">
        {emptyHint ?? "No placements yet. Plan a campaign and they will appear here as they build."}
      </div>
    );
  }

  return (
    <div className="tbl-wrap">
      <table className="tbl op-tbl w2-ledger">
        <thead>
          <tr>
            <th>Client</th>
            <th>Platform</th>
            <th>Article</th>
            <th>Anchor → destination</th>
            <th>Live post</th>
            <th>Link</th>
            <th>Stage</th>
            <th>Published</th>
            <th>Account</th>
          </tr>
        </thead>
        <tbody>
          {placements.map((p) => (
            <tr key={p.id}>
              <td className="op-strong">{p.client}</td>
              <td>{p.platform}</td>
              <td>
                <span title={p.topic}>{p.topic || "—"}</span>
                {p.framework && <span className="w2-sub">{p.framework}</span>}
              </td>
              <td>
                <span className="op-anchor">{p.anchor || "—"}</span>
                {p.targetUrl && (
                  <a className="w2-sub w2-link" href={p.targetUrl} target="_blank" rel="noreferrer">
                    {shortUrl(p.targetUrl)}
                  </a>
                )}
              </td>
              <td>
                {p.postUrl ? (
                  // The whole point of the report: click through to the actual article.
                  <a className="w2-link" href={p.postUrl} target="_blank" rel="noreferrer">
                    Open post ↗
                  </a>
                ) : (
                  <span className="op-muted">not yet</span>
                )}
              </td>
              <td><LinkCell p={p} /></td>
              <td><StageCell p={p} /></td>
              <td className="op-muted">{p.published || p.scheduledFor || "—"}</td>
              <td>
                <span title={p.account}>{p.account || "—"}</span>
                {p.accountOwnership && (
                  <span className={`w2-sub ${p.accountOwnership === "house" ? "w2-warn" : ""}`}>
                    {p.accountOwnership === "house" ? "shared house acct" : "client-owned"}
                  </span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Measured link state — never inferred from "published". */
function LinkCell({ p }: { p: Web2Placement }) {
  if (p.linkFound === true) {
    const nofollow = p.linkRel.includes("nofollow");
    return (
      <span className={`status-pill ${nofollow ? "warn" : "ok"}`} title={p.linkChecked ? `checked ${p.linkChecked}` : ""}>
        {nofollow ? "nofollow" : "followed"}
      </span>
    );
  }
  if (p.linkFound === false) {
    return <span className="status-pill crit" title="the page was fetched and our link was not on it">missing</span>;
  }
  // Deliberately NOT "ok": nobody has looked yet.
  return <span className="status-pill mut">unchecked</span>;
}

function StageCell({ p }: { p: Web2Placement }) {
  const tone =
    p.status === "published" ? "ok"
    : p.status === "failed" || p.status === "rejected" ? "crit"
    : p.status === "needs_review" ? "warn"
    : "info";
  return (
    <>
      <span className={`status-pill ${tone}`}>{p.status.replace(/_/g, " ")}</span>
      {p.note && <span className="w2-sub w2-note" title={p.note}>{p.note}</span>}
    </>
  );
}

function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    const path = u.pathname === "/" ? "" : u.pathname;
    return `${u.hostname}${path}`.replace(/^www\./, "").slice(0, 38);
  } catch {
    return url.slice(0, 38);
  }
}
