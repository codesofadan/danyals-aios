/**
 * The service worker: the only code in this extension that talks to the API.
 *
 * Everything else routes through here. The side panel sends a message and renders what
 * comes back; the content script receives selectors and values and returns an outcome.
 * Neither ever holds the operator token, because the panel is a document a user can open
 * devtools on and the content script shares a renderer with the directory's own scripts.
 *
 * MV3 TERMINATES THIS WORKER after ~30s idle, so nothing here may rely on a module-level
 * variable surviving between messages. State lives in `chrome.storage.session` and every
 * handler re-hydrates. The heartbeat runs on `chrome.alarms`, whose minimum period is one
 * minute — which is why the server's claim lease is twenty minutes rather than two.
 */

import { api, clearCredentials, NeedsPairing, readCredentials, storeCredentials } from "../lib/api";
import { diagnoseConnection } from "../lib/diagnose";
import type { ConnectionReport, PanelRequest, PanelResponse, QueueItem } from "../lib/messages";
import { clearClaim, readClaim, unbankedSeconds, writeClaim } from "../lib/session";

const HEARTBEAT_ALARM = "aios-queue-heartbeat";

chrome.runtime.onInstalled.addListener(() => {
  // The toolbar click opens the panel. `chrome.sidePanel.open()` throws outside a user
  // gesture, so the panel can never be opened from an alarm or a fetch callback.
  void chrome.sidePanel?.setPanelBehavior?.({ openPanelOnActionClick: true });
});

/** Bank the time worked so far and push the lease out. */
async function heartbeat(): Promise<void> {
  const claim = await readClaim();
  if (!claim) return;
  const delta = unbankedSeconds(claim, Date.now());
  if (delta <= 0) return;
  try {
    await api.heartbeat(claim.citationId, delta);
    // Only advance the local marker once the server has ACCEPTED the seconds. A failed
    // heartbeat must not silently discard the time it was carrying.
    await writeClaim({ ...claim, bankedSeconds: claim.bankedSeconds + delta, startedAtMs: Date.now() });
  } catch (err) {
    if (err instanceof NeedsPairing) await chrome.alarms.clear(HEARTBEAT_ALARM);
  }
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === HEARTBEAT_ALARM) void heartbeat();
});

/** Fill the active tab's form. The token never crosses into the page. */
async function fillActiveTab(item: QueueItem): Promise<unknown> {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error("No active tab to fill.");

  // Injected on the operator's explicit click, never on navigation: that keeps the
  // permission at `activeTab` and means a page is only touched when a human asked.
  const results = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    files: ["filler.js"],
  });
  void results;

  // ONLY the fields that carry a selector. This used to send `selector: ""` for every
  // field — the backend's QueueFieldValue had no selector at all — so
  // `document.querySelector("")` matched nothing and every field came back
  // `selector_not_found`. The extension filled nothing, and the read-back that catches a
  // React revert was unreachable because there was never anything to read back.
  const plan = item.fields
    .filter((f) => f.selector)
    .map((f) => ({ selector: f.selector, valueKey: f.key, value: f.value }));

  // No earned spec for this directory means no selectors, which is the NORMAL case while
  // the whitelist is empty. Say so plainly rather than reporting nine fields not found —
  // the operator copies the values by hand instead, which is a smaller feature, not a
  // broken one.
  if (plan.length === 0) {
    return {
      filled: [],
      failed: [{ key: "*", reason: "no_verified_spec_for_this_directory" }],
    };
  }
  return chrome.tabs.sendMessage(tab.id, { type: "aios-fill", plan });
}

async function handle(request: PanelRequest): Promise<PanelResponse> {
  try {
    switch (request.type) {
      case "pair": {
        const token = request.token.trim();
        const base = request.apiBase.trim();
        await storeCredentials(token, base);
        try {
          const board = await api.board();
          return { ok: true, data: board };
        } catch {
          // A failed pair must not leave dead credentials behind, and must not hand the
          // operator fetch()'s bare "Failed to fetch" — run the staged probe and return
          // a verdict the panel can turn into a next step.
          await clearCredentials();
          const diagnosis = await diagnoseConnection(base, token, fetch);
          return {
            ok: false,
            error: "Pairing failed.",
            diagnosis: { ...diagnosis, extensionId: chrome.runtime.id } satisfies ConnectionReport,
          };
        }
      }

      case "diagnose": {
        const creds = await readCredentials();
        const diagnosis = await diagnoseConnection(
          request.apiBase ?? creds?.base ?? "",
          request.token ?? creds?.token ?? "",
          fetch,
        );
        return { ok: true, data: { ...diagnosis, extensionId: chrome.runtime.id } satisfies ConnectionReport };
      }
      case "unpair": {
        await chrome.alarms.clear(HEARTBEAT_ALARM);
        await clearClaim();
        await clearCredentials();
        return { ok: true, data: null };
      }
      case "session": {
        const creds = await readCredentials();
        const claim = await readClaim();
        return { ok: true, data: { paired: creds !== null, claim } };
      }
      case "board":
        return { ok: true, data: await api.board() };

      case "claim": {
        const item = (await api.claim()) as QueueItem | null;
        if (!item) return { ok: true, data: null };
        await writeClaim({
          citationId: item.citationId,
          directory: item.directory,
          bankedSeconds: item.workedSeconds ?? 0,
          startedAtMs: Date.now(),
        });
        // One minute is the floor for an alarm period; the server's lease is twenty.
        await chrome.alarms.create(HEARTBEAT_ALARM, { periodInMinutes: 1 });
        return { ok: true, data: item };
      }

      case "fill": {
        const claim = await readClaim();
        if (!claim) return { ok: false, error: "No item is claimed." };
        const item = (await api.item(claim.citationId)) as QueueItem;
        return { ok: true, data: await fillActiveTab(item) };
      }

      case "complete": {
        const claim = await readClaim();
        if (!claim) return { ok: false, error: "No item is claimed." };
        const delta = unbankedSeconds(claim, Date.now());
        const result = await api.complete(claim.citationId, request.liveUrl, delta, request.note);
        // A REFUSED completion keeps the claim: the listing is usually just not published
        // yet, and dropping the claim would make the operator hunt for it again.
        if ((result as { accepted?: boolean }).accepted) {
          await chrome.alarms.clear(HEARTBEAT_ALARM);
          await clearClaim();
        } else {
          await writeClaim({ ...claim, bankedSeconds: claim.bankedSeconds + delta, startedAtMs: Date.now() });
        }
        return { ok: true, data: result };
      }

      case "blocked": {
        const claim = await readClaim();
        if (!claim) return { ok: false, error: "No item is claimed." };
        await api.blocked(
          claim.citationId, request.reason, request.detail, unbankedSeconds(claim, Date.now()),
        );
        await chrome.alarms.clear(HEARTBEAT_ALARM);
        await clearClaim();
        return { ok: true, data: null };
      }

      case "release": {
        const claim = await readClaim();
        if (claim) {
          await api.release(claim.citationId, unbankedSeconds(claim, Date.now()));
          await chrome.alarms.clear(HEARTBEAT_ALARM);
          await clearClaim();
        }
        return { ok: true, data: null };
      }
    }
  } catch (err) {
    if (err instanceof NeedsPairing) {
      return { ok: false, error: err.message, needsPairing: true };
    }
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}

chrome.runtime.onMessage.addListener((request: PanelRequest, _sender, sendResponse) => {
  // `true` keeps the message channel open for the async reply. Without it every response
  // is dropped and the panel hangs on every action.
  void handle(request).then(sendResponse);
  return true;
});
