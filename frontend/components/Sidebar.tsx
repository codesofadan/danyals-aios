"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth, ROLE_META } from "@/lib/auth";
import { isNavLocked } from "@/lib/lockedInProd";
import { ADMIN_NAV } from "@/lib/nav";
import { initialsOf } from "@/lib/initials";

// The nav tree lives in lib/nav.ts - ONE table renders here and indexes the
// search box, so the two can never drift again (they had: /admin/operations
// was in this sidebar and missing from search).
// The production lock list lives in ONE place — lib/lockedInProd.ts. Do not
// reintroduce a local copy here; lib/nav.test.ts fails if a second one appears.

export default function Sidebar() {
  const pathname = usePathname();
  const { session, logout } = useAuth();
  // At rest the nav is a thin docked handle; hovering floats it out (pure CSS).
  // `pinned` holds the floated/expanded state open and reflows the page content.
  const [pinned, setPinned] = useState(false);

  // Only a pinned nav reserves space — hover is a transient overlay, so peeking
  // never shifts the page. The class drives `.main`'s left margin.
  useEffect(() => {
    document.body.classList.toggle("nav-pinned", pinned);
    return () => document.body.classList.remove("nav-pinned");
  }, [pinned]);

  return (
    <aside className={`sidebar ${pinned ? "pinned" : ""}`}>
      <button
        type="button"
        className="fn-arrow"
        onClick={() => setPinned((p) => !p)}
        aria-label={pinned ? "Unpin navigation" : "Pin navigation open"}
        aria-pressed={pinned}
      >
        <span className="material-symbols-rounded">chevron_right</span>
      </button>

      <div className="brand">
        <div className="logo" />
        <div className="wm">
          {/* The subtitle names the WORKSPACE - TeamSidebar says "Team" and
              ClientSidebar says "Client". This one read "AIOS" under "AIOS":
              the line originally carried the builder's agency name, and when
              that was stripped for white-labelling it was blanket-replaced
              with the product name, breaking the pattern rather than filling
              it. "Agency" is the shell this is - the agency's own workspace,
              beside the Team portal and the Client portal. (Not "Admin": that
              collides with the operator name in the user chip below.) */}
          <div className="n">AIOS</div>
          <div className="s">Agency</div>
        </div>
      </div>

      <nav className="nav">
        {ADMIN_NAV.map((sec) => (
          <div key={sec.title}>
            <div className="sec">{sec.title}</div>
            {sec.items
              .filter((it) => !isNavLocked(it.href))
              .map((it) => {
              const active =
                it.href !== "#" &&
                (pathname === it.href || (it.href !== "/admin" && pathname.startsWith(`${it.href}/`)));
              return (
                <Link key={it.label} href={it.href} className={active ? "active" : undefined}>
                  <span className="material-symbols-rounded">{it.icon}</span>
                  <span className="lbl">{it.label}</span>
                  {it.badge && <span className="badge-n">{it.badge}</span>}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="side-foot">
        <div className="userchip">
          <div className="av">{session ? initialsOf(session.name) : "\u2026"}</div>
          <div className="who">
            <div className="nm">{session?.name ?? "Signed in"}</div>
            <div className="rl">{session ? ROLE_META[session.role].label : "\u00a0"}</div>
          </div>
          <button type="button" onClick={logout} className="ts-logout" title="Sign out" aria-label="Sign out">
            <span className="material-symbols-rounded">logout</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
