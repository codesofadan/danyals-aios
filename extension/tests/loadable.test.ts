import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { originPattern, needsGrant } from "../src/lib/origins";

/**
 * The extension has to actually LOAD, and it has to be able to reach the dashboard
 * it is paired with.
 *
 * QA could not load it at all: "Could not load manifest", "Could not load background
 * script". The build is fine - the manifest names BUILT files (service-worker.js,
 * panel.html, filler.js) which only exist after `npm run build`, and `dist/` is
 * gitignored on purpose so a loaded extension can never drift from the source that
 * produced it. Pointing Chrome at the project root finds manifest.json next to src/
 * and none of the files it names. So the fix is the instruction, not the build - and
 * this file keeps the manifest and the build honest about each other.
 *
 * CI already checks five known filenames. This derives the list FROM the manifest
 * instead, so adding a reference to a file the build does not emit fails here rather
 * than in someone's browser.
 */

const dist = (name: string): string => resolve(__dirname, "..", "dist", name);

function manifest(): Record<string, any> {
  return JSON.parse(readFileSync(dist("manifest.json"), "utf8"));
}

describe("dist/ is a loadable extension", () => {
  it("emits every file the manifest names", () => {
    const m = manifest();
    const refs: string[] = [];
    if (m.background?.service_worker) refs.push(m.background.service_worker);
    if (m.side_panel?.default_path) refs.push(m.side_panel.default_path);
    for (const cs of m.content_scripts ?? []) refs.push(...(cs.js ?? []), ...(cs.css ?? []));
    for (const r of m.web_accessible_resources ?? []) refs.push(...(r.resources ?? []));

    expect(refs.length).toBeGreaterThan(0);
    for (const ref of refs) {
      expect(existsSync(dist(ref)), `manifest names ${ref}, which the build did not emit`).toBe(true);
    }
  });

  it("emits the filler the service worker injects on demand", () => {
    // Injected via chrome.scripting.executeScript rather than declared as a content
    // script, so the check above cannot see it - and a missing filler.js fails only
    // at the moment an operator tries to fill a form.
    const sw = readFileSync(dist("service-worker.js"), "utf8");
    expect(sw).toContain("filler.js");
    expect(existsSync(dist("filler.js"))).toBe(true);
  });

  it("keeps the panel's own references resolvable", () => {
    const html = readFileSync(dist("panel.html"), "utf8");
    for (const asset of ["panel.js", "panel.css"]) {
      expect(html).toContain(asset);
      expect(existsSync(dist(asset))).toBe(true);
    }
  });

  it("is Manifest V3, which is the only version Chrome still loads", () => {
    expect(manifest().manifest_version).toBe(3);
  });
});

describe("reaching the dashboard it is paired with", () => {
  // host_permissions grants loopback ONLY. Pairing against the deployed dashboard -
  // where a real operator's queue lives - therefore needs a runtime grant, requested
  // inside the Pair click because Chrome only shows that prompt on a user gesture.
  it("derives the origin pattern Chrome grants against", () => {
    expect(originPattern("https://app.qanry.com")).toBe("https://app.qanry.com/*");
    // A trailing path or slash must not become part of the pattern.
    expect(originPattern("https://app.qanry.com/api/v1/")).toBe("https://app.qanry.com/*");
    expect(originPattern("  https://app.qanry.com  ")).toBe("https://app.qanry.com/*");
  });

  it("asks about loopback in the portless form the manifest grants it in", () => {
    // The backend has run on :8000 and :8099 from this tree in the same week. A pattern
    // pinned to one port silently strips the CORS bypass on the other, and
    // chrome.permissions.contains matches literally - a ported question about a
    // portless grant answers false. Portless matches every port.
    expect(originPattern("http://localhost:8000")).toBe("http://localhost/*");
    expect(originPattern("http://127.0.0.1:8099")).toBe("http://127.0.0.1/*");
  });

  it("refuses an unusable base rather than pairing into nothing", () => {
    expect(() => originPattern("not a url")).toThrow();
  });

  it("does not prompt for loopback, which the manifest already grants", () => {
    // Otherwise every developer gets a permission dialog for a grant they hold.
    expect(needsGrant("http://localhost/*")).toBe(false);
    expect(needsGrant("http://127.0.0.1/*")).toBe(false);
    expect(needsGrant("https://app.qanry.com/*")).toBe(true);
  });

  it("grants loopback portlessly in the manifest itself", () => {
    // The other half of the contract the two tests above rely on. If someone pins a
    // port back into host_permissions, pairing against any OTHER local port quietly
    // loses its CORS bypass and dies as "Failed to fetch" - the exact 2026-09-01 outage.
    expect(manifest().host_permissions).toContain("http://localhost/*");
    expect(manifest().host_permissions).toContain("http://127.0.0.1/*");
  });

  it("declares the optional permission the request draws from", () => {
    // chrome.permissions.request can only ask for something the manifest declares
    // as optional; without this the prompt never appears and the grant is impossible.
    expect(manifest().optional_host_permissions).toContain("https://*/*");
  });
});
