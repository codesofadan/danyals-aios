// ============================================================
// AIOS · notifications & alerts
//
// The backend delivery layer has been complete for some time — `notify()`,
// `notify_leads()`, `raise_alert()`, per-user preferences, Resend email, a Slack
// escalation, an RLS-scoped inbox and four read endpoints. NOTHING IN THE FRONTEND
// READ ANY OF IT. Every `notify()` call wrote a row into `public.notifications` that
// no screen in any of the three portals would ever display; only the email leg
// reached a human, and Settings let an operator configure preferences for
// notifications the product never showed them.
//
// These types back the surface that finally reads it.
// ============================================================

/** One per-user notification. Any signed-in principal has an inbox — a portal client
 *  included; RLS scopes it to them. */
export type AppNotification = {
  id: string;
  kind: string;
  title: string;
  body: string;
  read: boolean;
  createdAt: string;
};

/** One staff alert (the lead queue). Distinct from a notification: alerts are
 *  agency-wide operational signals, acknowledged rather than read. */
export type StaffAlert = {
  id: string;
  clientId: string;
  type: string;
  severity: string;
  detail: string;
  acknowledged: boolean;
  createdAt: string;
};

/** Icon per notification kind. An unknown kind is not an error — the catalogue in
 *  `NOTIF_EVENTS` grows server-side — so it falls back rather than rendering blank. */
const KIND_ICON: Record<string, string> = {
  audit_done: "fact_check",
  content_review: "rate_review",
  new_ticket: "support_agent",
  past_due: "payments",
  member_login: "login",
  access_change: "admin_panel_settings",
  task_assigned: "assignment_ind",
  work_reviewed: "how_to_reg",
  task_completed: "task_alt",
  task_comment: "forum",
  deadline_requested: "event_upcoming",
  deadline_decided: "event_available",
};

export function iconForKind(kind: string): string {
  return KIND_ICON[kind] ?? "notifications";
}

export const SEVERITY_CLS: Record<string, string> = {
  critical: "crit",
  high: "warn",
  medium: "info",
  low: "mut",
};

/** "2h ago" from an ISO instant. The API sends `createdAt`; the humanized form is a
 *  display concern, so it is derived here rather than shipped as a second field. */
export function agoFrom(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return "just now";
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}
