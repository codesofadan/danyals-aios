"use client";

import { useState } from "react";
import { usePlacedLinks } from "@/lib/hooks/offpage";
import type { PlacedLinkState } from "@/lib/offpage";
import ReadMore from "@/components/ui/ReadMore";

/**
 * Every outbound link a Web 2.0 property placed, and what became of it (M05 A8).
 *
 * THE QUESTION `web2_properties` COULD NOT ANSWER. Its three link columns record the
 * LATEST look and nothing else — each re-check overwrites the last answer — so "this
 * link was live in March, when did we lose it?" had no answer anywhere in the system.
 * The ledger keeps the transition; `lostAt` is stamped once, on the way out of live.
 *
 * ORDERED LOST-FIRST BY THE SERVER, and this component does not re-sort. Sorted by date,
 * the three links that went missing sit under two hundred that are fine — and the
 * missing ones are the only rows anybody needs to act on.
 *
 * `unknown` IS NOT `live`. It means nobody has successfully looked, which is a gap in
 * our monitoring rather than a clean bill of health — so it sorts with the problems and
 * is coloured as a caution, never as an ok.
 */

const STATE_META: Record<PlacedLinkState, { label: string; cls: string; icon: string; blurb: string }> = {
  live: {
    label: "Live", cls: "ok", icon: "link",
    blurb: "Fetched, and our link was found on the page.",
  },
  removed: {
    label: "Removed", cls: "op-crit", icon: "link_off",
    blurb: "The page was fetched and our link is no longer on it.",
  },
  nofollowed: {
    label: "Nofollowed", cls: "warn", icon: "do_not_disturb_on",
    blurb: "The link is still there, but now carries rel=nofollow — it passes nothing.",
  },
  unknown: {
    label: "Not checked", cls: "mut", icon: "help",
    blurb: "Nobody has successfully fetched this page. That is a gap in our monitoring, not a pass.",
  },
};

const FILTERS: { key: PlacedLinkState | ""; label: string }[] = [
  { key: "", label: "All" },
  { key: "removed", label: "Removed" },
  { key: "nofollowed", label: "Nofollowed" },
  { key: "unknown", label: "Not checked" },
  { key: "live", label: "Live" },
];

function day(stamp: string): string {
  if (!stamp) return "—";
  const parsed = new Date(stamp);
  return Number.isNaN(parsed.getTime()) ? stamp : parsed.toLocaleDateString();
}

export default function Web2PlacedLinks({ clientId }: { clientId?: string }) {
  const [state, setState] = useState<PlacedLinkState | "">("");
  const q = usePlacedLinks({ clientId, state });
  const board = q.data;
  const rows = board?.links ?? [];
  const lost = (board?.removed ?? 0) + (board?.nofollowed ?? 0);

  return (
    <div style={{ marginTop: 14 }}>
      {/* A named group, because the same state blurb appears here and on every row that
          is in that state — so "the summary" and "this one link" are otherwise
          indistinguishable to anything navigating by description, a screen reader
          included. */}
      <div
        role="group"
        aria-label="Link states"
        style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 10 }}
      >
        {(["live", "removed", "nofollowed", "unknown"] as PlacedLinkState[]).map((key) => {
          const meta = STATE_META[key];
          const count = board?.[key] ?? 0;
          return (
            <div
              key={key}
              className="stat-card"
              title={meta.blurb}
              style={{
                display: "flex", alignItems: "center", gap: 9, padding: "10px 14px",
                border: "1px solid var(--line)", borderRadius: 12, background: "var(--well)",
              }}
            >
              <span className="material-symbols-rounded" aria-hidden="true" style={{ fontSize: 18 }}>
                {meta.icon}
              </span>
              {/* A ZERO WE HAVE NOT LOADED IS NOT A ZERO. Rendering 0 during the fetch
                  says "no links are in this state", which is a claim — and on the
                  `removed` card it is the reassuring one. */}
              <b style={{ fontSize: 18 }}>{q.isLoading ? "—" : count}</b>
              <span className="op-muted">{meta.label}</span>
            </div>
          );
        })}
      </div>

      <div className="fld-hint" style={{ marginBottom: 10 }}>
        {lost > 0 ? (
          <>
            <b>{lost}</b> link(s) were placed and are no longer passing value. Those sit at
            the top — a list ordered by date buries them under the ones that are fine.
          </>
        ) : (
          <>
            No link has been lost. &ldquo;Not checked&rdquo; is counted separately on
            purpose: nobody having looked is not the same claim as a link being live.
          </>
        )}
      </div>

      <div className="seg" style={{ marginBottom: 10, width: "fit-content" }}>
        {FILTERS.map((f) => (
          <button
            key={f.key || "all"}
            className={state === f.key ? "on" : undefined}
            onClick={() => setState(f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="tbl-wrap">
        <table className="tbl op-tbl">
          <thead>
            <tr>
              <th>Client</th>
              <th>Platform</th>
              <th>The page carrying the link</th>
              <th>Anchor</th>
              <th>State</th>
              <th>First seen</th>
              <th>Last checked</th>
              <th>Lost</th>
            </tr>
          </thead>
          <tbody>
            {q.isLoading && (
              <tr><td colSpan={8} className="op-empty">Loading the link ledger…</td></tr>
            )}
            {q.isError && !q.isLoading && (
              <tr>
                <td colSpan={8} className="op-empty">
                  Couldn&apos;t load placed links — {(q.error as Error)?.message ?? "try again"}.
                </td>
              </tr>
            )}
            {!q.isLoading && !q.isError && rows.length > 0 && (
              <ReadMore
                items={rows}
                initialCount={15}
                tableColSpan={8}
                getKey={(r) => r.id}
                renderItem={(r) => {
                  const meta = STATE_META[r.state] ?? STATE_META.unknown;
                  return (
                    <tr>
                      <td className="op-strong">{r.client}</td>
                      <td>{r.platform}</td>
                      <td>
                        {r.pageUrl ? (
                          <a
                            className="op-url"
                            href={r.pageUrl.startsWith("http") ? r.pageUrl : `https://${r.pageUrl}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {r.pageUrl}
                            <span className="material-symbols-rounded" aria-hidden="true">open_in_new</span>
                          </a>
                        ) : (
                          <span className="op-muted">—</span>
                        )}
                      </td>
                      <td><span className="op-anchor">{r.anchor}</span></td>
                      <td title={meta.blurb}>
                        <span className={`status-pill ${meta.cls}`}>
                          <span className="material-symbols-rounded op-pill-ic" aria-hidden="true">{meta.icon}</span>
                          {meta.label}
                        </span>
                        {r.rel && (
                          <span className="op-muted" style={{ marginLeft: 6 }}>rel={r.rel}</span>
                        )}
                      </td>
                      <td className="op-muted">{day(r.firstSeenAt)}</td>
                      <td className="op-muted">{day(r.lastCheckedAt)}</td>
                      {/* The column the property row could never fill: the DATE it went,
                          stamped once on the transition rather than overwritten on every
                          re-check. */}
                      <td className="op-muted">{r.lostAt ? day(r.lostAt) : "—"}</td>
                    </tr>
                  );
                }}
              />
            )}
            {!q.isLoading && !q.isError && rows.length === 0 && (
              <tr>
                <td colSpan={8} className="op-empty">
                  No links in this state. The ledger fills as published properties are
                  re-checked by the link monitor.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
