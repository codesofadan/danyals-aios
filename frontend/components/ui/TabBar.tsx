"use client";

// Tabs whose state lives in the URL.
//
// The rule from the screen grammar: THE URL OWNS THE TAB. A tab held in
// useState cannot be linked, bookmarked, or opened from a notification - and
// this product needs exactly that ("open the QA tab of job C-0042"). `?tab=`
// keeps the page's identity in its address, survives refresh, and makes the
// browser's back button undo a tab change like any other navigation.

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";

export type TabDef = {
  key: string;
  label: string;
  icon?: string;
  /** Optional count chip (e.g. findings per tab). */
  badge?: number | string;
};

export function useUrlTab(tabs: TabDef[], param = "tab"): [string, (key: string) => void] {
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams();
  const fallback = tabs[0]?.key ?? "";
  const raw = search.get(param);
  // An unknown ?tab= falls back to the first tab rather than rendering nothing.
  const active = tabs.some((t) => t.key === raw) ? (raw as string) : fallback;

  const setTab = useCallback(
    (key: string) => {
      const next = new URLSearchParams(search.toString());
      if (key === fallback) next.delete(param); // the default tab keeps a clean URL
      else next.set(param, key);
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [router, pathname, search, param, fallback],
  );

  return [active, setTab];
}

export default function TabBar({
  tabs,
  active,
  onSelect,
}: {
  tabs: TabDef[];
  active: string;
  onSelect: (key: string) => void;
}) {
  return (
    <div role="tablist" style={{ display: "flex", gap: "var(--s-2)", flexWrap: "wrap" }}>
      {tabs.map((t) => {
        const selected = t.key === active;
        return (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={selected}
            className={selected ? "tabbtn on" : "tabbtn"}
            onClick={() => onSelect(t.key)}
          >
            {t.icon ? (
              <span className="material-symbols-rounded" aria-hidden="true">{t.icon}</span>
            ) : null}
            {t.label}
            {t.badge !== undefined && t.badge !== 0 ? (
              <span className="pill-tag" style={{ marginLeft: "var(--s-2)" }}>{t.badge}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
