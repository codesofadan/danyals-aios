"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth, type Role, ROLE_META } from "@/lib/auth";

// Wraps a dashboard shell and blocks it unless the signed-in session holds
// the required role. No session (or the wrong role) → bounce to /login.
// While the persisted session is still hydrating we render a neutral splash
// so protected content never flashes before the check completes.
//
// UX ONLY — this is NOT the security boundary. It gates what CHROME shows; every
// byte of real data is authorized server-side (bearer token → RLS + require_perm).
// A tampered session snapshot buys nothing: the token still fails on the API, and
// lib/api bounces the user back to /login.
export default function AuthGuard({ role, children }: { role: Role; children: React.ReactNode }) {
  const { session, ready } = useAuth();
  const router = useRouter();

  const allowed = ready && session?.role === role;

  useEffect(() => {
    if (!ready) return;
    if (!session) {
      router.replace("/login");
    } else if (session.role !== role) {
      // Signed in under a different role — send them to their own home.
      router.replace(ROLE_META[session.role].home);
    }
  }, [ready, session, role, router]);

  if (!allowed) {
    return (
      <div className="auth-splash">
        <div className="auth-splash-logo" />
        <div className="auth-splash-txt">Checking your access…</div>
      </div>
    );
  }

  return <>{children}</>;
}
