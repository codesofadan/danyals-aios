/**
 * Which dashboard origin this device may talk to.
 *
 * The manifest grants `http://localhost:8000/*` and nothing else, so a device paired
 * against the DEPLOYED dashboard - where every real operator's queue lives - would
 * have each request blocked by the extension's own permissions, with no error the
 * panel could explain. Any non-localhost origin therefore has to be granted at
 * runtime, drawn from `optional_host_permissions`.
 *
 * Pure and side-effect free so it can be tested without a browser: importing the
 * panel would run its bootstrap and reach for chrome.runtime.
 */

/** The pattern Chrome grants against, e.g. "https://app.qanry.com/*". Throws on junk. */
export function originPattern(apiBase: string): string {
  return `${new URL(apiBase.trim()).origin}/*`;
}

/** localhost is already in host_permissions - prompting for it would put a
 *  permission dialog in front of every developer for no grant. */
export function needsGrant(pattern: string): boolean {
  return !pattern.startsWith("http://localhost");
}
