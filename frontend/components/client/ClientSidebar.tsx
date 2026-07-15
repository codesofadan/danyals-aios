"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useClient } from "./ClientContext";
import { useAuth } from "@/lib/auth";

type Item = { icon: string; label: string; href: string; badge?: number };

export default function ClientSidebar() {
  const pathname = usePathname();
  const { client, accounts, clientId, setClientId, grants, requests } = useClient();
  const { logout } = useAuth();

  const openRequests = requests.filter((r) => r.status !== "resolved").length;

  const items: Item[] = [
    { icon: "insights", label: "Client Dashboard", href: "/client" },
    { icon: "flag", label: "Milestones", href: "/client/milestones" },
    { icon: "summarize", label: "Reports", href: "/client/reports" },
    { icon: "forum", label: "Requests", href: "/client/requests", badge: openRequests },
  ];

  return (
    <aside className="sidebar client-side">
      <div className="brand">
        <div className="logo" />
        <div className="wm">
          <div className="n">AIOS</div>
          <div className="s">Client</div>
        </div>
      </div>

      <nav className="nav">
        <div>
          <div className="sec">My Workspace</div>
          {items.map((it) => {
            const active =
              pathname === it.href || (it.href !== "/client" && pathname.startsWith(`${it.href}/`));
            return (
              <Link key={it.label} href={it.href} className={active ? "active" : undefined}>
                <span className="material-symbols-rounded">{it.icon}</span>
                <span className="lbl">{it.label}</span>
                {it.badge ? <span className="badge-n">{it.badge}</span> : null}
              </Link>
            );
          })}
        </div>

        <div>
          <div className="sec">Access</div>
          <div className="cl-side-access">
            <span className="material-symbols-rounded">lock_open</span>
            <span className="lbl">
              <b>{grants.size}</b> graphs unlocked for you
            </span>
          </div>
        </div>
      </nav>

      <div className="side-foot">
        {/* Demo-only account switcher — real auth resolves the client from
            the session. Lets you preview any client's dashboard for now. */}
        <label className="ts-switch">
          <span className="ts-switch-l">Signed in as</span>
          <select value={clientId} onChange={(e) => setClientId(e.target.value)} aria-label="Signed in as">
            {accounts.map((c) => (
              <option key={c.id} value={c.id}>{c.cn}</option>
            ))}
          </select>
        </label>

        <div className="userchip">
          <div className="av" style={{ background: client.contact.c }}>{client.contact.init}</div>
          <div className="who">
            <div className="nm">{client.cn}</div>
            <div className="rl">{client.tier} plan</div>
          </div>
          <button type="button" onClick={logout} className="ts-logout" title="Sign out" aria-label="Sign out">
            <span className="material-symbols-rounded">logout</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
