import { redirect } from "next/navigation";

// Modules that are LOCKED in production until they're fully built. The nav links are
// hidden in prod (see components/Sidebar.tsx LOCKED_IN_PROD) and these route pages
// also refuse direct-URL access there, redirecting to the dashboard. They remain
// fully usable in `next dev` so the team keeps building them. To relaunch a module,
// remove its guard call from the page and its href from Sidebar's LOCKED_IN_PROD.
export function blockIfLockedInProd(): void {
  if (process.env.NODE_ENV === "production") {
    redirect("/admin");
  }
}
