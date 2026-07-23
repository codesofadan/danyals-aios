"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";

type Item = { icon: string; label: string; href: string; badge?: string };
type Section = { title: string; items: Item[] };

// Only built, navigable routes live here — module items are added as
// each module ships.
const SECTIONS: Section[] = [
  {
    title: "Overview",
    items: [
      { icon: "space_dashboard", label: "Admin Dashboard", href: "/admin" },
      // Features tab hidden for now (not needed). The /admin/features route still
      // exists — re-enable by uncommenting this nav item.
      // { icon: "grid_view", label: "Features", href: "/admin/features" },
    ],
  },
  {
    title: "SEO Engine",
    items: [
      { icon: "fact_check", label: "Audit", href: "/admin/audit" },
      { icon: "contact_mail", label: "Free Audits", href: "/admin/leads" },
      { icon: "article", label: "Content", href: "/admin/content" },
      { icon: "storefront", label: "Citations", href: "/admin/citations" },
      { icon: "rocket_launch", label: "Web 2.0", href: "/admin/web2" },
      { icon: "radar", label: "Policy Radar", href: "/admin/policy-radar", badge: "3" },
    ],
  },
  {
    title: "Delivery",
    items: [
      { icon: "diversity_3", label: "Clients", href: "/admin/clients" },
      { icon: "groups", label: "Team Management", href: "/admin/team" },
      // { icon: "flag", label: "Milestones", href: "/admin/milestones" }, // hidden for now
      { icon: "summarize", label: "Reports", href: "/admin/reports" },
    ],
  },
  {
    title: "Platform",
    items: [
      { icon: "savings", label: "Cost Controls", href: "/admin/cost" },
      { icon: "key", label: "Key Vault", href: "/admin/vault" },
      { icon: "settings", label: "Settings", href: "/admin/settings" },
    ],
  },
];

// Tabs LOCKED in PRODUCTION until the module is fully built. They stay visible in
// `next dev` (NODE_ENV !== 'production') so the team keeps building them; the prod
// bundle hides them. To relaunch a tab, remove its href from this set.
const LOCKED_IN_PROD = new Set<string>(["/admin/citations", "/admin/web2"]);
const HIDE_LOCKED = process.env.NODE_ENV === "production";

export default function Sidebar() {
  const pathname = usePathname();
  const { logout } = useAuth();
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
              .filter((it) => !(HIDE_LOCKED && LOCKED_IN_PROD.has(it.href)))
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
          <div className="av">DA</div>
          <div className="who">
            <div className="nm">Danyal</div>
            <div className="rl">Super&nbsp;Admin</div>
          </div>
          <button type="button" onClick={logout} className="ts-logout" title="Sign out" aria-label="Sign out">
            <span className="material-symbols-rounded">logout</span>
          </button>
        </div>
      </div>
    </aside>
  );
}
