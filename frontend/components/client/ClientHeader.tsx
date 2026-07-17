"use client";

import { useEffect, useState } from "react";
import { HEALTH_META } from "@/lib/milestones";
import { useClient } from "./ClientContext";
import { useClientMilestones } from "@/lib/hooks/portalClient";

function greeting(name: string): string {
  const h = new Date().getHours();
  const part = h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  return `${part}, ${name.split(" ")[0]}`;
}

// Shared hero across the client portal pages — identity, plan, health. A portal
// login IS the client (the company), so the identity is company-level: the
// avatar/initials are derived from the name, and health comes from the client's
// own /portal/milestones project.
export default function ClientHeader({ eyebrow, focus }: { eyebrow: string; focus?: React.ReactNode }) {
  const { client, grants } = useClient();
  const project = useClientMilestones().data;
  const health = project ? HEALTH_META[project.health] : null;

  const [hi, setHi] = useState(`Welcome, ${client.cn.split(" ")[0]}`);
  useEffect(() => { setHi(greeting(client.cn)); }, [client.cn]);

  return (
    <section className="cl-hero">
      <span className="cl-hero-av av" style={{ background: client.c }}>{client.init}</span>

      <div className="cl-hero-id">
        <div className="cl-hero-hi">{eyebrow ?? hi}</div>
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
