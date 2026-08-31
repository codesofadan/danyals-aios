"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useClient } from "./ClientContext";
import { useAuth } from "@/lib/auth";
import { CLIENT_NAV } from "@/lib/nav";


export default function ClientSidebar() {
  const pathname = usePathname();
  const { client, grants, requests } = useClient();
  const { logout } = useAuth();

  const openRequests = requests.filter((r) => r.status !== "resolved").length;

  // Identity from lib/nav.ts; the unresolved-request count is this shell's
  // context, attached by href.
  const counts: Record<string, number> = { "/client/requests": openRequests };
  const items = CLIENT_NAV.map((it) => ({ ...it, count: counts[it.href] }));

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
                {it.count ? <span className="badge-n">{it.count}</span> : null}
              </Link>
            );
          })}
        </div>

        <div>
          <div className="sec">Access</div>
          <div className="cl-side-access">
            <span className="material-symbols-rounded">visibility</span>
            <span className="lbl">
              <b>{grants.size}</b> graphs shared with you
            </span>
          </div>
        </div>
      </nav>

      <div className="side-foot">
        {/* A signed-in client sees only its OWN tenant (RLS-scoped by token) —
            there is no account switcher and no cross-tenant preview. */}
        <div className="userchip">
          <div className="av" style={{ background: client.c }}>{client.init}</div>
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
