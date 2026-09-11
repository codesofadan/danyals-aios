/**
 * Proactive token rotation. Runs ONLY in the service worker (this module imports the
 * API client, so pulling it into the panel or the content script would fail the
 * isolation test — that is deliberate, not incidental).
 *
 * The design: the operator pastes a token once; from then on the extension exchanges
 * the live token for its successor BEFORE it expires, chained under the server's
 * 30-day installation identity. The alarm fires every few minutes and this module
 * decides — cheaply, from storage alone — whether it is time.
 *
 * WHY <2h REMAINING and not "just before expiry": an MV3 worker only wakes when Chrome
 * feels like it (a closed laptop misses alarms), so the window has to be wide enough
 * that missing several checks still leaves a live token to rotate with.
 *
 * FAILURE POSTURE, per branch:
 *  - 401 (NeedsPairing): the server no longer honours this token — revoked install,
 *    lapsed pairing window, or a replay that nuked the chain. Clear credentials so the
 *    panel shows the re-pair state it already knows how to render. Keeping a dead
 *    token would just turn every later action into the same confusing failure.
 *  - anything else (network blip, 5xx, 429): KEEP the token. It is still valid; the
 *    next alarm retries. A transient outage must never unpair a device.
 */

import {
  api,
  clearCredentials,
  NeedsPairing,
  readCredentials,
  swapToken,
  withRotationLock,
} from "./api";

export const ROTATION_ALARM = "aios-token-rotation";

/** How often the worker checks whether rotation is due. Cheap: a storage read. */
export const ROTATION_CHECK_PERIOD_MINUTES = 15;

/** Rotate when less than this remains on the stored expiry. */
export const ROTATE_WHEN_REMAINING_MS = 2 * 60 * 60 * 1000;

/**
 * The server's token lifetime, used as the pair-time ESTIMATE: a pasted raw token
 * carries no expiry, so the worker assumes a fresh 12h mint (which pairing is). If the
 * paste was stale the estimate errs late, the eventual rotation 401s, and the panel
 * shows re-pair — the same place a stale paste always ended up.
 */
export const ASSUMED_TTL_MS = 12 * 60 * 60 * 1000;

export type RotationOutcome = "not_paired" | "not_due" | "rotated" | "unpaired" | "failed";

export async function maybeRotate(nowMs: number): Promise<RotationOutcome> {
  const creds = await readCredentials();
  if (!creds) return "not_paired";
  // A credential stored before expiry tracking existed has no timestamp. Treat it as
  // due now: rotating immediately is how the worker LEARNS the real expiry.
  const expiresAtMs = creds.expiresAtMs ?? nowMs;
  if (expiresAtMs - nowMs >= ROTATE_WHEN_REMAINING_MS) return "not_due";
  try {
    // Exclusive: in-flight requests drain first, and no new request starts until the
    // successor is in storage. Without this, a queue call racing the swap would
    // present the consumed predecessor - which the server rightly treats as theft
    // and answers by revoking the whole install (a false unpair mid-shift).
    await withRotationLock(async () => {
      const rotated = await api.rotate();
      const serverExpiry = Date.parse(rotated.expiresAt);
      await swapToken(
        rotated.token,
        Number.isFinite(serverExpiry) ? serverExpiry : nowMs + ASSUMED_TTL_MS,
      );
    });
    return "rotated";
  } catch (err) {
    if (err instanceof NeedsPairing) {
      await clearCredentials();
      return "unpaired";
    }
    return "failed";
  }
}

/** Arm the periodic check. Idempotent — `chrome.alarms.create` replaces by name. */
export async function armRotationAlarm(): Promise<void> {
  await chrome.alarms.create(ROTATION_ALARM, { periodInMinutes: ROTATION_CHECK_PERIOD_MINUTES });
}
