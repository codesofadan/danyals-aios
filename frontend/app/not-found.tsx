"use client";

// The 404. Reached by a mistyped URL, a stale bookmark, or a `notFound()` call from a
// route that could not resolve what it was asked for.
//
// WHY IT MATTERS HERE MORE THAN USUAL. This app has three separate experiences behind
// one origin — the admin dashboard, the team portal and the client portal — and each
// brings its own navigation. Next's default 404 has none of them, so a client landing
// on a bad `/client/*` URL previously hit an unstyled dead end with no route back into
// their own portal. "Go home" is not obvious when there are three homes.
//
// So this offers BOTH a back step and an explicit route home, and deliberately does
// not guess which portal the visitor belongs to: guessing wrong sends a client at a
// staff URL, which the API would refuse anyway — an accurate refusal after a
// misleading redirect is a worse experience than an honest dead end.

import Link from "next/link";

export default function NotFound() {
  return (
    <div className="auth-splash">
      <div className="auth-splash-logo" />
      <div className="auth-splash-txt">That page doesn&apos;t exist.</div>
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
        The link may be out of date, or the item may have been removed.
      </div>
      <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
        <button
          type="button"
          className="primary-btn"
          onClick={() => window.history.back()}
        >
          <span className="material-symbols-rounded">arrow_back</span>
          Go back
        </button>
        <Link href="/" className="primary-btn" style={{ textDecoration: "none" }}>
          <span className="material-symbols-rounded">home</span>
          Home
        </Link>
      </div>
    </div>
  );
}
