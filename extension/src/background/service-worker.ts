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

import type { FormAnalysis } from "../lib/api";
import { api, clearCredentials, NeedsPairing, readCredentials, storeCredentials } from "../lib/api";
import { diagnoseConnection } from "../lib/diagnose";
import type {
  ConnectionReport,
  FillOutcome,
  PanelRequest,
  PanelResponse,
  QueueItem,
  SessionDetail,
} from "../lib/messages";
import {
  armRotationAlarm,
  ASSUMED_TTL_MS,
  maybeRotate,
  ROTATION_ALARM,
} from "../lib/rotation";
import { clearClaim, readClaim, unbankedSeconds, writeClaim } from "../lib/session";
import {
  type ActiveSession,
  clearSession,
  fillPlanFor,
  markTelemetrySent,
  mergeServerSession,
  readSession,
  sessionKind,
  taskForTab,
  openUrlFor,
  tasksNeedingTabs,
  withoutTab,
  withTab,
  writeSession,
} from "../lib/sessionBoard";

const HEARTBEAT_ALARM = "aios-queue-heartbeat";
const SESSION_HEARTBEAT_ALARM = "aios-session-heartbeat";

chrome.runtime.onInstalled.addListener(() => {
  // The toolbar click opens the panel. `chrome.sidePanel.open()` throws outside a user
  // gesture, so the panel can never be opened from an alarm or a fetch callback.
  void chrome.sidePanel?.setPanelBehavior?.({ openPanelOnActionClick: true });
  // Alarms do NOT survive an extension update/reload, but stored credentials do — a
  // paired device whose rotation alarm silently vanished would ride its token into
  // expiry and force a re-pair for no reason. Re-arm whenever we are (re)installed.
  void readCredentials().then((creds) => {
    if (creds) return armRotationAlarm();
  });
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

/** Session heartbeat (0130): extend every open task's lease + bank the delta. The
 *  server SPREADS the seconds across the open items so totals stay honest. */
async function sessionHeartbeat(): Promise<void> {
  const state = await readSession();
  if (!state) return;
  const delta = Math.max(0, Math.min(Math.floor((Date.now() - state.startedAtMs) / 1000), 4 * 60 * 60));
  try {
    await api.sessionHeartbeat(state.sessionId, delta);
    // Advance the anchor only once the server accepted the seconds (same rule as the
    // single-item heartbeat: a failed beat must not silently discard its time).
    await writeSession({ ...state, startedAtMs: Date.now() });
  } catch (err) {
    if (err instanceof NeedsPairing) await chrome.alarms.clear(SESSION_HEARTBEAT_ALARM);
    // A 409 means the session is no longer ours (closed/reaped) — drop the local state
    // so the panel's next look renders the start screen instead of a ghost session.
    if (err instanceof Error && /not active|not yours/i.test(err.message)) {
      await chrome.alarms.clear(SESSION_HEARTBEAT_ALARM);
      await clearSession();
    }
  }
}

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === HEARTBEAT_ALARM) void heartbeat();
  if (alarm.name === SESSION_HEARTBEAT_ALARM) void sessionHeartbeat();
  // Proactive rotation: swap the token for its successor while plenty of life remains,
  // so the operator never sees a mid-shift expiry. On a 401 `maybeRotate` clears the
  // credentials itself, and the panel's next "session" read renders the re-pair state.
  if (alarm.name === ROTATION_ALARM) void maybeRotate(Date.now());
});

// --------------------------------------------------------------------------- //
// Session tab orchestration (0130).
// --------------------------------------------------------------------------- //

/** Open a tab for every released task that has none yet; record tabId -> taskId.
 *  Kind-neutral (0136): a citation task opens its add-form, a web2 task its
 *  editor URL (spec-pinned when earned, platform homepage otherwise). */
async function openTabsForReleased(state: ActiveSession): Promise<ActiveSession> {
  let next = state;
  for (const task of tasksNeedingTabs(state)) {
    try {
      const tab = await chrome.tabs.create({ url: task.openUrl, active: false });
      if (tab.id !== undefined) next = withTab(next, tab.id, task.taskId);
    } catch {
      // A refused tab (window gone, URL rejected) is a smaller feature, not a crash —
      // the operator opens that one by hand from the panel's card.
    }
  }
  if (next !== state) await writeSession(next);
  return next;
}

/** Send a forward-only telemetry state at most once per task; 409s are "already
 *  known", never errors — the ledger in storage keeps us from re-sending. */
async function sendTelemetry(taskId: string, uiState: string): Promise<void> {
  const state = await readSession();
  if (!state) return;
  const { state: marked, shouldSend } = markTelemetrySent(state, taskId, uiState);
  if (!shouldSend) return;
  await writeSession(marked);
  try {
    await api.taskTelemetry(marked.sessionId, taskId, uiState);
  } catch {
    // Telemetry carries zero authority; losing a report costs a chip in the UI and
    // nothing else. Never retried — the next state supersedes it anyway.
  }
}

// 'opened' when a session tab finishes loading. The map lives in storage.session, so
// a worker restart between create and load still attributes the event correctly.
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status !== "complete") return;
  void (async () => {
    const state = await readSession();
    if (!state) return;
    const task = taskForTab(state, tabId);
    if (task) await sendTelemetry(task.taskId, "opened");
  })();
});

chrome.tabs.onRemoved.addListener((tabId) => {
  void (async () => {
    const state = await readSession();
    if (!state) return;
    if (state.tabMap[String(tabId)]) await writeSession(withoutTab(state, tabId));
  })();
});

/** Pull the server's view of the session, merge it, open tabs for anything newly
 *  released (a batch release happens inside the server's terminal handlers), and
 *  clear local state once the session is over. */
async function refreshSessionFromServer(): Promise<ActiveSession | null> {
  const state = await readSession();
  if (!state) return null;
  const server = (await api.getSession(state.sessionId)) as SessionDetail;
  if (server.status !== "active") {
    await chrome.alarms.clear(SESSION_HEARTBEAT_ALARM);
    await clearSession();
    return null;
  }
  const merged = mergeServerSession(state, server);
  await writeSession(merged);
  return openTabsForReleased(merged);
}

/** Fill one session task's OWN tab (falling back to the active tab when the task has
 *  no tab on record). Read-back drives 'form_detected'/'filled' telemetry.
 *
 *  Works for BOTH kinds through the same fail-closed rule: the plan is built ONLY
 *  from fields carrying a selector, and a web2 card ships selectors only when an
 *  ACTIVE earned placement spec provides them — with none, the answer is the honest
 *  no-spec outcome and the panel stays on copy-blocks. Nothing here ever submits. */
async function fillSessionTask(taskId: string): Promise<FillOutcome> {
  const state = await readSession();
  if (!state) throw new Error("No active session.");
  const task =
    state.tasks.find((t) => t.taskId === taskId) ??
    (state.web2Tasks ?? []).find((t) => t.taskId === taskId);
  if (!task) throw new Error("No such task in this session.");

  let tabId: number | undefined;
  for (const [tid, mapped] of Object.entries(state.tabMap)) {
    if (mapped === taskId) tabId = Number(tid);
  }
  if (tabId === undefined) {
    const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
    tabId = active?.id;
  }
  if (tabId === undefined) throw new Error("No tab to fill.");

  const plan = fillPlanFor(task.fields);
  if (plan.length === 0) {
    // hasSpec=false is the NORMAL case: no earned spec, no selectors, the panel shows
    // click-to-copy instead. Same honest shape the single-item fill returns.
    return { filled: [], failed: [{ key: "*", reason: "no_verified_spec_for_this_directory" }] };
  }

  await chrome.scripting.executeScript({ target: { tabId }, files: ["filler.js"] });
  const outcome = (await chrome.tabs.sendMessage(tabId, { type: "aios-fill", plan })) as FillOutcome;

  // The filler's honest read-back is the telemetry source: selectors that were FOUND
  // prove the form was detected; values that survived the read-back prove a fill.
  const selectorsFound =
    outcome.filled.length > 0 ||
    outcome.failed.some((f) => f.reason !== "selector_not_found");
  if (selectorsFound) await sendTelemetry(taskId, "form_detected");
  if (outcome.filled.length > 0) await sendTelemetry(taskId, "filled");
  return outcome;
}

/** Best-effort autofill for a task whose directory has NO earned spec. Instead of
 *  spec selectors, it hands the page the business VALUES and lets the injected filler
 *  match them to the site's own fields by their attributes (autocomplete / name / id /
 *  placeholder / label). Same honest read-back drives telemetry; nothing is submitted,
 *  no CAPTCHA or password field is ever touched. A directory the operator then finishes
 *  by hand is how a precise, per-directory spec later gets earned. */
async function autofillSessionTask(taskId: string): Promise<FillOutcome> {
  const state = await readSession();
  if (!state) throw new Error("No active session.");
  const task =
    state.tasks.find((t) => t.taskId === taskId) ??
    (state.web2Tasks ?? []).find((t) => t.taskId === taskId);
  if (!task) throw new Error("No such task in this session.");

  let tabId: number | undefined;
  for (const [tid, mapped] of Object.entries(state.tabMap)) {
    if (mapped === taskId) tabId = Number(tid);
  }
  if (tabId === undefined) {
    const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
    tabId = active?.id;
  }
  if (tabId === undefined) throw new Error("No tab to fill.");

  const values = (task.fields ?? []).map((f) => ({ key: f.key, label: f.label, value: f.value }));
  if (values.length === 0) {
    return { filled: [], failed: [{ key: "*", reason: "no_business_values_for_this_task" }] };
  }

  await chrome.scripting.executeScript({ target: { tabId }, files: ["filler.js"] });
  const outcome = (await chrome.tabs.sendMessage(tabId, { type: "aios-autofill", values })) as FillOutcome;

  // A matched field proves the form was on the page; a stuck value proves a fill.
  const formSeen = outcome.filled.length > 0 || outcome.failed.some((f) => f.reason !== "no_field_matched");
  if (formSeen) await sendTelemetry(taskId, "form_detected");
  if (outcome.filled.length > 0) await sendTelemetry(taskId, "filled");
  return outcome;
}


/** The stages the panel reports while an AI-assisted fill runs. */
export type AiFillStage = "analyzing" | "mapping" | "filling" | "ready" | "held";

export type AiFillResult = {
  stage: AiFillStage;
  outcome: FillOutcome;
  /** Fields mapped but BELOW the confidence bar: offered for the operator to check,
   *  never typed on their behalf. */
  review: { selector: string; key: string; confidence: number }[];
  /** True when the mapping was served from the cache, so this cost nothing. */
  cached: boolean;
  /** Set when nothing could be mapped. The panel shows it and the operator pastes. */
  reason: string;
  notes: string[];
};

/**
 * AI-assisted fill: the keyword heuristic first, the model only for what it missed.
 *
 * THE ORDER IS THE COST MODEL. `fillFormHeuristic` is free and instant and genuinely
 * handles a conventionally labelled form - measured, in `tests/heuristicGap.test.ts`.
 * Paying a model to re-derive "the box labelled Phone takes the phone number" would be
 * spending on a question already answered. So the model is asked only when fields are
 * still unfilled, and its plan is then narrowed to exactly those keys: a field the
 * heuristic already got right is never overwritten by a second opinion.
 *
 * What the model adds, and the heuristic provably cannot: an abbreviation nobody put in
 * a synonym list, a field whose only clue is the text beside it, and the traps - a
 * honeypot named `url` that the heuristic fills with the website and then truthfully
 * reports as filled, while the directory silently discards the submission.
 *
 * NOTHING IS SUBMITTED. This fills and reports; a person reviews and presses the
 * site's own button, exactly as before.
 */
async function aiFillSessionTask(taskId: string): Promise<AiFillResult> {
  const state = await readSession();
  if (!state) throw new Error("No active session.");
  const task =
    state.tasks.find((t) => t.taskId === taskId) ??
    (state.web2Tasks ?? []).find((t) => t.taskId === taskId);
  if (!task) throw new Error("No such task in this session.");

  let tabId: number | undefined;
  for (const [tid, mapped] of Object.entries(state.tabMap)) {
    if (mapped === taskId) tabId = Number(tid);
  }
  if (tabId === undefined) {
    const [active] = await chrome.tabs.query({ active: true, currentWindow: true });
    tabId = active?.id;
  }
  if (tabId === undefined) throw new Error("No tab to fill.");

  const values = (task.fields ?? []).map((f) => ({ key: f.key, label: f.label, value: f.value }));
  const byKey = new Map(values.map((v) => [v.key, v.value] as const));
  if (values.length === 0) {
    return {
      stage: "held", cached: false, review: [], notes: [],
      reason: "This task carries no business values to fill.",
      outcome: { filled: [], failed: [{ key: "*", reason: "no_business_values_for_this_task" }] },
    };
  }

  await chrome.scripting.executeScript({ target: { tabId }, files: ["filler.js"] });

  // PASS 1 - free, instant, and right on a conventionally labelled form.
  const heuristic = (await chrome.tabs.sendMessage(
    tabId, { type: "aios-autofill", values },
  )) as FillOutcome;
  const already = new Set(heuristic.filled);
  const missing = values.filter((v) => !already.has(v.key) && v.value.trim());
  if (missing.length === 0) {
    if (heuristic.filled.length) await sendTelemetry(taskId, "filled");
    return {
      stage: "ready", outcome: heuristic, review: [], cached: true, reason: "",
      notes: ["every field was matched without asking the model"],
    };
  }

  // PASS 2 - describe the form and ask what the remaining boxes want.
  const tab = await chrome.tabs.get(tabId);
  const fields = (await chrome.tabs.sendMessage(tabId, { type: "aios-collect" })) as unknown[];
  if (!Array.isArray(fields) || fields.length === 0) {
    return {
      stage: "held", outcome: heuristic, review: [], cached: false, notes: [],
      reason: "No form fields were found on this page.",
    };
  }

  let analysis: FormAnalysis;
  try {
    analysis = await api.analyzeForm(tab.url ?? "", fields);
  } catch (err) {
    // A refusal must leave the operator exactly where they were, not break the panel.
    return {
      stage: "held", outcome: heuristic, review: [], cached: false, notes: [],
      reason: err instanceof Error ? err.message : "The form mapper is unavailable.",
    };
  }
  if (!analysis.ok) {
    return {
      stage: "held", outcome: heuristic, review: [], cached: analysis.cached,
      notes: analysis.notes, reason: analysis.error || "The form could not be mapped.",
    };
  }

  // Narrowed to the keys the heuristic MISSED - a field it already filled correctly is
  // not overwritten by a second opinion, and a key we hold no value for is skipped
  // (typing an empty string can clear a pre-filled default).
  const wanted = new Set(missing.map((m) => m.key));
  const plan = analysis.mappings
    .filter((m) => m.fill && wanted.has(m.key))
    .map((m) => ({ selector: m.selector, valueKey: m.key, value: byKey.get(m.key) ?? "" }))
    .filter((p) => p.value.trim());

  const review = analysis.mappings
    .filter((m) => !m.fill && wanted.has(m.key))
    .map((m) => ({ selector: m.selector, key: m.key, confidence: m.confidence }));

  if (plan.length === 0) {
    return {
      stage: "ready", outcome: heuristic, review, cached: analysis.cached,
      notes: analysis.notes,
      reason: review.length
        ? "The remaining fields need a human eye - see the review list."
        : "",
    };
  }

  const aiOutcome = (await chrome.tabs.sendMessage(
    tabId, { type: "aios-fill", plan },
  )) as FillOutcome;

  const merged: FillOutcome = {
    filled: [...heuristic.filled, ...aiOutcome.filled],
    // A key the AI then filled is no longer a failure; keep only the genuinely unfilled.
    failed: [
      ...heuristic.failed.filter((f) => !aiOutcome.filled.includes(f.key)),
      ...aiOutcome.failed,
    ],
  };
  if (merged.filled.length > 0) {
    await sendTelemetry(taskId, "form_detected");
    await sendTelemetry(taskId, "filled");
  }
  return {
    stage: "ready", outcome: merged, review, cached: analysis.cached,
    reason: "", notes: analysis.notes,
  };
}

/** Resolve once a tab finishes loading (or after a timeout, so a slow/looping page
 *  never hangs the one-click flow). Event-driven via tabs.onUpdated with a fallback. */
function waitForTabLoad(tabId: number, timeoutMs = 9000): Promise<void> {
  return new Promise((resolve) => {
    let done = false;
    const finish = (): void => {
      if (done) return;
      done = true;
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    };
    const listener = (id: number, info: chrome.tabs.TabChangeInfo): void => {
      if (id === tabId && info.status === "complete") finish();
    };
    chrome.tabs.onUpdated.addListener(listener);
    // It may already be loaded by the time we start listening.
    chrome.tabs.get(tabId).then((t) => { if (t.status === "complete") finish(); }).catch(() => {});
    setTimeout(finish, timeoutMs);
  });
}

/** One click: open the task's add-form tab, wait for it to load, then best-effort
 *  autofill it. The panel grants host permission (a user gesture) BEFORE calling this,
 *  so the inject can run. Still never submits and never touches a CAPTCHA. */
async function openAndAutofill(taskId: string): Promise<FillOutcome> {
  const state = await readSession();
  if (!state) throw new Error("No active session.");
  const task = state.tasks.find((t) => t.taskId === taskId);
  if (!task) throw new Error("No such task in this session.");
  // Falls back to the directory homepage when no add-listing URL is on file - see
  // `openUrlFor`. Only a directory with NEITHER is genuinely unopenable.
  const target = openUrlFor(task);
  if (!target) {
    throw new Error("No add-listing URL and no homepage on file for this directory.");
  }

  const tab = await chrome.tabs.create({ url: target, active: true });
  if (tab.id === undefined) throw new Error("Could not open the form tab.");
  await writeSession(withTab((await readSession()) ?? state, tab.id, taskId));
  await sendTelemetry(taskId, "opened");
  await waitForTabLoad(tab.id);
  return autofillSessionTask(taskId);
}

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
  const plan = fillPlanFor(item.fields);

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
        // The pasted token carries no expiry, so store the fresh-mint ESTIMATE (12h);
        // the first rotation replaces it with the server's own timestamp.
        await storeCredentials(token, base, Date.now() + ASSUMED_TTL_MS);
        try {
          const board = await api.board();
          await armRotationAlarm();
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
        await chrome.alarms.clear(ROTATION_ALARM);
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

      // --- operator sessions (0130) ---------------------------------------- //
      case "sessionClients":
        return { ok: true, data: await api.sessionClients() };

      case "startSession": {
        const detail = (await api.createSession(
          request.clientId, request.limit ?? 25, request.batchSize ?? 10,
          request.kind ?? "citation",
        )) as SessionDetail;
        let state: ActiveSession = {
          sessionId: detail.id,
          client: detail.client,
          kind: detail.kind ?? request.kind ?? "citation",
          currentBatch: detail.currentBatch,
          totalBatches: detail.totalBatches,
          batchSize: detail.batchSize,
          tasks: detail.tasks ?? [],
          web2Tasks: detail.web2Tasks ?? [],
          tabMap: {},
          sentTelemetry: {},
          startedAtMs: Date.now(),
        };
        await writeSession(state);
        state = await openTabsForReleased(state);
        await chrome.alarms.create(SESSION_HEARTBEAT_ALARM, { periodInMinutes: 1 });
        return { ok: true, data: state };
      }

      case "sessionState": {
        // Local first (cheap, survives worker restarts). With no local state, ADOPT a
        // still-active server session from a previous browser lifetime (storage.session
        // dies with the browser; the server session outlives it until reaped) — so the
        // operator resumes instead of hitting a mysterious 409 on the next start.
        const state = await readSession();
        if (state) return { ok: true, data: state };
        try {
          const mine = (await api.myActiveSessions()) as Array<{ id: string }>;
          const first = mine[0];
          if (!first) return { ok: true, data: null };
          const detail = (await api.getSession(first.id)) as SessionDetail;
          if (detail.status !== "active") return { ok: true, data: null };
          const adopted: ActiveSession = {
            sessionId: detail.id,
            client: detail.client,
            kind: detail.kind ?? "citation",
            currentBatch: detail.currentBatch,
            totalBatches: detail.totalBatches,
            batchSize: detail.batchSize,
            tasks: detail.tasks ?? [],
            web2Tasks: detail.web2Tasks ?? [],
            tabMap: {},
            sentTelemetry: {},
            startedAtMs: Date.now(),
          };
          await writeSession(adopted);
          await chrome.alarms.create(SESSION_HEARTBEAT_ALARM, { periodInMinutes: 1 });
          return { ok: true, data: adopted };
        } catch (err) {
          // A FAILED ADOPTION IS NOT "NO SESSION".
          //
          // This used to swallow the error and report `data: null`, so the panel
          // believed the operator had no session and offered Start session - which the
          // server then refused with "You already have an active session", because
          // there IS one and only one is allowed per operator, whichever lane it
          // belongs to. The operator saw that refusal on a loop with nothing naming
          // the cause, and it hit BOTH tabs: a stuck web2 session blocks a citation
          // start just as hard.
          //
          // Reported from production on 2026-09-12, where the underlying read was
          // 500ing on an uncast enum comparison. That query is fixed, but a
          // swallow-and-claim-nothing is wrong whatever made the read fail - so the
          // failure is surfaced with the one action that resolves it.
          if (err instanceof NeedsPairing) throw err;
          return {
            ok: false,
            error:
              "You have an active session that could not be loaded, so a new one " +
              "cannot be started (only one runs at a time). Press Close session to " +
              "release it, then start again. " +
              ((err as Error)?.message ?? ""),
          };
        }
      }

      case "refreshSession":
        return { ok: true, data: await refreshSessionFromServer() };

      case "openTask": {
        const state = await readSession();
        if (!state) return { ok: false, error: "No active session." };
        const task = state.tasks.find((t) => t.taskId === request.taskId);
        if (!task) return { ok: false, error: "No such task in this session." };
        const target = openUrlFor(task);
        if (!target) {
          return { ok: false, error: "No add-listing URL and no homepage on file." };
        }
        const tab = await chrome.tabs.create({ url: target, active: true });
        if (tab.id !== undefined) await writeSession(withTab(state, tab.id, task.taskId));
        return { ok: true, data: null };
      }

      case "fillTask":
        return { ok: true, data: await fillSessionTask(request.taskId) };

      case "fillTaskAuto":
        return { ok: true, data: await autofillSessionTask(request.taskId) };

      case "fillTaskAi":
        return { ok: true, data: await aiFillSessionTask(request.taskId) };

      case "openAndAutofill":
        return { ok: true, data: await openAndAutofill(request.taskId) };

      case "markSubmitted": {
        // The server probe is the default door: it fetches the URL and a refusal
        // (accepted:false) comes back for inline rendering — the task stays non-terminal.
        // operatorConfirmed=true is the honest override for a probe FALSE NEGATIVE (a
        // JS-rendered or blocked page): the server records `submitted` (not probe-verified
        // `live`) and the task goes terminal. Never claims what the probe did not see.
        const state = await readSession();
        if (!state) return { ok: false, error: "No active session." };
        const task = state.tasks.find((t) => t.taskId === request.taskId);
        if (!task) return { ok: false, error: "No such task in this session." };
        const result = await api.complete(
          task.citationId, request.liveUrl, 0, request.note, request.operatorConfirmed ?? false,
        );
        if ((result as { accepted?: boolean }).accepted) await refreshSessionFromServer();
        return { ok: true, data: result };
      }

      case "markPlaced": {
        // Web2 placement completion (0136). The server is the only judge: it fetches
        // the pasted URL itself, pins the host to the platform and looks for the
        // client's link. A refusal comes back accepted:false for inline rendering —
        // the task stays non-terminal and the operator keeps their editor tab.
        const state = await readSession();
        if (!state) return { ok: false, error: "No active session." };
        const task = (state.web2Tasks ?? []).find((t) => t.taskId === request.taskId);
        if (!task) return { ok: false, error: "No such placement task in this session." };
        const result = await api.completePlacement(task.web2Id, request.url);
        if ((result as { accepted?: boolean }).accepted) await refreshSessionFromServer();
        return { ok: true, data: result };
      }

      case "skipTask": {
        const state = await readSession();
        if (!state) return { ok: false, error: "No active session." };
        await api.skipTask(state.sessionId, request.taskId, request.reason);
        return { ok: true, data: await refreshSessionFromServer() };
      }

      case "deferTask": {
        const state = await readSession();
        if (!state) return { ok: false, error: "No active session." };
        await api.deferTask(state.sessionId, request.taskId);
        return { ok: true, data: await refreshSessionFromServer() };
      }

      case "blockTask": {
        const state = await readSession();
        if (!state) return { ok: false, error: "No active session." };
        if (sessionKind(state) === "web2_placement") {
          // Web2 blocks are TASK-level (closed vocabulary, telemetry receipt); the
          // property stays parked — the citation door below also writes the citation
          // row, which is exactly why a web2 task must not travel through it.
          await api.blockPlacementTask(
            state.sessionId, request.taskId, request.reason, request.detail,
          );
          return { ok: true, data: await refreshSessionFromServer() };
        }
        const task = state.tasks.find((t) => t.taskId === request.taskId);
        if (!task) return { ok: false, error: "No such task in this session." };
        await api.blocked(task.citationId, request.reason, request.detail, 0);
        return { ok: true, data: await refreshSessionFromServer() };
      }

      case "closeSession": {
        // CLOSE WORKS WITHOUT LOCAL STATE, which is the whole point of the fallback
        // below. Close used to be a no-op when `storage.session` held nothing - and
        // that is exactly the situation an operator is in when a session cannot be
        // adopted: the server has one, the panel does not know about it, and the only
        // action that would release it did nothing. So the one escape from "You
        // already have an active session" was unreachable.
        const state = await readSession();
        let sessionId = state?.sessionId ?? "";
        if (!sessionId) {
          try {
            const mine = (await api.myActiveSessions()) as Array<{ id: string }>;
            sessionId = mine[0]?.id ?? "";
          } catch {
            // Nothing to close, or the list itself is unreachable. Clearing local
            // state below is still correct and still safe.
          }
        }
        try {
          if (sessionId) await api.closeSession(sessionId);
        } finally {
          await chrome.alarms.clear(SESSION_HEARTBEAT_ALARM);
          await clearSession();
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
