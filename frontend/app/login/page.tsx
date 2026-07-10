import type { Metadata } from "next";
import Link from "next/link";
import "./login.css";

export const metadata: Metadata = {
  title: "AIOS · Team Sign in",
  description: "Sign in to your AIOS team workspace.",
};

// Placeholder team sign-in. The form is visual only for now — real
// authentication is wired once the FastAPI auth service exists. Until
// then, "Continue" drops you into the portal. This page is deliberately
// separate from the admin dashboard: team members land here, not there.
export default function TeamLogin() {
  return (
    <div className="login-wrap">
      <div className="login-card">
        <div className="login-brand">
          <div className="logo" />
          <div>
            <div className="login-brand-n">AIOS</div>
            <div className="login-brand-s">Team Workspace</div>
          </div>
        </div>

        <h1 className="login-h">Sign in to your portal</h1>
        <p className="login-sub">Welcome back. Enter the credentials your admin shared with you.</p>

        <form className="login-form" action="/portal">
          <label className="login-fld">
            <span>Work email</span>
            <div className="login-input">
              <span className="material-symbols-rounded">mail</span>
              <input type="email" name="email" placeholder="you@xegents.ai" autoComplete="username" />
            </div>
          </label>

          <label className="login-fld">
            <span>Password</span>
            <div className="login-input">
              <span className="material-symbols-rounded">lock</span>
              <input type="password" name="password" placeholder="••••••••••" autoComplete="current-password" />
            </div>
          </label>

          <div className="login-row">
            <label className="login-remember">
              <input type="checkbox" defaultChecked /> Keep me signed in
            </label>
            <span className="login-link">Forgot password?</span>
          </div>

          {/* No backend yet — submitting navigates straight to the portal. */}
          <button type="submit" className="primary-btn wide">
            <span className="material-symbols-rounded">login</span>Sign in
          </button>
        </form>

        <div className="login-note">
          <span className="material-symbols-rounded">info</span>
          <span>Demo build — sign-in isn&apos;t enforced yet. <Link href="/portal">Continue to the portal →</Link></span>
        </div>
      </div>

      <div className="login-foot">Provisioned by your agency admin · Built by Xegents AI</div>
    </div>
  );
}
