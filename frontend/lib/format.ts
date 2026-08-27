// ============================================================
// AIOS · formatting, once.
//
// A cost rendered as "$1,234" on one screen and "$1234.00" on another, and
// "2h ago" computed by three different client clocks, is how two boards showing
// the same fact stop agreeing. Measured before this file existed: 5 currency
// implementations (lib/cost.ts `usd` plus four locals), 3 relative-time
// implementations, and 6 date formatters — every one a per-file re-invention.
//
// This is the canonical home. lib/cost.ts and lib/jobs.ts re-export from here so
// their existing importers keep working; NEW code imports from "@/lib/format".
// ============================================================

/** "$1,234" (dp=0) or "$12.50" (dp=2). The one way money renders. */
export const usd = (n: number, dp = 0) =>
  "$" + n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });

/**
 * "5m ago" / "in 2h" from an ISO instant. BOTH directions on purpose: a run's
 * `scheduledFor` is in the future, and rendering it as "ago" would be a lie about
 * work that has not happened yet. "" for null/empty/unparseable, so a missing
 * timestamp renders as nothing rather than "Invalid Date".
 */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const delta = Math.round((Date.now() - then) / 1000);
  const secs = Math.abs(delta);
  const past = delta >= 0;
  const phrase = (text: string) => (past ? `${text} ago` : `in ${text}`);
  if (secs < 45) return past ? "just now" : "in a moment";
  if (secs < 3600) return phrase(`${Math.floor(secs / 60)}m`);
  if (secs < 86400) return phrase(`${Math.floor(secs / 3600)}h`);
  return phrase(`${Math.floor(secs / 86400)}d`);
}

/** "26 Aug, 14:05" — the one absolute date-time treatment for table cells.
 *  "" for null/unparseable, same contract as relativeTime. */
export function formatWhen(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

/** "4m 48s" / "1h 12m" from seconds. "" for null/negative. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds) || seconds < 0) return "";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) {
    const m = Math.floor(s / 60);
    const rest = s % 60;
    return rest ? `${m}m ${rest}s` : `${m}m`;
  }
  const h = Math.floor(s / 3600);
  const m = Math.round((s % 3600) / 60);
  return m ? `${h}h ${m}m` : `${h}h`;
}
