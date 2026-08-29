import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The security property this extension is built around, asserted on the BUILT bundles.
 *
 * A content script shares a renderer process with whatever JavaScript a directory
 * serves. Anything it can read, a hostile page can eventually read too. So the operator
 * token, the API base and the API client must exist in the service worker and nowhere
 * else — the content script receives selectors and values over `chrome.runtime`, and
 * the panel receives rendered state.
 *
 * Asserted on `dist/` rather than on source because a bundler is exactly the thing that
 * can silently pull a shared import into two chunks.
 */

const read = (name: string): string => {
  try {
    return readFileSync(resolve(__dirname, "..", "dist", name), "utf8");
  } catch {
    return "";
  }
};

const worker = read("service-worker.js");
const filler = read("filler.js");
const panel = read("panel.js");

describe("bundle isolation", () => {
  it("the build produced all three worlds", () => {
    // If this fails the rest of the file is vacuously green, which would be worse than
    // a plain failure.
    expect(worker.length).toBeGreaterThan(500);
    expect(filler.length).toBeGreaterThan(200);
    expect(panel.length).toBeGreaterThan(500);
  });

  it("only the service worker knows the token storage key", () => {
    expect(worker).toContain("aios.operatorToken");
    expect(filler).not.toContain("aios.operatorToken");
    expect(panel).not.toContain("aios.operatorToken");
  });

  it("the content script cannot reach the API at all", () => {
    // No base URL, no path, no header name. It has nothing to call and no credential to
    // call it with.
    expect(filler).not.toContain("/api/v1");
    expect(filler).not.toContain("X-Operator-Token");
    expect(filler.toLowerCase()).not.toContain("fetch(");
  });

  it("the panel never sends the operator header either", () => {
    // The panel is a document a user can open devtools on. It messages the worker and
    // renders what comes back.
    expect(panel).not.toContain("X-Operator-Token");
  });

  it("the service worker is the one place that sends the credential", () => {
    expect(worker).toContain("X-Operator-Token");
  });

  it("the content script guards against double injection", () => {
    // Injecting twice would register a second listener, and the panel would receive two
    // replies to one request.
    expect(filler).toContain("__aiosFillerLoaded");
  });
});
