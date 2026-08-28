import { redirect } from "next/navigation";

// ============================================================
// AIOS · the production module lock — the SINGLE definition
//
// A module that is not ready is hidden from the production bundle but stays fully
// usable in `next dev` so the team keeps building it.
//
// This file is the only place the list may live. It used to exist three times:
// Sidebar.tsx held its own set, TopBar.tsx held a DIFFERENT one, and this module's
// `blockIfLockedInProd` was never called by any page. The two copies had already
// drifted — the sidebar offered Citations and Web 2.0 in production while the search
// box behaved as though neither existed. `lib/nav.test.ts` now fails if a second
// definition reappears.
//
// WHAT IS LOCKED, AND WHY:
//
//   /admin/citations — LOCKED. Its page is a "temporarily disabled" card: directory
//   auto-submission is blocked by captcha and dead forms, so the module is off rather
//   than shipping misleading listings. Advertising it in the nav would offer an
//   operator a module that tells them it is disabled when they click it.
//
//   /admin/web2 — NOT locked. It was deliberately unlocked once Web 2.0 publishing was
//   verified end-to-end. It carries an honest "in testing" warning on the page itself
//   and a "test" badge in the nav, which is the right way to communicate that. TopBar
//   kept locking it only because it was the copy nobody updated.
//
// To relaunch a module: remove its href here. To lock one: add it here AND call
// `blockIfLockedInProd()` at the top of its page, or the route is still reachable by
// typing the URL.
// ============================================================

// The 2026-08-27 restructure folded Citations into /admin/web2 as a TAB;
// its lock card moved with it (see that page). No whole ROUTE is production-
// locked right now - the set stays as the mechanism for the next one.
export const LOCKED_IN_PROD = new Set<string>([]);

export const HIDE_LOCKED = process.env.NODE_ENV === "production";

/** True when this href must be hidden from navigation in the current build. */
export function isNavLocked(href: string): boolean {
  return HIDE_LOCKED && LOCKED_IN_PROD.has(href);
}

/** Refuse direct-URL access to a locked module in production. */
export function blockIfLockedInProd(): void {
  if (process.env.NODE_ENV === "production") {
    redirect("/admin");
  }
}
