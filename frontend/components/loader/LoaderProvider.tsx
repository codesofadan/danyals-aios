"use client";

// ============================================================
// AIOS · Loader controller
// ------------------------------------------------------------
// Owns the single 3D loader overlay and decides WHEN it shows. Two
// channels feed it:
//
//   1. Navigation (automatic) — a capture-phase click listener catches
//      every in-app <a>/<Link> click that actually changes the route and
//      arms the loader; the loader is dismissed when `usePathname`
//      reports the new screen has mounted. This covers "clicked a feature
//      / went to another screen" with zero per-link wiring.
//
//   2. Tasks (opt-in) — `useLoader()` exposes show/hide/run/navigate for
//      buttons that kick off async work or programmatic router.push()es.
//      The same API is mirrored on `window.__aiosLoader` for non-React
//      call sites.
//
// A short APPEAR_DELAY suppresses the flash on instant transitions, and a
// MIN_VISIBLE floor stops the loader flickering out the moment it appears.
// ============================================================

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePathname } from "next/navigation";
import dynamic from "next/dynamic";

// The 3D kernel pulls in three.js — keep it out of every route's initial
// bundle. It's rendered unconditionally on mount, so its chunk prefetches
// right after hydration and is ready long before the first navigation.
const OSLoader = dynamic(() => import("./OSLoader"), { ssr: false });

const APPEAR_DELAY = 110; // hold off this long so instant nav never flashes
const MIN_VISIBLE = 520; // once shown, stay at least this long
const NAV_SAFETY = 8000; // release a navigation that never lands
const DEFAULT_LABEL = "Loading workspace";

type Task<T> = Promise<T> | (() => Promise<T>);

export type LoaderApi = {
  show: (label?: string) => void;
  hide: () => void;
  run: <T>(task: Task<T>, label?: string) => Promise<T>;
  /** Arm the loader for an imminent programmatic route change. */
  navigate: (label?: string) => void;
};

const Ctx = createContext<LoaderApi | null>(null);

declare global {
  interface Window {
    __aiosLoader?: LoaderApi;
  }
}

export function LoaderProvider({ children }: { children: React.ReactNode }) {
  const [active, setActive] = useState(false);
  const [label, setLabel] = useState(DEFAULT_LABEL);
  const pathname = usePathname();

  const count = useRef(0); // outstanding task requests
  const appearTimer = useRef<number | null>(null);
  const hideTimer = useRef<number | null>(null);
  const shownAt = useRef(0);
  const navPending = useRef(false);
  const navSafety = useRef<number | null>(null);

  const clearAppear = () => {
    if (appearTimer.current !== null) {
      clearTimeout(appearTimer.current);
      appearTimer.current = null;
    }
  };

  const reallyShow = useCallback(() => {
    if (hideTimer.current !== null) {
      clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
    shownAt.current = performance.now();
    setActive(true);
  }, []);

  const request = useCallback(
    (lbl?: string) => {
      if (lbl) setLabel(lbl);
      count.current += 1;
      if (count.current === 1 && !active) {
        clearAppear();
        appearTimer.current = window.setTimeout(() => {
          appearTimer.current = null;
          if (count.current > 0) reallyShow();
        }, APPEAR_DELAY);
      }
    },
    [active, reallyShow]
  );

  const release = useCallback(() => {
    count.current = Math.max(0, count.current - 1);
    if (count.current > 0) return;
    clearAppear();
    const elapsed = performance.now() - shownAt.current;
    const wait = Math.max(0, MIN_VISIBLE - elapsed);
    if (hideTimer.current !== null) clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      hideTimer.current = null;
      if (count.current === 0) {
        setActive(false);
        setLabel(DEFAULT_LABEL);
      }
    }, wait);
  }, []);

  const navStart = useCallback(
    (lbl?: string) => {
      if (navPending.current) return;
      navPending.current = true;
      request(lbl);
      if (navSafety.current !== null) clearTimeout(navSafety.current);
      navSafety.current = window.setTimeout(() => {
        navSafety.current = null;
        if (navPending.current) {
          navPending.current = false;
          release();
        }
      }, NAV_SAFETY);
    },
    [request, release]
  );

  // The route changed → the destination screen has mounted. Dismiss any
  // navigation-triggered loader (task-based show/hide is untouched).
  useEffect(() => {
    if (!navPending.current) return;
    navPending.current = false;
    if (navSafety.current !== null) {
      clearTimeout(navSafety.current);
      navSafety.current = null;
    }
    release();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);

  // Global capture listener: arm the loader on any real in-app navigation.
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (e.defaultPrevented || e.button !== 0) return;
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const el = e.target as Element | null;
      const a = el?.closest?.("a");
      if (!a) return;
      if (a.getAttribute("target") === "_blank" || a.hasAttribute("download")) return;
      const href = a.getAttribute("href");
      if (!href || href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("tel:")) return;

      let url: URL;
      try {
        url = new URL((a as HTMLAnchorElement).href, window.location.href);
      } catch {
        return;
      }
      if (url.origin !== window.location.origin) return;
      // same screen (or hash-only) → no transition, no loader
      if (url.pathname === window.location.pathname) return;

      navStart();
    }
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [navStart]);

  const run = useCallback(
    async <T,>(task: Task<T>, lbl?: string): Promise<T> => {
      request(lbl);
      try {
        return await (typeof task === "function" ? (task as () => Promise<T>)() : task);
      } finally {
        release();
      }
    },
    [request, release]
  );

  const api = useMemo<LoaderApi>(
    () => ({
      show: (lbl?: string) => request(lbl),
      hide: () => release(),
      run,
      navigate: (lbl?: string) => navStart(lbl),
    }),
    [request, release, run, navStart]
  );

  // Mirror the API onto window for non-React / imperative call sites.
  useEffect(() => {
    window.__aiosLoader = api;
    return () => {
      if (window.__aiosLoader === api) delete window.__aiosLoader;
    };
  }, [api]);

  return (
    <Ctx.Provider value={api}>
      {children}
      <OSLoader active={active} label={label} />
    </Ctx.Provider>
  );
}

export function useLoader(): LoaderApi {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useLoader must be used within a LoaderProvider");
  return ctx;
}
