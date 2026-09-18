import { redirect } from "next/navigation";

// The site root.
//
// This WAS the public free-audit lead magnet: a stranger typed their own site and
// email, and the platform ran a real crawl for them. It was retired on the client's
// 2026-09-17 instruction - audits are now run by an operator from the dashboard and
// SHARED as a link (`/leads/<slug>`), which is the same report without an
// anonymous, unauthenticated path to a crawl.
//
// Redirecting rather than serving a marketing page: this deployment is an internal
// operations platform, and the only thing a visitor at the root can usefully do is
// sign in. Already-issued report links are unaffected - they live under /leads.
export default function RootPage() {
  redirect("/login");
}
