"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { usePortal } from "./PortalContext";
import { useStore } from "@/lib/store";
import { useAuth } from "@/lib/auth";
import { toolForKey } from "@/lib/tools";

type Item = { icon: string; label: string; href: string; badge?: number };

export default function TeamSidebar() {
  const pathname = usePathname();
  const { me, members, memberId, setMemberId, openCount, reviewCount } = usePortal();
  const { memberGrants } = useStore();
  const { logout } = useAuth();

  const items: Item[] = [
    { icon: "space_dashboard", label: "Team Dashboard", href: "/portal" },
    { icon: "view_kanban", label: "My Queue", href: "/portal/queue", badge: openCount },
    { icon: "play_circle", label: "Deliver", href: "/portal/deliver" },
    { icon: "how_to_reg", label: "Review", href: "/portal/review", badge: reviewCount },
    { icon: "shield_person", label: "My Access", href: "/portal/access" },
    { icon: "history", label: "Activity", href: "/portal/activity" },
  ];

  // The tools this member can actually open — exactly what the admin
  // granted them, in feature order.
  const myTools = (memberGrants[me.id] ?? [])
    .map((key) => toolForKey(key))
    .filter((t): t is NonNullable<typeof t> => Boolean(t));

  return (
    <aside className="sidebar team-side">
      <div className="brand">
        <div className="logo" />
        <div className="wm">
          <div className="n">AIOS</div>
          <div className="s">Team</div>
        </div>
      </div>

      <nav className="nav">
        <div>
          <div className="sec">My Workspace</div>
          {items.map((it) => {
            const active =
              pathname === it.href || (it.href !== "/portal" && pathname.startsWith(`${it.href}/`));
            return (
              <Link key={it.label} href={it.href} className={active ? "active" : undefined}>
                <span className="material-symbols-rounded">{it.icon}</span>
                <span className="lbl">{it.label}</span>
                {it.badge ? <span className="badge-n">{it.badge}</span> : null}
              </Link>
            );
          })}
        </div>

        {myTools.length > 0 && (
          <div>
            <div className="sec">My Tools</div>
            {myTools.map((t) => {
              const href = `/portal/tools/${t.slug}`;
              const active = pathname === href;
              return (
                <Link key={t.key} href={href} className={active ? "active" : undefined} title={t.label}>
                  <span className="material-symbols-rounded">{t.icon}</span>
                  <span className="lbl">{t.label}</span>
                </Link>
              );
            })}
          </div>
        )}
      </nav>

      <div className="side-foot">
        {/* Demo-only account switcher — real auth resolves the member from
            the session. Lets you preview any member's portal for now. */}
        <label className="ts-switch">
          <span className="ts-switch-l">Signed in as</span>
          <select value={memberId} onChange={(e) => setMemberId(e.target.value)} aria-label="Signed in as">
            {members.map((m) => (
              <option key={m.id} value={m.id}>{m.name}</option>
            ))}
          </select>
        </label>

        <div className="userchip">
          <div className="av" style={{ background: me.c }}>{me.init}</div>
          <div className="who">
            <div className="nm">{me.name}</div>
            <div className="rl">{me.title}</div>
          </div>
          <button type="button" onClick={logout} className="ts-logout" title="Sign out" aria-label="Sign out">
            <span className="material-symbols-rounded">logout</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
