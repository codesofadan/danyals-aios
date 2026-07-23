"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, ROLE_META, type Role } from "@/lib/auth";
import { useLoader } from "@/components/loader/LoaderProvider";

const PORTALS: Role[] = ["admin", "team", "client"];

export default function LoginForm() {
  const { session, ready, login } = useAuth();
  const router = useRouter();
  const loader = useLoader();
  const [portal, setPortal] = useState<Role>("admin");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [expired, setExpired] = useState(false);

  // Bounced here by a 401 (expired/absent token)? Read the flag client-side
  // (avoids useSearchParams' Suspense requirement on this route).
  useEffect(() => {
    setExpired(new URLSearchParams(window.location.search).get("expired") === "1");
  }, []);

  // Already signed in? Skip the form and go to that role's dashboard.
  useEffect(() => {
    if (ready && session) router.replace(ROLE_META[session.role].home);
  }, [ready, session, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!username.trim() || !password) {
      setError("Enter both your username and password.");
      return;
    }
    setBusy(true);
    const res = await login(username.trim(), password);
    if (res.ok) {
      loader.navigate("Opening your workspace");
      // An admin lands on whichever portal tab they picked (super-admin preview);
      // team/client always land on their own portal (the server role wins).
      const dest = res.role === "admin" ? portal : res.role;
      router.replace(ROLE_META[dest].home);
    } else {
      setError(res.error);
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-brand">
          <div className="logo" />
          <div>
            <div className="login-brand-n">AIOS</div>
            <div className="login-brand-s">AIOS</div>
          </div>
        </div>

        <h1 className="login-h">Sign in to AIOS</h1>

        {/* Portal selector — pick which workspace you're signing into. The server
            still authorises by your account's real role; this sets where you land. */}
        <div className="seg login-portal-seg" role="tablist" aria-label="Portal">
          {PORTALS.map((p) => (
            <button
              key={p}
              type="button"
              role="tab"
              aria-selected={portal === p}
              className={portal === p ? "on" : undefined}
              onClick={() => setPortal(p)}
            >
              <span className="material-symbols-rounded">{ROLE_META[p].icon}</span>
              {ROLE_META[p].label}
            </button>
          ))}
        </div>
        <p className="login-sub">{ROLE_META[portal].hint}</p>

        <form className="login-form" onSubmit={submit}>
          {expired && !error && (
            <div className="login-error" role="status">
              <span className="material-symbols-rounded">schedule</span>
              Your session expired — please sign in again.
            </div>
          )}

          <label className="login-fld">
            <span>Email or username</span>
            <div className="login-input">
              <span className="material-symbols-rounded">mail</span>
              <input
                type="text"
                name="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="you@qanry.com"
                autoComplete="username"
                autoFocus
              />
            </div>
          </label>

          <label className="login-fld">
            <span>Password</span>
            <div className="login-input">
              <span className="material-symbols-rounded">lock</span>
              <input
                type="password"
                name="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••••"
                autoComplete="current-password"
              />
            </div>
          </label>

          {error && (
            <div className="login-error" role="alert">
              <span className="material-symbols-rounded">error</span>
              {error}
            </div>
          )}

          <button type="submit" className="primary-btn wide" disabled={busy}>
            <span className="material-symbols-rounded">login</span>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <div className="login-note">
          <span className="material-symbols-rounded">info</span>
          <span>Every dashboard sits behind this sign-in. Your role decides which workspace opens.</span>
        </div>
      </div>

      <div className="login-foot">Provisioned by your agency admin · AIOS</div>
    </div>
  );
}
