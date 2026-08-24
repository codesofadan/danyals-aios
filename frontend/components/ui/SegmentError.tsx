"use client";

// The shared body of every per-area error boundary.
//
// WHY PER-AREA BOUNDARIES EXIST AT ALL, given `app/error.tsx` already catches
// everything: a boundary replaces the subtree it wraps and keeps its PARENT layout
// alive. A boundary at `app/error.tsx` replaces the whole page including the sidebar,
// so a crash on one screen strands the user with no navigation and no way out but the
// browser's back button. A boundary inside `app/client/` keeps `client/layout.tsx` —
// the sidebar, the header, the tenant identity — and replaces only the crashed screen.
// The user can click straight to another page and carry on working.
//
// That is the difference between "the app broke" and "this screen broke", and it is
// worth three small files.
//
// AUDIENCE MATTERS. `error.message` is deliberately never rendered. Next strips it in
// production anyway, but the rule holds in development too: the client portal is a
// tenant-facing surface, and an internal exception string is agency-internal detail.
// `error.digest` — Next's own opaque hash — is rendered instead, because it is the
// only correlator that survives to production and it identifies the crash in the
// server log without disclosing anything.

import { useEffect } from "react";

export type SegmentErrorProps = {
  /** Which area crashed, for the log line and the heading. */
  area: string;
  /** One honest sentence. Say what failed, not what the user should feel. */
  headline: string;
  /** Optional second line. Use it to say what is NOT affected. */
  detail?: string;
  error: Error & { digest?: string };
  reset: () => void;
};

export default function SegmentError({
  area,
  headline,
  detail,
  error,
  reset,
}: SegmentErrorProps) {
  useEffect(() => {
    console.error(`[aios] ${area} render error`, error.digest ?? "(no digest)", error);
  }, [area, error]);

  return (
    <div
      style={{
        display: "grid",
        placeItems: "center",
        minHeight: 420,
        padding: 32,
        textAlign: "center",
      }}
      role="alert"
    >
      <div>
        <span
          className="material-symbols-rounded"
          style={{ fontSize: 34, color: "var(--warn)" }}
          aria-hidden="true"
        >
          error
        </span>
        <div style={{ marginTop: 10, fontSize: 15, fontWeight: 700 }}>{headline}</div>
        {detail ? (
          <div
            style={{
              marginTop: 6,
              fontSize: 12.5,
              color: "var(--muted)",
              maxWidth: 420,
              lineHeight: 1.55,
            }}
          >
            {detail}
          </div>
        ) : null}
        <button type="button" className="primary-btn" onClick={reset} style={{ marginTop: 16 }}>
          <span className="material-symbols-rounded">refresh</span>
          Try again
        </button>
        {error.digest ? (
          <div style={{ marginTop: 14, fontSize: 11.5, color: "var(--muted)" }}>
            Reference <code>{error.digest}</code>
          </div>
        ) : null}
      </div>
    </div>
  );
}
