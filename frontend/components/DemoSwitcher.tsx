"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { useAuth, ROLE_META } from "@/lib/auth";

// A small floating session control: shows who's signed in and lets the user
// sign out (to switch between the admin / team / client portals via the login
// page). It only appears once you're signed in — every dashboard sits behind
// the login. (The old "reset demo data" button is gone: every screen is on the
// real API now, so there is no demo store left to reset.)
export default function DemoSwitcher() {
  const pathname = usePathname() || "/";
  const { session, logout } = useAuth();
  const [open, setOpen] = useState(false);

  // Nothing to show on the login screen or before a session exists. A cached
  // localStorage session snapshot can go stale (e.g. from an older build's role
  // shape) — guard against an unrecognized role rather than crash the whole shell.
  if (pathname.startsWith("/login") || !session) return null;
  const meta = ROLE_META[session.role];
  if (!meta) return null;

  return (
    <div className={`demo-switch${open ? " open" : ""}`} role="region" aria-label="Session controls">
      {open && (
        <div className="demo-switch-panel">
          <div className="demo-switch-h">
            <span className="material-symbols-rounded">{meta.icon}</span>
            Signed in
          </div>
          <div className="demo-switch-who">
            <div className="demo-switch-name">{session.name}</div>
            <div className="demo-switch-role">{meta.label}</div>
          </div>
          <button type="button" className="demo-switch-link" onClick={() => { setOpen(false); logout(); }}>
            <span className="material-symbols-rounded">logout</span>
            <span className="demo-switch-lbl">Sign out</span>
          </button>
          <div className="demo-switch-note">
            Sign out to switch between the admin, team &amp; client logins.
          </div>
        </div>
      )}
      <button
        type="button"
        className="demo-switch-fab"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-label={open ? "Close session menu" : "Open session menu"}
        title="Session"
      >
        <span className="material-symbols-rounded">{open ? "close" : meta.icon}</span>
      </button>
    </div>
  );
}
