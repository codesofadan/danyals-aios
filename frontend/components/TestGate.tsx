"use client";

import { useEffect, useState } from "react";

// A lightweight username/password gate for the in-test modules (Citations, Web 2.0)
// so they can ship in PRODUCTION but stay behind an extra credential while being
// validated. This is a SOFT gate (client-side, shared credential) layered on top of
// the admin login that already guards /admin — it is not cryptographic security, it
// just keeps the in-test pages behind a shared password the operator hands out.
// Access is remembered for the browser session (sessionStorage), per gate key.
const GATE_USER = "Adan2026";
const GATE_PASS = "Adan2026";

export default function TestGate({
  gateKey,
  label,
  children,
}: {
  gateKey: string;
  label: string;
  children: React.ReactNode;
}) {
  const storeKey = `aios-testgate-${gateKey}`;
  const [ok, setOk] = useState(false);
  const [ready, setReady] = useState(false);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    try {
      setOk(sessionStorage.getItem(storeKey) === "1");
    } catch {
      /* storage blocked — stay gated */
    }
    setReady(true);
  }, [storeKey]);

  // Avoid a flash of the gated content before hydration resolves.
  if (!ready) return null;
  if (ok) return <>{children}</>;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (username.trim() === GATE_USER && password === GATE_PASS) {
      try {
        sessionStorage.setItem(storeKey, "1");
      } catch {
        /* ignore */
      }
      setOk(true);
      setErr("");
    } else {
      setErr("Wrong username or password.");
    }
  }

  return (
    <section className="card" style={{ maxWidth: 420, margin: "48px auto" }}>
      <div className="card-h">
        <div>
          <div className="ct">
            <span className="material-symbols-rounded" style={{ verticalAlign: "middle", marginRight: 8 }}>
              lock
            </span>
            {label} — restricted
          </div>
          <div className="cs">This module is in testing. Enter the access credentials to continue.</div>
        </div>
      </div>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 12, padding: "4px 2px" }}>
        <div className="fld">
          <label>Username</label>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" placeholder="Username" />
        </div>
        <div className="fld">
          <label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="off" placeholder="Password" />
        </div>
        {err && (
          <div className="cs" role="alert" style={{ color: "var(--warn, #A96913)" }}>
            {err}
          </div>
        )}
        <button className="primary-btn wide" type="submit">
          <span className="material-symbols-rounded">key</span>
          Unlock {label}
        </button>
      </form>
    </section>
  );
}
