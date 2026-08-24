"use client";

// The LAST-RESORT boundary: a crash in the root layout itself.
//
// `app/error.tsx` cannot catch this one — it renders *inside* the root layout, so if
// the layout is what threw, there is nothing left to render it. `global-error.tsx`
// REPLACES the root layout entirely, which is why it must supply its own <html> and
// <body>: at this point React has no document shell to attach to.
//
// It therefore cannot use the app's fonts, providers, or CSS variables — the layout
// that defines them is the thing that failed. Every style here is inline and
// self-contained on purpose. A boundary that depends on the thing it is catching is
// not a boundary.
//
// This should essentially never fire. When it does, the app is not degraded, it is
// down, and the honest copy says so rather than inviting a retry that cannot work.

import { useEffect } from "react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[aios] root layout error", error.digest ?? "(no digest)", error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "grid",
          placeItems: "center",
          background: "#0b0d10",
          color: "#e7ecf3",
          fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
        }}
      >
        <main style={{ maxWidth: 420, padding: 24, textAlign: "center" }}>
          <h1 style={{ fontSize: 17, fontWeight: 700, margin: "0 0 8px" }}>
            AIOS could not start.
          </h1>
          <p style={{ fontSize: 13.5, lineHeight: 1.6, color: "#93a1b5", margin: "0 0 18px" }}>
            This is a failure in the application shell, not in your data. Reloading may
            help if it was transient; if it persists, the deployment needs attention.
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              font: "inherit",
              fontSize: 13,
              fontWeight: 700,
              color: "#0b0d10",
              background: "#7cc4ff",
              border: 0,
              borderRadius: 10,
              padding: "10px 16px",
              cursor: "pointer",
            }}
          >
            Reload
          </button>
          {error.digest ? (
            <p style={{ marginTop: 16, fontSize: 11.5, color: "#6b7a90" }}>
              Reference <code>{error.digest}</code>
            </p>
          ) : null}
        </main>
      </body>
    </html>
  );
}
