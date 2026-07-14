"use client";

import { useEffect, useState } from "react";
import {
  ROLE_META, STATUS_META, dueInfo,
  type TeamMemberRecord, type Task,
} from "@/lib/data";

function greeting(name: string): string {
  const h = new Date().getHours();
  const part = h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  return `${part}, ${name.split(" ")[0]}`;
}

export default function PortalHeader({
  me, myTasks,
}: {
  me: TeamMemberRecord;
  myTasks: Task[];
}) {
  // Greeting is time-of-day aware — resolve on the client to avoid a
  // hydration mismatch, then keep it fresh.
  const [hi, setHi] = useState(`Welcome, ${me.name.split(" ")[0]}`);
  useEffect(() => { setHi(greeting(me.name)); }, [me.name]);

  const open = myTasks.filter((t) => t.status !== "done");
  const next = [...open]
    .map((t) => ({ t, d: dueInfo(t.due) }))
    .sort((a, b) => a.d.days - b.d.days)[0];
  const role = ROLE_META[me.role];
  const status = STATUS_META[me.status];

  return (
    <section className="pt-hero">
      <span className="pt-hero-av av" style={{ background: me.c }}>{me.init}</span>

      <div className="pt-hero-id">
        <div className="pt-hero-hi">{hi}</div>
        <div className="pt-hero-name">{me.name}</div>
        <div className="pt-hero-meta">
          <span className="role-chip" style={{ color: role.c, borderColor: role.c }}>{me.role}</span>
          <span className="pt-hero-title">{me.title}</span>
          <span className="status-dot">
            <span className="dot" style={{ background: status.c, boxShadow: `0 0 8px ${status.c}` }} />
            {status.label}
          </span>
        </div>
      </div>

      <div className="pt-hero-side">
        <div className="pt-hero-focus">
          {next ? (
            <>
              <span className="pt-focus-k">Next up</span>
              <span className="pt-focus-v">{next.t.title}</span>
              <span className={`pt-focus-due ${next.d.tone}`}>
                <span className="material-symbols-rounded">schedule</span>{next.d.label}
              </span>
            </>
          ) : (
            <>
              <span className="pt-focus-k">Your queue</span>
              <span className="pt-focus-v">All clear — nothing open 🎉</span>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
