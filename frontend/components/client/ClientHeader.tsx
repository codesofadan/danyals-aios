"use client";

import { useEffect, useState } from "react";
import { HEALTH_META } from "@/lib/milestones";
import { useClient } from "./ClientContext";
import { useClientMilestones } from "@/lib/hooks/portalClient";
import { ApiError } from "@/lib/api";

function greeting(name: string): string {
  const h = new Date().getHours();
  const part = h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  return `${part}, ${name.split(" ")[0]}`;
}

// Shared hero across the client portal pages — identity, plan, health. A portal
// login IS the client (the company), so the identity is company-level: the
// avatar/initials are derived from the name, and health comes from the client's
// own /portal/milestones project. The eyebrow line is the time-of-day greeting
// ("Good morning, {name}"), computed after mount to stay SSR-safe.
//
// ONLY THE HEALTH PILL DEGRADES. This hero is the client's own chrome — their
// name, their plan, their site — none of which comes from /portal/milestones, so
// a milestones failure must not take the header down with it; the tenant would be
// looking at a portal that had forgotten who they are. So the failure is scoped to
// the one figure that came from the failed read (which is why this file does not
// use QueryGuard: the guard replaces its whole region, and the region here is a
// single pill inside a flex row).
//
// A 404 is NOT a failure here: the hook documents it as "this client has no project
// yet", which is true and expected, and it stays silent exactly as before. Anything
// else — a 500, a dropped connection — says so, because a missing pill otherwise
// reads as "no health concerns".
export default function ClientHeader({ focus }: { focus?: React.ReactNode }) {
  const { client, grants } = useClient();
  const projectQ = useClientMilestones();
  const project = projectQ.data;
  const health = project ? HEALTH_META[project.health] : null;
  const healthUnavailable =
    !project && projectQ.isError && (projectQ.error as ApiError)?.status !== 404;

  const [hi, setHi] = useState(`Welcome, ${client.cn.split(" ")[0]}`);
  useEffect(() => { setHi(greeting(client.cn)); }, [client.cn]);

  return (
    <section className="cl-hero">
      <span className="cl-hero-av av" style={{ background: client.c }}>{client.init}</span>

      <div className="cl-hero-id">
        <div className="cl-hero-hi">{hi}</div>
        <div className="cl-hero-name">{client.cn}</div>
        <div className="cl-hero-meta">
          <span className="cl-hero-plan">{client.tier} plan</span>
          {client.site && <span className="cl-hero-title">{client.site}</span>}
          {health && (
            <span className={`status-pill ${health.cls}`}>
              <span className="material-symbols-rounded" style={{ fontSize: 14 }}>{health.icon}</span>
              {health.label}
            </span>
          )}
          {healthUnavailable && (
            <span className="status-pill mut" title="We couldn't reach the server for your project health.">
              <span className="material-symbols-rounded" style={{ fontSize: 14 }}>cloud_off</span>
              Health unavailable
            </span>
          )}
        </div>
      </div>

      <div className="cl-hero-side">
        <div className="cl-hero-focus">
          {focus ?? (
            <>
              <span className="cl-focus-k">Unlocked graphs</span>
              <span className="cl-focus-v">{grants.size} reports available to you</span>
              <span className="cl-focus-note">
                <span className="material-symbols-rounded">lock_open</span>Tap a locked card to reveal it
              </span>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
