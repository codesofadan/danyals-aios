"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { usePortal } from "./PortalContext";
import { useAuth } from "@/lib/auth";
import { toolForKey } from "@/lib/tools";
import { TEAM_NAV } from "@/lib/nav";


export default function TeamSidebar() {
  const pathname = usePathname();
  const { me, myGrants, openCount } = usePortal();
  const { logout } = useAuth();

  // Identity from lib/nav.ts; the runtime COUNTS are this shell's context and
  // are attached here by href.
  const counts: Record<string, number> = {
    "/team/queue": openCount,
  };
  const items = TEAM_NAV.map((it) => ({ ...it, count: counts[it.href] }));

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
                {it.count ? <span className="badge-n">{it.count}</span> : null}
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
