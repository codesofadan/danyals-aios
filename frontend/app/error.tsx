"use client";

// The route-tree error boundary. Catches a render crash anywhere below the root
// layout and replaces the crashed subtree — the document chrome survives.
//
// WHY THIS FILE EXISTS. The dashboard had no error boundary of any kind: no
// `error.tsx`, no `global-error.tsx`, no `componentDidCatch` anywhere. A single
// render crash — one `undefined.map`, one bad shape from an endpoint — took the whole
// screen to blank. That is the worst possible failure mode for an operator, because a
// white screen carries no information at all: it cannot be distinguished from a
// network failure, a logout, or a deploy in progress.
//
// WHAT IT DELIBERATELY DOES NOT DO. It does not say "something went wrong, please try
// again" and leave it there. `reset()` genuinely re-renders the segment, so it is
// offered as a real action; and when a reset does not help, the reference code is what
// makes the crash findable in the server logs. Advice that cannot work is the UI
// equivalent of a green board over a failed job.
//
// `error.digest` is Next's own opaque hash of the server-side error. In production
// Next strips `error.message` before it reaches the browser, so the digest is the only
// correlator that survives — which is why it is rendered rather than hidden.

import { useEffect } from "react";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface it where a developer looks first. The server has already logged the
    // real stack; this is the browser-side breadcrumb that ties to the digest.
    console.error("[aios] render error", error.digest ?? "(no digest)", error);
  }, [error]);

  return (
    <div className="auth-splash">
      <div className="auth-splash-logo" />
      <div className="auth-splash-txt">This screen failed to load.</div>
      <div
        style={{
          marginTop: 6,
          fontSize: 12.5,
          color: "var(--muted)",
          maxWidth: 380,
          textAlign: "center",
          lineHeight: 1.5,
        }}
      >
        Nothing was lost — the failure is in displaying this page, not in your data.
      </div>
      <button type="button" className="primary-btn" onClick={reset} style={{ marginTop: 16 }}>
        <span className="material-symbols-rounded">refresh</span>
        Try this screen again
      </button>
      {error.digest ? (
        <div style={{ marginTop: 14, fontSize: 11.5, color: "var(--muted)" }}>
          Reference <code>{error.digest}</code>
        </div>
      ) : null}
    </div>
  );
}
