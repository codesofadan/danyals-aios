"use client";

import { useState } from "react";
import { notificationDefaults, type NotifPref } from "@/lib/data";
import { Switch } from "./controls";

type LogFn = (action: string, target: string, meta?: string) => void;

export default function NotificationSettings({ onLog }: { onLog: LogFn }) {
  const [prefs, setPrefs] = useState<NotifPref[]>(notificationDefaults);

  function toggle(key: string, channel: "email" | "inApp", value: boolean) {
    setPrefs((prev) => prev.map((p) => (p.key === key ? { ...p, [channel]: value } : p)));
    const p = prefs.find((x) => x.key === key);
    onLog(`${value ? "enabled" : "disabled"} ${channel === "email" ? "email" : "in-app"} alerts`, p?.label ?? key, "Notifications");
  }

  return (
    <div className="panel-in">
      <div className="panel-h">
        <div className="panel-hint">
          <span className="material-symbols-rounded">notifications</span>
          Choose how the platform reaches you for each event
        </div>
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
