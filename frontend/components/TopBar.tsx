"use client";

import { useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { isNavLocked } from "@/lib/lockedInProd";
import { searchDestinations, type NavItem } from "@/lib/nav";
import NotificationBell from "@/components/notifications/NotificationBell";

type Props = { eyebrow?: string; title: string; searchPlaceholder?: string; hideSearch?: boolean };

// Destinations come from lib/nav.ts - the same table the sidebars render, so
// search can never again lose a page the sidebar shows. This file used to carry
// its own copies and they had drifted.

function destsForPath(pathname: string): NavItem[] {
  if (pathname.startsWith("/team")) return searchDestinations("team");
  if (pathname.startsWith("/client")) return searchDestinations("client");
  return searchDestinations("admin").filter((d) => !isNavLocked(d.href));
}

export default function TopBar({ eyebrow, title, searchPlaceholder = "Search…", hideSearch = false }: Props) {
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
        {!hideSearch && (
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
                  background: "var(--card)",
                  border: "1px solid var(--line)",
                  borderRadius: 12,
                  boxShadow: "var(--e-3)",
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
                        color: "var(--ink)",
                        background: i === active ? "var(--hover)" : "transparent",
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
        )}
        {/* Outside the `hideSearch` guard on purpose: seven admin pages hide the
            search box, and notifications must not vanish along with it. */}
        <NotificationBell />
      </div>
    </div>
  );
}
