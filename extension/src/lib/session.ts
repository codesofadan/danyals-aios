/**
 * The claim, and why it lives in `chrome.storage.session` rather than in a variable.
 *
 * An MV3 service worker is terminated after ~30 seconds idle. Everything held in memory
 * goes with it — the claimed item, the elapsed seconds, a pending upload — and
 * `setTimeout`/`setInterval` do not survive either. A worker that keeps its state in a
 * module-level variable therefore "forgets" which item the operator is working on
 * roughly every time they read a form carefully.
 *
 * `chrome.storage.session` is memory-backed, cleared when the browser closes, and never
 * written to disk — the right home for a lease that must not outlive the browser but
 * must outlive the worker. Every handler re-hydrates from it rather than trusting a
 * variable that may belong to a previous incarnation.
 */

const KEY = "aios.activeClaim";

export type ActiveClaim = {
  citationId: string;
  directory: string;
  /** Seconds already BANKED on the server. Kept so a heartbeat sends only the delta. */
  bankedSeconds: number;
  /** Wall-clock ms when this claim's timer last started, for computing the delta. */
  startedAtMs: number;
};

export async function readClaim(): Promise<ActiveClaim | null> {
  const got = await chrome.storage.session.get(KEY);
  return (got[KEY] as ActiveClaim | undefined) ?? null;
}

export async function writeClaim(claim: ActiveClaim): Promise<void> {
  await chrome.storage.session.set({ [KEY]: claim });
}

export async function clearClaim(): Promise<void> {
  await chrome.storage.session.remove(KEY);
}

/** Seconds worked since the last bank. Never negative, never absurd. */
export function unbankedSeconds(claim: ActiveClaim, nowMs: number): number {
  const elapsed = Math.floor((nowMs - claim.startedAtMs) / 1000);
  // A clock jump backwards, or a claim restored from a previous browser session, must
  // not send a negative or wildly large number. The server clamps too, but sending
  // nonsense would corrupt the median that the whole cost model rests on.
  if (!Number.isFinite(elapsed) || elapsed < 0) return 0;
  return Math.min(elapsed, 4 * 60 * 60);
}
