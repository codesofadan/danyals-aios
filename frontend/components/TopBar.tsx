"use client";

import { useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";

type Props = { eyebrow?: string; title: string; searchPlaceholder?: string };

type Dest = { icon: string; label: string; href: string; keywords?: string };

// Searchable destinations per dashboard area. The top-bar search resolves the
// current area from the pathname and jumps to any of its pages — so it works
// identically in the admin, team and client shells without any area-only API
// calls. Mirrors the Sidebar nav plus a few routes that exist but are unlisted.
const ADMIN_DESTS: Dest[] = [
  { icon: "space_dashboard", label: "Admin Dashboard", href: "/admin", keywords: "home overview" },
  { icon: "fact_check", label: "Audit", href: "/admin/audit", keywords: "seo scan report" },
  { icon: "contact_mail", label: "Free Audits", href: "/admin/leads", keywords: "leads public" },
  { icon: "article", label: "Content", href: "/admin/content", keywords: "articles writing draft publish" },
  { icon: "auto_awesome", label: "Site Builder", href: "/admin/site-builder", keywords: "website reconstruction wizard design templates gutenberg elementor" },
  { icon: "language", label: "WordPress", href: "/admin/wordpress", keywords: "wordpress publish connections sites cms plugin xmlrpc" },
  { icon: "storefront", label: "Citations", href: "/admin/citations", keywords: "nap directories" },
  { icon: "rocket_launch", label: "Web 2.0", href: "/admin/web2", keywords: "backlinks properties" },
  { icon: "radar", label: "Policy Radar", href: "/admin/policy-radar", keywords: "google updates algorithm" },
  { icon: "diversity_3", label: "Clients", href: "/admin/clients", keywords: "accounts customers directory" },
  { icon: "groups", label: "Team Management", href: "/admin/team", keywords: "members assignees staff" },
  { icon: "task_alt", label: "Task Manager", href: "/admin/tasks", keywords: "tasks progress proof assignee queue board" },
  { icon: "summarize", label: "Reports", href: "/admin/reports", keywords: "cron jobs pdf downloads" },
  { icon: "savings", label: "Cost Controls", href: "/admin/cost", keywords: "spend budget dials pricing" },
  { icon: "key", label: "Key Vault", href: "/admin/vault", keywords: "api keys credentials secrets" },
  { icon: "settings", label: "Settings", href: "/admin/settings", keywords: "config preferences" },
];

const TEAM_DESTS: Dest[] = [
  { icon: "space_dashboard", label: "Team Home", href: "/team", keywords: "overview" },
  { icon: "inbox", label: "Queue", href: "/team/queue", keywords: "tasks work" },
  { icon: "rate_review", label: "Review", href: "/team/review", keywords: "qa approve" },
  { icon: "local_shipping", label: "Deliver", href: "/team/deliver", keywords: "handoff" },
  { icon: "timeline", label: "Activity", href: "/team/activity", keywords: "log history" },
  { icon: "vpn_key", label: "Access", href: "/team/access", keywords: "permissions tools" },
];

const CLIENT_DESTS: Dest[] = [
  { icon: "space_dashboard", label: "Portal Home", href: "/client", keywords: "overview dashboard" },
  { icon: "fact_check", label: "Audits", href: "/client/audits", keywords: "seo scan report pdf findings" },
  { icon: "summarize", label: "Reports", href: "/client/reports", keywords: "deliverables pdf downloads" },
  { icon: "support_agent", label: "Requests", href: "/client/requests", keywords: "tickets edits support" },
  { icon: "flag", label: "Milestones", href: "/client/milestones", keywords: "roadmap progress" },
];

const HIDE_LOCKED = process.env.NODE_ENV === "production";
const LOCKED_IN_PROD = new Set<string>(["/admin/citations", "/admin/web2"]);

function destsForPath(pathname: string): Dest[] {
  if (pathname.startsWith("/team")) return TEAM_DESTS;
  if (pathname.startsWith("/client")) return CLIENT_DESTS;
  return ADMIN_DESTS.filter((d) => !(HIDE_LOCKED && LOCKED_IN_PROD.has(d.href)));
}

export default function TopBar({ eyebrow, title, searchPlaceholder = "Search…" }: Props) {
  const pathname = usePathname() || "/admin";
  const router = useRouter();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const blurTimer = useRef<number | null>(null);

  const dests = useMemo(() => destsForPath(pathname), [pathname]);
  const results = useMemo(() => {
    const term = q.trim().toLowerCase();
    if (!term) return dests;
    return dests.filter(
      (d) => d.label.toLowerCase().includes(term) || (d.keywords ?? "").includes(term),
    );
  }, [q, dests]);

  const go = (href: string) => {
    setOpen(false);
    setQ("");
    router.push(href);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const pick = results[active] ?? results[0];
      if (pick) go(pick.href);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <div className="topbar">
      <div className="tt">
        {eyebrow && <div className="ey">{eyebrow}</div>}
        <h1>{title}</h1>
      </div>
      <div className="topbar-actions">
        <div style={{ position: "relative" }}>
          <label className="search">
            <span className="material-symbols-rounded" style={{ fontSize: 20 }}>search</span>
            <input
              placeholder={searchPlaceholder}
              value={q}
              onChange={(e) => { setQ(e.target.value); setOpen(true); setActive(0); }}
              onFocus={() => setOpen(true)}
              onBlur={() => { blurTimer.current = window.setTimeout(() => setOpen(false), 120); }}
              onKeyDown={onKeyDown}
              aria-label="Search the dashboard"
              autoComplete="off"
            />
          </label>

          {open && (
            <div
              role="listbox"
              onMouseDown={(e) => { e.preventDefault(); if (blurTimer.current) window.clearTimeout(blurTimer.current); }}
              style={{
                position: "absolute",
                top: "calc(100% + 6px)",
                left: 0,
                right: 0,
                zIndex: 60,
                background: "var(--card, #fff)",
                border: "1px solid var(--line, #E8D2D7)",
                borderRadius: 12,
                boxShadow: "0 12px 32px rgba(63,14,24,0.14)",
                padding: 6,
                maxHeight: 340,
                overflowY: "auto",
              }}
            >
              {results.length === 0 ? (
                <div style={{ padding: "10px 12px", fontSize: 13, opacity: 0.6 }}>
                  No matches for &ldquo;{q}&rdquo;
                </div>
              ) : (
                results.map((d, i) => (
                  <button
                    key={d.href}
                    type="button"
                    role="option"
                    aria-selected={i === active}
                    onMouseEnter={() => setActive(i)}
                    onClick={() => go(d.href)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 10,
                      width: "100%",
                      textAlign: "left",
                      padding: "9px 11px",
                      borderRadius: 8,
                      border: "none",
                      cursor: "pointer",
                      fontSize: 14,
                      color: "var(--ink, #241015)",
                      background: i === active ? "var(--blush, #F8ECEE)" : "transparent",
                    }}
                  >
                    <span className="material-symbols-rounded" style={{ fontSize: 19, opacity: 0.7 }}>{d.icon}</span>
                    <span>{d.label}</span>
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
