"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type Item = { icon: string; label: string; href: string; badge?: string };
type Section = { title: string; items: Item[] };

// Only built, navigable routes live here — module items are added as
// each module ships.
const SECTIONS: Section[] = [
  {
    title: "Overview",
    items: [
      { icon: "space_dashboard", label: "Command Center", href: "/" },
      { icon: "grid_view", label: "Features", href: "/features" },
    ],
  },
  {
    title: "Agency",
    items: [
      { icon: "groups", label: "Team Management", href: "/team" },
      { icon: "diversity_3", label: "Clients", href: "/clients" },
    ],
  },
  {
    title: "Platform",
    items: [
      { icon: "backup", label: "Backups", href: "/backups" },
      { icon: "settings", label: "Settings", href: "/settings" },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="logo" />
        <div className="wm">
          <div className="n">AIOS</div>
          <div className="s">Xegents</div>
        </div>
      </div>

      <nav className="nav">
        {SECTIONS.map((sec) => (
          <div key={sec.title}>
            <div className="sec">{sec.title}</div>
            {sec.items.map((it) => {
              const active =
                it.href !== "#" &&
                (pathname === it.href || (it.href !== "/" && pathname.startsWith(`${it.href}/`)));
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
        </div>
      </div>
    </aside>
  );
}
