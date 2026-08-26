// ============================================================
// The palette has ONE source of truth.
//
// `SERIES` (lib/data.ts) is the JS mirror of the --c1…--c5 theme tokens in
// app/globals.css. It carried a comment saying it "mirrors" them while all
// five values had drifted to a different palette entirely — neon lime/teal/
// amber/cyan/magenta against a muted violet UI — and 19 files consumed the
// drifted copy. A comment cannot hold two copies in sync; this test can.
//
// It also guards the ghost-token class of bug: `--border` and `--text` were
// referenced in app/admin/audit/*.css with NO fallback and never defined
// anywhere, so those borders rendered as `initial` (invisible) and that text
// lost its colour on the flagship audit screens.
// ============================================================

import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { SERIES } from "./data";

const GLOBALS = path.join(process.cwd(), "app", "globals.css");
const css = fs.readFileSync(GLOBALS, "utf8");

/** Every `--name: value;` declaration in globals.css. */
function definedTokens(): Map<string, string> {
  const out = new Map<string, string>();
  for (const m of css.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;}]+)[;}]/gi)) {
    out.set(m[1], m[2].trim());
  }
  return out;
}

describe("the chart palette mirrors the theme tokens", () => {
  const tokens = definedTokens();

  it.each(["c1", "c2", "c3", "c4", "c5"] as const)(
    "SERIES.%s equals its --%s token",
    (key) => {
      const fromCss = tokens.get(`--${key}`);
      expect(fromCss, `--${key} is not defined in globals.css`).toBeDefined();
      expect(SERIES[key].toLowerCase()).toBe(String(fromCss).toLowerCase());
    },
  );

  it("keeps SERIES as literal hex, because callers append an alpha suffix", () => {
    // `${SERIES.c1}88` is used for a gradient stop; `var(--c1)88` is invalid CSS.
    for (const value of Object.values(SERIES)) {
      expect(value).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });
});

describe("no stylesheet reads a custom property that nothing defines", () => {
  // Injected at runtime, so correctly absent from globals.css: the first group
  // is set per-element via inline style (e.g. style={{ "--c": colour }}), and
  // --font-bricolage is supplied by next/font's localFont() in app/layout.tsx.
  const RUNTIME = new Set([
    "--c", "--i", "--sev", "--sx", "--sy", "--to", "--circ", "--pct", "--bi",
    "--font-bricolage",
  ]);

  it("has no var(--x) without a fallback pointing at an undefined token", () => {
    const root = process.cwd();
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        // Test files are excluded: this one discusses `var(--x)` in prose, and
        // a guard that flags its own documentation is a guard nobody keeps.
        else if (/\.(css|tsx?|ts)$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name)) {
          files.push(full);
        }
      }
    };
    for (const dir of ["app", "components", "lib"]) {
      const d = path.join(root, dir);
      if (fs.existsSync(d)) walk(d);
    }

    const defined = new Set<string>();
    for (const f of files) {
      for (const m of fs.readFileSync(f, "utf8").matchAll(/(--[a-z0-9-]+)\s*:/gi)) {
        defined.add(m[1]);
      }
    }

    const offenders: string[] = [];
    for (const f of files) {
      const text = fs.readFileSync(f, "utf8");
      // `var(--x)` with NO comma = no fallback. Those are the ones that render
      // as `initial` when undefined, which is the silent-breakage case.
      for (const m of text.matchAll(/var\(\s*(--[a-z0-9-]+)\s*\)/gi)) {
        const name = m[1];
        if (!defined.has(name) && !RUNTIME.has(name)) {
          offenders.push(`${path.relative(root, f)} reads undefined ${name}`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
