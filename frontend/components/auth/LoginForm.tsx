"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, ROLE_META } from "@/lib/auth";
import { useLoader } from "@/components/loader/LoaderProvider";

export default function LoginForm() {
  const { session, ready, login } = useAuth();
  const router = useRouter();
  const loader = useLoader();
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
      router.replace(ROLE_META[res.role].home); // the SERVER decides the portal
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
            <div className="login-brand-s">Xegents</div>
          </div>
        </div>

        <h1 className="login-h">Sign in to AIOS</h1>
        <p className="login-sub">Enter the credentials your agency issued you — your role opens the right workspace.</p>

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
                placeholder="you@xegents.ai"
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

      <div className="login-foot">Provisioned by your agency admin · Built by Xegents AI</div>
    </div>
  );
}
