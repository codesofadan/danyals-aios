"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth, ROLE_META } from "@/lib/auth";
import { isNavLocked } from "@/lib/lockedInProd";
import { initialsOf } from "@/lib/initials";

type Item = { icon: string; label: string; href: string; badge?: string };
type Section = { title: string; items: Item[] };

// Only built, navigable routes live here — module items are added as
// each module ships.
const SECTIONS: Section[] = [
  {
    title: "Overview",
    items: [
      { icon: "space_dashboard", label: "Admin Dashboard", href: "/admin" },
    ],
  },
  {
    title: "SEO Engine",
    items: [
      { icon: "fact_check", label: "Audit", href: "/admin/audit" },
      { icon: "contact_mail", label: "Free Audits", href: "/admin/leads" },
      { icon: "article", label: "Content", href: "/admin/content" },
      { icon: "language", label: "WordPress", href: "/admin/wordpress" },
      { icon: "storefront", label: "Citations", href: "/admin/citations", badge: "off" },
      { icon: "rocket_launch", label: "Web 2.0", href: "/admin/web2", badge: "test" },
      { icon: "radar", label: "Policy Radar", href: "/admin/policy-radar" },
    ],
  },
  {
    title: "Delivery",
    items: [
      { icon: "diversity_3", label: "Clients", href: "/admin/clients" },
      { icon: "flag", label: "Milestones", href: "/admin/milestones" },
      { icon: "groups", label: "Team Management", href: "/admin/team" },
      { icon: "task_alt", label: "Task Manager", href: "/admin/tasks" },
      { icon: "summarize", label: "Reports", href: "/admin/reports" },
    ],
  },
  {
    title: "Platform",
    items: [
      // First in the group: Operations is the health surface. Every other item here
      // configures the platform; this one says whether it is actually working.
      { icon: "monitor_heart", label: "Operations", href: "/admin/operations" },
      { icon: "savings", label: "Cost Controls", href: "/admin/cost" },
      { icon: "key", label: "Key Vault", href: "/admin/vault" },
      { icon: "settings", label: "Settings", href: "/admin/settings" },
    ],
  },
];

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
          <div className="n">AIOS</div>
          <div className="s">AIOS</div>
        </div>
      </div>

      <nav className="nav">
        {SECTIONS.map((sec) => (
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
