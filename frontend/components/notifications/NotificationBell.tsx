"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import {
  useAcknowledgeAlert,
  useAlerts,
  useMarkAllRead,
  useMarkNotificationRead,
  useNotificationToasts,
  useNotifications,
  useUnreadCount,
} from "@/lib/hooks/notifications";
import { SEVERITY_CLS, agoFrom, iconForKind } from "@/lib/notifications";

// The notification surface — the thing that finally READS the delivery layer.
//
// The backend has written `public.notifications` rows for a long time: task
// assignments, review outcomes, deadline decisions, audit completions. No screen in
// any of the three portals displayed one. Meanwhile Settings offered per-event
// email/in-app toggles, so an operator could configure the visibility of
// notifications the product had no way to show them.
//
// Mounted in the shared TopBar, so it is present on all 26 pages across admin, team
// and client with one mount point.
//
// TWO FEEDS, ONE CONTROL. A notification is personal and is READ; an alert is an
// agency-wide operational signal and is ACKNOWLEDGED. They are different objects with
// different audiences — a portal client has an inbox but is 403'd from alerts — so
// they are separate tabs rather than one merged list that would have to explain
// itself.
export default function NotificationBell() {
  const { session } = useAuth();
  const isStaff = session?.role === "admin" || session?.role === "team";

  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"inbox" | "alerts">("inbox");
  const wrapRef = useRef<HTMLDivElement>(null);

  const unreadQ = useUnreadCount();
  // Announce arrivals while the portal is open (QA 4). Lives here because the bell is
  // the one component mounted on every page of all three portals, via TopBar — a team
  // member on their dashboard gets the toast without the dashboard knowing about it.
  // Suppressed while the panel is open: the operator is already looking at the inbox,
  // and toasting what they can see would be noise.
  useNotificationToasts(!open);
  // Bodies are fetched only while the panel is open; the always-mounted cost is the
  // one-integer badge poll.
  const listQ = useNotifications(open && tab === "inbox");
  const alertsQ = useAlerts(open && tab === "alerts" && isStaff);
  const markRead = useMarkNotificationRead();
  const markAll = useMarkAllRead();
  const ack = useAcknowledgeAlert();

  const unread = unreadQ.data?.unread ?? 0;
  const items = listQ.data ?? [];
  const alerts = alertsQ.data ?? [];

  // Close on outside click / Escape. A panel that traps the page is worse than none.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!session) return null;

  return (
    <div className="nb" ref={wrapRef}>
      <button
        type="button"
        className={`nb-btn${unread > 0 ? " has" : ""}`}
        onClick={() => setOpen((o) => !o)}
        aria-label={unread > 0 ? `Notifications — ${unread} unread` : "Notifications"}
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <span className="material-symbols-rounded">notifications</span>
        {/* Only ever a real count. The one badge this app shipped before was the
            literal "3" pinned to Policy Radar in the sidebar. */}
        {unread > 0 && <span className="nb-badge">{unread > 99 ? "99+" : unread}</span>}
      </button>

      {open && (
        <div className="nb-panel" role="dialog" aria-label="Notifications">
          <div className="nb-head">
            {isStaff ? (
              <div className="seg nb-tabs" role="tablist" aria-label="Notification feeds">
                <button role="tab" aria-selected={tab === "inbox"} className={tab === "inbox" ? "on" : ""} onClick={() => setTab("inbox")}>
                  Inbox{unread > 0 ? ` (${unread})` : ""}
                </button>
                <button role="tab" aria-selected={tab === "alerts"} className={tab === "alerts" ? "on" : ""} onClick={() => setTab("alerts")}>
                  Alerts
                </button>
              </div>
            ) : (
              <div className="nb-title">Notifications</div>
            )}
            {tab === "inbox" && unread > 0 && (
              <button type="button" className="mini-btn" disabled={markAll.isPending} onClick={() => markAll.mutate()}>
                Mark all read
              </button>
            )}
          </div>

          <div className="nb-list">
            {tab === "inbox" ? (
              <>
                {listQ.isLoading && <div className="nb-state">Loading…</div>}
                {listQ.isError && !listQ.isLoading && (
                  <div className="nb-state err" role="alert">
                    Couldn&apos;t load notifications.
                    <button type="button" className="mini-btn" onClick={() => void listQ.refetch()}>Retry</button>
                  </div>
                )}
                {!listQ.isLoading && !listQ.isError && items.length === 0 && (
                  <div className="nb-state">You&apos;re all caught up.</div>
                )}
                {items.map((n) => (
                  <button
                    type="button"
                    key={n.id}
                    className={`nb-item${n.read ? "" : " unread"}`}
                    onClick={() => !n.read && markRead.mutate(n.id)}
                    title={n.read ? undefined : "Mark read"}
                  >
                    <span className="nb-ic material-symbols-rounded">{iconForKind(n.kind)}</span>
                    <span className="nb-main">
                      <span className="nb-t">{n.title}</span>
                      {n.body && <span className="nb-b">{n.body}</span>}
                      <span className="nb-when">{agoFrom(n.createdAt)}</span>
                    </span>
                    {!n.read && <span className="nb-dot" aria-label="Unread" />}
                  </button>
                ))}
              </>
            ) : (
              <>
                {alertsQ.isLoading && <div className="nb-state">Loading…</div>}
                {alertsQ.isError && !alertsQ.isLoading && (
                  <div className="nb-state err" role="alert">Couldn&apos;t load alerts.</div>
                )}
                {!alertsQ.isLoading && !alertsQ.isError && alerts.length === 0 && (
                  <div className="nb-state">No open alerts.</div>
                )}
                {ack.isError && (
                  <div className="nb-state err" role="alert">
                    Couldn&apos;t acknowledge — this is lead-only.
                  </div>
                )}
                {alerts.map((a) => (
                  <div className="nb-item alert" key={a.id}>
                    <span className={`nb-sev ${SEVERITY_CLS[a.severity] ?? "mut"}`} aria-label={`Severity: ${a.severity}`} />
                    <span className="nb-main">
                      <span className="nb-t">{a.type.replace(/_/g, " ")}</span>
                      <span className="nb-b">{a.detail}</span>
                      <span className="nb-when">{agoFrom(a.createdAt)}</span>
                    </span>
                    <button
                      type="button"
                      className="mini-btn"
                      disabled={ack.isPending}
                      onClick={() => ack.mutate(a.id)}
                    >
                      Acknowledge
                    </button>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
