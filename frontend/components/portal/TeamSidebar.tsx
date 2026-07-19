"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { usePortal } from "./PortalContext";
import { useAuth } from "@/lib/auth";
import { toolForKey } from "@/lib/tools";

type Item = { icon: string; label: string; href: string; badge?: number };

export default function TeamSidebar() {
  const pathname = usePathname();
  const { me, myGrants, openCount, reviewCount } = usePortal();
  const { logout } = useAuth();

  const items: Item[] = [
    { icon: "space_dashboard", label: "Team Dashboard", href: "/team" },
    { icon: "view_kanban", label: "My Queue", href: "/team/queue", badge: openCount },
    { icon: "play_circle", label: "Deliver", href: "/team/deliver" },
    { icon: "how_to_reg", label: "Review", href: "/team/review", badge: reviewCount },
    { icon: "shield_person", label: "My Access", href: "/team/access" },
    { icon: "history", label: "Activity", href: "/team/activity" },
  ];

  // The tools this member can actually open — exactly what the admin
  // granted them, in feature order.
  const myTools = myGrants
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
              pathname === it.href || (it.href !== "/team" && pathname.startsWith(`${it.href}/`));
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
              const href = `/team/tools/${t.slug}`;
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
