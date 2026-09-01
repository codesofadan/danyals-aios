/**
 * Which dashboard origin this device may talk to.
 *
 * The manifest grants loopback PORTLESS — `http://localhost/*` and `http://127.0.0.1/*`.
 * A match pattern without a port matches every port on that host, which is what a dev
 * machine needs: the backend has run on :8000 and :8099 from this very tree, and a
 * pattern pinned to one port silently strips the CORS bypass on the other. Any
 * non-loopback origin still has to be granted at runtime, drawn from
 * `optional_host_permissions`.
 *
 * Pure and side-effect free so it can be tested without a browser: importing the
 * panel would run its bootstrap and reach for chrome.runtime.
 */

const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1"]);

/** The pattern Chrome grants against, e.g. "https://app.qanry.com/*". Throws on junk. */
export function originPattern(apiBase: string): string {
  const url = new URL(apiBase.trim());
  // Loopback must be asked about in the same portless form the manifest grants it in —
  // chrome.permissions.contains matches patterns literally, and a ported question about
  // a portless grant answers false.
  if (LOOPBACK_HOSTS.has(url.hostname)) return `${url.protocol}//${url.hostname}/*`;
  return `${url.origin}/*`;
}

/** Loopback is already in host_permissions — prompting for it would put a
 *  permission dialog in front of every developer for no grant. */
export function needsGrant(pattern: string): boolean {
  return !(pattern.startsWith("http://localhost/") || pattern.startsWith("http://127.0.0.1/"));
}
