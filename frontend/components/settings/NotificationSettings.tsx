"use client";

import { useEffect, useRef, useState } from "react";
import { type NotifPref } from "@/lib/data";
import { useNotificationSettings, useSaveNotificationSettings } from "@/lib/hooks/settings";
import { Switch } from "./controls";

type LogFn = (action: string, target: string, meta?: string) => void;

export default function NotificationSettings({ onLog }: { onLog: LogFn }) {
  // Per-user notification prefs (GET/PUT /settings/notifications). Each toggle
  // upserts the one changed (event, channel) row via the partial PUT.
  const notifQ = useNotificationSettings();
  const saveNotif = useSaveNotificationSettings();
  const [prefs, setPrefs] = useState<NotifPref[] | null>(null);

  const seeded = useRef(false);
  useEffect(() => {
    if (!seeded.current && notifQ.data) { setPrefs(notifQ.data); seeded.current = true; }
  }, [notifQ.data]);

  function toggle(key: string, channel: "email" | "inApp", value: boolean) {
    setPrefs((prev) => (prev ? prev.map((p) => (p.key === key ? { ...p, [channel]: value } : p)) : prev));
    const cur = prefs?.find((x) => x.key === key);
    if (cur) {
      const nextRow = { ...cur, [channel]: value };
      saveNotif.mutate([{ key, email: nextRow.email, inApp: nextRow.inApp }]);
    }
    onLog(`${value ? "enabled" : "disabled"} ${channel === "email" ? "email" : "in-app"} alerts`, cur?.label ?? key, "Notifications");
  }

  const muted: React.CSSProperties = { padding: "2.5rem 1rem", textAlign: "center", color: "var(--muted)" };
  if (notifQ.isLoading && !prefs) return <div className="panel-in"><div style={muted}>Loading notification preferences…</div></div>;
  if (notifQ.isError && !prefs)
    return <div className="panel-in"><div style={muted}>Couldn&apos;t load — {(notifQ.error as Error)?.message ?? "try again"}.</div></div>;
  if (!prefs) return null;

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">notifications</span>
          Choose how the platform reaches you for each event
        </div>
        {saveNotif.isError && (
          <div className="sec-note inline" role="alert">
            <span className="material-symbols-rounded">error</span>
            Couldn&apos;t save the last change — {(saveNotif.error as Error)?.message ?? "try again"}.
          </div>
        )}
      </div>

      <div className="tbl-wrap">
        <table className="tbl notif-tbl">
          <thead>
            <tr>
              <th>Event</th>
              <th className="ta-c">Email</th>
              <th className="ta-c">In-app</th>
            </tr>
          </thead>
          <tbody>
            {prefs.map((p) => (
              <tr key={p.key}>
                <td>
                  <div className="mem">
                    <span className="notif-ic material-symbols-rounded">{p.icon}</span>
                    <div className="mem-meta">
                      <div className="mem-name">{p.label}</div>
                      <div className="mem-sub">{p.desc}</div>
                    </div>
                  </div>
                </td>
                <td className="ta-c"><Switch checked={p.email} onChange={(v) => toggle(p.key, "email", v)} label={`Email alerts for ${p.label}`} /></td>
                <td className="ta-c"><Switch checked={p.inApp} onChange={(v) => toggle(p.key, "inApp", v)} label={`In-app alerts for ${p.label}`} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
