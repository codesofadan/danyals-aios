"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth, ROLE_META, type Role } from "@/lib/auth";
import { useLoader } from "@/components/loader/LoaderProvider";

const ROLES: Role[] = ["admin", "team", "client"];

export default function LoginForm() {
  const { session, ready, login } = useAuth();
  const router = useRouter();
  const loader = useLoader();
  const [role, setRole] = useState<Role>("admin");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Already signed in? Skip the form and go to that role's dashboard.
  useEffect(() => {
    if (ready && session) router.replace(ROLE_META[session.role].home);
  }, [ready, session, router]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const res = login(role, username, password);
    if (res.ok) {
      loader.navigate("Opening your workspace");
      router.replace(ROLE_META[role].home);
    } else {
      setError(res.error ?? "Sign-in failed.");
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
        <p className="login-sub">Choose how you&apos;re signing in, then enter the credentials your agency issued you.</p>

        <form className="login-form" onSubmit={submit}>
          <div className="login-fld">
            <span>Sign in as</span>
            <div className="login-roles" role="radiogroup" aria-label="Role">
              {ROLES.map((r) => {
                const m = ROLE_META[r];
                return (
                  <button
                    type="button"
                    key={r}
                    role="radio"
                    aria-checked={role === r}
                    className={`login-role${role === r ? " on" : ""}`}
                    onClick={() => { setRole(r); setError(null); }}
                  >
                    <span className="material-symbols-rounded">{m.icon}</span>
                    {m.label}
                  </button>
                );
              })}
            </div>
            <div className="login-role-hint">{ROLE_META[role].hint}</div>
          </div>

          <label className="login-fld">
            <span>{role === "admin" ? "Admin email" : role === "team" ? "Work email" : "Portal login"}</span>
            <div className="login-input">
              <span className="material-symbols-rounded">mail</span>
              <input
                type="text"
                name="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder={role === "client" ? "admin@yourcompany.com" : "you@xegents.ai"}
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
            Sign in as {ROLE_META[role].label}
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
