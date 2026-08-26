"use client";

// A number an operator acts on must never be a guess.
//
// THE BUG THIS EXISTS TO END. KPI strips across the product read their data as
// `useThing().data ?? []` and derive a count from it. When the request FAILS
// that fallback is an empty array, so the tile animates a crisp `0` into view:
//
//     "0 at-risk projects"     (milestones)
//     "0 toxic links flagged"  (off-page)
//     "Avg. utilization 0%"    (team)
//
// A dead backend is rendered as a healthy platform, and there is nothing on
// screen to tell the two apart. `EmptyState` in this folder already states the
// rule — never show fabricated data where the truth is "we don't know" — but
// the rule had only ever been applied to tables, not to the numbers people
// actually make decisions from.
//
// This is the guard for the loading and failure halves of that rule. Wrap the
// derived view; pass in the queries it derives FROM. While they load nothing
// is asserted; if any of them failed, the failure is what's shown.
//
// It deliberately does NOT handle "loaded, but empty" — that IS data, and
// `EmptyState` is its honest voice.

import type { ReactNode } from "react";

/** The only parts of a react-query result this needs. Structural, so it accepts
 *  a real UseQueryResult, a fake in a test, or a hand-rolled object. */
export type GuardableQuery = {
  isLoading?: boolean;
  isPending?: boolean;
  isError?: boolean;
  refetch?: () => unknown;
};

export type QueryGuardProps = {
  /** Every query the wrapped view derives from. */
  queries: GuardableQuery[];
  /** What failed, in the operator's words: "team stats", "the link profile". */
  label: string;
  /** Height the placeholder reserves, so the page does not jump on load. */
  minHeight?: number;
  children: ReactNode;
};

const isBusy = (q: GuardableQuery) => Boolean(q.isLoading ?? q.isPending);

export default function QueryGuard({
  queries,
  label,
  minHeight = 96,
  children,
}: QueryGuardProps) {
  const failed = queries.filter((q) => q.isError);
  const loading = queries.some(isBusy);

  // FAILURE WINS OVER LOADING. A strip with one failed and one still-refetching
  // query must not show a spinner and then silently settle into wrong numbers.
  if (failed.length > 0) {
    const retry = failed.map((q) => q.refetch).filter(Boolean) as Array<() => unknown>;
    return (
      <div
        role="alert"
        style={{
          display: "grid",
          placeItems: "center",
          minHeight,
          padding: "18px 16px",
          border: "1px solid var(--line)",
          borderRadius: 12,
          background: "var(--card)",
          textAlign: "center",
        }}
      >
        <div>
          <span
            className="material-symbols-rounded"
            style={{ fontSize: 26, color: "var(--warn)" }}
            aria-hidden="true"
          >
            cloud_off
          </span>
          <div style={{ marginTop: 6, fontSize: 13.5, fontWeight: 700 }}>
            Couldn&apos;t load {label}
          </div>
          <div style={{ marginTop: 4, fontSize: 12, color: "var(--muted)" }}>
            These figures are unavailable right now — they are not zero.
          </div>
          {retry.length > 0 ? (
            <button
              type="button"
              className="ghostbtn"
              style={{ marginTop: 12 }}
              onClick={() => retry.forEach((r) => r())}
            >
              <span className="material-symbols-rounded" aria-hidden="true">
                refresh
              </span>
              Try again
            </button>
          ) : null}
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div
        role="status"
        aria-busy="true"
        aria-label={`Loading ${label}`}
        style={{
          display: "grid",
          placeItems: "center",
          minHeight,
          padding: "18px 16px",
          border: "1px solid var(--line)",
          borderRadius: 12,
          background: "var(--card)",
          color: "var(--muted)",
          fontSize: 12.5,
        }}
      >
        Loading {label}…
      </div>
    );
  }

  return <>{children}</>;
}
